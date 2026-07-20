import { useState, useEffect, useCallback } from "react";
import type { ReactNode } from "react";
import {
  Cpu, Cat, Mic, Search, HardDrive, Server,
  Palette, DatabaseBackup, ShieldCheck, Info, Check, X,
} from "lucide-react";
import ProviderSettings from "./ProviderSettings";
import ThemeSettings from "./ThemeSettings";
import { apiGet, apiPost } from "@/lib/api";

const TABS = [
  { key: "model",     label: "模型",       icon: Cpu },
  { key: "pet",       label: "桌宠",       icon: Cat },
  { key: "voice",     label: "语音",       icon: Mic },
  { key: "search",    label: "搜索",       icon: Search },
  { key: "storage",   label: "文件与存储", icon: HardDrive },
  { key: "system",    label: "系统与环境", icon: Server },
  { key: "interface", label: "界面",       icon: Palette },
  { key: "backup",    label: "备份与迁移", icon: DatabaseBackup },
  { key: "security",  label: "安全",       icon: ShieldCheck },
  { key: "about",     label: "关于",       icon: Info },
];

/* ── 全局 Toast（自定义，禁用浏览器原生弹窗）── */
type ToastKind = "ok" | "err";
type ShowFn = (msg: string, kind?: ToastKind) => void;

function useToast() {
  const [toast, setToast] = useState<{ msg: string; kind: ToastKind } | null>(null);
  const show = useCallback<ShowFn>((msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2200);
  }, []);
  const node = toast && (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2 rounded-xl shadow-lg bg-sakura-100 border border-sakura-200 text-sm text-sakura-700">
      {toast.kind === "ok"
        ? <Check className="w-4 h-4 text-sakura-500" />
        : <X className="w-4 h-4 text-sakura-500" />}
      <span>{toast.msg}</span>
    </div>
  );
  return { show, node };
}

/* ── 复用样式（全部走主题语义类，跟随明暗）── */
const CARD = "bg-sakura-50 border border-sakura-100 rounded-xl";
const INPUT = "w-full mt-1 bg-sakura-50 border border-sakura-200 rounded-lg px-3 py-2 text-sm text-sakura-700 focus:outline-none focus:border-sakura-300";
const LABEL = "text-xs text-sakura-400";
const BTN = "px-4 py-1.5 bg-sakura-500 text-white rounded-lg text-sm hover:bg-sakura-400 transition-colors disabled:opacity-60";
const BTN_GHOST = "px-4 py-1.5 border border-sakura-200 text-sakura-500 rounded-lg text-sm hover:bg-sakura-100 transition-colors";
const HEAD = "text-sm font-semibold text-sakura-500";

function Row({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-sakura-400 shrink-0">{k}</span>
      <span className={`text-sakura-600 text-right ${mono ? "font-mono text-[11px] break-all" : ""}`}>{v}</span>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState("model");
  const { show, node } = useToast();

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 px-4 pt-3 pb-0 border-b border-sakura-200/40 overflow-x-auto">
        {TABS.map(t => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-t-lg whitespace-nowrap transition-colors ${
                active
                  ? "bg-sakura-100 text-sakura-700 font-medium"
                  : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "model" && <SettingsModel />}
        {tab === "pet" && <SettingsPet show={show} />}
        {tab === "voice" && <SettingsVoice show={show} />}
        {tab === "search" && <SettingsSearch show={show} />}
        {tab === "storage" && <SettingsStorage />}
        {tab === "system" && <SettingsSystem show={show} />}
        {tab === "interface" && <div className="max-w-xl"><p className={`${HEAD} mb-3`}>界面与主题</p><ThemeSettings /></div>}
        {tab === "backup" && <SettingsBackup show={show} />}
        {tab === "security" && <SettingsSecurity />}
        {tab === "about" && <SettingsAbout />}
      </div>
      {node}
    </div>
  );
}

/* ── 模型 ── */
function SettingsModel() {
  return (
    <div className="space-y-6">
      <p className={HEAD}>模型供应商与默认配置</p>
      <ProviderSettings />
    </div>
  );
}

/* ── 桌宠 ── */
function SettingsPet({ show }: { show: ShowFn }) {
  const [mode, setMode] = useState("live2d");
  const [modelPath, setModelPath] = useState("");
  const [ttsEngine, setTtsEngine] = useState("cosyvoice");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    apiGet<any>("/api/live/config").then(d => {
      if (d.render_mode) setMode(d.render_mode);
      if (d.model_path) setModelPath(d.model_path);
      if (d.tts_engine) setTtsEngine(d.tts_engine);
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/api/live/save-config", { render_mode: mode, model_path: modelPath, tts_engine: ttsEngine });
      show("桌宠配置已保存");
    } catch { show("保存失败", "err"); }
    finally { setSaving(false); }
  };
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>桌宠设置</p>
      <div>
        <label className={LABEL}>渲染模式</label>
        <select value={mode} onChange={e => setMode(e.target.value)} className={INPUT}>
          <option value="live2d">Live2D</option>
          <option value="vrm">VRM (Godot)</option>
        </select>
      </div>
      <div>
        <label className={LABEL}>模型文件路径</label>
        <input value={modelPath} onChange={e => setModelPath(e.target.value)} className={INPUT} />
      </div>
      <div>
        <label className={LABEL}>TTS 引擎</label>
        <select value={ttsEngine} onChange={e => setTtsEngine(e.target.value)} className={INPUT}>
          <option value="cosyvoice">CosyVoice (百炼)</option>
          <option value="edge-tts">Edge TTS</option>
        </select>
      </div>
      <button onClick={save} disabled={saving} className={BTN}>{saving ? "保存中..." : "保存"}</button>
    </div>
  );
}

/* ── 语音 ── */
function SettingsVoice({ show }: { show: ShowFn }) {
  const [mode, setMode] = useState("browser");
  const [voice, setVoice] = useState("zh-CN-XiaoxiaoNeural");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    apiGet<any>("/api/config/tts").then(d => {
      if (d.mode) setMode(d.mode);
      if (d.voice) setVoice(d.voice);
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/api/config/tts", { mode, voice });
      show("语音配置已保存");
    } catch { show("保存失败", "err"); }
    finally { setSaving(false); }
  };
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>语音设置</p>
      <div>
        <label className={LABEL}>朗读模式</label>
        <select value={mode} onChange={e => setMode(e.target.value)} className={INPUT}>
          <option value="browser">浏览器内置</option>
          <option value="edge-tts">Edge TTS</option>
          <option value="cosyvoice">CosyVoice (百炼)</option>
        </select>
      </div>
      <div>
        <label className={LABEL}>默认音色</label>
        <input value={voice} onChange={e => setVoice(e.target.value)} className={INPUT} />
      </div>
      <button onClick={save} disabled={saving} className={BTN}>{saving ? "保存中..." : "保存"}</button>
    </div>
  );
}

/* ── 搜索 ── */
function SettingsSearch({ show }: { show: ShowFn }) {
  const [searxng, setSearxng] = useState("http://127.0.0.1:8899");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    apiGet<any>("/api/desktop/config").then(d => {
      const s = d.settings || {};
      if (s.searxng_url) setSearxng(s.searxng_url);
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/api/desktop/config", { settings: { searxng_url: searxng } });
      show("搜索配置已保存");
    } catch { show("保存失败", "err"); }
    finally { setSaving(false); }
  };
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>搜索设置</p>
      <div>
        <label className={LABEL}>SearXNG 地址</label>
        <input value={searxng} onChange={e => setSearxng(e.target.value)} className={INPUT} />
      </div>
      <button onClick={save} disabled={saving} className={BTN}>{saving ? "保存中..." : "保存"}</button>
    </div>
  );
}

/* ── 文件与存储（真实路径）── */
function SettingsStorage() {
  const [p, setP] = useState<any>(null);
  useEffect(() => {
    apiGet<any>("/api/desktop/paths").then(setP).catch(() => setP({ error: true }));
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>文件与存储</p>
      <div className={`${CARD} p-4 space-y-3 text-xs`}>
        {!p && <p className="text-sakura-400">加载中...</p>}
        {p?.error && <p className="text-sakura-400">无法获取路径信息</p>}
        {p && !p.error && <>
          <Row k="数据库路径" v={p.db_path} mono />
          <Row k="数据库大小" v={`${p.db_size_mb} MB`} />
          <Row k="日志目录" v={p.logs_dir} mono />
          <Row k="模型目录" v={p.models_dir} mono />
          <Row k="日志保留" v={`${p.log_keep_days} 天`} />
        </>}
      </div>
    </div>
  );
}

/* ── 系统与环境 ── */
function SettingsSystem({ show }: { show: ShowFn }) {
  const [port] = useState("9845");
  const [logLevel, setLogLevel] = useState("INFO");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    apiGet<any>("/api/desktop/config").then(d => {
      const s = d.settings || {};
      if (s.log_level) setLogLevel(s.log_level);
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/api/desktop/config", { settings: { log_level: logLevel } });
      show("系统配置已保存");
    } catch { show("保存失败", "err"); }
    finally { setSaving(false); }
  };
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>系统与环境</p>
      <div>
        <label className={LABEL}>服务端口（只读，改动需重启后端）</label>
        <input value={port} readOnly className={`${INPUT} opacity-60 cursor-not-allowed`} />
      </div>
      <div>
        <label className={LABEL}>日志级别</label>
        <select value={logLevel} onChange={e => setLogLevel(e.target.value)} className={INPUT}>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
      </div>
      <button onClick={save} disabled={saving} className={BTN}>{saving ? "保存中..." : "保存"}</button>
    </div>
  );
}

/* ── 备份与迁移 ── */
function SettingsBackup({ show }: { show: ShowFn }) {
  const exportCfg = async () => {
    try {
      const d = await apiGet<any>("/api/desktop/config");
      const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "naixi-config.json";
      a.click();
      show("配置已导出");
    } catch { show("导出失败", "err"); }
  };
  const importCfg = () => {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = "application/json";
    inp.onchange = async () => {
      const file = inp.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const cfg = JSON.parse(text);
        await apiPost("/api/desktop/config", cfg);
        show("配置已导入");
      } catch { show("导入失败，文件格式错误", "err"); }
    };
    inp.click();
  };
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>备份与迁移</p>
      <p className="text-xs text-sakura-400">导出当前全部配置为 JSON 文件，或从备份文件恢复。</p>
      <div className="flex gap-2">
        <button onClick={exportCfg} className={BTN}>导出配置</button>
        <button onClick={importCfg} className={BTN_GHOST}>导入配置</button>
      </div>
    </div>
  );
}

/* ── 安全 ── */
function SettingsSecurity() {
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>安全设置</p>
      <div className={`${CARD} p-4 space-y-3 text-xs`}>
        <Row k="CORS 策略" v="*（允许所有来源，仅本地使用）" />
        <Row k="API Key 加密" v="Fernet 对称加密（机器 UUID 派生密钥）" />
        <Row k="密钥存储" v="SQLite desktop_config 表（加密后存储）" />
      </div>
    </div>
  );
}

/* ── 关于 ── */
function SettingsAbout() {
  const [ver, setVer] = useState("加载中...");
  const [tools, setTools] = useState<number | null>(null);
  useEffect(() => {
    apiGet<any>("/api/status").then(d => {
      setVer(d.version || "未知");
      if (typeof d.tools === "number") setTools(d.tools);
    }).catch(() => setVer("无法获取"));
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <p className={HEAD}>关于</p>
      <div className={`${CARD} p-4 space-y-2 text-xs`}>
        <Row k="版本" v={ver} />
        <Row k="已加载工具" v={tools === null ? "-" : `${tools} 个`} />
        <Row k="技术栈" v="Python + React + Tauri + Godot" />
        <Row k="项目" v="naixi_desktop" />
      </div>
    </div>
  );
}
