import { useState, useEffect, useCallback } from "react";
import {
  Network, RefreshCw, Trash2, Shield, ShieldAlert, Loader2, Zap, Cpu, Radio,
  Plus, Check, X, Copy, KeyRound, ChevronDown, ChevronRight, AlertTriangle,
  Eye, EyeOff, Dices,
} from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";

/* ─── Gateway 对等互联页 ───
   左侧：本端状态 / 对端列表 / 能力清单
   右侧：**可操作的接入面板** —— 让任何第三方（Claude Code / Cursor / 手搓脚本）
         都能连进来，用户只需「复制一段配置」或「填一个 token」。

   后端端点：
     GET  /api/gateway/status          → Hub 状态 + peers
     GET  /api/gateway/capabilities    → 能力清单（含 disabled）
     GET  /api/gateway/access          → 接入信息聚合（地址/端口/token状态/配置片段）
     POST /api/gateway/capabilities    → 注册/更新一条能力（支持自定义）
     POST /api/gateway/capability/toggle→ 启用/停用
     POST /api/gateway/capability/delete → 注销
*/

type Trust = "read" | "write" | "dangerous";

interface Cap {
  id: string;
  provider: string;
  kind: string;
  title: string;
  description: string;
  endpoint: string;
  trust: Trust;
  requires_confirm: boolean;
  enabled: boolean;
  updated_at: string;
  schema?: { type?: string; properties?: Record<string, { type?: string; description?: string }> };
  meta?: { http_method?: string; query_params?: string[] };
}

interface Peer {
  provider: string;
  remote?: string;
  subs?: string[];
  idle_s?: number;
}

interface AccessInfo {
  ok: boolean;
  provider: string;
  http_port: number;
  ws_port: number;
  ws_path: string;
  ws_host: string;
  ws_lan_reachable: boolean;
  ws_token_configured: boolean;
  ws_token_count: number;
  lan_ip: string;
  localhost_url: string;
  lan_url: string;
  ws_localhost: string;
  ws_lan: string;
  mcp: { running: boolean; port: number; tools: number; token_configured: boolean; token_count: number; needs_token_for_lan: boolean };
  configs: Record<string, string>;
}

const TRUST_STYLE: Record<Trust, { label: string; cls: string; Icon: typeof Shield }> = {
  read: { label: "只读", cls: "text-green-600 bg-green-50 border-green-100", Icon: Shield },
  write: { label: "可写", cls: "text-yellow-600 bg-yellow-50 border-yellow-100", Icon: ShieldAlert },
  dangerous: { label: "危险", cls: "text-red-600 bg-red-50 border-red-100", Icon: ShieldAlert },
};

const TRUST_OPTIONS: Trust[] = ["read", "write", "dangerous"];
const KIND_OPTIONS = ["tool", "channel", "task"];

function fmtIdle(sec?: number) {
  const s = sec ?? 0;
  if (s < 60) return `${Math.round(s)} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  return `${Math.floor(s / 3600)} 小时前`;
}

/** 复制到剪贴板。navigator.clipboard 在非安全上下文（http://127.0.0.1 之外的
 *  http 局域网地址）会被浏览器拒绝，故降级到 textarea + execCommand。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* 落到降级路径 */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/* ── 右侧：单个「复制块」 ── */
function CopyBlock({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const { notify } = useToast();
  const [copied, setCopied] = useState(false);
  const doCopy = async () => {
    const ok = await copyText(value);
    if (ok) {
      setCopied(true);
      notify(`已复制${label}`, "success");
      setTimeout(() => setCopied(false), 1500);
    } else {
      notify("复制失败，请手动选中下方文本复制", "error");
    }
  };
  return (
    <div className="border border-sakura-100 rounded-lg overflow-hidden">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-sakura-50/60 border-b border-sakura-100">
        <span className="text-[11px] font-medium text-sakura-600">{label}</span>
        {hint && <span className="text-[10px] text-sakura-400 truncate">{hint}</span>}
        <button onClick={doCopy}
          className={`ml-auto flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-colors shrink-0 ${
            copied ? "text-green-600 bg-green-50" : "text-sakura-400 hover:bg-white hover:text-sakura-600"
          }`}>
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre className="px-2.5 py-2 text-[10px] font-mono text-sakura-600 bg-white
                       whitespace-pre-wrap break-all leading-relaxed max-h-40 overflow-y-auto">
        {value}
      </pre>
    </div>
  );
}

/* ── 行内小复制按钮 ── */
function CopyBtn({ text, label }: { text: string; label: string }) {
  const { notify } = useToast();
  const [done, setDone] = useState(false);
  return (
    <button onClick={async () => {
      const ok = await copyText(text);
      if (ok) { setDone(true); notify(`已复制${label}`, "success"); setTimeout(() => setDone(false), 1500); }
      else notify("复制失败，请手动选中复制", "error");
    }} disabled={!text}
      className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-colors ${
        done ? "text-green-600 bg-green-50" : "text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600"}`}>
      {done ? <Check size={10} /> : <Copy size={10} />} {done ? "已复制" : "复制"}
    </button>
  );
}

/* ── 右侧：自定义能力注册表单 ── */
function AddCapabilityForm({ onDone }: { onDone: () => void }) {
  const { notify } = useToast();
  // 默认展开：用户诉求是「页面要有能填的东西」。
  // 折叠起来虽然更清爽，但进来看到的是一片只读清单 —— 感受上跟没改一样。
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    id: "", title: "", description: "", endpoint: "",
    kind: "tool", trust: "read" as Trust, requires_confirm: false,
  });
  const set = (k: keyof typeof f, v: any) => setF((p) => ({ ...p, [k]: v }));

  const submit = async () => {
    if (!f.id.trim() || !f.endpoint.trim()) {
      notify("能力 ID 与端点不能为空", "error");
      return;
    }
    setBusy(true);
    try {
      const r = await apiPost<any>("/api/gateway/capabilities", { ...f, id: f.id.trim() });
      if (r?.ok) {
        notify(`能力 ${f.id} 已注册`, "success");
        setF({ id: "", title: "", description: "", endpoint: "", kind: "tool", trust: "read", requires_confirm: false });
        setOpen(false);
        onDone();
      } else {
        notify(`注册失败：${(r?.errors || []).join("; ") || r?.error || "未知"}`, "error");
      }
    } catch (e) {
      notify(`注册异常：${String(e).slice(0, 100)}`, "error");
    }
    setBusy(false);
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg
                   border border-dashed border-sakura-200 text-[11px] text-sakura-400
                   hover:border-sakura-400 hover:text-sakura-600 transition-colors">
        <Plus size={12} /> 注册自定义能力
      </button>
    );
  }

  const label = "block text-[10px] text-sakura-400 mb-1";
  const input = "w-full px-2 py-1.5 rounded-lg border border-sakura-100 bg-white text-[12px] " +
                "text-sakura-700 outline-none focus:border-sakura-300";

  return (
    <div className="space-y-2 border border-sakura-100 rounded-lg p-2.5 bg-sakura-50/40">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-sakura-600">注册自定义能力</span>
        <button onClick={() => setOpen(false)} className="text-sakura-300 hover:text-sakura-500">
          <X size={12} />
        </button>
      </div>
      <div>
        <span className={label}>能力 ID（唯一，建议 domain.action 格式）</span>
        <input className={input} value={f.id} placeholder="custom.my_action"
          onChange={(e) => set("id", e.target.value)} />
      </div>
      <div>
        <span className={label}>显示名称</span>
        <input className={input} value={f.title} placeholder="我的动作"
          onChange={(e) => set("title", e.target.value)} />
      </div>
      <div>
        <span className={label}>描述（会进入对端的工具检索，务必写清用途）</span>
        <input className={input} value={f.description} placeholder="做什么用的，谁该用它"
          onChange={(e) => set("description", e.target.value)} />
      </div>
      <div>
        <span className={label}>端点路径（本服务内相对路径）</span>
        <input className={input} value={f.endpoint} placeholder="/api/xxx"
          onChange={(e) => set("endpoint", e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className={label}>类型</span>
          <select className={input} value={f.kind} onChange={(e) => set("kind", e.target.value)}>
            {KIND_OPTIONS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
        <div>
          <span className={label}>权限等级</span>
          <select className={input} value={f.trust} onChange={(e) => set("trust", e.target.value)}>
            {TRUST_OPTIONS.map((t) => <option key={t} value={t}>{TRUST_STYLE[t].label}</option>)}
          </select>
        </div>
      </div>
      <label className="flex items-center gap-1.5 text-[11px] text-sakura-500 cursor-pointer">
        <input type="checkbox" checked={f.requires_confirm}
          onChange={(e) => set("requires_confirm", e.target.checked)} />
        需要人工确认后才能执行
      </label>
      <div className="flex gap-1.5">
        <button onClick={submit} disabled={busy}
          className="flex-1 py-1.5 rounded-lg bg-sakura-500 text-white text-[11px] font-medium
                     hover:bg-sakura-600 transition-colors disabled:opacity-50">
          {busy ? "注册中…" : "确认注册"}
        </button>
        <button onClick={() => setOpen(false)}
          className="px-3 py-1.5 rounded-lg border border-sakura-200 text-[11px] text-sakura-500 hover:bg-white">
          取消
        </button>
      </div>
    </div>
  );
}

/* ── 右侧：能力详情编辑器 ── */
function CapEditor({ cap, onClose, onSaved }: {
  cap: Cap; onClose: () => void; onSaved: () => void;
}) {
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState<Trust>(cap.trust);
  const [rc, setRc] = useState(cap.requires_confirm);
  const [title, setTitle] = useState(cap.title);
  const [desc, setDesc] = useState(cap.description);

  const save = async () => {
    setBusy(true);
    try {
      const r = await apiPost<any>("/api/gateway/capabilities", {
        ...cap, trust: t, requires_confirm: rc, title, description: desc,
      });
      if (r?.ok) {
        notify(`${cap.id} 已更新`, "success");
        onSaved();
        onClose();
      } else {
        notify(`更新失败：${(r?.errors || []).join("; ") || r?.error || "未知"}`, "error");
      }
    } finally {
      setBusy(false);
    }
  };

  const input = "w-full px-2 py-1.5 rounded-lg border border-sakura-100 bg-white text-[12px] " +
                "text-sakura-700 outline-none focus:border-sakura-300";

  return (
    <div className="border border-sakura-200 rounded-lg p-2.5 bg-sakura-50/50 space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-sakura-400">编辑</span>
        <span className="text-[11px] font-mono text-sakura-600 truncate">{cap.id}</span>
        <button onClick={onClose} className="ml-auto text-sakura-300 hover:text-sakura-500 shrink-0">
          <X size={12} />
        </button>
      </div>
      <div>
        <span className="block text-[10px] text-sakura-400 mb-1">显示名称</span>
        <input className={input} value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <span className="block text-[10px] text-sakura-400 mb-1">描述</span>
        <input className={input} value={desc} onChange={(e) => setDesc(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className="block text-[10px] text-sakura-400 mb-1">权限等级</span>
          <select className={input} value={t} onChange={(e) => setT(e.target.value as Trust)}>
            {TRUST_OPTIONS.map((x) => <option key={x} value={x}>{TRUST_STYLE[x].label}</option>)}
          </select>
        </div>
        <label className="flex items-end gap-1.5 pb-1.5 text-[11px] text-sakura-500 cursor-pointer">
          <input type="checkbox" checked={rc} onChange={(e) => setRc(e.target.checked)} />
          需人工确认
        </label>
      </div>
      <button onClick={save} disabled={busy}
        className="w-full py-1.5 rounded-lg bg-sakura-500 text-white text-[11px] font-medium
                   hover:bg-sakura-600 transition-colors disabled:opacity-50">
        {busy ? "保存中…" : "保存"}
      </button>
    </div>
  );
}


/* ── 一个大开关（傻瓜模式用） ── */
function BigSwitch({ on, onChange, disabled }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button role="switch" aria-checked={on} disabled={disabled} onClick={() => onChange(!on)}
      className={`shrink-0 w-[46px] h-[26px] rounded-full p-0.5 transition-colors ${
        on ? "bg-green-500" : "bg-sakura-200"} ${disabled ? "opacity-60" : ""}`}>
      <span className={`block w-[22px] h-[22px] rounded-full bg-white shadow transition-transform ${
        on ? "translate-x-[20px]" : "translate-x-0"}`} />
    </button>
  );
}

/* ── 开放接入面板 ──
   双档：默认「傻瓜模式」—— 一个开关 + 自动口令 + 复制配置，让完全不懂的人也能跨机联；
        「硬核 DIY」保留原有 MCP 状态 / 配置片段 / 自定义能力 / 环境变量说明。 */
type Drawer = "quick" | "lan" | "custom" | "adv";

const DRAWERS: { key: Drawer; label: string }[] = [
  { key: "quick", label: "快速接入" },
  { key: "lan", label: "跨设备接入" },
  { key: "custom", label: "自定义能力" },
  { key: "adv", label: "高级 / DIY" },
];

/* ── 开放接入面板（四抽屉）──────────────────────────────
   一次只展开一个抽屉，不把内容堆在一条长滚动里。
   定位：面向「任何兼容 MCP 的工具」，不局限于自家对端。 */
function AccessPanel({ access, mesh, onToggleMesh, onRegenerateToken, onSetCustomToken, onSetAdvanced, onClose, onChanged, remotes, onAddRemote, onRemoveRemote }: {
  access: AccessInfo | null;
  mesh: any;
  onToggleMesh: (enabled: boolean) => void;
  onRegenerateToken: () => Promise<void>;
  onSetCustomToken: (token: string) => Promise<void>;
  onSetAdvanced: (wsHost: string, wsPort: string, mcpHost: string, mcpPort: string) => Promise<void>;
  onClose: () => void;
  onChanged: () => void;
  remotes: any[];
  onAddRemote: (label: string, url: string, token: string) => Promise<void>;
  onRemoveRemote: (label: string) => Promise<void>;
}) {
  const { notify } = useToast();
  const [d, setD] = useState<Drawer>("quick");
  // 口令默认打码：避免被旁观者/截图/录屏直接看到。复制仍拿明文。
  const [showToken, setShowToken] = useState(false);
  const [regenBusy, setRegenBusy] = useState(false);
  // 高级档：用户自己指定口令
  const [customTok, setCustomTok] = useState("");
  const [savingTok, setSavingTok] = useState(false);
  // 高级档：互联参数（两条通道各自的绑定地址 + 端口）
  const [advWsHost, setAdvWsHost] = useState("0.0.0.0");
  const [advWsPort, setAdvWsPort] = useState("");
  const [advMcpHost, setAdvMcpHost] = useState("0.0.0.0");
  const [advMcpPort, setAdvMcpPort] = useState("");
  const [savingAdv, setSavingAdv] = useState(false);
  // 打开「高级」抽屉时才拉取真实生效值（别在页面加载时多打一次接口）
  useEffect(() => {
    if (d !== "adv") return;
    let alive = true;
    (async () => {
      try {
        const a = await apiGet<any>("/api/gateway/advanced");
        if (!alive) return;
        setAdvWsHost(a?.ws_host === "127.0.0.1" ? "127.0.0.1" : "0.0.0.0");
        setAdvWsPort(String(a?.ws_port_base ?? ""));
        setAdvMcpHost(a?.mcp_host === "127.0.0.1" ? "127.0.0.1" : "0.0.0.0");
        setAdvMcpPort(String(a?.mcp_port ?? ""));
      } catch { /* 忽略 */ }
    })();
    return () => { alive = false; };
  }, [d]);
  const applyAdvanced = async () => {
    setSavingAdv(true);
    try { await onSetAdvanced(advWsHost, advWsPort.trim(), advMcpHost, advMcpPort.trim()); }
    finally { setSavingAdv(false); }
  };
  const toggleTokenReveal = () => setShowToken((v) => !v);
  const regenToken = async () => {
    setRegenBusy(true);
    try { await onRegenerateToken(); }
    finally { setRegenBusy(false); }
  };
  const applyCustomToken = async () => {
    const t = customTok.trim();
    // 前端先做一遍校验（后端也会校验，这里只是为了即时反馈）
    if (t.length < 8) { notify("口令至少 8 位", "error"); return; }
    if (!/[a-zA-Z]/.test(t) || !/[0-9]/.test(t)) {
      notify("口令需同时包含字母和数字", "error"); return;
    }
    setSavingTok(true);
    try { await onSetCustomToken(t); setCustomTok(""); }
    finally { setSavingTok(false); }
  };
  // 主动接入其他设备：表单状态 + 连接/删除
  const [rLabel, setRLabel] = useState("");
  const [rUrl, setRUrl] = useState("");
  const [rToken, setRToken] = useState("");
  const [rBusy, setRBusy] = useState(false);
  const connectRemote = async () => {
    if (!rLabel.trim() || !rUrl.trim()) {
      notify("请填写名称与对端地址", "error");
      return;
    }
    setRBusy(true);
    try {
      await onAddRemote(rLabel.trim(), rUrl.trim(), rToken.trim());
      setRUrl("");
      setRToken("");
    } finally {
      setRBusy(false);
    }
  };
  const mcp = access?.mcp;
  const on = !!mesh?.enabled;
  const lanIp = mesh?.lan_ip || access?.lan_ip || "";
  const mcpUrl = `http://${lanIp}:9846/mcp`;   // 通用 MCP 接入地址
  const cfg = access?.configs || {};
  const quickItems = [
    { label: "Claude Code", hint: "命令行一条接入", text: cfg.claude_code },
    { label: "Cursor", hint: "粘进配置文件", text: cfg.cursor },
    { label: "其他工具", hint: "通用接入方式", text: cfg.generic_http },
  ].filter((i) => !!i.text);

  return (
    <div className="lg:w-[320px] lg:flex-shrink-0 bg-white border border-sakura-100 rounded-xl flex flex-col min-h-0 overflow-hidden">
      {/* 头部 + 抽屉导航 */}
      <div className="bg-white px-3 py-2 border-b border-sakura-100 shrink-0">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-sakura-500">开放接入</span>
          <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
        </div>
        <div className="mt-2 grid grid-cols-4 gap-1">
          {DRAWERS.map((it) => (
            <button key={it.key} onClick={() => setD(it.key)}
              className={`text-[10px] px-1 py-1 rounded leading-tight ${
                d === it.key ? "bg-sakura-500 text-white font-medium" : "text-sakura-500 hover:bg-sakura-50"}`}>
              {it.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {d === "quick" && (
          <>
            <p className="text-[11px] text-sakura-500 leading-relaxed">
              把这里的能力接进你已经在用的 AI 工具。选一个、复制、粘贴，就完成了——不用装任何东西。
            </p>
            {quickItems.map((i) => (
              <div key={i.label} className="border border-sakura-100 rounded-lg">
                <div className="flex items-center gap-2 px-2.5 py-1.5">
                  <span className="text-[12px] font-medium text-sakura-600">{i.label}</span>
                  <span className="text-[10px] text-sakura-400 truncate">{i.hint}</span>
                  <div className="ml-auto"><CopyBtn text={i.text} label={i.label} /></div>
                </div>
                <pre className="px-2.5 pb-2 text-[10px] font-mono text-sakura-500 whitespace-pre-wrap break-all leading-relaxed">{i.text}</pre>
              </div>
            ))}
            {quickItems.length === 0 && (
              <p className="text-[11px] text-sakura-400">开放接入服务未就绪，请先到「跨设备接入」开启。</p>
            )}
          </>
        )}

        {d === "lan" && (<>
          <div className="border border-sakura-100 rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2.5">
              <Network size={13} className="text-sakura-400" />
              <span className="text-[12px] font-semibold text-sakura-600">允许其他设备连接</span>
              <div className="ml-auto"><BigSwitch on={on} onChange={onToggleMesh} /></div>
            </div>
            <div className="p-3 space-y-2.5">
              {!on ? (
                <p className="text-[11px] text-sakura-500 leading-relaxed">
                  打开开关，其他电脑、虚拟机或手机上的 AI 工具就能用上这里的能力。会自动生成一个连接口令。
                </p>
              ) : (
                <>
                  <p className="text-[11px] text-sakura-500 leading-relaxed">
                    已开启。任何兼容 MCP 的工具，用下面这个地址 + 口令就能连上。
                  </p>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-sakura-400">接入地址</span>
                      <CopyBtn text={mcpUrl} label="地址" />
                    </div>
                    <p className="font-mono text-[11px] text-sakura-700 bg-sakura-50 rounded px-2 py-1.5 break-all">{mcpUrl}</p>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-sakura-400">连接口令</span>
                      <div className="flex items-center gap-1">
                        <button onClick={toggleTokenReveal} disabled={regenBusy}
                          title={showToken ? "隐藏口令" : "显示口令"}
                          className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600 transition-colors">
                          {showToken ? <EyeOff size={10} /> : <Eye size={10} />}
                          {showToken ? "隐藏" : "显示"}
                        </button>
                        <button onClick={regenToken} disabled={regenBusy}
                          title="换一个全新的连接口令（旧口令立即失效）"
                          className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600 transition-colors disabled:opacity-40">
                          {regenBusy ? <Loader2 size={10} className="animate-spin" /> : <Dices size={10} />}
                          {regenBusy ? "换口中" : "换一个"}
                        </button>
                        <CopyBtn text={mesh?.token || ""} label="口令" />
                      </div>
                    </div>
                    <p className="font-mono text-[13px] tracking-wider text-sakura-700 bg-sakura-50 rounded px-2 py-1.5">
                      {showToken ? (mesh?.token || "-") : "••••••••••"}
                    </p>
                    <p className="text-[10px] text-sakura-400 leading-relaxed mt-1">
                      口令自动随机生成。已连接的设备需要重新填入新口令。
                    </p>
                  </div>
                  <ol className="text-[11px] text-sakura-500 leading-relaxed list-decimal pl-4 space-y-0.5">
                    <li>在另一台设备上打开你要用的 AI 工具</li>
                    <li>把上面的「地址 + 口令」填进去</li>
                    <li>完成，它就能调用这里的能力了</li>
                  </ol>
                </>
              )}
            </div>
          </div>

          {/* ── 主动接入其他设备（出站拨号）── */}
          <div className="mt-3 border border-sakura-100 rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2.5">
              <Radio size={13} className="text-sakura-400" />
              <span className="text-[12px] font-semibold text-sakura-600">主动接入其他设备</span>
            </div>
            <div className="p-3 space-y-2.5">
              <p className="text-[11px] text-sakura-500 leading-relaxed">
                反过来：填入另一台奶昔设备的网关地址与口令，主动连过去。连上后可调用对方共享的能力。
              </p>
              <input
                value={rLabel}
                onChange={(e) => setRLabel(e.target.value)}
                placeholder="名称（便于识别，如 客厅电脑）"
                className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                           bg-sakura-50 border border-sakura-100 rounded
                           focus:outline-none focus:border-sakura-300" />
              <input
                value={rUrl}
                onChange={(e) => setRUrl(e.target.value)}
                placeholder="对端地址：192.168.1.5:18400 或 ws://..."
                className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                           bg-sakura-50 border border-sakura-100 rounded
                           focus:outline-none focus:border-sakura-300" />
              <input
                value={rToken}
                onChange={(e) => setRToken(e.target.value)}
                placeholder="连接口令（对方「开放接入」里显示的）"
                className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                           bg-sakura-50 border border-sakura-100 rounded
                           focus:outline-none focus:border-sakura-300" />
              <button onClick={connectRemote} disabled={rBusy || !rLabel.trim() || !rUrl.trim()}
                className="w-full flex items-center justify-center gap-1 text-[11px] py-1.5 rounded
                           bg-sakura-500 text-white hover:bg-sakura-600 transition-colors disabled:opacity-40">
                {rBusy ? "连接中…" : "连接"}
              </button>
              {remotes.length > 0 && (
                <div className="space-y-2 pt-1">
                  {remotes.map((rm) => (
                    <div key={rm.label} className="border border-sakura-100 rounded-lg p-2.5">
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-medium text-sakura-600 truncate">{rm.label}</span>
                        <span className={`ml-auto text-[10px] px-1.5 py-px rounded border ${
                          rm.state === "connected"
                            ? "text-green-600 bg-green-50 border-green-100"
                            : rm.state === "connecting"
                            ? "text-yellow-600 bg-yellow-50 border-yellow-100"
                            : "text-red-600 bg-red-50 border-red-100"}`}>
                          {rm.state === "connected" ? "已连接" : rm.state === "connecting" ? "连接中" : "未连接"}
                        </span>
                      </div>
                      <p className="text-[10px] text-sakura-400 font-mono truncate mt-0.5">{rm.url}</p>
                      <p className="text-[10px] text-sakura-400 mt-0.5">对方能力 {rm.capabilities?.length ?? 0} 条</p>
                      {rm.error ? <p className="text-[10px] text-red-500 mt-0.5 break-all">{rm.error}</p> : null}
                      <button onClick={() => onRemoveRemote(rm.label)}
                        className="mt-1.5 text-[10px] px-2 py-0.5 rounded text-sakura-400
                                   hover:bg-sakura-50 hover:text-sakura-600 transition-colors">
                        断开并删除
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>)}

        {d === "custom" && (
          <>
            <p className="text-[11px] text-sakura-500 leading-relaxed">
              把你自己的接口也发布出来，让 AI 工具能直接调用。
            </p>
            <AddCapabilityForm onDone={onChanged} />
          </>
        )}

        {d === "adv" && (
          <>
            <div className="border border-sakura-100 rounded-lg">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
                <KeyRound size={12} className="text-sakura-400" />
                <span className="text-[12px] font-semibold text-sakura-600">接入服务状态</span>
                <span className={`ml-auto text-[10px] px-1.5 py-px rounded border ${
                  mcp?.running ? "text-green-600 bg-green-50 border-green-100" : "text-sakura-400 bg-sakura-50 border-sakura-100"}`}>
                  {mcp?.running ? `运行中 · ${mcp.tools} 工具` : "未启动"}
                </span>
              </div>
              <div className="p-3 space-y-1.5 text-[10px]">
                <div className="flex justify-between"><span className="text-sakura-400">本机地址</span>
                  <span className="font-mono text-sakura-600 truncate">{access?.localhost_url ?? "-"}</span></div>
                <div className="flex justify-between"><span className="text-sakura-400">局域网 IP</span>
                  <span className="font-mono text-sakura-600 truncate">{lanIp || "-"}</span></div>
                <div className="flex justify-between"><span className="text-sakura-400">订阅通道</span>
                  <span className="font-mono text-sakura-600 truncate">ws :{access?.ws_port ?? 18400}</span></div>
              </div>
            </div>
            <div className="border border-sakura-100 rounded-lg overflow-hidden">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
                <KeyRound size={12} className="text-sakura-400" />
                <span className="text-[12px] font-semibold text-sakura-600">自定义连接口令</span>
              </div>
              <div className="p-3 space-y-2">
                <p className="text-[11px] text-sakura-500 leading-relaxed">
                  想用自己的口令（比如和其它设备统一）就填在这里，会立刻生效。留空则继续用自动生成的随机口令。
                </p>
                <input
                  value={customTok}
                  onChange={(e) => setCustomTok(e.target.value)}
                  placeholder="至少 8 位，需含字母和数字"
                  className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                             bg-sakura-50 border border-sakura-100 rounded
                             focus:outline-none focus:border-sakura-300" />
                <div className="flex items-center gap-1.5">
                  <button onClick={applyCustomToken} disabled={savingTok || !customTok.trim()}
                    className="flex items-center gap-1 text-[11px] px-2 py-1 rounded
                               bg-sakura-500 text-white hover:bg-sakura-600 transition-colors disabled:opacity-40">
                    {savingTok ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />}
                    {savingTok ? "应用中" : "应用口令"}
                  </button>
                  {customTok && (
                    <button onClick={() => setCustomTok(mesh?.token || "")}
                      className="text-[11px] px-2 py-1 rounded text-sakura-400
                                 hover:bg-sakura-50 hover:text-sakura-600 transition-colors">
                      填回当前
                    </button>
                  )}
                </div>
                <p className="text-[10px] text-sakura-400">修改后，已连接的设备需要用新口令重新连入。</p>
              </div>
            </div>
            <div className="border border-sakura-100 rounded-lg overflow-hidden">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
                <Network size={12} className="text-sakura-400" />
                <span className="text-[12px] font-semibold text-sakura-600">互联参数</span>
                <span className="ml-auto text-[10px] text-sakura-400">改完立即重启通道</span>
              </div>
              <div className="p-3 space-y-2.5">
                {/* 订阅通道（WS）—— 地址 + 端口 */}
                <div className="border border-sakura-100 rounded-lg overflow-hidden">
                  <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-sakura-50/60 border-b border-sakura-50">
                    <Radio size={11} className="text-sakura-400" />
                    <span className="text-[11px] font-medium text-sakura-600">订阅通道（WS）</span>
                    <span className="ml-auto text-[10px] text-sakura-400">对端发现与通知</span>
                  </div>
                  <div className="p-2.5 space-y-2">
                    <select value={advWsHost} onChange={(e) => setAdvWsHost(e.target.value)}
                      className="w-full px-2 py-1.5 text-[12px] text-sakura-700 bg-sakura-50
                                 border border-sakura-100 rounded focus:outline-none focus:border-sakura-300">
                      <option value="0.0.0.0">0.0.0.0 · 允许其他设备连入</option>
                      <option value="127.0.0.1">127.0.0.1 · 仅本机（最安全）</option>
                    </select>
                    <input value={advWsPort} onChange={(e) => setAdvWsPort(e.target.value)}
                      inputMode="numeric" placeholder="端口 18400"
                      className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </div>
                </div>
                {/* 能力调用通道（HTTP/MCP）—— 地址 + 端口 */}
                <div className="border border-sakura-100 rounded-lg overflow-hidden">
                  <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-sakura-50/60 border-b border-sakura-50">
                    <Cpu size={11} className="text-sakura-400" />
                    <span className="text-[11px] font-medium text-sakura-600">能力调用通道（HTTP）</span>
                    <span className="ml-auto text-[10px] text-sakura-400">外部工具调用能力</span>
                  </div>
                  <div className="p-2.5 space-y-2">
                    <select value={advMcpHost} onChange={(e) => setAdvMcpHost(e.target.value)}
                      className="w-full px-2 py-1.5 text-[12px] text-sakura-700 bg-sakura-50
                                 border border-sakura-100 rounded focus:outline-none focus:border-sakura-300">
                      <option value="0.0.0.0">0.0.0.0 · 允许其他设备连入</option>
                      <option value="127.0.0.1">127.0.0.1 · 仅本机（最安全）</option>
                    </select>
                    <input value={advMcpPort} onChange={(e) => setAdvMcpPort(e.target.value)}
                      inputMode="numeric" placeholder="端口 9846"
                      className="w-full px-2 py-1.5 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </div>
                </div>
                <button onClick={applyAdvanced} disabled={savingAdv}
                  className="w-full flex items-center justify-center gap-1 text-[11px] py-1.5 rounded
                             bg-sakura-500 text-white hover:bg-sakura-600 transition-colors disabled:opacity-40">
                  {savingAdv ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                  {savingAdv ? "应用中…" : "应用并重启通道"}
                </button>
                <p className="text-[10px] text-sakura-400 leading-relaxed">
                  能力调用走 HTTP 通道，订阅通知走 WS 通道，两条分离以避免双向回环。
                </p>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function GatewayPage() {
  const { notify } = useToast();
  const [status, setStatus] = useState<any>(null);
  const [access, setAccess] = useState<AccessInfo | null>(null);
  const [caps, setCaps] = useState<Cap[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [showDisabled, setShowDisabled] = useState(true);
  const [trustFilter, setTrustFilter] = useState<Trust | "all">("all");
  const [editingId, setEditingId] = useState("");
  // 隐藏式右侧栏的显隐（点顶部「开放接入」按钮切换）。
  // 隐藏时不挂载右栏组件，故不占任何宽度（无空列）。
  const [sideTab, setSideTab] = useState<string | null>(null);
  // 跨机互联（mesh）状态：傻瓜开关用。含自动生成的口令与局域网地址。
  const [mesh, setMesh] = useState<any>(null);
  const loadMesh = useCallback(async () => {
    try { setMesh(await apiGet<any>("/api/gateway/mesh")); } catch { /* 忽略 */ }
  }, []);
  useEffect(() => { loadMesh(); }, [loadMesh]);
  // 出站对端（主动接入其他设备）列表
  const [remotes, setRemotes] = useState<any[]>([]);
  const loadRemotes = useCallback(async () => {
    try { const d = await apiGet<any>("/api/gateway/remotes"); setRemotes(d?.remotes || []); } catch { /* 忽略 */ }
  }, []);
  useEffect(() => { loadRemotes(); }, [loadRemotes]);
  const addRemote = async (label: string, url: string, token: string) => {
    try {
      const r = await apiPost<any>("/api/gateway/remotes", { label, url, token });
      if (r?.ok) { setRemotes(r.remotes || []); notify(`已发起对 ${label} 的连接`, "success"); await loadMesh(); }
      else notify(`连接失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`连接异常：${String(e).slice(0, 60)}`, "error"); }
  };
  const removeRemote = async (label: string) => {
    try {
      const r = await apiPost<any>("/api/gateway/remotes/delete", { label });
      if (r?.ok) { setRemotes(r.remotes || []); notify(`已断开并删除 ${label}`, "success"); }
      else notify(`删除失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`删除异常：${String(e).slice(0, 60)}`, "error"); }
  };
  const toggleMesh = async (enabled: boolean) => {
    try {
      const r = await apiPost<any>("/api/gateway/mesh", { enabled });
      if (r?.ok) {
        setMesh(r);
        notify(enabled ? "已开启：其他设备现在可以连进来了" : "已关闭跨机互联", "success");
      } else notify(`操作失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`操作失败：${String(e).slice(0, 60)}`, "error"); }
  };
  // 换新口令：旧口令立即作废（已连的设备需要重填），MCP 子进程会带新口令重启。
  const regenerateToken = async () => {
    try {
      const r = await apiPost<any>("/api/gateway/mesh", { regenerate: true });
      if (r?.ok) {
        setMesh(r);
        notify("已生成新的连接口令，旧口令已失效", "success");
      } else notify(`生成失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`生成失败：${String(e).slice(0, 60)}`, "error"); }
  };

  // 高级档：用户自己指定口令（弱口令后端会拒）
  const setCustomToken = async (token: string) => {
    try {
      const r = await apiPost<any>("/api/gateway/mesh", { token });
      if (r?.ok) {
        setMesh(r);
        notify("已应用自定义口令，已连接的设备需要用新口令重连", "success");
      } else notify(`应用失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`应用失败：${String(e).slice(0, 60)}`, "error"); }
  };

  // 高级档：改互联参数（改完后端会重启对应通道，所以要等一会儿再刷新）
  const setAdvanced = async (
    wsHost: string, wsPort: string, mcpHost: string, mcpPort: string,
  ) => {
    try {
      const body: any = { ws_host: wsHost, mcp_host: mcpHost };
      if (wsPort) body.ws_port = Number(wsPort);
      if (mcpPort) body.mcp_port = Number(mcpPort);
      const r = await apiPost<any>("/api/gateway/advanced", body);
      if (r?.ok) {
        notify(r.changed?.length ? "已应用，通道已重启" : "没有改动", "success");
        await loadMesh();
        await load(true);
      } else notify(`应用失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`应用失败：${String(e).slice(0, 60)}`, "error"); }
  };

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    const safe = async (p: Promise<any>) => {
      try { return await p; } catch (e: any) {
        if (e?.name === "AbortError" || e?.message?.includes("aborted")) return null;
        return null;
      }
    };
    try {
      const [st, cp, ac] = await Promise.all([
        safe(apiGet<any>("/api/gateway/status")),
        // include_disabled=1：让用户能看到并重新启用自己停用的能力
        safe(apiGet<any>("/api/gateway/capabilities?include_disabled=1")),
        safe(apiGet<any>("/api/gateway/access")),
      ]);
      if (st) setStatus(st);
      if (cp) setCaps(cp.capabilities || []);
      if (ac) setAccess(ac);
    } catch (e) {
      console.error("Gateway 加载失败", e);
    }
    loadRemotes();
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // 互联对端自动刷新：固定每 3 秒刷一次，不再依赖 peer_count 判断。
  // 否则「只主动连出、无人连入」时 peer_count 恒为 0 → 退化成 15s 才刷一次，
  // 出站对端连上后状态（连接中→已连）迟迟不更新，观感就是「连上却不显示」。
  // load(true) 同时覆盖入站 peers + 出站 remotes；loadMesh 同步开放接入开关/口令。
  useEffect(() => {
    const t = setInterval(() => { load(true); loadMesh(); }, 3000);
    return () => clearInterval(t);
  }, [load, loadMesh]);

  const handleUnregister = async (id: string) => {
    setBusyId(id);
    try {
      const r = await apiPost<any>("/api/gateway/capability/delete", { id });
      if (r?.ok) { notify(`已注销能力 ${id}`, "success"); await load(true); }
      else notify(`注销失败：${r?.error || "未知错误"}`, "error");
    } catch (e) {
      notify(`注销异常：${String(e)}`, "error");
    }
    setBusyId("");
  };

  const handleToggle = async (c: Cap) => {
    setBusyId(c.id);
    try {
      const r = await apiPost<any>("/api/gateway/capability/toggle",
        { id: c.id, enabled: !c.enabled });
      if (r?.ok) {
        notify(`${c.id} 已${r.enabled ? "启用" : "停用"}`, "success");
        await load(true);
      } else notify(`操作失败：${r?.error || "未知"}`, "error");
    } catch (e) {
      notify(`操作异常：${String(e).slice(0, 80)}`, "error");
    }
    setBusyId("");
  };

  function methodOf(c: Cap): "GET" | "POST" {
    const declared = (c.meta?.http_method || "").toUpperCase();
    if (declared === "GET" || declared === "POST") return declared;
    return Object.keys(c.schema?.properties || {}).length > 0 ? "POST" : "GET";
  }

  const handleTest = async (cap: Cap) => {
    setBusyId(cap.id);
    try {
      if (cap.trust !== "read") {
        notify(`${cap.trust === "write" ? "可写" : "危险"}能力不提供直接测试（需人工确认后才执行）`, "error");
        setBusyId("");
        return;
      }
      const method = methodOf(cap);
      const props = cap.schema?.properties || {};
      let r: any;
      if (method === "GET") {
        let url = cap.endpoint;
        const qs = Object.entries(props)
          .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(
            v.type === "integer" || v.type === "number" ? "1"
              : v.type === "boolean" ? "false"
              : v.type === "array" ? "[]" : "")}`)
          .join("&");
        if (qs) url = `${url}?${qs}`;
        r = await apiGet<any>(url);
      } else {
        const payload: Record<string, any> = {};
        for (const [k, v] of Object.entries(props)) {
          const t = v.type;
          payload[k] = t === "integer" || t === "number" ? 1
            : t === "boolean" ? false : t === "array" ? [] : t === "object" ? {} : "";
        }
        r = await apiPost<any>(cap.endpoint, payload);
      }
      notify(`${cap.title} 响应正常（${method}）：${JSON.stringify(r).slice(0, 80)}`, "success");
    } catch (e) {
      notify(`${cap.title} 调用失败：${String(e).slice(0, 120)}`, "error");
    }
    setBusyId("");
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <p className="text-sm font-semibold text-sakura-600">对等互联</p>
        <div className="text-center py-8">
          <div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" />
        </div>
      </div>
    );
  }

  const wsOn = !!status?.ws_started;
  const peerCount = status?.peer_count ?? 0;
  const peers: Peer[] = status?.peers || [];
  // 出站对端（我主动接入的其它设备）。remotes 是「配置 + 实时状态」混排，
  // 即使未连上也列出，便于用户排查；state: connected | connecting | disconnected。
  const outboundRemotes: any[] = remotes || [];
  const connectedOutbound = outboundRemotes.filter((r) => r.state === "connected").length;
  const activePeerTotal = peerCount + connectedOutbound;
  const visibleCaps = caps.filter(c =>
    (showDisabled || c.enabled) && (trustFilter === "all" || c.trust === trustFilter));
  const readCount = caps.filter(c => c.trust === "read" && c.enabled).length;
  const writeCount = caps.filter(c => c.trust === "write" && c.enabled).length;
  const confirmCount = caps.filter(c => c.requires_confirm && c.enabled).length;
  const disabledCount = caps.filter(c => !c.enabled).length;

  const mcp = access?.mcp;

  /* 单条能力行。启用/停用改用标准开关（Switch）：
     替代原先 6px 圆点 —— 点击目标太小、看不出可点、红绿色盲难辨状态。
     开关同时承担「状态指示」与「点击停用/启用」。 */
  const capRow = (c: Cap) => {
    const ts = TRUST_STYLE[c.trust] || TRUST_STYLE.read;
    const editing = editingId === c.id;
    const busy = busyId === c.id;
    return (
      <div key={c.id}
        className={`border-b border-sakura-50 px-3 py-2
                    ${c.enabled ? "hover:bg-sakura-50/50" : "bg-sakura-50/30"}`}>
        <div className="flex items-center gap-2">
          <button role="switch" aria-checked={c.enabled}
            aria-label={`${c.enabled ? "停用" : "启用"}能力 ${c.title || c.id}`}
            onClick={() => handleToggle(c)} disabled={busy}
            title={c.enabled ? "点击停用（对端将不再看到这条）" : "点击启用"}
            className={`shrink-0 w-[30px] h-[17px] rounded-full p-0.5 transition-colors
                        ${c.enabled ? "bg-green-500" : "bg-sakura-200"}
                        ${busy ? "opacity-60 cursor-wait" : ""}`}>
            <span className={`block w-[13px] h-[13px] rounded-full bg-white transition-transform
                             ${c.enabled ? "translate-x-[13px]" : "translate-x-0"}`} />
          </button>
          <ts.Icon size={12} className="shrink-0 text-sakura-300" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <p title={c.title || c.id}
                className={`text-[12px] font-medium truncate
                            ${c.enabled ? "text-sakura-600" : "text-sakura-400 line-through"}`}>
                {c.title || c.id}
              </p>
              <span className={`text-[10px] px-1.5 py-px rounded border shrink-0 ${ts.cls}`}>
                {ts.label}
              </span>
              {c.requires_confirm && (
                <span className="text-[10px] px-1.5 py-px rounded border border-yellow-100 bg-yellow-50 text-yellow-600 shrink-0">
                  需确认
                </span>
              )}
              {c.kind === "channel" && (
                <span className="text-[10px] px-1.5 py-px rounded border border-sakura-100 bg-sakura-50 text-sakura-500 shrink-0">
                  通道
                </span>
              )}
              {!c.enabled && (
                <span className="text-[10px] px-1.5 py-px rounded border border-sakura-200 bg-white text-sakura-400 shrink-0">
                  已停用
                </span>
              )}
            </div>
            <p title={c.id} className="text-[11px] text-sakura-400 truncate font-mono">{c.id}</p>
            <p title={c.description} className="text-[11px] text-sakura-400 truncate">{c.description}</p>
          </div>
          <button onClick={() => handleTest(c)} disabled={busy || !c.enabled}
            className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors shrink-0 disabled:opacity-40"
            title={c.trust === "read"
              ? `测试调用（${methodOf(c)}）`
              : "该能力需确认，不提供直接测试"}>
            {busy ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
          </button>
          <button onClick={() => setEditingId(editing ? "" : c.id)}
            className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-600 transition-colors shrink-0"
            title="编辑名称 / 描述 / 权限">
            {editing ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          </button>
          <button onClick={() => handleUnregister(c.id)} disabled={busy}
            className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors shrink-0 disabled:opacity-40"
            title="彻底删除这条能力">
            <Trash2 size={11} />
          </button>
        </div>
        {editing && (
          <div className="mt-2">
            <CapEditor cap={c} onClose={() => setEditingId("")}
              onSaved={() => load(true)} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sakura-600">对等互联</p>
        <div className="flex items-center gap-2">
          {/* 侧栏触发按钮。用项目里最显眼的主操作按钮样式
              （与知识库页「添加」按钮同一套：渐变实心 + 白字 + px-3 py-1.5 text-[12px]），
              选中态改teal 让"已展开"一眼可辨。 */}
          <button onClick={() => setSideTab(t => (t === "access" ? null : "access"))}
            className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-shadow ${
              sideTab === "access"
                ? "bg-gradient-to-br from-teal-400 to-teal-500 text-white shadow-md"
                : "bg-gradient-to-br from-sakura-400 to-sakura-500 text-white hover:shadow-md"
            }`}>
            <KeyRound size={12} />
            开放接入
            {sideTab === "access" && <span className="text-[10px] opacity-80">已展开</span>}
          </button>
          <button onClick={() => load(true)} disabled={refreshing}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600 transition-colors disabled:opacity-50">
            <RefreshCw size={11} className={refreshing ? "animate-spin" : ""} /> 刷新
          </button>
        </div>
      </div>

      {/* 后端未连接时的页内提示（与全局横幅互补，直接出现在本页顶部更醒目）。
          条件：加载完成且 gateway status 仍为 null（即后端不可达）。 */}
      {!loading && !status && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-xs">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="flex-1">
            后端未连接，对等互联功能不可用。请双击项目根目录的 <code className="px-1 py-px rounded bg-amber-100 font-mono">start_dev.bat</code> 启动（保持窗口不关）。
          </span>
        </div>
      )}

      {/* 对齐 OpsPage 的已批准规范：flex 容器，lg 以上才并排，右栏固定 320px。
          隐藏时不挂载右栏 —— 不会像 grid 那样预留空列把左栏挤窄。
          h-full 链：Dashboard 第 242 行给本页 height:100% → 这里 flex-1 min-h-0
          承接，左右两栏各自独立滚动，侧栏不再无限撑高。 */}
      <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-3">
        {/* ════════ 左：状态与能力 ════════ */}
        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto space-y-3">
          {/* 状态总览 */}
          <div className="grid grid-cols-4 gap-2">
            <div className="bg-white border border-sakura-100 rounded-xl p-3">
              <p className="text-[10px] text-sakura-400">控制平面</p>
              <p className={`text-xs font-bold ${wsOn ? "text-green-600" : "text-red-600"}`}>
                {wsOn ? "运行中" : "未启动"}
              </p>
              <p className="text-[10px] text-sakura-300 mt-0.5 font-mono">
                WS {status?.ws_port ?? "-"}
              </p>
            </div>
            <div className="bg-white border border-sakura-100 rounded-xl p-3">
              <p className="text-[10px] text-sakura-400">已连接对端</p>
              <p className={`text-xs font-bold ${activePeerTotal > 0 ? "text-green-600" : "text-sakura-400"}`}>
                {activePeerTotal} 个
              </p>
              <p className="text-[10px] text-sakura-300 mt-0.5">
                {activePeerTotal > 0 ? "互联已建立" : "独立运行中"}
                {connectedOutbound > 0 ? ` · 主动 ${connectedOutbound}` : ""}
              </p>
            </div>
            <div className="bg-white border border-sakura-100 rounded-xl p-3">
              <p className="text-[10px] text-sakura-400">已启用能力</p>
              <p className="text-xs font-bold text-sakura-700">
                {caps.length - disabledCount} 条
              </p>
              <p className="text-[10px] text-sakura-300 mt-0.5">
                只读 {readCount} · 可写 {writeCount}
                {disabledCount > 0 ? ` · 停用 ${disabledCount}` : ""}
              </p>
            </div>
            <div className="bg-white border border-sakura-100 rounded-xl p-3">
              <p className="text-[10px] text-sakura-400">需人工确认</p>
              <p className={`text-xs font-bold ${confirmCount > 0 ? "text-yellow-600" : "text-sakura-400"}`}>
                {confirmCount} 条
              </p>
              <p className="text-[10px] text-sakura-300 mt-0.5">确认后才执行</p>
            </div>
          </div>

          {/* 对端列表（入站 + 出站主动接入） */}
          <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
              <Radio size={12} className="text-sakura-400" />
              <span className="text-[12px] font-semibold text-sakura-600">
                互联对端<span className="text-sakura-300 font-normal ml-1">
                  ({peers.length + outboundRemotes.length})
                </span>
              </span>
              {outboundRemotes.length > 0 && (
                <span className="text-[10px] px-1.5 py-px rounded border border-teal-100 bg-teal-50 text-teal-600 shrink-0">
                  含 {outboundRemotes.length} 个主动接入
                </span>
              )}
            </div>
            {peers.length === 0 && outboundRemotes.length === 0 ? (
              <div className="px-3 py-5 text-center">
                <p className="text-[12px] text-sakura-400">暂无对端接入</p>
                <p className="text-[11px] text-sakura-300 mt-1">
                  桌面端仍可独立运行 —— 点上方「开放接入」把地址给别人，或在右侧「主动接入其他设备」填地址
                </p>
              </div>
            ) : (
              <>
                {/* 入站：别人连进来（都在线才会出现在 peers 里） */}
                {peers.map((p, i) => (
                  <div key={"in-" + p.provider + i}
                    className="flex items-center gap-2 px-3 py-2 border-b border-sakura-50 last:border-0 hover:bg-sakura-50/50">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[12px] font-medium text-sakura-600 truncate">{p.provider}</p>
                      <p className="text-[11px] text-sakura-400 truncate font-mono">
                        {p.remote || "本机"}
                        {p.subs?.length ? ` · 订阅 ${p.subs.join("/")}` : ""}
                      </p>
                    </div>
                    <span className="text-[11px] text-sakura-300 shrink-0">{fmtIdle(p.idle_s)}</span>
                  </div>
                ))}
                {/* 出站：我主动连出去（含连接中 / 失败，便于排查） */}
                {outboundRemotes.map((r, i) => {
                  const dot = r.state === "connected" ? "bg-green-500"
                            : r.state === "connecting" ? "bg-yellow-400"
                            : "bg-sakura-200";
                  const stateText = r.state === "connected" ? "已连"
                                  : r.state === "connecting" ? "连接中"
                                  : "未连";
                  return (
                    <div key={"out-" + r.label + i}
                      className="flex items-center gap-2 px-3 py-2 border-b border-sakura-50 last:border-0 hover:bg-sakura-50/50">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-[12px] font-medium text-sakura-600 truncate">{r.label}</p>
                          <span className="text-[10px] px-1.5 py-px rounded border border-teal-100 bg-teal-50 text-teal-600 shrink-0">
                            我主动接入
                          </span>
                        </div>
                        <p className="text-[11px] text-sakura-400 truncate font-mono">
                          {r.url}
                          {r.peer_count ? ` · 对端 ${r.peer_count} 个` : ""}
                        </p>
                        {r.error && r.state !== "connected" && (
                          <p className="text-[11px] text-red-400 truncate" title={r.error}>
                            失败：{r.error}
                          </p>
                        )}
                      </div>
                      <span className={`text-[11px] shrink-0 ${r.state === "connected" ? "text-green-600" : r.state === "connecting" ? "text-yellow-600" : "text-sakura-300"}`}>
                        {stateText}
                      </span>
                    </div>
                  );
                })}
              </>
            )}
          </div>

          {/* 能力清单 */}
          <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
              <Network size={12} className="text-sakura-400" />
              <span className="text-[12px] font-semibold text-sakura-600">
                能力清单<span className="text-sakura-300 font-normal ml-1">({visibleCaps.length})</span>
              </span>
              {/* 筛选器 */}
              <div className="ml-auto flex items-center gap-1">
                <select
                  value={trustFilter}
                  onChange={(e) => setTrustFilter(e.target.value as Trust | "all")}
                  className="text-[10px] px-1 py-0.5 rounded border border-sakura-100
                             bg-white text-sakura-500 outline-none">
                  <option value="all">全部权限</option>
                  {TRUST_OPTIONS.map(t => (
                    <option key={t} value={t}>{TRUST_STYLE[t].label}</option>
                  ))}
                </select>
                {disabledCount > 0 && (
                  <span className="text-[10px] text-sakura-300">停用 {disabledCount}</span>
                )}
                <label className="flex items-center gap-1 text-[10px] text-sakura-400 cursor-pointer">
                  <input type="checkbox" checked={showDisabled}
                    onChange={(e) => setShowDisabled(e.target.checked)} />
                  含停用
                </label>
              </div>
            </div>
            {visibleCaps.length === 0 ? (
              <div className="px-3 py-6 text-center">
                <p className="text-[12px] text-sakura-400">
                  {caps.length === 0 ? "未注册任何能力" : "当前筛选下没有能力"}
                </p>
              </div>
            ) : (
              (["read", "write", "dangerous"] as Trust[]).map((t) => {
                const group = visibleCaps.filter((c) => c.trust === t);
                if (group.length === 0) return null;
                const gt = TRUST_STYLE[t];
                const GIcon = gt.Icon;
                return (
                  <div key={t}>
                    <div className="flex items-center gap-1.5 px-3 py-1.5 bg-sakura-50/60 border-b border-sakura-50">
                      <GIcon size={11} className="shrink-0 text-sakura-400" />
                      <span className="text-[11px] font-medium text-sakura-600">{gt.label}能力</span>
                      <span className="text-[10px] text-sakura-300">{group.length}</span>
                    </div>
                    {group.map(capRow)}
                  </div>
                );
              })
            )}
          </div>
        </div>
        {/* 右：开放接入侧栏（点顶部按钮展开，对齐 OpsPage 右栏规范）。
            AccessPanel 根节点自带 lg:w-[320px] lg:flex-shrink-0，故此处直接作为 flex 右子元素。 */}
      {sideTab === "access" && (
        <AccessPanel access={access} mesh={mesh} onToggleMesh={toggleMesh}
          onRegenerateToken={regenerateToken} onSetCustomToken={setCustomToken}
          onSetAdvanced={setAdvanced}
          remotes={remotes} onAddRemote={addRemote} onRemoveRemote={removeRemote}
          onClose={() => setSideTab(null)} onChanged={() => load(true)} />
      )}
      </div>
    </div>
  );
}