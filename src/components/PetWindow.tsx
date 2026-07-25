import { useEffect, useRef, useState } from "react";

const MODEL_KEY = "naixi_pet_model";

// 情绪(中文) → 英文关键词（用于模糊匹配模型的表情名）
const EMOTION_KEYWORDS: Record<string, string[]> = {
  "开心": ["happy", "smile", "joy"],
  "欢迎": ["welcome", "greeting", "hello", "hi"],
  "惊讶": ["surprise", "shock", "amaze"],
  "悲伤": ["sad", "cry", "grief", "blue"],
  "害羞": ["shy", "blush", "embarrass", "red"],
  "生气": ["angry", "mad", "rage"],
  "卖萌": ["love", "moe", "cute", "heart", "like"],
  "无奈": ["hopeless", "sigh", "helpless", "tired"],
};

// 动作标签 → 英文关键词（用于模糊匹配模型的 motion 组/名）
const ACTION_KEYWORDS: Record<string, string[]> = {
  "wave": ["wave", "greet", "hello", "hi", "bye"],
  "bye": ["bye", "wave", "greet"],
  "nod": ["nod", "yes"],
  "think": ["think", "ponder"],
  "surprise": ["surprise", "shock"],
  "shake": ["shake", "no"],
  "kime": ["kime", "pose"],
  "sing": ["sing", "song"],
  "angry": ["angry", "mad"],
  "cry": ["cry", "sad", "tear"],
  "smile": ["smile", "happy", "joy"],
  "sad": ["sad", "cry", "blue"],
};

// 口型参数名（兼容不同 Cubism 模型命名）
const MOUTH_PARAMS = ["ParamMouthOpenY", "ParamMouthOpen"];

function setMouth(sprite: any, v: number) {
  const val = Math.max(0, Math.min(1, v));
  for (const p of MOUTH_PARAMS) {
    try { sprite.setParameterValueById(p, val, 1); } catch {}
  }
}

function applyEmotion(sprite: any, expressions: any[], emotion?: string) {
  if (!emotion || !expressions.length) return;
  const kws = EMOTION_KEYWORDS[emotion.trim()] || [];
  if (!kws.length) return;
  const hit = expressions.find(x => kws.some(k => String(x.name).toLowerCase().includes(k)));
  if (hit) {
    try { sprite.setExpression({ expressionId: hit.name }); } catch {}
  }
}

function applyAction(sprite: any, motions: any[], action?: string) {
  if (!action || !motions.length) return;
  const kws = ACTION_KEYWORDS[action.trim()] || [];
  if (!kws.length) return;
  const hit = motions.find(m => kws.some(k => (m.group + " " + m.name).toLowerCase().includes(k)));
  if (hit) {
    try { sprite.startMotion({ group: hit.group, no: hit.no, priority: 3 }); } catch {}
  } else {
    // 没有精确匹配时随机播一个动作，保证有表现力
    const r = motions[Math.floor(Math.random() * motions.length)];
    try { sprite.startMotion({ group: r.group, no: r.no, priority: 2 }); } catch {}
  }
}

/**
 * 桌宠窗口 — 透明 Live2D 浮窗
 * 用 easy-live2d + Pixi.js 渲染，WebSocket 接收口型/表情/动作数据
 */
export default function PetWindow() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);
  const [models, setModels] = useState<any[]>([]);
  const [currentModel, setCurrentModel] = useState(() => localStorage.getItem(MODEL_KEY) || "绒E_正式版.model3.json");
  const [loading, setLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const appRef = useRef<any>(null);
  const live2dRef = useRef<any>(null);
  const expressionsRef = useRef<any[]>([]);
  const motionsRef = useRef<any[]>([]);
  const speakingRef = useRef(false);
  const idleTimerRef = useRef<number | null>(null);

  // 加载模型列表
  useEffect(() => {
    fetch("/api/live2d-model-list")
      .then(r => r.json())
      .then(d => { if (d.models) setModels(d.models); })
      .catch(() => {});
  }, []);

  // 初始化 Live2D
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    if (appRef.current) {
      appRef.current.destroy();
      appRef.current = null;
    }
    live2dRef.current = null;
    expressionsRef.current = [];
    motionsRef.current = [];
    if (idleTimerRef.current) { clearInterval(idleTimerRef.current); idleTimerRef.current = null; }

    async function init() {
      await loadScript("/Core/live2dcubismcore.js");
      const { Application } = await import("pixi.js");
      const { Live2DSprite, Config, Priority } = await import("easy-live2d");
      if (cancelled || !canvasRef.current) return;

      Config.MotionGroupIdle = "Idle";
      Config.MouseFollow = false;

      const app = new Application();
      await app.init({
        view: canvasRef.current,
        backgroundAlpha: 0,
        resizeTo: window,
        antialias: true,
      });
      appRef.current = app;

      // 加载选中的模型
      const modelPath = `/api/live2d-model/${encodeURIComponent(currentModel)}`;
      try {
        const sprite = new Live2DSprite();
        await sprite.init({ modelPath, ticker: app.ticker });
        sprite.width = window.innerWidth * window.devicePixelRatio;
        sprite.height = window.innerHeight * window.devicePixelRatio;
        app.stage.addChild(sprite);
        live2dRef.current = sprite;

        // 自省模型：缓存表情与动作列表（供口型/动作映射使用）
        try { expressionsRef.current = await sprite.getExpressions(); } catch { expressionsRef.current = []; }
        try { motionsRef.current = await sprite.getMotions(); } catch { motionsRef.current = []; }

        connectWs(sprite);
        startIdleLoop(Priority);
        setLoading(false);
      } catch (e) {
        console.error("模型加载失败:", e);
        setLoading(false);
      }
    }
    init();
    return () => {
      cancelled = true;
      if (idleTimerRef.current) { clearInterval(idleTimerRef.current); idleTimerRef.current = null; }
    };
  }, [currentModel]);

  function startIdleLoop(Priority: any) {
    if (idleTimerRef.current) clearInterval(idleTimerRef.current);
    idleTimerRef.current = window.setInterval(() => {
      const sprite = live2dRef.current;
      const motions = motionsRef.current;
      if (!sprite || !motions.length || speakingRef.current) return;
      const idle = motions.filter((m: any) => m.group.toLowerCase() === "idle");
      const pool = idle.length ? idle : motions;
      const r = pool[Math.floor(Math.random() * pool.length)];
      try { sprite.startMotion({ group: r.group, no: r.no, priority: Priority.Idle }); } catch {}
    }, 8000);
  }

  function connectWs(sprite: any) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/live/live2d-stream`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => { setConnected(false); setTimeout(() => connectWs(sprite), 3000); };
    ws.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === "speak") {
          const { mouth, frame_ms, emotion, action } = data;
          speakingRef.current = true;
          // 说话开始即触发表情与动作
          applyEmotion(sprite, expressionsRef.current, emotion);
          applyAction(sprite, motionsRef.current, action);
          // 口型逐帧驱动
          if (Array.isArray(mouth)) {
            for (const m of mouth) {
              if (ws.readyState !== WebSocket.OPEN) break;
              setMouth(sprite, m);
              await sleep(frame_ms || 80);
            }
          }
          setMouth(sprite, 0);
          speakingRef.current = false;
        }
      } catch {}
    };
  }

  function handleModelChange(val: string) {
    localStorage.setItem(MODEL_KEY, val);
    setCurrentModel(val);
  }

  function handleFilePick() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".model3.json";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      // 将 model3.json 文件名存为自定义路径标记
      handleModelChange(file.name);
    };
    input.click();
  }

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden" }}>
      {/* 顶部工具栏 */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        display: "flex", alignItems: "center", gap: 6,
        padding: "6px 10px", background: "rgba(0,0,0,0.35)",
        zIndex: 10, fontSize: 12,
      }}>
        <select
          value={currentModel}
          onChange={e => handleModelChange(e.target.value)}
          style={{ flex: 1, padding: "3px 6px", borderRadius: 4, border: "none", fontSize: 12, background: "rgba(255,255,255,0.15)", color: "#fff", outline: "none" }}
        >
          {models.map(m => (
            <option key={m.modelFile} value={m.modelFile} style={{ color: "#000" }}>{m.name}</option>
          ))}
        </select>
        <button
          onClick={handleFilePick}
          style={{ padding: "3px 8px", borderRadius: 4, border: "none", fontSize: 11, background: "rgba(255,255,255,0.15)", color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }}
        >
          导入模型
        </button>
        <span style={{ fontSize: 10, opacity: 0.6, color: "#fff", whiteSpace: "nowrap" }}>
          {loading ? "加载中..." : connected ? "已连接" : "未连接"}
        </span>
      </div>

      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />

      {!connected && !loading && (
        <div style={{
          position: "absolute", bottom: 10, right: 10,
          background: "rgba(0,0,0,0.4)", color: "#fff",
          padding: "4px 10px", borderRadius: 8, fontSize: 11,
        }}>
          等待连接...
        </div>
      )}
    </div>
  );
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function sleep(ms: number) {
  return new Promise(r => setTimeout(r, ms));
}
