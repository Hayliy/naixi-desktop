import { useState, useEffect } from "react";
import ProviderSettings from "./ProviderSettings";
import PromptPanel from "./PromptPanel";
import ThemeSettings from "./ThemeSettings";
import PreferencesPanel from "./PreferencesPanel";
import { apiGet, apiPost } from "@/lib/api";

const TABS = [
  { key: "model",     label: "模型" },
  { key: "pet",       label: "桌宠" },
  { key: "voice",     label: "语音" },
  { key: "search",    label: "搜索" },
  { key: "storage",   label: "文件与存储" },
  { key: "system",    label: "系统与环境" },
  { key: "interface", label: "界面" },
  { key: "backup",    label: "备份与迁移" },
  { key: "security",  label: "安全" },
  { key: "about",     label: "关于" },
];

export default function SettingsPage() {
  const [tab, setTab] = useState("model");

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 px-4 pt-3 pb-0 border-b border-sakura-200/30 overflow-x-auto">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 text-xs rounded-t-lg whitespace-nowrap transition-colors ${
              tab === t.key
                ? "bg-sakura-100 text-sakura-700 font-medium"
                : "text-gray-400 hover:text-sakura-500"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {tab === "model" && <SettingsModel />}
        {tab === "pet" && <SettingsPet />}
        {tab === "voice" && <SettingsVoice />}
        {tab === "search" && <SettingsSearch />}
        {tab === "storage" && <SettingsStorage />}
        {tab === "system" && <SettingsSystem />}
        {tab === "interface" && <ThemeSettings />}
        {tab === "backup" && <SettingsBackup />}
        {tab === "security" && <SettingsSecurity />}
        {tab === "about" && <SettingsAbout />}
      </div>
    </div>
  );
}

/* ── 模型 ── */
function SettingsModel() {
  return (
    <div className="space-y-6">
      <p className="text-sm font-semibold text-sakura-500">模型供应商与默认配置</p>
      <ProviderSettings />
    </div>
  );
}

/* ── 桌宠 ── */
function SettingsPet() {
  const [mode, setMode] = useState("live2d");
  const [modelPath, setModelPath] = useState("");
  const [ttsEngine, setTtsEngine] = useState("cosyvoice");
  useEffect(() => {
    fetch("/api/live/config").then(r => r.json().then(d => {
      if (d.render_mode) setMode(d.render_mode);
      if (d.model_path) setModelPath(d.model_path);
      if (d.tts_engine) setTtsEngine(d.tts_engine);
    })).catch(() => {});
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">桌宠设置</p>
      <div>
        <label className="text-xs text-gray-400">渲染模式</label>
        <select value={mode} onChange={e => setMode(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm">
          <option value="live2d">Live2D</option>
          <option value="vrm">VRM (Godot)</option>
        </select>
      </div>
      <div>
        <label className="text-xs text-gray-400">模型文件路径</label>
        <input value={modelPath} onChange={e => setModelPath(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm" />
      </div>
      <div>
        <label className="text-xs text-gray-400">TTS 引擎</label>
        <select value={ttsEngine} onChange={e => setTtsEngine(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm">
          <option value="cosyvoice">CosyVoice (百炼)</option>
          <option value="edge-tts">Edge TTS</option>
        </select>
      </div>
      <button onClick={() => apiPost("/api/live/save-config", { render_mode: mode, model_path: modelPath, tts_engine: ttsEngine })}
        className="px-4 py-1.5 bg-sakura-500 text-white rounded-lg text-sm">保存</button>
    </div>
  );
}

/* ── 语音 ── */
function SettingsVoice() {
  const [engine, setEngine] = useState("cosyvoice");
  const [voice, setVoice] = useState("longfeifei_v3");
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">语音设置</p>
      <div>
        <label className="text-xs text-gray-400">TTS 引擎</label>
        <select value={engine} onChange={e => setEngine(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm">
          <option value="cosyvoice">CosyVoice (百炼)</option>
          <option value="edge-tts">Edge TTS</option>
        </select>
      </div>
      <div>
        <label className="text-xs text-gray-400">默认音色</label>
        <input value={voice} onChange={e => setVoice(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm" />
      </div>
    </div>
  );
}

/* ── 搜索 ── */
function SettingsSearch() {
  const [searxng, setSearxng] = useState("http://127.0.0.1:8899");
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">搜索设置</p>
      <div>
        <label className="text-xs text-gray-400">SearXNG 地址</label>
        <input value={searxng} onChange={e => setSearxng(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm" />
      </div>
    </div>
  );
}

/* ── 文件与存储 ── */
function SettingsStorage() {
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">文件与存储</p>
      <div className="bg-[#1a1a2e] rounded-xl p-4 space-y-3 text-xs text-gray-300">
        <div className="flex justify-between"><span>数据库路径</span><span className="text-sakura-300 font-mono">D:\naixi_desktop\data\naixi_desktop.db</span></div>
        <div className="flex justify-between"><span>日志文件</span><span className="text-sakura-300 font-mono">D:\naixi_desktop\logs\</span></div>
        <div className="flex justify-between"><span>模型缓存</span><span className="text-sakura-300 font-mono">D:\naixi_desktop\models\</span></div>
        <div className="flex justify-between"><span>日志保留</span><span className="text-sakura-300">7 天</span></div>
      </div>
    </div>
  );
}

/* ── 系统与环境 ── */
function SettingsSystem() {
  const [port, setPort] = useState("9845");
  const [logLevel, setLogLevel] = useState("INFO");
  useEffect(() => {
    fetch("/api/status").then(r => r.json().then(d => {
      if (d.port) setPort(String(d.port));
    })).catch(() => {});
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">系统与环境</p>
      <div>
        <label className="text-xs text-gray-400">服务端口</label>
        <input value={port} onChange={e => setPort(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm" />
      </div>
      <div>
        <label className="text-xs text-gray-400">日志级别</label>
        <select value={logLevel} onChange={e => setLogLevel(e.target.value)}
          className="w-full mt-1 bg-[#1a1a2e] border border-sakura-200/20 rounded-lg px-3 py-2 text-sm">
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
      </div>
    </div>
  );
}

/* ── 备份与迁移 ── */
function SettingsBackup() {
  const [status, setStatus] = useState("");
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">备份与迁移</p>
      <button onClick={() => {
        fetch("/api/desktop/config").then(r => r.json()).then(d => {
          const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
          const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "naixi-config.json"; a.click();
          setStatus("配置已导出");
        }).catch(() => setStatus("导出失败"));
      }}
        className="px-4 py-1.5 bg-sakura-500 text-white rounded-lg text-sm mr-2">导出配置</button>
      <button onClick={() => setStatus("功能开发中")}
        className="px-4 py-1.5 border border-sakura-200/30 text-sakura-300 rounded-lg text-sm">导入配置</button>
      {status && <p className="text-xs text-sakura-400">{status}</p>}
    </div>
  );
}

/* ── 安全 ── */
function SettingsSecurity() {
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">安全设置</p>
      <div className="bg-[#1a1a2e] rounded-xl p-4 space-y-3 text-xs text-gray-300">
        <div className="flex justify-between"><span>CORS</span><span className="text-sakura-300">*（所有来源）</span></div>
        <div className="flex justify-between"><span>API Key 加密</span><span className="text-sakura-300">AES-256</span></div>
      </div>
    </div>
  );
}

/* ── 关于 ── */
function SettingsAbout() {
  const [ver, setVer] = useState("加载中...");
  useEffect(() => {
    fetch("/api/status").then(r => r.json().then(d => {
      setVer(d.version || "未知");
    })).catch(() => setVer("无法获取"));
  }, []);
  return (
    <div className="space-y-4 max-w-xl">
      <p className="text-sm font-semibold text-sakura-500">关于</p>
      <div className="bg-[#1a1a2e] rounded-xl p-4 space-y-2 text-xs text-gray-300">
        <div className="flex justify-between"><span>版本</span><span className="text-sakura-300">{ver}</span></div>
        <div className="flex justify-between"><span>技术栈</span><span className="text-sakura-300">Python + React + Tauri + Godot</span></div>
        <div className="flex justify-between"><span>项目地址</span><span className="text-sakura-300">naixi_desktop</span></div>
      </div>
    </div>
  );
}
