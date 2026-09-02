import { useState, useEffect, useCallback } from "react";
import {
  Cpu, Cat, Mic, Search, HardDrive, Server,
  Palette, DatabaseBackup, ShieldCheck, Info, Check, X, Lock, Download,
} from "lucide-react";
import ProviderSettings from "./ProviderSettings";
import ThemeSettings from "./ThemeSettings";
import { apiGet, apiPost } from "@/lib/api";
import { SPONSOR_REAL_NAME, SPONSOR_QR, sha256Hex } from "@/lib/sponsorIntegrity";
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
  { key: "update",    label: "更新",       icon: Download },
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
          {tab === "update" && <SettingsUpdate />}
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
  const [tampered, setTampered] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      for (const k of ["wechat", "alipay"] as const) {
        const b64 = SPONSOR_QR[k].b64;
        if (!b64) continue;
        try {
          const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
          const h = await sha256Hex(bin);
          if (h !== SPONSOR_QR[k].sha256) { if (!cancelled) setTampered(true); return; }
        } catch { if (!cancelled) setTampered(true); return; }
      }
      if (!cancelled) setTampered(false);
    })();
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    apiGet<any>("/api/status").then(d => {
      setVer(d.version || "未知");
      if (typeof d.tools === "number") setTools(d.tools);
    }).catch(() => setVer("无法获取"));
  }, []);
  const openRepo = async () => {
    // 开源仓库（GitHub）：代码托管 + 技术交流 + Issue/PR 主入口。
    // GitHub Sponsors 在中国大陆不可用，故收款走下方微信/支付宝收款码。
    const url = "https://github.com/Hayliy/naixi-desktop";
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_url", { url });
    } catch { try { window.open(url); } catch {} }
  };
  return (
    <>
    <Section title="关于" desc="版本与运行环境信息">
      <InfoRow label="版本" value={ver} />
      <InfoRow label="已加载工具" value={tools === null ? "-" : `${tools} 个`} />
      <InfoRow label="技术栈" value="Python + React + Tauri + Godot" />
      <InfoRow label="项目" value="naixi_desktop" />
      <SettingRow label="开源仓库" desc="GitHub：源码 / 技术交流 / 提交 Issue 与 PR（GitHub Sponsors 在中国大陆不可用，收款见下方赞助）">
        <button onClick={openRepo} className={BTN_GHOST}>在 GitHub 查看 ↗</button>
      </SettingRow>
    </Section>
    <Section title="赞助支持" desc="如果这个项目对你有帮助，欢迎赞助作者（微信 / 支付宝，国内最正规的个人收款方式）">
      <div className="mt-1 rounded-lg border border-dashed border-sakura-200 bg-sakura-50/40 p-3">
        <div className="mb-2 text-xs font-semibold text-sakura-500">扫码赞助（微信 / 支付宝）</div>
        <div className="flex gap-4">
          {(["wechat", "alipay"] as const).map((k) => (
            <div key={k} className="flex flex-col items-center">
              <img
                src={`data:image/png;base64,${SPONSOR_QR[k].b64}`}
                alt={k}
                className="h-28 w-28 rounded-lg border border-sakura-100 bg-white object-contain"
              />
              <span className="mt-1 text-[10px] text-sakura-300">{k === "wechat" ? "微信" : "支付宝"}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-sakura-400">收款人：<span className="font-semibold text-sakura-500">{SPONSOR_REAL_NAME}</span></p>
        {tampered ? (
          <p className="mt-2 rounded bg-red-50 px-2 py-1 text-[10px] font-semibold text-red-600">
            ⚠️ 收款码完整性校验未通过，可能被篡改。请只从官方 GitHub Releases 下载安装包，并核对收款人姓名。
          </p>
        ) : (
          <p className="mt-1 text-[10px] text-amber-500">✅ 收款码完整性校验通过。付款前仍请核对收款人姓名与上方一致再支付——姓名是最后一道人工防线。</p>
        )}
      </div>
    </Section>
    <SecurityScanCard />
    <SelfIntegrityCard />
    <FirstAidCard />
    <SentinelCard />
    </>
  );
}

/* ── 银狐应急哨兵面板（用户态痕迹检测 + 一键引导专业处置）── */
function SecurityScanCard() {
  const [scan, setScan] = useState<null | { risk: string; checks: any[]; note: string }>(null);
  const [scanning, setScanning] = useState(false);
  const runScan = async () => {
    setScanning(true);
    try {
      const d = await apiGet<any>("/api/security_scan");
      setScan(d);
    } catch {
      setScan({ risk: "error", checks: [], note: "扫描失败：无法连接后端 API（请确认桌宠已启动）。" });
    } finally {
      setScanning(false);
    }
  };
  const openUrl = async (url: string) => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_url", { url });
    } catch {
      try { window.open(url); } catch { /* noop */ }
    }
  };
  const [remediating, setRemediating] = useState(false);
  const [remResult, setRemResult] = useState<null | { summary: string; actions: any[]; note: string }>(null);
  const doRemediate = async () => {
    if (!window.confirm("确定要移除检测到的银狐用户态痕迹？\n将结束相关进程、删除可疑计划任务、恢复被篡改的 Defender 排除项。\n（内核级 rootkit 用户态清不掉，仍需专业杀软 + 安全模式）")) return;
    setRemediating(true);
    try {
      const d = await apiPost<any>("/api/security_remediate", {});
      setRemResult(d);
    } catch {
      setRemResult({ summary: "急救失败", actions: [], note: "无法连接后端 API，请确认桌宠已启动；移除 Defender 排除项可能需要以管理员身份运行。" });
    } finally {
      setRemediating(false);
    }
  };
  const riskColor = scan
    ? scan.risk === "danger" ? "text-red-600"
      : scan.risk === "warn" ? "text-amber-600"
      : scan.risk === "safe" ? "text-green-600"
      : "text-gray-500"
    : "text-gray-500";
  const riskText = scan
    ? scan.risk === "danger" ? "⚠️ 发现高危银狐痕迹"
      : scan.risk === "warn" ? "⚠️ 发现可疑痕迹"
      : scan.risk === "safe" ? "✅ 未发现已知银狐痕迹"
      : scan.risk === "skipped" ? "已跳过（非 Windows 平台）"
      : scan.risk === "error" ? "检测异常" : "未扫描"
    : "未扫描";
  return (
    <Section title="安全急救 · 银狐应急哨兵" desc="检测本机是否残留银狐类木马的用户态痕迹。用户态前哨——非内核查杀，内核级 rootkit 需专业杀软 + 安全模式。">
      <div className="rounded-lg border border-dashed border-sakura-200 bg-sakura-50/40 p-3">
        <button onClick={runScan} disabled={scanning} className={BTN_GHOST}>
          {scanning ? "扫描中…" : "立即扫描本机"}
        </button>
        {scan && (
          <div className="mt-2">
            <p className={`text-xs font-semibold ${riskColor}`}>{riskText}</p>
            <ul className="mt-1 space-y-1">
              {scan.checks.map((c: any, i: number) => (
                <li key={i} className="text-[10px] text-gray-600">
                  <span className={c.level === "danger" ? "text-red-600" : c.level === "warn" ? "text-amber-600" : "text-green-600"}>
                    {c.level === "danger" ? "❌" : c.level === "warn" ? "⚠️" : "✅"}
                  </span>{" "}
                  {c.name}：{c.detail}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-gray-500">{scan.note}</p>
            {(scan.risk === "danger" || scan.risk === "warn") && (
              <button onClick={doRemediate} disabled={remediating} className="mt-2 rounded bg-red-500 px-3 py-1 text-[11px] font-semibold text-white hover:bg-red-600 disabled:opacity-50">
                {remediating ? "急救中…" : "🛡️ 一键急救（移除用户态痕迹）"}
              </button>
            )}
            {remResult && (
              <div className="mt-2 rounded bg-gray-50 p-2 text-[10px]">
                <p className="font-semibold text-gray-700">{remResult.summary}</p>
                <ul className="mt-1 space-y-0.5">
                  {remResult.actions.map((a: any, i: number) => (
                    <li key={i} className={a.status === "done" ? "text-green-600" : a.status === "failed" || a.status === "error" ? "text-red-600" : "text-gray-500"}>
                      {a.status === "done" ? "✅" : a.status === "skipped" ? "⏭️" : "❌"} {a.kind}：{a.target}{a.msg ? " — " + a.msg : ""}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-gray-500">{remResult.note}</p>
              </div>
            )}
            {scan.risk === "danger" && (
              <div className="mt-2 rounded bg-red-50 p-2 text-[10px] text-red-600">
                <p className="font-semibold">应急动作（请立即执行）：</p>
                <ol className="list-decimal pl-4">
                  <li>断网（拔网线 / 关 Wi-Fi），阻止数据外泄</li>
                  <li>用其他安全设备修改微信 / QQ / 支付宝 / 邮箱密码</li>
                  <li>重启进安全模式，用专业杀软全盘查杀</li>
                </ol>
                <div className="mt-1 flex flex-wrap gap-2">
                  <button onClick={() => openUrl("https://www.huorong.cn")} className={BTN_GHOST}>火绒官网 ↗</button>
                  <button onClick={() => openUrl("https://virus.cverc.org.cn")} className={BTN_GHOST}>国家病毒平台 ↗</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

/* ── 自身安装包哈希自检（防伪造安装包 / 整包替换）── */
function SelfIntegrityCard() {
  const [info, setInfo] = useState<null | { ok: boolean; sha256: string; exe_path: string; note: string }>(null);
  useEffect(() => {
    apiGet<any>("/api/self_hash").then(setInfo).catch(() => {});
  }, []);
  return (
    <Section title="安装包完整性 · 本程序哈希" desc="将此 SHA-256 与 GitHub Releases 的 sha256sums.txt 比对；不一致即安装包可能被伪造/替换。随包携带清单比对无意义（攻击者连清单一起换），故只暴露哈希供你人工核对。">
      <div className="rounded-lg border border-dashed border-sakura-200 bg-sakura-50/40 p-3">
        {!info && <p className="text-[10px] text-gray-500">读取中…</p>}
        {info && (
          <div className="text-[10px]">
            {info.ok ? (
              <>
                <p className="break-all font-mono text-gray-700">SHA-256: {info.sha256}</p>
                <p className="mt-1 text-gray-500">路径：{info.exe_path}</p>
                <p className="mt-1 text-amber-600">⚠️ 当前安装包未做代码签名（无 OV/EV 证书），SmartScreen 会提示「未知发布者」。请务必核对上方哈希与官方发布值一致后再使用。</p>
              </>
            ) : (
              <p className="text-red-600">读取失败：{info.note}</p>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

/* ── 360系统急救箱调用（官方正版 · 内核/rootkit 级强杀）── */
function FirstAidCard() {
  const [status, setStatus] = useState<string>("点击检测本机是否已安装 360急救箱");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<any>(null);
  const openUrl = async (url: string) => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_url", { url });
    } catch {
      try { window.open(url); } catch { /* noop */ }
    }
  };
  const detect = async () => {
    setBusy(true);
    try {
      const d = await apiPost<any>("/api/run_360box", {});
      if (d.ok) {
        setInfo({ ok: true, launched: d.launched, source: d.source });
        setStatus(d.source === "installed" ? "已启动本机安装的 360急救箱" : "已启动已校验的 360急救箱副本");
      } else {
        setInfo({ ok: false, error: d.error });
        setStatus("本机未安装 360急救箱，请先下载并校验");
      }
    } catch {
      setStatus("调用失败：请确认桌宠已启动");
    } finally { setBusy(false); }
  };
  const fetchBox = async () => {
    setBusy(true);
    setStatus("正在从 360 官方域名下载并校验数字签名…");
    try {
      const d = await apiPost<any>("/api/fetch_360box", {});
      if (d.ok) {
        setInfo({ ok: true, version: d.version, sha256: d.sha256, publisher: d.publisher, verified: d.verified });
        setStatus("下载并校验完成（官方正版）。可点『运行已下载副本』启动强杀。");
      } else {
        setInfo({ ok: false, error: d.error });
        setStatus("下载/校验失败，请用下方官网链接手动下载");
      }
    } catch {
      setStatus("下载失败：请确认网络或桌宠已启动");
    } finally { setBusy(false); }
  };
  const runDownloaded = async () => {
    setBusy(true);
    try {
      const d = await apiPost<any>("/api/run_360box", {});
      if (d.ok) setStatus("已启动 360急救箱（请在其界面勾选『强力模式 + 全盘扫描』）");
      else setStatus(d.error || "启动失败");
    } catch { setStatus("启动失败"); } finally { setBusy(false); }
  };
  return (
    <Section title="360系统急救箱 · 官方正版内核强杀" desc="360系统急救箱支持驱动型/MBR 型（内核 rootkit 层）强杀，是清理银狐顽固木马的靠谱专业工具。它是『按需急救』工具，非实时监测；真正的常驻实时防护请用 360安全卫士。">
      <div className="rounded-lg border border-dashed border-sakura-200 bg-sakura-50/40 p-3 space-y-2">
        <p className="text-[10px] text-gray-600">{status}</p>
        <div className="flex flex-wrap gap-2">
          <button onClick={detect} disabled={busy} className={BTN_GHOST}>检测并运行 360急救箱</button>
          <button onClick={fetchBox} disabled={busy} className={BTN_GHOST}>下载并校验 360急救箱（官方最新）</button>
          <button onClick={runDownloaded} disabled={busy} className="rounded bg-red-500 px-3 py-1 text-[11px] font-semibold text-white hover:bg-red-600 disabled:opacity-50">🛡️ 运行已下载副本</button>
        </div>
        {info && (
          <div className="text-[10px]">
            {info.ok && info.verified ? (
              <div className="rounded bg-green-50 p-2 text-green-700">
                <p>✅ 已校验为 360 官方正版（数字签名有效）</p>
                {info.version && <p>版本：{info.version}</p>}
                {info.sha256 && <p className="break-all font-mono">SHA-256: {info.sha256}</p>}
                {info.publisher && <p>签名主体：{info.publisher}</p>}
                {info.launched && <p>已启动：{info.launched}</p>}
              </div>
            ) : info.error ? (
              <p className="text-red-600">⚠️ {info.error}</p>
            ) : null}
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <button onClick={() => openUrl("https://weishi.360.cn/jijiuxiang/")} className={BTN_GHOST}>360急救箱官网 ↗</button>
          <button onClick={() => openUrl("https://weishi.360.cn/")} className={BTN_GHOST}>安装 360安全卫士（常驻防护）↗</button>
        </div>
        <p className="text-[10px] text-amber-600">⚠️ 下载仅来自官方域名 dl.360safe.com，启动前校验数字签名；非 360 签名的文件会被立即删除，防投毒反噬。建议定期从官网手动更新。</p>
      </div>
    </Section>
  );
}

/* ── 自动监测哨兵（后台周期扫描银狐用户态痕迹）── */
function SentinelCard() {
  const [st, setSt] = useState<any>(null);
  const [scanning, setScanning] = useState(false);
  const poll = async () => {
    try { const d = await apiGet<any>("/api/sentinel_status"); setSt(d); } catch { /* noop */ }
  };
  const nowScan = async () => {
    setScanning(true);
    try { await apiGet<any>("/api/security_scan"); await poll(); } catch { /* noop */ } finally { setScanning(false); }
  };
  useEffect(() => { poll(); const t = setInterval(poll, 30000); return () => clearInterval(t); }, []);
  const riskColor = !st ? "text-gray-500"
    : st.risk === "danger" ? "text-red-600"
    : st.risk === "warn" ? "text-amber-600"
    : st.risk === "safe" ? "text-green-600" : "text-gray-500";
  const riskText = !st ? "加载中…"
    : st.risk === "danger" ? "⚠️ 监测发现高危银狐痕迹"
    : st.risk === "warn" ? "⚠️ 监测发现可疑痕迹"
    : st.risk === "safe" ? "✅ 监测未发现问题" : "监测状态未知";
  return (
    <Section title="自动监测 · 银狐哨兵" desc="奶昔后台每 10 分钟自动扫描一次本机银狐用户态痕迹，命中即在此提示。用户态前哨——内核级 rootkit 仍需专业杀软 + 安全模式。">
      <div className="rounded-lg border border-dashed border-sakura-200 bg-sakura-50/40 p-3">
        <div className="flex items-center justify-between">
          <p className={`text-xs font-semibold ${riskColor}`}>{riskText}</p>
          <button onClick={nowScan} disabled={scanning} className={BTN_GHOST}>{scanning ? "扫描中…" : "立即扫描"}</button>
        </div>
        {st && (
          <p className="mt-1 text-[10px] text-gray-500">
            监测{st.running ? "运行中" : "已停止"} · 上次自动扫描：{st.last_scan || "—"} · 可疑项：{st.findings}
          </p>
        )}
        {st && st.risk === "danger" && (
          <p className="mt-2 rounded bg-red-50 px-2 py-1 text-[10px] font-semibold text-red-600">
            ⚠️ 发现高危痕迹！请立即断网、修改密码，并运行上方「360系统急救箱」强力模式 + 进安全模式全盘查杀。
          </p>
        )}
      </div>
    </Section>
  );
}

/* ── 更新源 ── */
function SettingsUpdate() {
  const [src, setSrc] = useState("");
  const [saving, setSaving] = useState(false);
  const { show, node } = useToast();
  useEffect(() => {
    apiGet<any>("/api/desktop/config").then(d => {
      if (d && typeof d.update_source === "string") setSrc(d.update_source);
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      await apiPost("/api/desktop/config", { update_source: src.trim() });
      show("更新源已保存");
    } catch { show("保存失败", "err"); }
    finally { setSaving(false); }
  };
  return (
    <Section title="版本更新源" desc="留空则默认从 GitHub Releases（Hayliy/naixi-desktop）检查更新；填写一个返回 {version, notes, url} 的 JSON 地址可覆盖默认源">
      <SettingRow label="自定义更新源" desc="返回最新版本信息的 JSON 地址（可选）">
        <input value={src} onChange={e => setSrc(e.target.value)} className={INPUT}
          placeholder="https://example.com/update.json（留空=默认 GitHub）" />
      </SettingRow>
      <p className="text-[10px] text-sakura-400 mt-1">默认更新源：https://github.com/Hayliy/naixi-desktop/releases</p>
      <SaveBar saving={saving} onSave={save} />
    </Section>
  );
}
