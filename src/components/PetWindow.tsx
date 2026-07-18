import { useEffect, useRef, useState } from "react";

const MODEL_KEY = "naixi_pet_model";

/**
 * 桌宠窗口 — 透明 Live2D 浮窗
 * 用 easy-live2d + Pixi.js 渲染，WebSocket 接收口型/表情数据
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

    async function init() {
      await loadScript("/Core/live2dcubismcore.js");
      const { Application } = await import("pixi.js");
      const { Live2DSprite, Config } = await import("easy-live2d");
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
        connectWs(sprite);
        setLoading(false);
      } catch (e) {
        console.error("模型加载失败:", e);
        setLoading(false);
      }
    }
    init();
    return () => { cancelled = true; };
  }, [currentModel]);

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
          const { mouth, frame_ms } = data;
          for (const m of mouth) {
            if (ws.readyState !== WebSocket.OPEN) break;
            sprite.setParameter?.("ParamMouthOpenY", m);
            await sleep(frame_ms);
          }
          sprite.setParameter?.("ParamMouthOpenY", 0);
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
