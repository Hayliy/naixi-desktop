import { useState, useEffect, useCallback } from "react";
import {
  Cpu, Cat, Mic, Search, HardDrive, Server,
  Palette, DatabaseBackup, ShieldCheck, Info, Check, X, Lock,
} from "lucide-react";
import ProviderSettings from "./ProviderSettings";
import ThemeSettings from "./ThemeSettings";
import { apiGet, apiPost } from "@/lib/api";
import { INPUT, BTN, BTN_GHOST, Section, SettingRow, InfoRow, SaveBar } from "./settings/primitives";

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
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-2xl">
          {tab === "model" && <SettingsModel />}
          {tab === "pet" && <SettingsPet show={show} />}
          {tab === "voice" && <SettingsVoice show={show} />}
          {tab === "search" && <SettingsSearch show={show} />}
          {tab === "storage" && <SettingsStorage />}
          {tab === "system" && <SettingsSystem show={show} />}
          {tab === "interface" && (
            <Section title="界面与主题" desc="切换明暗主题与配色">
              <ThemeSettings />
            </Section>
          )}
          {tab === "backup" && <SettingsBackup show={show} />}
          {tab === "security" && <SettingsSecurity />}
          {tab === "about" && <SettingsAbout />}
        </div>
      </div>
      {node}
    </div>
  );
}

/* ── 模型 ── */
function SettingsModel() {
  return (
    <Section title="模型供应商" desc="配置各模型的 API Key 与默认调用模型">
      <ProviderSettings />
    </Section>
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
    <Section title="桌宠设置" desc="控制虚拟形象的渲染方式与语音">
      <SettingRow label="渲染模式" desc="Live2D 或 VRM 三维模型">
        <select value={mode} onChange={e => setMode(e.target.value)} className={INPUT}>
          <option value="live2d">Live2D</option>
          <option value="vrm">VRM (Godot)</option>
        </select>
      </SettingRow>
      <SettingRow label="模型文件路径" desc="桌宠模型资源的本地路径">
        <input value={modelPath} onChange={e => setModelPath(e.target.value)} className={INPUT} placeholder="留空则自动发现" />
      </SettingRow>
      <SettingRow label="TTS 引擎" desc="桌宠说话使用的合成引擎">
        <select value={ttsEngine} onChange={e => setTtsEngine(e.target.value)} className={INPUT}>
          <option value="cosyvoice">CosyVoice (百炼)</option>
          <option value="edge-tts">Edge TTS</option>
        </select>
      </SettingRow>
      <SaveBar onSave={save} saving={saving} />
    </Section>
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
    <Section title="朗读设置" desc="控制奶昔说话使用的引擎与音色">
      <SettingRow label="朗读模式" desc="选择本地或云端 TTS 引擎">
        <select value={mode} onChange={e => setMode(e.target.value)} className={INPUT}>
          <option value="browser">浏览器内置</option>
          <option value="edge-tts">Edge TTS</option>
          <option value="cosyvoice">CosyVoice (百炼)</option>
        </select>
      </SettingRow>
      <SettingRow label="默认音色" desc="合成语音使用的音色标识">
        <input value={voice} onChange={e => setVoice(e.target.value)} className={INPUT} />
      </SettingRow>
      <SaveBar onSave={save} saving={saving} />
    </Section>
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
    <Section title="搜索设置" desc="配置联网搜索使用的检索服务">
      <SettingRow label="SearXNG 地址" desc="本地或远程 SearXNG 实例的 URL">
        <input value={searxng} onChange={e => setSearxng(e.target.value)} className={INPUT} />
      </SettingRow>
      <SaveBar onSave={save} saving={saving} />
    </Section>
  );
}

/* ── 文件与存储（真实路径）── */
function SettingsStorage() {
  const [p, setP] = useState<any>(null);
  useEffect(() => {
    apiGet<any>("/api/desktop/paths").then(setP).catch(() => setP({ error: true }));
  }, []);
  return (
    <Section title="文件与存储" desc="数据库与日志的本地位置">
      {!p && <p className="text-sm text-sakura-400 py-3 border-t border-sakura-200/50">加载中...</p>}
      {p?.error && <p className="text-sm text-sakura-400 py-3 border-t border-sakura-200/50">无法获取路径信息</p>}
      {p && !p.error && <>
        <InfoRow label="数据库路径" value={p.db_path} mono />
        <InfoRow label="数据库大小" value={`${p.db_size_mb} MB`} />
        <InfoRow label="日志目录" value={p.logs_dir} mono />
        <InfoRow label="模型目录" value={p.models_dir} mono />
        <InfoRow label="日志保留" value={`${p.log_keep_days} 天`} />
      </>}
    </Section>
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
    <Section title="系统与环境" desc="后端服务与日志相关配置">
      <SettingRow label="服务端口" desc="改动需重启后端生效">
        <div className="flex items-center gap-2 min-w-[180px]">
          <input value={port} readOnly className={`${INPUT} opacity-60 cursor-not-allowed flex-1`} />
          <Lock className="w-3.5 h-3.5 text-sakura-300 shrink-0" />
        </div>
      </SettingRow>
      <SettingRow label="日志级别" desc="控制后端日志输出的详细程度">
        <select value={logLevel} onChange={e => setLogLevel(e.target.value)} className={INPUT}>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
      </SettingRow>
      <SaveBar onSave={save} saving={saving} />
    </Section>
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
    <Section title="备份与迁移" desc="导出当前全部配置为 JSON 文件，或从备份文件恢复">
      <SettingRow label="导出配置" desc="将全部配置保存为 naixi-config.json">
        <button onClick={exportCfg} className={BTN}>导出配置</button>
      </SettingRow>
      <SettingRow label="导入配置" desc="从备份文件恢复配置（会覆盖当前值）">
        <button onClick={importCfg} className={BTN_GHOST}>选择文件</button>
      </SettingRow>
    </Section>
  );
}

/* ── 安全 ── */
function SettingsSecurity() {
  return (
    <Section title="安全设置" desc="数据加密与访问策略（只读）">
      <InfoRow label="CORS 策略" value="*（允许所有来源，仅本地使用）" />
      <InfoRow label="API Key 加密" value="Fernet 对称加密（机器 UUID 派生密钥）" />
      <InfoRow label="密钥存储" value="SQLite desktop_config 表（加密后存储）" />
    </Section>
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
    <Section title="关于" desc="版本与运行环境信息">
      <InfoRow label="版本" value={ver} />
      <InfoRow label="已加载工具" value={tools === null ? "-" : `${tools} 个`} />
      <InfoRow label="技术栈" value="Python + React + Tauri + Godot" />
      <InfoRow label="项目" value="naixi_desktop" />
    </Section>
  );
}
