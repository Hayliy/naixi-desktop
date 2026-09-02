import { useEffect, useRef, useState } from "react";
import { Minus, X } from "lucide-react";
import {
  setMouth, applyEmotion, applyAction, applyParams, loadScript, sleep,
} from "@/lib/avatarDriver";
import { API_BASE } from "@/lib/api";

const MODEL_KEY = "naixi_pet_model";

// 模型唯一标识：目录名/文件名（后端按此拼贴图相对路径，避免 404 白板）
const modelKey = (m: { name: string; modelFile: string }) => `${m.name}/${m.modelFile}`;

/**
 * 桌宠窗口 — 透明 Live2D 浮窗
 * 用 easy-live2d + Pixi.js 渲染，WebSocket 接收口型/表情/动作数据
 */
export default function PetWindow() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);
  const [models, setModels] = useState<any[]>([]);
  const [currentModel, setCurrentModel] = useState<string>(() => localStorage.getItem(MODEL_KEY) || "");
  const clickThroughRef = useRef(false);
  const [loading, setLoading] = useState(true);
  const [appReady, setAppReady] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const appRef = useRef<any>(null);
  const live2dRef = useRef<any>(null);
  const expressionsRef = useRef<any[]>([]);
  const motionsRef = useRef<any[]>([]);
  const speakingRef = useRef(false);
  const idleTimerRef = useRef<number | null>(null);

  // 加载模型列表
  useEffect(() => {
    fetch(`${API_BASE}/api/live2d-model-list`)
      .then(r => r.json())
      .then(d => { if (d.models) setModels(d.models); })
      .catch(() => {});
  }, []);

  // 监听顶栏菜单的桌宠控制事件（切换模型 / 鼠标穿透）
  useEffect(() => {
    const onNextModel = () => {
      if (!models.length) return;
      const idx = models.findIndex(m => modelKey(m) === currentModel);
      const next = models[(idx + 1) % models.length];
      handleModelChange(modelKey(next));
    };
    const onToggleClickThrough = () => {
      if (!isTauri) return;
      (async () => {
        try {
          const { getCurrentWindow } = await import("@tauri-apps/api/window");
          const w = getCurrentWindow();
          clickThroughRef.current = !clickThroughRef.current;
          await w.setIgnoreMouseEvents(clickThroughRef.current);
        } catch {}
      })();
    };
    window.addEventListener("naixi:pet:next-model", onNextModel);
    window.addEventListener("naixi:pet:toggle-clickthrough", onToggleClickThrough);
    return () => {
      window.removeEventListener("naixi:pet:next-model", onNextModel);
      window.removeEventListener("naixi:pet:toggle-clickthrough", onToggleClickThrough);
    };
  }, [models, currentModel, isTauri]);

  // 模型列表加载后，若无有效选择则自动选第一个（避免硬编码默认导致 404 白板）
  useEffect(() => {
    if (!models.length) return;
    if (!models.some(m => modelKey(m) === currentModel)) {
      setCurrentModel(modelKey(models[0]));
    }
  }, [models]);

  // 初始化 Pixi Application（仅一次，避免切换模型时复用已销毁 canvas 导致卡死）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadScript("/Core/live2dcubismcore.js");
      const { Application } = await import("pixi.js");
      if (cancelled || !canvasRef.current) return;
      const app = new Application();
      await app.init({
        view: canvasRef.current,
        backgroundAlpha: 0,
        resizeTo: window,
        antialias: true,
        // 强制 WebGL：easy-live2d 仅支持 WebGL 上下文，Pixi v8 默认会优先选 WebGPU，
        // 导致 canvas 已被 webgpu 上下文占用后 easy-live2d 取不到 webgl 上下文（gl is null / 白板）
        preference: "webgl",
      });
      if (cancelled) { try { app.destroy(true); } catch {} return; }
      appRef.current = app;
      setAppReady(true);
    })();
    return () => {
      cancelled = true;
      try { wsRef.current?.close(); } catch {}
      wsRef.current = null;
      try { appRef.current?.destroy(true); } catch {}
      appRef.current = null;
      setAppReady(false);
    };
  }, []);

  // 加载/切换模型（仅替换 Live2DSprite，Application 常驻，规避 canvas 复用卡死）
  useEffect(() => {
    if (!currentModel || !appReady || !appRef.current) return;
    let cancelled = false;
    setLoading(true);
    const app = appRef.current;
    // 清旧 sprite
    if (live2dRef.current) {
      try { app.stage.removeChild(live2dRef.current); } catch {}
      try { live2dRef.current.destroy(); } catch {}
      live2dRef.current = null;
    }
    expressionsRef.current = [];
    motionsRef.current = [];
    if (idleTimerRef.current) { clearInterval(idleTimerRef.current); idleTimerRef.current = null; }

    (async () => {
      const { Live2DSprite, Config, Priority } = await import("easy-live2d");
      if (cancelled) return;
      Config.MotionGroupIdle = "Idle";
      Config.MouseFollow = false;
      const modelPath = `${API_BASE}/api/live2d-model/${currentModel.split("/").map(encodeURIComponent).join("/")}`;
      try {
        const sprite = new Live2DSprite();
        await sprite.init({ modelPath, ticker: app.ticker });
        if (cancelled) { try { sprite.destroy(); } catch {} return; }
        sprite.width = window.innerWidth * window.devicePixelRatio;
        sprite.height = window.innerHeight * window.devicePixelRatio;
        app.stage.addChild(sprite);
        live2dRef.current = sprite;
        try { expressionsRef.current = await sprite.getExpressions(); } catch { expressionsRef.current = []; }
        try { motionsRef.current = await sprite.getMotions(); } catch { motionsRef.current = []; }
        connectWs();
        startIdleLoop(Priority);
        setLoading(false);
      } catch (e) {
        console.error("模型加载失败:", e);
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [currentModel, appReady]);

  // VTS 风格全局热键：窗口聚焦时由浏览器 keydown 兜底（后端 pynput 全局监听不可用时）。
  // 若后端全局监听已激活（global_active=true），则跳过，避免双触发。
  const hotkeyCfgRef = useRef<{ global_active: boolean; hotkeys: any[] }>({ global_active: false, hotkeys: [] });
  useEffect(() => {
    fetch(`${API_BASE}/api/hotkeys/config`)
      .then(r => r.json())
      .then(d => { hotkeyCfgRef.current = { global_active: !!d.global_active, hotkeys: d.hotkeys || [] }; })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!appReady) return;
    function normalizeCombo(e: KeyboardEvent): string {
      const mods: string[] = [];
      if (e.ctrlKey) mods.push("ctrl");
      if (e.altKey) mods.push("alt");
      if (e.shiftKey) mods.push("shift");
      if (e.metaKey) mods.push("meta");
      let key = e.key.toLowerCase();
      if (key === " ") key = "space";
      if (key.startsWith("arrow")) key = key.slice(5);
      return [...mods.sort(), key].join("+");
    }
    function onKeyDown(e: KeyboardEvent) {
      if (hotkeyCfgRef.current.global_active) return; // 全局监听已接管
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      const combo = normalizeCombo(e);
      const hit = hotkeyCfgRef.current.hotkeys.find(
        (h: any) => h.enabled !== 0 && h.combo.toLowerCase() === combo
      );
      if (!hit) return;
      const sprite = live2dRef.current;
      if (!sprite) return;
      e.preventDefault();
      if (hit.kind === "expression") {
        applyEmotion(sprite, expressionsRef.current, hit.label);
      } else {
        applyAction(sprite, motionsRef.current, hit.label);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [appReady]);

  // 模型加载后，默认导入该模型文件里原本写的快捷键动作（force：有内置热键则用模型真实动作
  // 替换通用种子，实现「模型文件里原本写的快捷键默认支持」；无内置动作则保留种子）。
  useEffect(() => {
    if (!currentModel) return;
    fetch(`${API_BASE}/api/hotkeys/import-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: currentModel, force: true }),
    })
      .then(() => fetch(`${API_BASE}/api/hotkeys/config`))
      .then(r => r.json())
      .then(d => { hotkeyCfgRef.current = { global_active: !!d.global_active, hotkeys: d.hotkeys || [] }; })
      .catch(() => {});
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

  function connectWs() {
    if (wsRef.current) return; // 仅连接一次
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/live/live2d-stream`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      setTimeout(() => connectWs(), 3000);
    };
    ws.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data);
        const sprite = live2dRef.current; // 始终驱动当前 sprite（切换模型后自动生效）
        if (!sprite) return;
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
        } else if (data.type === "audio") {
          if (data.audio) {
            const a = new Audio(`data:audio/wav;base64,${data.audio}`);
            a.play().catch((e) => console.error("[语音] 播放失败", e));
          }
        } else if (data.type === "avatar_expression") {
          // 后端 SelfRenderBackend：情绪 → 表情模糊匹配
          applyEmotion(sprite, expressionsRef.current, data.emotion);
        } else if (data.type === "avatar_motion") {
          // 后端 SelfRenderBackend：动作标签 → motion 组模糊匹配
          applyAction(sprite, motionsRef.current, data.action);
        } else if (data.type === "avatar_params") {
          // 后端 SelfRenderBackend：参数字典 → 批量注入（如 MouthOpen/FaceAngleX）
          applyParams(sprite, data.params);
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

  // 窗口控制（pet 窗口 decorations:false 无原生标题栏，需自绘最小/关闭）
  const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  async function handleMinimize() {
    if (isTauri) {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        await getCurrentWindow().minimize();
      } catch {}
    } else {
      try { window.blur(); } catch {}
    }
  }
  async function handleClose() {
    if (isTauri) {
      try {
        const { getCurrentWindow } = await import("@tauri-apps/api/window");
        await getCurrentWindow().close();
      } catch {}
    } else {
      // 浏览器预览：返回仪表盘
      window.location.href = "/";
    }
  }

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden" }}>
      {/* 顶部工具栏（data-tauri-drag-region 让无边框窗体可拖动；交互控件 stopPropagation 避免误触拖动） */}
      <div
        data-tauri-drag-region
        style={{
          position: "absolute", top: 0, left: 0, right: 0,
          display: "flex", alignItems: "center", gap: 6,
          padding: "6px 10px", background: "rgba(0,0,0,0.45)",
          zIndex: 10, fontSize: 12,
        }}
      >
        <select
          data-tauri-drag-region
          onMouseDown={(e) => e.stopPropagation()}
          value={currentModel}
          onChange={(e) => handleModelChange(e.target.value)}
          style={{ flex: 1, padding: "3px 6px", borderRadius: 4, border: "none", fontSize: 12, background: "rgba(255,255,255,0.15)", color: "#fff", outline: "none", cursor: "default" }}
        >
          {models.map((m) => (
            <option key={modelKey(m)} value={modelKey(m)} style={{ color: "#000" }}>{m.name}</option>
          ))}
        </select>
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={handleFilePick}
          style={{ padding: "3px 8px", borderRadius: 4, border: "none", fontSize: 11, background: "rgba(255,255,255,0.15)", color: "#fff", cursor: "pointer", whiteSpace: "nowrap" }}
        >
          导入模型
        </button>
        <span style={{ fontSize: 10, opacity: 0.6, color: "#fff", whiteSpace: "nowrap" }}>
          {loading ? "加载中..." : connected ? "已连接" : "未连接"}
        </span>
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={handleMinimize}
          title="最小化"
          style={{ marginLeft: "auto", width: 22, height: 20, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 4, border: "none", background: "rgba(255,255,255,0.12)", color: "#fff", cursor: "pointer" }}
        >
          <Minus size={13} />
        </button>
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={handleClose}
          title="关闭"
          style={{ width: 22, height: 20, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 4, border: "none", background: "rgba(255,90,90,0.55)", color: "#fff", cursor: "pointer" }}
        >
          <X size={13} />
        </button>
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

