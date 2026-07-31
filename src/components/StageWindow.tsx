import { useEffect, useRef, useState } from "react";
import {
  setMouth, applyEmotion, applyAction, applyParams, loadScript, sleep,
} from "@/lib/avatarDriver";

const STAGE_MODELS_KEY = "naixi_stage_models"; // agent_id -> 模型复合key 映射（localStorage 持久化）

// 模型唯一标识：目录名/文件名（后端按此拼贴图相对路径）
const modelKey = (m: { name: string; modelFile: string }) => `${m.name}/${m.modelFile}`;

interface StageActor {
  agentId: string;
  name: string;
  sprite: any;
  expressions: any[];
  motions: any[];
  speaking: boolean;
}

interface RosterItem {
  agent_id: string;
  name: string;
  human_controlled?: boolean;
}

function loadModelMap(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(STAGE_MODELS_KEY) || "{}"); } catch { return {}; }
}

function saveModelMap(map: Record<string, string>) {
  localStorage.setItem(STAGE_MODELS_KEY, JSON.stringify(map));
}

/**
 * 多角色舞台窗口 — 一个 Pixi stage 放 N 个 Live2DSprite。
 * WebSocket 消息按 agent_id 路由到对应 sprite（speak / avatar_expression / avatar_motion / avatar_params）。
 * 路由规则：消息带 agent_id 则精准投递；不带则投给奶昔（兼容旧消息）。
 */
export default function StageWindow() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [roster, setRoster] = useState<RosterItem[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [modelMap, setModelMap] = useState<Record<string, string>>(loadModelMap);
  const defaultModel = models.length > 0 ? modelKey(models[0]) : "";
  const wsRef = useRef<WebSocket | null>(null);
  const appRef = useRef<any>(null);
  const actorsRef = useRef<Map<string, StageActor>>(new Map());
  const idleTimerRef = useRef<number | null>(null);
  const wsRetryRef = useRef<number | null>(null);

  // 拉取角色名单与模型列表
  useEffect(() => {
    fetch("/api/live/connectors")
      .then(r => r.json())
      .then(d => {
        const list: RosterItem[] = (d.connectors || []).filter((c: RosterItem) => !c.human_controlled);
        // 奶昔排最前，其余保持后端顺序
        list.sort((a, b) => (a.agent_id === "naixi" ? 0 : 1) - (b.agent_id === "naixi" ? 0 : 1));
        setRoster(list);
      })
      .catch(() => {});
    fetch("/api/live2d-model-list")
      .then(r => r.json())
      .then(d => { if (d.models) setModels(d.models); })
      .catch(() => {});
  }, []);

  // 初始化舞台：一个 Pixi Application + N 个 Live2DSprite
  useEffect(() => {
    if (!roster.length || !models.length) return;
    let cancelled = false;
    setLoading(true);

    async function init() {
      await loadScript("/Core/live2dcubismcore.js");
      const { Application } = await import("pixi.js");
      const { Live2DSprite, Config, Priority } = await import("easy-live2d");
      if (cancelled || !canvasRef.current) return;

      Config.MotionGroupIdle = "Idle";
      Config.MouseFollow = false;

      // 销毁旧舞台
      if (appRef.current) {
        try { appRef.current.destroy(); } catch {}
        appRef.current = null;
      }
      actorsRef.current.clear();
      if (idleTimerRef.current) { clearInterval(idleTimerRef.current); idleTimerRef.current = null; }

      const app = new Application();
      await app.init({
        view: canvasRef.current,
        backgroundAlpha: 0,
        resizeTo: window,
        antialias: true,
      });
      if (cancelled) { try { app.destroy(); } catch {} return; }
      appRef.current = app;

      const dpr = window.devicePixelRatio;
      const slotW = window.innerWidth / roster.length;
      const slotH = window.innerHeight;

      for (let i = 0; i < roster.length; i++) {
        const item = roster[i];
        const modelFile = modelMap[item.agent_id] || defaultModel;
        if (!modelFile) continue;
        const modelPath = `/api/live2d-model/${modelFile.split("/").map(encodeURIComponent).join("/")}`;
        try {
          const sprite = new Live2DSprite();
          await sprite.init({ modelPath, ticker: app.ticker });
          if (cancelled) return;
          sprite.width = slotW * dpr;
          sprite.height = slotH * dpr;
          sprite.x = i * slotW * dpr;
          sprite.y = 0;
          app.stage.addChild(sprite);

          const actor: StageActor = {
            agentId: item.agent_id, name: item.name, sprite,
            expressions: [], motions: [], speaking: false,
          };
          try { actor.expressions = await sprite.getExpressions(); } catch {}
          try { actor.motions = await sprite.getMotions(); } catch {}
          actorsRef.current.set(item.agent_id, actor);
        } catch (e) {
          console.error(`角色 ${item.agent_id} 模型加载失败:`, e);
        }
      }

      startIdleLoop(Priority);
      connectWs();
      setLoading(false);
    }
    init();
    return () => {
      cancelled = true;
      if (idleTimerRef.current) { clearInterval(idleTimerRef.current); idleTimerRef.current = null; }
      if (wsRetryRef.current) { clearTimeout(wsRetryRef.current); wsRetryRef.current = null; }
      try { wsRef.current?.close(); } catch {}
    };
  }, [roster, models, modelMap]);

  function startIdleLoop(Priority: any) {
    if (idleTimerRef.current) clearInterval(idleTimerRef.current);
    idleTimerRef.current = window.setInterval(() => {
      for (const actor of actorsRef.current.values()) {
        if (!actor.motions.length || actor.speaking) continue;
        const idle = actor.motions.filter((m: any) => m.group.toLowerCase() === "idle");
        const pool = idle.length ? idle : actor.motions;
        const r = pool[Math.floor(Math.random() * pool.length)];
        try { actor.sprite.startMotion({ group: r.group, no: r.no, priority: Priority.Idle }); } catch {}
      }
    }, 8000);
  }

  // 消息路由：带 agent_id 精准投递；缺省投给奶昔（兼容旧消息）
  function resolveActor(agentId?: string): StageActor | undefined {
    const actors = actorsRef.current;
    if (agentId && actors.has(agentId)) return actors.get(agentId);
    return actors.get("naixi") || actors.values().next().value;
  }

  function connectWs() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/live/live2d-stream`);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      wsRetryRef.current = window.setTimeout(() => connectWs(), 3000);
    };
    ws.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data);
        const actor = resolveActor(data.agent_id);
        if (!actor) return;
        if (data.type === "speak") {
          const { mouth, frame_ms, emotion, action } = data;
          actor.speaking = true;
          applyEmotion(actor.sprite, actor.expressions, emotion);
          applyAction(actor.sprite, actor.motions, action);
          if (Array.isArray(mouth)) {
            for (const m of mouth) {
              if (ws.readyState !== WebSocket.OPEN) break;
              setMouth(actor.sprite, m);
              await sleep(frame_ms || 80);
            }
          }
          setMouth(actor.sprite, 0);
          actor.speaking = false;
        } else if (data.type === "audio") {
          if (data.audio) {
            const a = new Audio(`data:audio/wav;base64,${data.audio}`);
            a.play().catch((e) => console.error("[语音] 播放失败", e));
          }
        } else if (data.type === "avatar_expression") {
          applyEmotion(actor.sprite, actor.expressions, data.emotion);
        } else if (data.type === "avatar_motion") {
          applyAction(actor.sprite, actor.motions, data.action);
        } else if (data.type === "avatar_params") {
          applyParams(actor.sprite, data.params);
        }
      } catch {}
    };
  }

  function handleModelChange(agentId: string, modelFile: string) {
    const next = { ...modelMap, [agentId]: modelFile };
    saveModelMap(next);
    setModelMap(next); // 触发舞台重建
  }

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", overflow: "hidden", background: "transparent" }}>
      {/* 顶部工具栏：每个角色一个模型下拉 */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0,
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 10px", background: "rgba(0,0,0,0.35)",
        zIndex: 10, fontSize: 12, flexWrap: "wrap",
      }}>
        {roster.map(item => (
          <div key={item.agent_id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ color: "#fff", fontSize: 11, whiteSpace: "nowrap", opacity: 0.85 }}>{item.name}</span>
            <select
              value={modelMap[item.agent_id] || defaultModel}
              onChange={e => handleModelChange(item.agent_id, e.target.value)}
              style={{ padding: "3px 6px", borderRadius: 4, border: "none", fontSize: 11, background: "rgba(255,255,255,0.15)", color: "#fff", outline: "none", maxWidth: 140 }}
            >
              {models.map(m => (
                <option key={modelKey(m)} value={modelKey(m)} style={{ color: "#000" }}>{m.name}</option>
              ))}
            </select>
          </div>
        ))}
        <span style={{ fontSize: 10, opacity: 0.6, color: "#fff", whiteSpace: "nowrap", marginLeft: "auto" }}>
          {loading ? "加载中..." : connected ? `已连接 · ${actorsRef.current.size} 角色在台` : "未连接"}
        </span>
      </div>

      <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />

      {!roster.length && !loading && (
        <div style={{
          position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          color: "#fff", background: "rgba(0,0,0,0.4)", padding: "10px 18px", borderRadius: 8, fontSize: 13,
        }}>
          暂无可上台角色（真人角色由真人操控，不在自研舞台渲染）
        </div>
      )}
    </div>
  );
}
