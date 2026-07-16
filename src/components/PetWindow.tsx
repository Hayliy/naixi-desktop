import { useEffect, useRef, useState } from "react";

/**
 * 桌宠窗口 — 透明 Live2D 浮窗
 * 用 easy-live2d + Pixi.js 渲染，WebSocket 接收口型/表情数据
 */
export default function PetWindow() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const appRef = useRef<any>(null);
  const live2dRef = useRef<any>(null);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      // 1. 加载 Cubism Core
      await loadScript("/Core/live2dcubismcore.js");

      // 2. 初始化 Pixi + Live2D
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

      // 3. 加载模型（从 VTube Studio 目录读取）
      const modelPath = "/api/live2d-model/model3.json"; // 后端代理
      const sprite = new Live2DSprite();
      await sprite.init({ modelPath, ticker: app.ticker });
      sprite.width = window.innerWidth * window.devicePixelRatio;
      sprite.height = window.innerHeight * window.devicePixelRatio;
      app.stage.addChild(sprite);
      live2dRef.current = sprite;

      // 4. 连接 WebSocket 接收口型数据
      connectWs(sprite);
    }

    init();
    return () => { cancelled = true; };
  }, []);

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

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden" }}>
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
      {!connected && (
        <div style={{
          position: "absolute", bottom: 10, right: 10,
          background: "rgba(0,0,0,0.5)", color: "#fff",
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
