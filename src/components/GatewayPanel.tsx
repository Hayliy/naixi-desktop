import { useState, useEffect, useCallback } from "react";
import { Network, RefreshCw, Trash2, Shield, ShieldAlert, Loader2, Zap, Cpu, Radio } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";

/* ─── Gateway 对等互联页 ───
   展示桌面端作为 Hub 的运行状态：WS 控制平面、已连接的对端、以及本端对外暴露的能力。
   数据来源（后端 desktop_core/api.py 的 7 个 /api/gateway/* 端点）：
     GET  /api/gateway/status        → { ok, ws_started, ws_port, peers[], peer_count }
     GET  /api/gateway/capabilities  → { ok, provider, count, capabilities[] }
     POST /api/gateway/capability/delete → 注销某条能力
   能力对象字段：id / kind / title / description / endpoint / trust / requires_confirm / enabled
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
  /** 入参 schema。决定「测试」按钮走 POST（带参数）还是 GET（无参数） */
  schema?: { type?: string; properties?: Record<string, { type?: string; description?: string }> };
  /** 对端登记的能力元信息。http_method 是权威依据（2026-10-04 起） */
  meta?: { http_method?: string; query_params?: string[] };
}

interface Peer {
  provider: string;
  remote?: string;
  subs?: string[];
  idle_s?: number;
}

const TRUST_STYLE: Record<Trust, { label: string; cls: string; Icon: typeof Shield }> = {
  read: { label: "只读", cls: "text-green-600 bg-green-50 border-green-100", Icon: Shield },
  write: { label: "可写", cls: "text-yellow-600 bg-yellow-50 border-yellow-100", Icon: ShieldAlert },
  dangerous: { label: "危险", cls: "text-red-600 bg-red-50 border-red-100", Icon: ShieldAlert },
};

function fmtIdle(sec?: number) {
  const s = sec ?? 0;
  if (s < 60) return `${Math.round(s)} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  return `${Math.floor(s / 3600)} 小时前`;
}

export default function GatewayPage() {
  const { notify } = useToast();
  const [status, setStatus] = useState<any>(null);
  const [caps, setCaps] = useState<Cap[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async (silent = false) => {
    if (silent) setRefreshing(true);
    // 单个请求失败不影响另一个；AbortError 属瞬态（窗口隐藏时 WebView 网络挂起），静默处理
    const safe = async (p: Promise<any>) => {
      try { return await p; } catch (e: any) {
        if (e?.name === "AbortError" || e?.message?.includes("aborted")) return null;
        return null;
      }
    };
    try {
      const [st, cp] = await Promise.all([
        safe(apiGet<any>("/api/gateway/status")),
        safe(apiGet<any>("/api/gateway/capabilities")),
      ]);
      if (st) setStatus(st);
      if (cp) setCaps(cp.capabilities || []);
    } catch (e) {
      console.error("Gateway 加载失败", e);
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // 有 peer 在线时缩短轮询间隔——对端状态变化要能较快反映
  useEffect(() => {
    const online = (status?.peer_count ?? 0) > 0;
    const t = setInterval(() => load(true), online ? 5000 : 15000);
    return () => clearInterval(t);
  }, [load, status?.peer_count]);

  const handleUnregister = async (id: string) => {
    setBusyId(id);
    try {
      const r = await apiPost<any>("/api/gateway/capability/delete", { id });
      if (r?.ok) {
        notify(`已注销能力 ${id}`, "success");
        await load(true);
      } else {
        notify(`注销失败：${r?.error || "未知错误"}`, "error");
      }
    } catch (e) {
      notify(`注销异常：${String(e)}`, "error");
    }
    setBusyId("");
  };

  /** 该能力该用哪个 HTTP 方法调。
   * 权威依据是 meta.http_method（对端显式声明）；
   * 没有声明时才回退「有参 POST / 无参 GET」——与 gateway_bridge._do_http 同一套规则。
   */
  function methodOf(c: Cap): "GET" | "POST" {
    const declared = (c.meta?.http_method || "").toUpperCase();
    if (declared === "GET" || declared === "POST") return declared;
    const n = Object.keys(c.schema?.properties || {}).length;
    return n > 0 ? "POST" : "GET";
  }

  const handleTest = async (cap: Cap) => {
    setBusyId(cap.id);
    try {
      // write/dangerous 不测：不能无确认就触发副作用
      if (cap.trust !== "read") {
        notify(`${cap.trust === "write" ? "可写" : "危险"}能力不提供直接测试（需人工确认后才执行）`, "error");
        setBusyId("");
        return;
      }
      const method = methodOf(cap);
      const props = cap.schema?.properties || {};
      const hasArgs = Object.keys(props).length > 0;
      let r: any;
      if (method === "GET") {
        // GET 不能带 body，参数拼query string
        let url = cap.endpoint;
        if (hasArgs) {
          const qs = Object.entries(props)
            .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(
              v.type === "integer" || v.type === "number" ? "1"
                : v.type === "boolean" ? "false"
                : v.type === "array" ? "[]" : "")}`)
            .join("&");
          url = `${url}?${qs}`;
        }
        r = await apiGet<any>(url);
      } else {
        const payload: Record<string, any> = {};
        for (const [k, v] of Object.entries(props)) {
          const t = v.type;
          payload[k] = t === "integer" || t === "number" ? 1
            : t === "boolean" ? false
            : t === "array" ? []
            : t === "object" ? {}
            : "";
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
  const readCount = caps.filter(c => c.trust === "read").length;
  const writeCount = caps.filter(c => c.trust === "write").length;
  const confirmCount = caps.filter(c => c.requires_confirm).length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sakura-600">对等互联</p>
        <button onClick={() => load(true)} disabled={refreshing}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600 transition-colors disabled:opacity-50">
          <RefreshCw size={11} className={refreshing ? "animate-spin" : ""} /> 刷新
        </button>
      </div>

      {/* 状态总览 */}
      <div className="grid grid-cols-4 gap-2">
        <div className="bg-white border border-sakura-100 rounded-xl p-3">
          <p className="text-[9px] text-sakura-400">控制平面</p>
          <p className={`text-xs font-bold ${wsOn ? "text-green-600" : "text-red-600"}`}>
            {wsOn ? "运行中" : "未启动"}
          </p>
          <p className="text-[8px] text-sakura-300 mt-0.5 font-mono">
            WS {status?.ws_port ?? "-"}
          </p>
        </div>
        <div className="bg-white border border-sakura-100 rounded-xl p-3">
          <p className="text-[9px] text-sakura-400">已连接对端</p>
          <p className={`text-xs font-bold ${peerCount > 0 ? "text-green-600" : "text-sakura-400"}`}>
            {peerCount} 个
          </p>
          <p className="text-[8px] text-sakura-300 mt-0.5">
            {peerCount > 0 ? "互联已建立" : "独立运行中"}
          </p>
        </div>
        <div className="bg-white border border-sakura-100 rounded-xl p-3">
          <p className="text-[9px] text-sakura-400">暴露能力</p>
          <p className="text-xs font-bold text-sakura-700">{caps.length} 条</p>
          <p className="text-[8px] text-sakura-300 mt-0.5">
            只读 {readCount} · 可写 {writeCount}
          </p>
        </div>
        <div className="bg-white border border-sakura-100 rounded-xl p-3">
          <p className="text-[9px] text-sakura-400">需人工确认</p>
          <p className={`text-xs font-bold ${confirmCount > 0 ? "text-yellow-600" : "text-sakura-400"}`}>
            {confirmCount} 条
          </p>
          <p className="text-[8px] text-sakura-300 mt-0.5">确认后才执行</p>
        </div>
      </div>

      {/* 对端列表（行式布局） */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
          <Radio size={12} className="text-sakura-400" />
          <span className="text-[11px] font-semibold text-sakura-600">
            对端
            <span className="text-sakura-300 font-normal ml-1">({peers.length})</span>
          </span>
        </div>
        {peers.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <p className="text-[11px] text-sakura-400">暂无对端接入</p>
            <p className="text-[10px] text-sakura-300 mt-1">
              桌面端仍可独立运行；对端接入后能力会自动双向同步
            </p>
          </div>
        ) : (
          peers.map((p, i) => (
            <div key={p.provider + i}
              className="flex items-center gap-2 px-3 py-2 border-b border-sakura-50 last:border-0 hover:bg-sakura-50/50">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-[11px] font-medium text-sakura-600 truncate">{p.provider}</p>
                <p className="text-[10px] text-sakura-400 truncate font-mono">
                  {p.remote || "本机"}
                  {p.subs?.length ? ` · 订阅 ${p.subs.join("/")}` : ""}
                </p>
              </div>
              <span className="text-[10px] text-sakura-300 shrink-0">{fmtIdle(p.idle_s)}</span>
            </div>
          ))
        )}
      </div>

      {/* 能力清单（行式布局） */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100">
          <Network size={12} className="text-sakura-400" />
          <span className="text-[11px] font-semibold text-sakura-600">
            本端能力
            <span className="text-sakura-300 font-normal ml-1">({caps.length})</span>
          </span>
          <span className="text-[10px] text-sakura-300 ml-auto">对端可发现并调用</span>
        </div>
        {caps.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <p className="text-[11px] text-sakura-400">未注册任何能力</p>
          </div>
        ) : (
          caps.map((c) => {
            const ts = TRUST_STYLE[c.trust] || TRUST_STYLE.read;
            return (
              <div key={c.id}
                className="flex items-center gap-2 px-3 py-2 border-b border-sakura-50 last:border-0 hover:bg-sakura-50/50">
                <ts.Icon size={12} className="shrink-0 text-sakura-300" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-[11px] font-medium text-sakura-600 truncate">{c.title}</p>
                    <span className={`text-[8px] px-1.5 py-px rounded border shrink-0 ${ts.cls}`}>
                      {ts.label}
                    </span>
                    {c.requires_confirm && (
                      <span className="text-[8px] px-1.5 py-px rounded border border-yellow-100 bg-yellow-50 text-yellow-600 shrink-0">
                        需确认
                      </span>
                    )}
                    {c.kind === "channel" && (
                      <span className="text-[8px] px-1.5 py-px rounded border border-sakura-100 bg-sakura-50 text-sakura-500 shrink-0">
                        通道
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] text-sakura-400 truncate font-mono">{c.id}</p>
                  <p className="text-[10px] text-sakura-300 truncate">{c.description}</p>
                </div>
                <button onClick={() => handleTest(c)} disabled={busyId === c.id}
                  className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors shrink-0 disabled:opacity-40"
                  title={c.trust === "read"
                    ? `测试调用（${methodOf(c)}）`
                    : "该能力需确认，不提供直接测试"}>
                  {busyId === c.id ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
                </button>
                <button onClick={() => handleUnregister(c.id)} disabled={busyId === c.id}
                  className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors shrink-0 disabled:opacity-40"
                  title="注销该能力">
                  <Trash2 size={11} />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* 说明 */}
      <div className="bg-sakura-50 border border-sakura-100 rounded-xl px-3 py-2.5">
        <p className="text-[10px] text-sakura-500 leading-relaxed">
          桌面端作为常驻 Hub，对端（QQ 机器人）主动接入。
          能力调用走 HTTP <span className="font-mono">:9845</span>，
          订阅通知走 WS <span className="font-mono">:{status?.ws_port ?? 18400}</span>，
          两条通道分离以避免双向往返死锁。
          <span className="text-yellow-600"> 可写能力不提供直接测试</span>——
          模型只能发起提议，用户回复确认后才真正执行。
          只读能力的测试按钮会按其 schema 判断走POST（带参数）还是 GET（无参数）。
        </p>
      </div>
    </div>
  );
}