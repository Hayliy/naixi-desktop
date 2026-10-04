import { useState, useEffect, useCallback } from "react";
import {
  Network, RefreshCw, Trash2, Shield, ShieldAlert, Loader2, Zap, Cpu, Radio,
  Plus, Check, X, Copy, KeyRound, ChevronDown, ChevronRight,
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


/* ── 开放接入面板 ──
   结构对齐 ConnectionPanel（项目既有的隐藏式右侧栏）：
   `w-[320px] shrink-0 border-l bg-white` + 头部带 X 关闭。
   由 GatewayPage 右侧图标条切换显隐（sideTab）。
   放进这个面板的都是**用户能直接操作**的东西：注册能力、填参数、复制接入配置。 */
function AccessPanel({ access, onClose, onChanged }: {
  access: AccessInfo | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const mcp = access?.mcp;
  return (
    <div className="w-[320px] shrink-0 border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="bg-white flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500">开放接入
          <span className="text-sakura-300 font-normal ml-1">MCP</span>
        </span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
          <X size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
      {/* MCP 状态 */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
          <KeyRound size={12} className="text-sakura-400" />
          <span className="text-[12px] font-semibold text-sakura-600">开放接入 · MCP</span>
          <span className={`ml-auto text-[10px] px-1.5 py-px rounded border ${
            mcp?.running
              ? "text-green-600 bg-green-50 border-green-100"
              : "text-sakura-400 bg-sakura-50 border-sakura-100"}`}>
            {mcp?.running ? `运行中 · ${mcp.tools} 工具` : "未启动"}
          </span>
        </div>
        <div className="p-3 space-y-2">
          <p className="text-[11px] text-sakura-500 leading-relaxed">
            任何支持 MCP 的客户端（Claude Code / Cursor / Cline / 自己写的脚本）
            填下面的地址就能调用本机能力，不需要装任何东西。
          </p>
          {!mcp?.running && (
            <div className="rounded-lg bg-yellow-50 border border-yellow-100 px-2 py-1.5">
              <p className="text-[10px] text-yellow-700 leading-relaxed">
                MCP 服务未运行。启动命令：
                <code className="block mt-1 font-mono text-[10px] text-yellow-800">
                  python desktop_core/mcp_server.py
                </code>
              </p>
            </div>
          )}
          {mcp?.needs_token_for_lan && (
            <div className="rounded-lg bg-yellow-50 border border-yellow-100 px-2 py-1.5">
              <p className="text-[10px] text-yellow-700 leading-relaxed">
                未配置访问 token —— 当前仅本机免鉴权。
                要让局域网/云端的设备连入，必须先设置环境变量
                <code className="font-mono"> NAIXI_MCP_TOKENS</code>
                （格式 <code className="font-mono">token1:*</code>），
                否则服务会拒绝绑定非本机地址。
              </p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-1.5 text-[10px]">
            <div className="rounded-lg bg-sakura-50 px-2 py-1.5">
              <p className="text-sakura-400">本机地址</p>
              <p className="font-mono text-sakura-600 truncate">{access?.localhost_url ?? "-"}</p>
            </div>
            <div className="rounded-lg bg-sakura-50 px-2 py-1.5">
              <p className="text-sakura-400">局域网地址</p>
              <p className="font-mono text-sakura-600 truncate">{access?.lan_url ?? "-"}</p>
            </div>
            <div className="rounded-lg bg-sakura-50 px-2 py-1.5">
              <p className="text-sakura-400">局域网 IP</p>
              <p className="font-mono text-sakura-600 truncate">{access?.lan_ip ?? "-"}</p>
            </div>
            <div className="rounded-lg bg-sakura-50 px-2 py-1.5">
              <p className="text-sakura-400">访问凭据</p>
              <p className="font-mono text-sakura-600 truncate">
                {mcp?.token_configured ? `已配 ${mcp.token_count} 个` : "免鉴权"}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* 配置片段 —— 核心：给用户能直接拿走的东西 */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
          <Copy size={12} className="text-sakura-400" />
          <span className="text-[12px] font-semibold text-sakura-600">一键接入配置</span>
        </div>
        <div className="p-2.5 space-y-2">
          {access?.configs?.claude_code && (
            <CopyBlock label="Claude Code" value={access.configs.claude_code}
              hint="终端执行" />
          )}
          {access?.configs?.cursor && (
            <CopyBlock label="Cursor" value={access.configs.cursor}
              hint="粘进 mcp.json" />
          )}
          {access?.configs?.generic_http && (
            <CopyBlock label="通用 HTTP" value={access.configs.generic_http}
              hint="任意语言客户端" />
          )}
          {access?.configs?.ws_internal && (
            <CopyBlock label="内部 WS" value={access.configs.ws_internal}
              hint="同机脚本用" />
          )}
        </div>
      </div>

      {/* 自定义能力 */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
          <Plus size={12} className="text-sakura-400" />
          <span className="text-[12px] font-semibold text-sakura-600">扩展能力</span>
        </div>
        <div className="p-2.5">
          <AddCapabilityForm onDone={onChanged} />
        </div>
      </div>

      {/* 说明 */}
      <div className="bg-sakura-50 border border-sakura-100 rounded-xl px-3 py-2.5">
        <p className="text-[11px] text-sakura-500 leading-relaxed">
          <Cpu size={10} className="inline mr-1" />
          能力调用走 HTTP <span className="font-mono">:{access?.http_port ?? 9845}</span>，
          订阅通知走 WS <span className="font-mono">:{access?.ws_port ?? 18400}</span>，
          两条通道分离以避免双向往返死锁。
          <span className="text-yellow-600"> 可写能力不提供直接测试</span>——
          调用方只能发起提议，用户确认后才真正执行。
          左侧圆点可停用能力，对端即刻不再看到它。
        </p>
      </div>
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
  // 隐藏式右侧栏的显隐（对齐 Chat.tsx 的 sideTab 模式）：
  // 平时不占宽度，点右侧图标条才展开。
  const [sideTab, setSideTab] = useState<string | null>(null);

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
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const online = (status?.peer_count ?? 0) > 0;
    const t = setInterval(() => load(true), online ? 5000 : 15000);
    return () => clearInterval(t);
  }, [load, status?.peer_count]);

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
  const visibleCaps = caps.filter(c =>
    (showDisabled || c.enabled) && (trustFilter === "all" || c.trust === trustFilter));
  const readCount = caps.filter(c => c.trust === "read" && c.enabled).length;
  const writeCount = caps.filter(c => c.trust === "write" && c.enabled).length;
  const confirmCount = caps.filter(c => c.requires_confirm && c.enabled).length;
  const disabledCount = caps.filter(c => !c.enabled).length;

  const mcp = access?.mcp;

  return (
    <div className="space-y-3">
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

      <div className="flex h-full">
        {/* ════════ 左栏：状态与能力 ════════ */}
        <div className="flex-1 min-w-0 overflow-y-auto space-y-3 pr-1">
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
              <p className={`text-xs font-bold ${peerCount > 0 ? "text-green-600" : "text-sakura-400"}`}>
                {peerCount} 个
              </p>
              <p className="text-[10px] text-sakura-300 mt-0.5">
                {peerCount > 0 ? "互联已建立" : "独立运行中"}
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

          {/* 对端列表 */}
          <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
              <Radio size={12} className="text-sakura-400" />
              <span className="text-[12px] font-semibold text-sakura-600">
                已连接对端<span className="text-sakura-300 font-normal ml-1">({peers.length})</span>
              </span>
            </div>
            {peers.length === 0 ? (
              <div className="px-3 py-5 text-center">
                <p className="text-[12px] text-sakura-400">暂无对端接入</p>
                <p className="text-[11px] text-sakura-300 mt-1">
                  桌面端仍可独立运行 —— 点上方「开放接入」把地址给别人即可
                </p>
              </div>
            ) : (
              peers.map((p, i) => (
                <div key={p.provider + i}
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
              ))
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
              visibleCaps.map((c) => {
                const ts = TRUST_STYLE[c.trust] || TRUST_STYLE.read;
                const editing = editingId === c.id;
                return (
                  <div key={c.id}
                    className={`border-b border-sakura-50 last:border-0 px-3 py-2
                                ${c.enabled ? "hover:bg-sakura-50/50" : "bg-sakura-50/30"}`}>
                    <div className="flex items-center gap-2">
                      <button onClick={() => handleToggle(c)} disabled={busyId === c.id}
                        title={c.enabled ? "点击停用（对端将不再看到这条）" : "点击启用"}
                        className={`shrink-0 w-1.5 h-1.5 rounded-full transition-colors
                                    ${c.enabled ? "bg-green-500 hover:bg-yellow-400"
                                                : "bg-sakura-200 hover:bg-green-400"}`} />
                      <ts.Icon size={12} className="shrink-0 text-sakura-300" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className={`text-[12px] font-medium truncate
                                        ${c.enabled ? "text-sakura-600" : "text-sakura-300 line-through"}`}>
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
                        <p className="text-[11px] text-sakura-400 truncate font-mono">{c.id}</p>
                        <p className="text-[11px] text-sakura-300 truncate">{c.description}</p>
                      </div>
                      <button onClick={() => handleTest(c)} disabled={busyId === c.id || !c.enabled}
                        className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors shrink-0 disabled:opacity-40"
                        title={c.trust === "read"
                          ? `测试调用（${methodOf(c)}）`
                          : "该能力需确认，不提供直接测试"}>
                        {busyId === c.id ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
                      </button>
                      <button onClick={() => setEditingId(editing ? "" : c.id)}
                        className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-600 transition-colors shrink-0"
                        title="编辑名称 / 描述 / 权限">
                        {editing ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                      </button>
                      <button onClick={() => handleUnregister(c.id)} disabled={busyId === c.id}
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
              })
            )}
          </div>
        </div>
      </div>
    {/* 右侧栏：点顶部「开放接入」按钮展开（对齐 PetMemoryPage 的左选右显模式） */}
      {sideTab === "access" && (
        <AccessPanel access={access} onClose={() => setSideTab(null)}
          onChanged={() => load(true)} />
      )}
    </div>
  );
}