import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { AppShell, Sidebar, Header, Main } from "@/components/shell";
import { AppProvider } from "@/contexts/AppContext";
import { ToastProvider, useToast } from "@/components/Toast";
import { Card } from "@/components/ui";
import { loadAvatarCache } from "@/lib/avatar";
import ChatPage from "@/components/Chat";
import WorkflowEditor from "@/components/WorkflowEditor";
import { ReactFlowProvider } from "@xyflow/react";
import ErrorBoundary from "@/components/ErrorBoundary";
import SetupGuide from "@/components/SetupGuide";
import {
  LayoutDashboard, MessageCircle, BookOpen, Wrench, Brain,
  Bot, Server, Settings, Gamepad, Calendar, FileText,
  Heart, Activity, Cpu, Database,
  Globe, Sparkles, Clock,
  CheckCircle, AlertTriangle, Users, Wifi, WifiOff,
  HardDrive, Shield, Film, Layers, GitBranch,
  Cpu as CpuIcon, Zap, Network, Lock,
  Plus, Check, Repeat, Play, Pause, ChevronDown, ChevronUp, ChevronLeft, Edit3, Trash2, CircleAlert,
  Search, X, Loader2, Copy, Download,
} from "lucide-react";

const PAGE_TITLES: Record<string, string> = {
  dashboard: "仪表盘", chat: "对话", knowledge: "知识库",
  tools: "工具", memory: "记忆", napcat: "NapCat",
  ops: "运维", live: "直播", scheduler: "自动化",
  logs: "日志", settings: "设置", workflow: "工作流",
};
const PAGE_ICONS: Record<string, React.ReactNode> = {
  dashboard: <LayoutDashboard size={15} className="text-sakura-400" />,
  chat: <MessageCircle size={15} className="text-sakura-400" />,
  knowledge: <BookOpen size={15} className="text-sakura-400" />,
  tools: <Wrench size={15} className="text-sakura-400" />,
  memory: <Brain size={15} className="text-sakura-400" />,
  napcat: <Bot size={15} className="text-sakura-400" />,
  ops: <Server size={15} className="text-sakura-400" />,
  live: <Film size={15} className="text-sakura-400" />,
  scheduler: <Calendar size={15} className="text-sakura-400" />,
  logs: <FileText size={15} className="text-sakura-400" />,
  settings: <Settings size={15} className="text-sakura-400" />,
  workflow: <GitBranch size={15} className="text-sakura-400" />,
};
const ACTIVE_PAGE_ITEMS = ["dashboard", "chat"];

const NAV_ITEMS = [
  { key: "dashboard", icon: <LayoutDashboard size={16} />, label: "仪表盘" },
  { key: "chat",      icon: <MessageCircle size={16} />,   label: "对话" },
  { key: "workflow",  icon: <GitBranch size={16} />,       label: "工作流" },
  { key: "scheduler", icon: <Calendar size={16} />,        label: "自动化" },
  { key: "knowledge",  icon: <BookOpen size={16} />,       label: "知识库" },
  { key: "tools",      icon: <Wrench size={16} />,         label: "工具" },
  { key: "memory",     icon: <Brain size={16} />,          label: "记忆" },
  { key: "connection", icon: <Wifi size={16} />,         label: "连接" },
  { key: "ops",        icon: <Server size={16} />,         label: "运维" },
  { key: "live",       icon: <Film size={16} />,           label: "直播" },
  { key: "logs",       icon: <FileText size={16} />,       label: "日志" },
  { key: "settings",   icon: <Settings size={16} />,       label: "设置" },
];

interface NapcatData { connected: boolean; groups: number; }
interface SysData { cpu: number; memory: number; disk: number; gpu_name?: string; gpu_mem_total?: number; gpu_mem_used?: number; gpu_util?: number; }
interface KbData { categories: { name: string; count: number }[]; total: number; }
interface QuotaData { models: { name: string; used: number; limit: number; depleted: boolean }[]; }
interface MemData { layers: { name: string; desc: string; count: number; status: string }[]; }
interface StatusData { trust_level: number; trust_total: number; trust_rate: number; knowledge_items: number; knowledge_cats: number; tools: number; skills: number; agents: number; cases: number; napcat_connected: boolean; version: string; experiences: number; }
interface AgentItem { name: string; desc: string; }
interface AgentData { agents: AgentItem[]; }
interface DesktopConfig { configured?: boolean; }

export default function Dashboard() {
  const [globalErrors, setGlobalErrors] = useState<{ msg: string; stack: string; time: number }[]>([]);

  useEffect(() => {
    const handler = (e: ErrorEvent) => {
      console.error("[全局异常]", e.error?.message || e.message, e.error?.stack || "");
      setGlobalErrors(prev => [{ msg: e.error?.message || e.message, stack: e.error?.stack || "", time: Date.now() }, ...prev].slice(0, 5));
    };
    const rejectionHandler = (e: PromiseRejectionEvent) => {
      console.error("[未捕获的 Promise]", e.reason?.message || String(e.reason));
      setGlobalErrors(prev => [{ msg: e.reason?.message || String(e.reason), stack: e.reason?.stack || "", time: Date.now() }, ...prev].slice(0, 5));
    };
    window.addEventListener("error", handler);
    window.addEventListener("unhandledrejection", rejectionHandler);
    return () => {
      window.removeEventListener("error", handler);
      window.removeEventListener("unhandledrejection", rejectionHandler);
    };
  }, []);

  const [st, setSt] = useState<StatusData | null>(null);
  const [napcat, setNapcat] = useState<NapcatData | null>(null);
  const [sys, setSys] = useState<SysData | null>(null);
  const [kb, setKb] = useState<KbData | null>(null);
  const [quota, setQuota] = useState<QuotaData | null>(null);
  const [mem, setMem] = useState<MemData | null>(null);
  const [agentsData, setAgentsData] = useState<AgentData | null>(null);
  const [toolsData, setToolsData] = useState<{tools: {name: string; desc: string}[]} | null>(null);
  const [health, setHealth] = useState<{napcat: boolean; ollama: boolean; glm_api: boolean; backend: boolean} | null>(null);
  const [dbStats, setDbStats] = useState<{tables: {name: string; count: number}[]} | null>(null);
  const [activeNav, setActiveNav] = useState("dashboard");
  const [showSetup, setShowSetup] = useState(false);

  useEffect(() => {
    // 加载头像缓存
    loadAvatarCache();

    const fetch = () => {
      apiGet<StatusData>("/api/status").then(setSt).catch(() => {});
      apiGet<NapcatData>("/api/napcat/status").then(setNapcat).catch(() => {});
      apiGet<SysData>("/api/system/resources").then(setSys).catch(() => {});
      apiGet<KbData>("/api/knowledge/summary").then(setKb).catch(() => {});
      apiGet<QuotaData>("/api/quota/stats").then(setQuota).catch(() => {});
      apiGet<MemData>("/api/memory/stats").then(setMem).catch(() => {});
      apiGet<AgentData>("/api/agents").then(setAgentsData).catch(() => {});
      apiGet("/api/tools").then(setToolsData).catch(() => {});
      apiGet("/api/service/health").then(setHealth).catch(() => {});
      apiGet("/api/database/stats").then(setDbStats).catch(() => {});
    };
    fetch();
    const t = setInterval(fetch, 5000);
    return () => clearInterval(t);
  }, []);

  // 首次启动检测（无 API Key 配置时弹出引导）
  useEffect(() => {
    const dismissed = localStorage.getItem("naixi_setup_dismissed");
    if (dismissed === "true") return;
    apiGet<DesktopConfig>("/api/desktop/config").then((d) => {
      if (!d?.configured) setShowSetup(true);
    }).catch(() => {});
  }, []);

  const handleCloseSetup = useCallback(() => {
    setShowSetup(false);
    localStorage.setItem("naixi_setup_dismissed", "true");
  }, []);

  if (!st) return (
    <div className="flex items-center justify-center h-screen bg-sakura-50">
      <div className="flex items-center gap-2 text-sakura-400">
        <Activity className="w-4 h-4 animate-pulse" />
        <span className="text-xs">连接中...</span>
      </div>
    </div>
  );

  const napcatOk = napcat?.connected ?? false;
  const kbCategories = kb?.categories ?? [];
  const memLayers = mem?.layers ?? [];

  const findQuota = (name: string) => quota?.models?.find(q => q.name === name) ?? null;

  const MODEL_CONFIG = [
    { n: "qwen3-32b",              r: "主人专属 · 百炼",      p: null,  qn: "qwen3-32b" },
    { n: "ling-2.6-1t",            r: "群聊主力 · 百灵",      p: null,  qn: "ling-2.6-1t" },
    { n: "glm-4.7-flash",          r: "智谱备用 · 对话",      p: null,  qn: "glm-4.7-flash" },
    { n: "qwen-vl-plus",           r: "识图 · 百炼视觉",      p: null,  qn: "qwen-vl-plus" },
    { n: "qwen-turbo",             r: "备用降级 · 百炼",      p: null,  qn: "qwen-turbo" },
    { n: "CogView-3-Flash",        r: "文生图 · 智谱",        p: "免费", qn: null },
    { n: "CogVideoX-Flash",        r: "文生视频 · 智谱",       p: "免费", qn: null },
  ];
  const modelTotal = MODEL_CONFIG.reduce((a, m) => {
    const q = m.qn ? findQuota(m.qn) : null;
    return a + (q?.used ?? 0);
  }, 0);

  return (
    <AppProvider>
    <ToastProvider>
    <AppShell sidebar={<Sidebar items={NAV_ITEMS} activeNav={activeNav} onNavChange={setActiveNav} version={`v${st.version}`} />}>
      <Header>
        <div className="flex items-center gap-2">
          {PAGE_ICONS[activeNav] || <LayoutDashboard size={15} className="text-sakura-400" />}
          <span className="text-sm font-medium text-sakura-600">{PAGE_TITLES[activeNav] || "仪表盘"}</span>
        </div>
      </Header>
      <Main fluid={activeNav !== "dashboard"}>
        <>
          {/* 设置引导弹窗 */}
          {showSetup && !st.napcat_connected && (
            <SetupGuide onClose={handleCloseSetup} />
          )}

          {/* 全局错误浮窗 */}
          {globalErrors.length > 0 && (
            <div className="fixed bottom-4 right-4 z-[100] space-y-2 max-w-md">
              {globalErrors.map((err, i) => (
                <div key={i} className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 shadow-lg">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-medium text-red-600">未捕获的异常</p>
                    <button onClick={() => setGlobalErrors(prev => prev.filter((_, j) => j !== i))}
                      className="text-red-400 hover:text-red-600 shrink-0">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                  </div>
                  <p className="text-[11px] text-red-500 mt-1 font-mono break-all">{err.msg}</p>
                  <details className="mt-1">
                    <summary className="text-[10px] text-red-400 cursor-pointer">堆栈</summary>
                    <pre className="mt-1 text-[10px] text-gray-500 max-h-[120px] overflow-auto whitespace-pre-wrap">{err.stack}</pre>
                  </details>
                </div>
              ))}
            </div>
          )}

          <div style={{ display: activeNav === "chat" || activeNav === "settings" ? "block" : "none", height: "100%" }}>
            {activeNav === "settings" ? (
              <ErrorBoundary name="设置"><SetupGuide standalone onClose={() => setActiveNav("dashboard")} /></ErrorBoundary>
            ) : (
              <ErrorBoundary name="对话"><ChatPage /></ErrorBoundary>
            )}
          </div>
          <div style={{ display: activeNav === "workflow" ? "block" : "none", height: "100%" }}><ErrorBoundary name="工作流"><ReactFlowProvider><WorkflowEditor /></ReactFlowProvider></ErrorBoundary></div>
          <div style={{ display: activeNav === "knowledge" ? "block" : "none", height: "100%" }}><ErrorBoundary name="知识库"><KbPage kb={kb} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "tools" ? "block" : "none", height: "100%" }}><ErrorBoundary name="工具"><ToolsPage toolsData={toolsData} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "memory" ? "block" : "none", height: "100%" }}><ErrorBoundary name="记忆"><MemPage memLayers={memLayers} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "connection" ? "block" : "none", height: "100%" }}><ErrorBoundary name="连接"><NapcatPage napcat={napcat} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "ops" ? "block" : "none", height: "100%" }}><ErrorBoundary name="运维"><OpsPage sys={sys} health={health} dbStats={dbStats} status={st} errors={globalErrors} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "live" ? "block" : "none", height: "100%" }}><ErrorBoundary name="直播"><LivePage /></ErrorBoundary></div>
          <div style={{ display: activeNav === "scheduler" ? "block" : "none", height: "100%" }}><ErrorBoundary name="自动化"><SchedulerPage /></ErrorBoundary></div>
          <div style={{ display: activeNav === "logs" ? "block" : "none", height: "100%" }}><ErrorBoundary name="日志"><LogsPage /></ErrorBoundary></div>
          <div style={{ display: activeNav === "dashboard" ? "block" : "none" }}>
            <div className="space-y-4">

          <div className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${napcatOk ? "bg-green-50 border-green-200" : "bg-red-50 border-red-200"}`}>
            <div className={`w-10 h-10 rounded-full flex items-center justify-center ${napcatOk ? "bg-green-100" : "bg-red-100"}`}>
              {napcatOk ? <Wifi size={20} className="text-green-500" /> : <WifiOff size={20} className="text-red-500" />}
            </div>
            <div>
              <p className={`text-sm font-bold ${napcatOk ? "text-green-700" : "text-red-700"}`}>
                {napcatOk ? "NapCat 已连接" : "NapCat 离线"}
              </p>
              <p className="text-xs text-sakura-400 mt-0.5">
                {napcatOk ? `QQ 在线 · ${napcat?.groups ?? 0} 个群` : "QQ 消息无法收发"}
              </p>
            </div>
          </div>

          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <p className="text-xs text-sakura-400 mb-0.5">今日消息</p>
              <p className="text-2xl font-bold text-sakura-500">{st.trust_total}</p>
              <p className="text-[11px] text-green-600 mt-0.5">成功率 {st.trust_rate}%</p>
            </Card>
            <Card className="p-4">
              <p className="text-xs text-sakura-400 mb-0.5">工具总数</p>
              <p className="text-2xl font-bold text-sakura-500">{st.tools}</p>
              <p className="text-[11px] text-sakura-400 mt-0.5">{st.skills} 技能</p>
            </Card>
            <Card className="p-4">
              <p className="text-xs text-sakura-400 mb-0.5">知识条目</p>
              <p className="text-2xl font-bold text-sakura-500">{kb?.total ?? st.knowledge_items}</p>
              <p className="text-[11px] text-green-600 mt-0.5">{kbCategories.length} 个分类</p>
            </Card>
            <Card className="p-4">
              <p className="text-xs text-sakura-400 mb-0.5">核心模块</p>
              <p className="text-2xl font-bold text-sakura-500">{st.agents}</p>
              <p className="text-[11px] text-sakura-400 mt-0.5">{st.cases} 经验案例</p>
            </Card>
          </div>

          <div className="grid gap-4 grid-cols-1 lg:grid-cols-2 xl:grid-cols-3">

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">模型用量</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {MODEL_CONFIG.map((m, i) => {
                  const q = m.qn ? findQuota(m.qn) : null;
                  const used = q?.used ?? null;
                  const limit = q?.limit ?? null;
                  const pct = (limit && limit > 0 && used !== null) ? Math.round(used * 100 / limit) : null;
                  const showQuota = used !== null;
                  return (
                    <div key={i} className="border-b border-sakura-50 last:border-0 py-1.5">
                      <div className="flex items-center gap-2 text-xs">
                        <Brain size={12} className="text-sakura-400 shrink-0" />
                        <span className="text-sakura-600 w-28 truncate font-medium">{m.n}</span>
                        <span className="text-sakura-400 flex-1 truncate">{m.r}</span>
                        {showQuota ? (
                          <span className={`shrink-0 ${limit && used > limit ? "text-red-500" : "text-sakura-500"}`}>
                            {(used / 10000).toFixed(1)}万
                            {limit > 0 ? ` / ${(limit / 10000).toFixed(0)}万` : ""}
                          </span>
                        ) : m.p ? (
                          <span className="text-sakura-300 shrink-0">{m.p}</span>
                        ) : (
                          <span className="text-sakura-300 shrink-0">—</span>
                        )}
                        {q?.depleted && limit > 0 && <span className="text-[10px] px-1 py-0.5 rounded bg-red-50 text-red-600">耗尽</span>}
                      </div>
                      {showQuota && limit > 0 && (
                        <div className="mt-1 ml-8 h-1 rounded-full bg-sakura-100 overflow-hidden">
                          <div className={`h-full rounded-full ${pct && pct > 90 ? "bg-red-400" : "bg-gradient-to-r from-sakura-400 to-sakura-500"}`}
                               style={{width: `${Math.min(pct ?? 0, 100)}%`}} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="mt-2 pt-2 border-t border-sakura-100 text-[10px] text-sakura-300 flex justify-between">
                <span>总计 {(modelTotal / 10000).toFixed(1)}万</span>
                <span>降级链：Ollama → Dify → 卖萌</span>
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">系统资源</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-3">
                <Bar label="CPU" val={`${sys?.cpu ?? 0}%`} w={sys?.cpu ?? 0} />
                <Bar label="内存" val={`${sys?.memory ?? 0}%`} w={sys?.memory ?? 0} />
                <Bar label="磁盘" val={`${sys?.disk ?? 0}%`} w={sys?.disk ?? 0} />
                <Bar label="GPU" val={`${sys?.gpu_util ?? 0}%`} w={sys?.gpu_util ?? 0} />
                <div className="border-t border-sakura-100 pt-3 space-y-1.5 text-xs">
                  <Row l="GPU 型号" v={sys?.gpu_name ?? "无"} />
                  <Row l="显存" v={`${sys?.gpu_mem_used ?? 0} MB / ${sys?.gpu_mem_total ?? 0} MB`} />
                  <Row l="后端 API" v="dashboard_api.py :9845" />
                  <Row l="NapCat" v="WS 3001 · HTTP 3000" />
                  <Row l="SearXNG" v="本地搜索引擎 :8898" />
                  <Row l="Ollama" v="本地模型 :11434" />
                </div>
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">知识库</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {kbCategories.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 py-1.5 border-b border-sakura-50 last:border-0 text-xs">
                    <BookOpen size={12} className="text-sakura-400 shrink-0" />
                    <span className="text-sakura-600 flex-1 truncate">{c.name}</span>
                    <span className="text-sakura-500 font-medium">{c.count}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 pt-2 border-t border-sakura-100 text-[10px] text-sakura-300">
                总计 {kb?.total ?? 0} 条目 · 来自库街区 wiki
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">记忆系统</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {memLayers.map((l, i) => (
                  <div key={i} className="flex items-center gap-2 py-1.5 border-b border-sakura-50 last:border-0 text-xs">
                    <Brain size={12} className="text-sakura-400 shrink-0" />
                    <span className="text-sakura-600 w-20 shrink-0">{l.name}</span>
                    <span className="text-sakura-400 flex-1 truncate">{l.desc}</span>
                    <span className="text-sakura-500 font-medium">{l.count}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">工具概览（{toolsData?.count ?? st.tools ?? 0} 个）</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {(toolsData?.tools ?? []).slice(0, 50).map((t, i) => (
                  <div key={i} className="flex items-center gap-2 py-1 border-b border-sakura-50 last:border-0 text-xs">
                    <Wrench size={11} className="text-sakura-400 shrink-0 mt-0.5" />
                    <span className="text-sakura-600 w-40 shrink-0 truncate font-medium">{t.name}</span>
                    <span className="text-sakura-400 flex-1 truncate">{t.desc || ""}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">智能体（{agentsData?.agents?.length ?? 0} 个）</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1">
                {(agentsData?.agents ?? []).map((a, i) => (
                  <div key={i} className="flex items-start gap-2 py-1 border-b border-sakura-50 last:border-0 text-xs">
                    <Bot size={11} className="text-sakura-400 shrink-0 mt-0.5" />
                    <span className="text-sakura-600 w-16 shrink-0">{a.name}</span>
                    <span className="text-sakura-400 flex-1 truncate">{a.desc.slice(0, 24)}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">服务状态</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {[
                  { i: Bot, n: "NapCat", s: health?.napcat ?? false, d: `WS 3001 · ${napcat?.groups ?? 0}群` },
                  { i: Globe, n: "后端 API", s: health?.backend ?? true, d: "localhost:9845" },
                  { i: Brain, n: "智谱 GLM", s: health?.glm_api ?? false, d: "免费额度" },
                  { i: CpuIcon, n: "Ollama", s: health?.ollama ?? false, d: "localhost:11434" },
                ].map((svc, idx) => (
                  <div key={idx} className="flex items-center gap-2 py-1.5 border-b border-sakura-50 last:border-0 text-xs">
                    <svc.i size={12} className="text-sakura-400 shrink-0" />
                    <span className="text-sakura-600 w-16">{svc.n}</span>
                    <span className={svc.s ? "text-green-600" : "text-red-500"}>
                      ● {svc.s ? "在线" : "离线"}
                    </span>
                    <span className="text-sakura-300 ml-auto">{svc.d}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-4 h-[220px] flex flex-col"><p className="text-xs font-semibold text-sakura-500 mb-3">系统数据</p>
              <div className="flex-1 min-h-0 overflow-y-auto space-y-1.5">
                {[
                  { n: "审计日志", v: dbStats?.tables?.find(t => t.name === "audit_log")?.count ?? "—", i: "条" },
                  { n: "对话记录", v: dbStats?.tables?.find(t => t.name === "conversations")?.count ?? "—", i: "条" },
                  { n: "工具调用", v: dbStats?.tables?.find(t => t.name === "tool_usage")?.count ?? "—", i: "次" },
                  { n: "反馈", v: dbStats?.tables?.find(t => t.name === "feedback")?.count ?? "—", i: "条" },
                  { n: "缓存", v: dbStats?.tables?.find(t => t.name === "response_cache")?.count ?? "—", i: "条" },
                  { n: "用户画像", v: dbStats?.tables?.find(t => t.name === "user_profiles")?.count ?? "—", i: "个" },
                ].map((d, i) => (
                  <div key={i} className="flex items-center gap-2 py-1 border-b border-sakura-50 last:border-0 text-xs">
                    <Database size={11} className="text-sakura-400 shrink-0" />
                    <span className="text-sakura-600 w-16 shrink-0">{d.n}</span>
                    <span className="text-sakura-500 font-medium">{d.v}</span>
                    <span className="text-sakura-300 text-[10px]">{d.i}</span>
                  </div>
                ))}
              </div>
            </Card>

          </div>

        </div>
        </div>
        </>
      </Main>
    </AppShell>
    </ToastProvider>
    </AppProvider>
  );
}

function Bar({ label, val, w }: { label: string; val: string; w: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-sakura-400">{label}</span>
        <span className="text-sakura-600 font-medium">{val}</span>
      </div>
      <div className="h-1.5 rounded-full bg-sakura-100 overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-sakura-400 to-sakura-500" style={{width:`${Math.min(w,100)}%`}} />
      </div>
    </div>
  );
}
function Row({ l, v }: { l: string; v: string }) {
  return <div className="flex justify-between"><span className="text-sakura-400">{l}</span><span className="text-sakura-600 font-medium">{v}</span></div>;
}

/* ─── 子页面 ─── */
function KbPage({ kb }: { kb: KbData | null }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeCat, setActiveCat] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editItem, setEditItem] = useState<any | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formTitle, setFormTitle] = useState("");
  const [formContent, setFormContent] = useState("");
  const [formCategory, setFormCategory] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const { notify } = useToast();

  const cats = kb?.categories ?? [];
  const total = kb?.total ?? 0;

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGet<{ items: any[]; categories: any[]; total: number }>("/api/knowledge/list");
      setItems(res.items || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadItems(); }, [loadItems]);

  const catsAll = cats.length > 0 ? [{ name: "", count: total }, ...cats] : [];

  const filtered = items.filter(item => {
    if (activeCat && item.category !== activeCat) return false;
    if (search) {
      const q = search.toLowerCase();
      return item.title?.toLowerCase().includes(q) || item.content?.toLowerCase().includes(q);
    }
    return true;
  });

  const handleAdd = async () => {
    if (!formTitle.trim()) { notify("标题不能为空", "warning"); return; }
    try {
      await apiPost("/api/knowledge/add", { title: formTitle.trim(), content: formContent.trim(), category: formCategory.trim() || "默认" });
      notify("已添加", "success");
      setShowAddForm(false); setFormTitle(""); setFormContent(""); setFormCategory("");
      await loadItems();
    } catch { notify("添加失败", "error"); }
  };

  const handleUpdate = async () => {
    if (!editItem || !formTitle.trim()) return;
    try {
      await apiPost("/api/knowledge/update", { id: editItem.id, title: formTitle.trim(), content: formContent.trim(), category: formCategory.trim() || editItem.category });
      notify("已更新", "success");
      setEditItem(null); setFormTitle(""); setFormContent(""); setFormCategory("");
      await loadItems();
    } catch { notify("更新失败", "error"); }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiPost("/api/knowledge/delete", { id });
      notify("已删除", "success");
      setDeleteConfirm(null);
      await loadItems();
    } catch { notify("删除失败", "error"); }
  };

  const startEdit = (item: any) => {
    setEditItem(item);
    setFormTitle(item.title);
    setFormContent(item.content);
    setFormCategory(item.category || "");
    setShowAddForm(false);
  };

  const startAdd = () => {
    setShowAddForm(true);
    setEditItem(null);
    setFormTitle(""); setFormContent(""); setFormCategory("");
  };

  return (
    <div className="space-y-3">
      {/* 顶栏：标题 + 总数 + 添加 */}
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sakura-600">知识库 <span className="text-sakura-300 font-normal text-[11px]">({total} 条目)</span></p>
        <button onClick={startAdd} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-gradient-to-br from-sakura-400 to-sakura-500 text-white hover:shadow-md transition-shadow">
          <Plus size={12} /> 添加
        </button>
      </div>

      {/* 搜索 */}
      <div className="relative">
        <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sakura-300" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          className="w-full pl-8 pr-3 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50/50 text-sakura-600 placeholder:text-sakura-300 transition-colors"
          placeholder="搜索标题或内容..." />
      </div>

      {/* 分类筛选标签 */}
      {catsAll.length > 1 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {catsAll.map((c, i) => (
            <button key={i} onClick={() => setActiveCat(activeCat === c.name ? "" : c.name)}
              className={`text-[10px] px-2.5 py-1 rounded-full border transition-colors ${
                activeCat === c.name
                  ? "bg-sakura-500 text-white border-sakura-500"
                  : "bg-white text-sakura-500 border-sakura-100 hover:border-sakura-300"
              }`}>
              {c.name || "全部"} {c.count !== undefined && <span className="ml-0.5 opacity-60">{c.count}</span>}
            </button>
          ))}
        </div>
      )}

      {/* 加载状态 */}
      {loading ? (
        <div className="text-center py-8">
          <div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" />
          <p className="text-xs text-sakura-400 mt-2">加载中...</p>
        </div>
      ) : (
        <>
          {/* 空状态 */}
          {filtered.length === 0 && !showAddForm && (
            <div className="text-center py-10">
              <div className="w-10 h-10 rounded-full bg-sakura-50 flex items-center justify-center mx-auto mb-2">
                <BookOpen size={16} className="text-sakura-300" />
              </div>
              <p className="text-xs text-sakura-400 mb-1">
                {search || activeCat ? "没有匹配的知识条目" : "知识库为空"}
              </p>
              <p className="text-[10px] text-sakura-300">
                {search || activeCat ? "试试其他关键词或分类" : "点击右上角「添加」创建第一条知识"}
              </p>
            </div>
          )}

          {/* 新建/编辑表单 */}
          {(showAddForm || editItem) && (
            <div className="bg-white border border-sakura-200 rounded-xl p-3 space-y-2 shadow-sm">
              <p className="text-[10px] font-semibold text-sakura-500">
                {editItem ? "编辑知识" : "新建知识"}
              </p>
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">标题</p>
                <input value={formTitle} onChange={e => setFormTitle(e.target.value)}
                  className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50"
                  placeholder="知识标题" />
              </div>
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">内容</p>
                <textarea value={formContent} onChange={e => setFormContent(e.target.value)}
                  className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50 resize-none"
                  rows={4} placeholder="知识内容..." />
              </div>
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">分类（可选）</p>
                <input value={formCategory} onChange={e => setFormCategory(e.target.value)}
                  className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50"
                  placeholder="默认" />
              </div>
              <div className="flex items-center gap-1.5 pt-0.5">
                <button onClick={() => { setShowAddForm(false); setEditItem(null); }}
                  className="px-3 py-1.5 rounded text-[10px] text-sakura-400 hover:bg-sakura-50 border border-sakura-100 transition-colors">
                  取消
                </button>
                <button onClick={editItem ? handleUpdate : handleAdd}
                  disabled={!formTitle.trim()}
                  className="px-3 py-1.5 rounded text-[10px] font-medium bg-sakura-500 text-white disabled:opacity-50 hover:bg-sakura-600 transition-colors">
                  <Check size={10} className="inline mr-0.5" />
                  {editItem ? "保存" : "创建"}
                </button>
              </div>
            </div>
          )}

          {/* 条目列表 */}
          <div className="space-y-1">
            {filtered.map((item) => (
              <div key={item.id} className="bg-white border border-sakura-100 rounded-lg overflow-hidden">
                {/* 条目行 */}
                <div className="flex items-center gap-2 px-3 py-2.5 group hover:bg-sakura-50/30 transition-colors cursor-pointer"
                  onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}>
                  <BookOpen size={12} className="text-sakura-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-medium text-sakura-600 truncate">{item.title}</span>
                      {item.category && (
                        <span className="text-[9px] text-sakura-400 bg-sakura-50 px-1.5 py-0.5 rounded-full shrink-0">{item.category}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[9px] text-sakura-300 mt-0.5">
                      <span>{item.created_at?.slice(0, 10) || ""}</span>
                      <span>{item.content ? `${item.content.length} 字` : ""}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); startEdit(item); }}
                      className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500 transition-colors" title="编辑">
                      <Edit3 size={10} />
                    </button>
                    {deleteConfirm === item.id ? (
                      <div className="flex items-center gap-0.5">
                        <button onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
                          className="px-1.5 py-0.5 rounded text-[9px] bg-red-500 text-white hover:bg-red-600 transition-colors">确认</button>
                        <button onClick={(e) => { e.stopPropagation(); setDeleteConfirm(null); }}
                          className="px-1.5 py-0.5 rounded text-[9px] text-sakura-400 hover:bg-sakura-100 transition-colors">取消</button>
                      </div>
                    ) : (
                      <button onClick={(e) => { e.stopPropagation(); setDeleteConfirm(item.id); }}
                        className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors" title="删除">
                        <Trash2 size={10} />
                      </button>
                    )}
                  </div>
                </div>
                {/* 展开详情 */}
                {expandedId === item.id && (
                  <div className="px-3 py-2.5 border-t border-sakura-50 bg-sakura-50/30">
                    <p className="text-[10px] text-sakura-600 leading-relaxed whitespace-pre-wrap">{item.content}</p>
                    <div className="flex items-center gap-2 mt-1.5 text-[9px] text-sakura-300">
                      <span>分类: {item.category || "未分类"}</span>
                      <span>创建: {item.created_at || "未知"}</span>
                      {item.updated_at && <span>更新: {item.updated_at}</span>}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* 结果统计 */}
          {filtered.length > 0 && (
            <div className="text-[9px] text-sakura-300 text-center py-1">
              共 {filtered.length} 条{search || activeCat ? `（共 ${total} 条）` : ""}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ToolsPage({ toolsData }: { toolsData: { tools: { name: string; desc: string }[] } | null }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeCat, setActiveCat] = useState("");
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const { notify } = useToast();

  // MCP 弹窗
  const [showMcpDialog, setShowMcpDialog] = useState(false);
  const [mcpServers, setMcpServers] = useState<Record<string, { command: string; args: string[]; env: Record<string, string> }>>({});
  const [mcpDialogLoading, setMcpDialogLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [showMcpForm, setShowMcpForm] = useState(false);
  const [mcpEditKey, setMcpEditKey] = useState<string | null>(null);
  const [fName, setFName] = useState("");
  const [fCmd, setFCmd] = useState("");
  const [fArgs, setFArgs] = useState("");
  const [mcpDelete, setMcpDelete] = useState<string | null>(null);

  const openMcpDialog = async () => {
    setShowMcpDialog(true);
    setMcpDialogLoading(true);
    try {
      const res = await apiGet<{ servers: any }>("/api/mcp/servers");
      setMcpServers(res.servers || {});
    } catch {}
    setMcpDialogLoading(false);
  };

  useEffect(() => {
    setLoading(true);
    apiGet<{ tools: any[]; count: number; categories: { name: string; count: number }[] }>("/api/tools")
      .then(d => { setItems(d.tools || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const catMap = new Map<string, number>();
  items.forEach(t => {
    const c = t.category || "core";
    catMap.set(c, (catMap.get(c) || 0) + 1);
  });
  const cats = Array.from(catMap.entries()).map(([name, count]) => ({ name, count }));
  const total = items.length;

  const filtered = items.filter(t => {
    if (activeCat && t.category !== activeCat) return false;
    if (search) {
      const q = search.toLowerCase();
      return t.name?.toLowerCase().includes(q) || t.description?.toLowerCase().includes(q);
    }
    return true;
  });

  const catIcon = (c: string) => {
    switch(c) {
      case "core": return <Zap size={11} />;
      case "extra": return <Layers size={11} />;
      case "system": return <CpuIcon size={11} />;
      case "mcp": return <Wifi size={11} />;
      case "plugin": return <HardDrive size={11} />;
      case "workflow": return <GitBranch size={11} />;
      default: return <Wrench size={11} />;
    }
  };

  // 所有分类使用统一 sakura 配色，只通过图标区分
  const catBadge = "bg-sakura-50 text-sakura-500 border-sakura-100";

  // ── MCP 操作 ──
  const saveMcp = async () => {
    if (!fName.trim() || !fCmd.trim()) { notify("名称和命令为必填", "warning"); return; }
    const updated = { ...mcpServers };
    if (mcpEditKey && mcpEditKey !== fName.trim()) delete updated[mcpEditKey];
    updated[fName.trim()] = { command: fCmd.trim(), args: fArgs.split(" ").filter(Boolean), env: {} };
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setMcpServers(updated);
      notify(mcpEditKey ? "已更新" : "已添加", "success");
      setShowMcpForm(false); setMcpEditKey(null); setFName(""); setFCmd(""); setFArgs("");
    } catch { notify("保存失败", "error"); }
  };

  const deleteMcp = async (key: string) => {
    const updated = { ...mcpServers };
    delete updated[key];
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setMcpServers(updated);
      notify("已删除", "success");
      setMcpDelete(null);
    } catch { notify("删除失败", "error"); }
  };

  const connectMcp = async () => {
    setConnecting(true);
    try {
      const res = await apiPost<{ ok: boolean; tool_count: number }>("/api/mcp/connect", {});
      notify(`连接完成，共 ${res.tool_count} 个工具`, "success");
    } catch { notify("连接失败", "error"); }
    setConnecting(false);
  };

  const testMcp = async (key: string) => {
    setTesting(key);
    try {
      const res = await apiPost<{ ok: boolean; error?: string; tools?: string[] }>("/api/mcp/test", { name: key });
      if (res.ok) notify(`连接成功，工具: ${(res.tools || []).join(", ") || "无"}`, "success");
      else notify(res.error || "测试失败", "error");
    } catch { notify("测试失败", "error"); }
    setTesting(null);
  };

  const mcpKeys = Object.keys(mcpServers);

  return (
    <div className="space-y-3">
      {/* 顶栏 */}
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sakura-600">工具列表 <span className="text-sakura-300 font-normal text-[11px]">({total} 个)</span></p>
        <button onClick={openMcpDialog}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-medium bg-sakura-50 text-sakura-500 hover:bg-sakura-100 border border-sakura-100 transition-colors">
          <Wifi size={10} /> MCP 配置
        </button>
      </div>

      {/* 统计卡片 */}
      {!loading && cats.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {cats.map((c, i) => (
            <div key={i}
              className="bg-white border border-sakura-100 rounded-xl px-3 py-2.5 flex items-center gap-2.5 cursor-pointer hover:shadow-sm transition-shadow"
              onClick={() => setActiveCat(activeCat === c.name ? "" : c.name)}>
              <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white bg-gradient-to-br from-sakura-400 to-sakura-500">
                {catIcon(c.name)}
              </div>
              <div>
                <p className="text-[11px] font-semibold text-sakura-600">{c.count}</p>
                <p className="text-[9px] text-sakura-400">{catLabel(c.name)}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 搜索 */}
      <div className="relative">
        <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sakura-300" />
        <input value={search} onChange={e => setSearch(e.target.value)}
          className="w-full pl-8 pr-3 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50/50 text-sakura-600 placeholder:text-sakura-300 transition-colors"
          placeholder="搜索工具名称或描述..." />
      </div>

      {/* ── MCP 配置弹窗 ── */}
      {showMcpDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowMcpDialog(false)}>
          <div className="absolute inset-0 bg-black/20" />
          <div className="relative bg-white rounded-xl shadow-2xl w-[520px] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="p-4 space-y-3">
              {/* 弹窗标题 */}
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-sakura-600">MCP 服务器</p>
                <div className="flex items-center gap-1.5">
                  <button onClick={async () => { setConnecting(true); try { const r = await apiPost<{ ok: boolean; tool_count: number }>("/api/mcp/connect", {}); notify(`连接完成，共 ${r.tool_count} 个工具`, "success"); } catch { notify("连接失败", "error"); } setConnecting(false); }}
                    disabled={connecting || Object.keys(mcpServers).length === 0}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-medium bg-teal-50 text-teal-600 hover:bg-teal-100 disabled:opacity-50 transition-colors">
                    {connecting ? <Loader2 size={10} className="animate-spin" /> : <Zap size={10} />} 连接全部
                  </button>
                  <button onClick={() => setShowMcpDialog(false)} className="p-1 hover:bg-sakura-50 rounded text-sakura-400"><X size={14} /></button>
                </div>
              </div>

              {mcpDialogLoading ? (
                <div className="flex items-center justify-center py-8 text-xs text-sakura-400">
                  <Loader2 size={12} className="animate-spin mr-2" />加载中...
                </div>
              ) : (
                <>
                  {/* 添加/编辑表单 */}
                  {showMcpForm && (
                    <div className="bg-sakura-50 border border-sakura-100 rounded-lg p-3 space-y-2">
                      <p className="text-[10px] font-semibold text-sakura-500">{mcpEditKey ? "编辑 MCP 服务器" : "添加 MCP 服务器"}</p>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <p className="text-[9px] text-sakura-400 mb-0.5">名称</p>
                          <input value={fName} onChange={e => setFName(e.target.value)}
                            className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-white" placeholder="如: fetch" />
                        </div>
                        <div>
                          <p className="text-[9px] text-sakura-400 mb-0.5">命令</p>
                          <input value={fCmd} onChange={e => setFCmd(e.target.value)}
                            className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-white font-mono" placeholder="如: npx" />
                        </div>
                      </div>
                      <div>
                        <p className="text-[9px] text-sakura-400 mb-0.5">参数（空格分隔）</p>
                        <input value={fArgs} onChange={e => setFArgs(e.target.value)}
                          className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-white font-mono" placeholder="如: @modelcontextprotocol/server-fetch" />
                      </div>
                      <div className="flex items-center gap-1.5 pt-0.5">
                        <button onClick={() => { setShowMcpForm(false); setMcpEditKey(null); }}
                          className="px-3 py-1.5 rounded text-[10px] text-sakura-400 hover:bg-sakura-50 border border-sakura-100 transition-colors">取消</button>
                        <button onClick={saveMcp} disabled={!fName.trim() || !fCmd.trim()}
                          className="px-3 py-1.5 rounded text-[10px] font-medium bg-sakura-500 text-white disabled:opacity-50 hover:bg-sakura-600 transition-colors">
                          <Check size={10} className="inline mr-0.5" />{mcpEditKey ? "保存" : "添加"}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* 服务器列表 */}
                  {Object.keys(mcpServers).length === 0 && !showMcpForm && (
                    <div className="text-center py-8">
                      <div className="w-10 h-10 rounded-full bg-sakura-50 flex items-center justify-center mx-auto mb-2">
                        <Wifi size={16} className="text-sakura-300" />
                      </div>
                      <p className="text-xs text-sakura-400 mb-1">未配置 MCP 服务器</p>
                      <p className="text-[10px] text-sakura-300">点击下方按钮添加</p>
                    </div>
                  )}

                  {Object.keys(mcpServers).length > 0 && (
                    <div className="space-y-1.5">
                      {Object.keys(mcpServers).map(key => {
                        const srv = mcpServers[key];
                        return (
                          <div key={key} className="flex items-center justify-between gap-2 px-3 py-2.5 bg-white border border-sakura-100 rounded-lg hover:bg-sakura-50/30 transition-colors">
                            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                              <div className="w-7 h-7 rounded-lg flex items-center justify-center bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">
                                <Wifi size={11} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <p className="text-[11px] font-medium text-sakura-600">{key}</p>
                                <p className="text-[9px] text-sakura-400 truncate font-mono">{srv.command} {(srv.args || []).join(" ")}</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <button onClick={() => testMcp(key)} disabled={testing === key}
                                className="p-1.5 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors" title="测试">
                                {testing === key ? <Loader2 size={10} className="animate-spin" /> : <Zap size={10} />}
                              </button>
                              <button onClick={() => { setShowMcpForm(true); setMcpEditKey(key); setFName(key); setFCmd(srv.command); setFArgs((srv.args || []).join(" ")); }}
                                className="p-1.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500 transition-colors" title="编辑">
                                <Edit3 size={10} />
                              </button>
                              {mcpDelete === key ? (
                                <div className="flex items-center gap-0.5">
                                  <button onClick={() => deleteMcp(key)} className="px-1.5 py-0.5 rounded text-[9px] bg-red-500 text-white hover:bg-red-600">确认</button>
                                  <button onClick={() => setMcpDelete(null)} className="px-1.5 py-0.5 rounded text-[9px] text-sakura-400 hover:bg-sakura-100">取消</button>
                                </div>
                              ) : (
                                <button onClick={() => setMcpDelete(key)} className="p-1.5 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors" title="删除">
                                  <Trash2 size={10} />
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* 添加按钮 */}
                  {!showMcpForm && (
                    <button onClick={() => { setShowMcpForm(true); setMcpEditKey(null); setFName(""); setFCmd(""); setFArgs(""); }}
                      className="w-full flex items-center justify-center gap-1 px-3 py-2 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
                      <Plus size={11} /> 添加服务器
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 加载状态 */}

      {/* 加载状态 */}
      {loading ? (
        <div className="text-center py-8">
          <div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" />
          <p className="text-xs text-sakura-400 mt-2">加载中...</p>
        </div>
      ) : (
        <>
          {/* 空状态 */}
          {filtered.length === 0 && (
            <div className="text-center py-10">
              <div className="w-10 h-10 rounded-full bg-sakura-50 flex items-center justify-center mx-auto mb-2">
                <Wrench size={16} className="text-sakura-300" />
              </div>
              <p className="text-xs text-sakura-400 mb-1">
                {search || activeCat ? "没有匹配的工具" : "暂无可用工具"}
              </p>
              <p className="text-[10px] text-sakura-300">
                {search || activeCat ? "试试其他关键词或分类" : "工具将在注册后自动出现"}
              </p>
            </div>
          )}

          {/* 工具列表 */}
          <div className="space-y-1">
            {filtered.map((t) => {
              const catCls = catBadge;
              const isExpanded = expandedTool === t.name;
              return (
              <div key={t.name} className="bg-white border border-sakura-100 rounded-lg overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2.5 group hover:bg-sakura-50/30 transition-colors cursor-pointer"
                  onClick={() => setExpandedTool(isExpanded ? null : t.name)}>
                  <div className="w-6 h-6 rounded flex items-center justify-center bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">
                    {catIcon(t.category)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-semibold text-sakura-600 truncate">{t.name}</span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full shrink-0 border ${catCls}`}>{catLabel(t.category)}</span>
                      {t.param_count > 0 && (
                        <span className="text-[9px] text-sakura-300">{t.param_count} 参数</span>
                      )}
                    </div>
                    <p className="text-[10px] text-sakura-400 mt-0.5 truncate">{t.description}</p>
                  </div>
                  {isExpanded ? <ChevronUp size={11} className="text-sakura-300 shrink-0" /> : <ChevronDown size={11} className="text-sakura-300 shrink-0" />}
                </div>
                {/* 展开详情：完整描述 + 参数列表 */}
                {isExpanded && (
                  <div className="px-3 py-2.5 border-t border-sakura-50 bg-sakura-50/30 space-y-2">
                    <p className="text-[10px] text-sakura-600 leading-relaxed">{t.description}</p>
                    <div className="flex items-center gap-3 text-[9px] text-sakura-400">
                      <span><span className="text-sakura-500 font-medium">分类:</span> {catLabel(t.category)}</span>
                      <span><span className="text-sakura-500 font-medium">参数:</span> {t.param_count} 个</span>
                      <span><span className="text-sakura-500 font-medium">类型:</span> function</span>
                    </div>
                    {/* 参数详情 */}
                    {t.params && t.params.length > 0 && (
                      <div>
                        <p className="text-[9px] font-semibold text-sakura-500 mb-1">参数列表</p>
                        <div className="space-y-0.5">
                          {t.params.map((p: any, pi: number) => (
                            <div key={pi} className="flex items-center gap-2 px-2 py-1 rounded bg-white/60 text-[10px]">
                              <span className="font-mono font-medium text-sakura-600 w-28 shrink-0 truncate">{p.name}</span>
                              <span className="text-sakura-400 w-16 shrink-0 text-[9px]">{p.type}</span>
                              {p.required ? (
                                <span className="text-red-400 text-[9px] shrink-0">必填</span>
                              ) : (
                                <span className="text-sakura-300 text-[9px] shrink-0">可选</span>
                              )}
                              <span className="text-sakura-400 flex-1 truncate">{p.description}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {(!t.params || t.params.length === 0) && (
                      <p className="text-[9px] text-sakura-300 italic">该工具无需参数</p>
                    )}
                  </div>
                )}
              </div>
            )})}
          </div>

          {/* 底部统计 */}
          {filtered.length > 0 && (
            <div className="text-[9px] text-sakura-300 text-center py-1">
              共 {filtered.length} 个工具{search || activeCat ? `（总共 ${total} 个）` : ""}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function catLabel(cat: string): string {
  const labels: Record<string, string> = {
    core: "核心",
    extra: "扩展",
    system: "系统",
    mcp: "MCP",
    plugin: "插件",
    workflow: "工作流",
  };
  return labels[cat] || cat;
}

function MemPage({ memLayers }: { memLayers: { name: string; desc: string; count: number; status: string }[] }) {
  const [stats, setStats] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [searchConvFilter, setSearchConvFilter] = useState("");
  const [activeCat, setActiveCat] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchPage, setSearchPage] = useState(1);
  const [viewingConv, setViewingConv] = useState<string | null>(null);
  const [convMsgs, setConvMsgs] = useState<any[]>([]);
  const [convLoading, setConvLoading] = useState(false);
  const [timeFilter, setTimeFilter] = useState("all");
  const { notify } = useToast();
  const PAGE_SIZE = 20;

  useEffect(() => {
    Promise.all([
      apiGet<any>("/api/memory/stats").then(setStats).catch(() => {}),
      apiGet<any>("/api/memory/categories").then(d => setCategories(d.categories || [])).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const doSearch = useCallback(async (q: string, convFilter: string, page: number = 1) => {
    if (!q.trim()) { setItems([]); setSearchTotal(0); return; }
    try {
      const res = await apiPost<{ items: any[]; total: number; page: number }>("/api/memory/search", {
        query: q, conv: convFilter, page, limit: PAGE_SIZE,
      });
      setItems(res.items || []);
      setSearchTotal(res.total || 0);
      setSearchPage(res.page || 1);
    } catch { setItems([]); }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => doSearch(search, searchConvFilter, 1), 300);
    return () => clearTimeout(timer);
  }, [search, searchConvFilter, doSearch]);

  const openConv = async (key: string) => {
    setViewingConv(key);
    setConvLoading(true);
    try {
      const res = await apiGet<{ key: string; messages: any[] }>(`/api/conversation/${encodeURIComponent(key)}`);
      setConvMsgs(res.messages || []);
    } catch { setConvMsgs([]); }
    setConvLoading(false);
  };

  const deleteConv = async (key: string) => {
    if (!confirm(`确定删除对话「${key}」？`)) return;
    try {
      await apiPost("/api/conversation/delete", { key });
      notify("已删除", "success");
      setCategories(prev => prev.filter((c: any) => c.key !== key));
      if (viewingConv === key) { setViewingConv(null); setConvMsgs([]); }
    } catch { notify("删除失败", "error"); }
  };

  const exportConv = async (key: string, msgs: any[]) => {
    const text = msgs.map((m: any) => `[${m.role === "user" ? "用户" : "奶昔"} ${safeTime(m.time).slice(0, 16) || ""}]\n${m.content}`).join("\n\n");
    const blob = new Blob([`对话：${key}\n共 ${msgs.length} 条消息\n${"=".repeat(30)}\n\n${text}`], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${key.replace(/[^a-zA-Z0-9_]/g, "_")}.txt`;
    a.click(); URL.revokeObjectURL(url);
    notify("已导出");
  };

  const safeTime = (t: any): string => {
    if (!t) return "";
    if (typeof t === "string") return t;
    if (typeof t === "number") return new Date(t * 1000).toLocaleString("zh-CN");
    return String(t);
  };

  const groupByDate = (msgs: any[]) => {
    const groups: { label: string; items: any[] }[] = [];
    const today = new Date().toISOString().slice(0, 10);
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    for (const m of msgs) {
      const d = safeTime(m.time).slice(0, 10);
      let label = d;
      if (d === today) label = "今天";
      else if (d === yesterday) label = "昨天";
      const last = groups[groups.length - 1];
      if (last && last.label === label) last.items.push(m);
      else groups.push({ label, items: [m] });
    }
    return groups;
  };

  if (viewingConv !== null) {
    const filtered = convMsgs.filter((m: any) => {
      if (timeFilter === "all") return true;
      const d = safeTime(m.time).slice(0, 10);
      if (!d) return true;
      const diff = Math.floor((Date.now() - new Date(d).getTime()) / 86400000);
      return timeFilter === "7d" ? diff <= 7 : diff <= 30;
    });
    const groups = groupByDate(filtered);
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <button onClick={() => { setViewingConv(null); setConvMsgs([]); }}
            className="p-1 rounded hover:bg-sakura-50 text-sakura-400 transition-colors"><ChevronLeft size={14} /></button>
          <p className="text-sm font-semibold text-sakura-600 truncate flex-1">{viewingConv}</p>
          <span className="text-[10px] text-sakura-400">{convMsgs.length} 条</span>
          <button onClick={() => exportConv(viewingConv, convMsgs)} className="p-1.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500 transition-colors" title="导出对话"><Download size={11} /></button>
          <button onClick={() => deleteConv(viewingConv)} className="p-1.5 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors" title="删除对话"><Trash2 size={11} /></button>
        </div>
        <div className="flex items-center gap-1.5">
          {[{k:"all",l:"全部"},{k:"7d",l:"近7天"},{k:"30d",l:"近30天"}].map(t => (
            <button key={t.k} onClick={() => setTimeFilter(t.k)}
              className={`text-[10px] px-2 py-1 rounded-full border transition-colors ${timeFilter===t.k?"bg-sakura-500 text-white border-sakura-500":"bg-white text-sakura-500 border-sakura-100 hover:border-sakura-300"}`}>{t.l}</button>
          ))}
        </div>
        {convLoading ? (
          <div className="text-center py-8"><Loader2 size={14} className="animate-spin mx-auto text-sakura-300" /></div>
        ) : groups.length === 0 ? (
          <div className="text-center py-10 text-xs text-sakura-400">该时间范围内暂无消息</div>
        ) : groups.map((g, gi) => (
          <div key={gi}>
            <div className="flex items-center gap-2 mb-1"><span className="text-[10px] font-medium text-sakura-500">{g.label}</span><span className="text-[9px] text-sakura-300">{g.items.length} 条</span><div className="flex-1 border-t border-sakura-100" /></div>
            <div className="space-y-1">
              {g.items.map((m: any, mi: number) => (
                <div key={mi} className="flex items-start gap-2 px-2.5 py-2 bg-white border border-sakura-100 rounded-lg group">
                  <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${m.role==="user"?"bg-pink-100":"bg-sakura-100"}`}>
                    <Brain size={10} className={m.role==="user"?"text-pink-400":"text-sakura-400"} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[9px] font-medium text-sakura-500">{m.role==="user"?"用户":"奶昔"}</span>
                      <span className="text-[8px] text-sakura-300">{safeTime(m.time).slice(11,16)}</span>
                    </div>
                    <p className="text-[10px] text-sakura-600 mt-0.5 whitespace-pre-wrap">{m.content}</p>
                  </div>
                  <button onClick={() => { navigator.clipboard.writeText(m.content||""); notify("已复制","success"); }}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500 transition-all shrink-0"><Copy size={10} /></button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-sakura-600">记忆系统</p>
      </div>
      {!loading && stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[{l:"总记忆",v:stats.total},{l:"对话数",v:stats.conversations},{l:"近7天活跃",v:stats.recent_7d},{l:"分类",v:stats.categories?.length||0}].map((c,i) => (
            <div key={i} className="bg-white border border-sakura-100 rounded-xl px-3 py-2.5">
              <p className="text-[9px] text-sakura-400">{c.l}</p>
              <p className="text-sm font-semibold text-sakura-600">{c.v}</p>
            </div>
          ))}
        </div>
      )}
      {!loading && stats?.categories?.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {stats.categories.map((c: any, i: number) => (
            <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-sakura-50 text-sakura-500 border border-sakura-100">{c.name} <span className="opacity-60">{c.count}</span></span>
          ))}
        </div>
      )}
      {!loading && categories.length > 0 && !search && (
        <div>
          <p className="text-[10px] font-medium text-sakura-500 mb-1">所有对话</p>
          <div className="space-y-1">
            {categories.map((c: any, i: number) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2 bg-white border border-sakura-100 rounded-lg group cursor-pointer hover:bg-sakura-50/50 transition-colors" onClick={() => openConv(c.key)}>
                <div className="w-6 h-6 rounded flex items-center justify-center bg-gradient-to-br from-sakura-400 to-sakura-500 text-white"><MessageCircle size={11} /></div>
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] font-medium text-sakura-600 truncate">{c.label}</p>
                  <p className="text-[9px] text-sakura-400 truncate">{c.last_msg||"暂无消息"}</p>
                </div>
                <div className="text-right shrink-0 mr-1"><p className="text-[10px] font-semibold text-sakura-500">{c.count}</p><p className="text-[8px] text-sakura-300">条</p></div>
                <button onClick={(e) => { e.stopPropagation(); deleteConv(c.key); }} className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-all shrink-0" title="删除对话"><Trash2 size={10} /></button>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sakura-300" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50/50 text-sakura-600 placeholder:text-sakura-300 transition-colors"
            placeholder="搜索记忆内容..." />
        </div>
        <select value={searchConvFilter} onChange={e => { setSearchConvFilter(e.target.value); setSearchPage(1); }}
          className="px-2 py-1.5 border border-sakura-100 rounded-lg text-[10px] outline-none focus:border-sakura-300 bg-white text-sakura-500 shrink-0">
          <option value="">全部对话</option>
          <option value="auto:">自动</option>
          <option value="test">测试</option>
        </select>
      </div>
      {loading ? (
        <div className="text-center py-8"><div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" /><p className="text-xs text-sakura-400 mt-2">加载中...</p></div>
      ) : (<>
        {!search && stats?.recent?.length > 0 && (
          <div><p className="text-[10px] font-medium text-sakura-500 mb-1">最近记忆</p>
            <div className="space-y-1">{stats.recent.map((r: any, i: number) => (
              <div key={i} className="flex items-start gap-2 px-2.5 py-2 bg-white border border-sakura-100 rounded-lg cursor-pointer hover:bg-sakura-50/50" onClick={() => openConv(r.conv)}>
                <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${r.role==="user"?"bg-pink-100":"bg-sakura-100"}`}>
                  <Brain size={10} className={r.role==="user"?"text-pink-400":"text-sakura-400"} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5"><span className="text-[9px] font-medium text-sakura-500">{r.role==="user"?"用户":"奶昔"}</span><span className="text-[8px] text-sakura-300 truncate">{r.conv}</span></div>
                  <p className="text-[10px] text-sakura-600 mt-0.5 truncate">{r.content}</p>
                </div>
                <span className="text-[8px] text-sakura-300 shrink-0">{safeTime(r.time).slice(5,16)}</span>
              </div>
            ))}</div>
          </div>
        )}
        {search && items.length===0 && searchTotal===0 && (
          <div className="text-center py-10"><div className="w-10 h-10 rounded-full bg-sakura-50 flex items-center justify-center mx-auto mb-2"><Brain size={16} className="text-sakura-300" /></div><p className="text-xs text-sakura-400">没有找到匹配的记忆</p><p className="text-[10px] text-sakura-300 mt-1">试试其他关键词</p></div>
        )}
        {items.length > 0 && (<div className="space-y-1"><p className="text-[10px] text-sakura-400 mb-1">找到 {searchTotal} 条结果</p>
          {items.map((item) => (
            <div key={item.id} className="bg-white border border-sakura-100 rounded-lg overflow-hidden">
              <div className="flex items-start gap-2 px-3 py-2.5 cursor-pointer hover:bg-sakura-50/30 transition-colors" onClick={() => setExpandedId(expandedId===item.id?null:item.id)}>
                <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${item.role==="user"?"bg-pink-100":"bg-sakura-100"}`}>
                  <Brain size={10} className={item.role==="user"?"text-pink-400":"text-sakura-400"} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5"><span className="text-[10px] font-medium text-sakura-600">{item.role==="user"?"用户":"奶昔"}</span><span className="text-[8px] text-sakura-300 px-1.5 py-0.5 rounded bg-sakura-50">{item.conv?.startsWith("auto:")?"自动":"对话"}</span></div>
                  <p className="text-[10px] text-sakura-500 mt-0.5 line-clamp-2">{item.content}</p>
                  <span className="text-[8px] text-sakura-300 mt-0.5 block">{safeTime(item.time)}</span>
                </div>
              </div>
              {expandedId===item.id && (
                <div className="px-3 py-2 border-t border-sakura-50 bg-sakura-50/30">
                  <p className="text-[10px] text-sakura-600 leading-relaxed whitespace-pre-wrap">{item.content}</p>
                  <div className="flex items-center gap-2 mt-1.5 text-[9px] text-sakura-400">
                    <span>对话: {item.conv}</span><span>角色: {item.role}</span><span>时间: {safeTime(item.time)}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
          {/* 分页 */}
          {searchTotal > PAGE_SIZE && (
            <div className="flex items-center justify-center gap-1 pt-1">
              <button onClick={() => doSearch(search, searchConvFilter, Math.max(1, searchPage - 1))}
                disabled={searchPage <= 1}
                className="px-2 py-1 rounded text-[9px] border border-sakura-100 text-sakura-500 disabled:opacity-30 hover:bg-sakura-50 transition-colors">上一页</button>
              <span className="text-[9px] text-sakura-400 px-1">{searchPage} / {Math.ceil(searchTotal / PAGE_SIZE)}</span>
              <button onClick={() => doSearch(search, searchConvFilter, searchPage + 1)}
                disabled={searchPage >= Math.ceil(searchTotal / PAGE_SIZE)}
                className="px-2 py-1 rounded text-[9px] border border-sakura-100 text-sakura-500 disabled:opacity-30 hover:bg-sakura-50 transition-colors">下一页</button>
            </div>
          )}
        </div>)}
      </>)}
    </div>
  );
}

function NapcatPage({ napcat }: { napcat: NapcatData | null }) {
  const [conns, setConns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [configMode, setConfigMode] = useState<string | null>(null);
  const [fExtra, setFExtra] = useState("{}");
  const [fEnabled, setFEnabled] = useState(true);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const { notify } = useToast();

  const loadConns = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await apiGet<any>("/api/desktop/config");
      const saved = cfg.platform_configs || {};
      const defaults = [
        { id:"napcat", name:"QQ (NapCat)", desc:"NapCat/LLOneBot WebSocket 桥接", tp:"msg", fields:[{k:"ws_url",l:"WebSocket 地址",p:"ws://127.0.0.1:3001"},{k:"http_url",l:"HTTP 地址",p:"http://127.0.0.1:3000"},{k:"token",l:"Token(可选)",p:""}] },
        { id:"qq_official", name:"QQ 官方机器人", desc:"QQ 官方 Bot API + 沙箱环境", tp:"msg", fields:[{k:"app_id",l:"App ID",p:"从开放平台获取"},{k:"token",l:"Bot Token",p:""},{k:"secret",l:"Secret",p:""}] },
        { id:"qq_guild", name:"QQ 频道", desc:"QQ 频道机器人 WebSocket", tp:"msg", fields:[{k:"app_id",l:"App ID",p:""},{k:"token",l:"Bot Token",p:""}] },
        { id:"wechat_personal", name:"个人微信", desc:"通过第三方库桥接(需扫码)", tp:"msg", fields:[{k:"mode",l:"连接方式",p:"pc / docker"},{k:"host",l:"服务地址",p:"http://127.0.0.1:8080"},{k:"token",l:"Token(可选)",p:""}] },
        { id:"wechat_mp", name:"微信公众号", desc:"公众号开发模式消息回调", tp:"msg", fields:[{k:"app_id",l:"AppID",p:"从公众号后台获取"},{k:"app_secret",l:"AppSecret",p:""},{k:"token",l:"Token",p:"手动设置的 Token"}] },
        { id:"wecom", name:"企业微信", desc:"企业内部应用消息回调", tp:"msg", fields:[{k:"corp_id",l:"企业 ID",p:"wwxxxx"},{k:"agent_id",l:"Agent ID",p:""},{k:"secret",l:"Secret",p:""},{k:"token",l:"Token",p:""}] },
        { id:"feishu", name:"飞书", desc:"自建应用事件回调+机器人", tp:"msg", fields:[{k:"app_id",l:"App ID",p:"cli_xxxxx"},{k:"app_secret",l:"App Secret",p:""}] },
        { id:"dingtalk", name:"钉钉", desc:"机器人出站消息+Stream 模式", tp:"msg", fields:[{k:"client_id",l:"Client ID",p:"从开放平台获取"},{k:"client_secret",l:"Client Secret",p:""}] },
        { id:"telegram", name:"Telegram", desc:"Bot API 轮询或 Webhook", tp:"msg", fields:[{k:"token",l:"Bot Token",p:"123456:ABC-DEF123"},{k:"proxy",l:"代理地址(可选)",p:""}] },
        { id:"discord", name:"Discord", desc:"Bot Token + Gateway Intents", tp:"msg", fields:[{k:"token",l:"Bot Token",p:"MTIzNDU2Nzg5"},{k:"guild_id",l:"服务器 ID(可选)",p:""}] },
        { id:"slack", name:"Slack", desc:"App + Bot Token + Event Sub", tp:"msg", fields:[{k:"token",l:"Bot Token",p:"xoxb-xxx"},{k:"signing_secret",l:"Signing Secret",p:""}] },
        { id:"line", name:"LINE", desc:"LINE Messaging API 回调", tp:"msg", fields:[{k:"channel_secret",l:"Channel Secret",p:"从 LINE Dev Console 获取"},{k:"access_token",l:"Channel Access Token",p:""}] },
        { id:"kook", name:"KOOK(开黑啦)", desc:"KOOK Bot WebSocket", tp:"msg", fields:[{k:"token",l:"Bot Token",p:"从开发者中心获取"}] },
        { id:"whatsapp", name:"WhatsApp", desc:"Cloud API / Baileys Webhook", tp:"msg", fields:[{k:"phone_id",l:"Phone Number ID",p:"Meta Business 后台"},{k:"token",l:"Access Token",p:""}] },
        { id:"weibo", name:"微博", desc:"微博开放平台消息回调", tp:"msg", fields:[{k:"app_key",l:"App Key",p:"从开放平台获取"},{k:"app_secret",l:"App Secret",p:""}] },
        { id:"bilibili", name:"哔哩哔哩", desc:"B站开放平台 WS 直播/私信", tp:"msg", fields:[{k:"access_key",l:"Access Key",p:"从开放平台获取"},{k:"room_id",l:"直播间 ID(可选)",p:""}] },
        { id:"email", name:"电子邮件", desc:"POP3/IMAP 监听+SMTP 发送", tp:"webhook", fields:[{k:"imap_host",l:"IMAP 服务器",p:"imap.qq.com"},{k:"imap_port",l:"IMAP 端口",p:"993"},{k:"email",l:"邮箱地址",p:"xxx@qq.com"},{k:"password",l:"密码/授权码",p:""}] },
        { id:"sms", name:"短信", desc:"通过 Twilio / 云片 收发", tp:"webhook", fields:[{k:"provider",l:"服务商",p:"twilio / 云片"},{k:"account_sid",l:"Account SID",p:""},{k:"auth_token",l:"Auth Token",p:""},{k:"phone",l:"绑定手机号",p:""}] },
        { id:"webhook", name:"自定义 HTTP", desc:"通用 Webhook 接收器", tp:"webhook", fields:[{k:"endpoint",l:"自定义端点",p:"/webhook/my-bot"},{k:"secret",l:"验签 Secret",p:""}] },
      ];
      const merged = defaults.map(d => {
        const s = saved[d.id] || {};
        return { ...d, enabled: s.enabled !== false, fields: d.fields.map(f => ({ ...f, v: s[f.k] || "" })) };
      });
      setConns(merged);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadConns(); }, [loadConns]);

  const openConfig = (conn: any) => {
    setConfigMode(conn.id);
    setFEnabled(conn.enabled);
    setTestResult(null);
    const vals: Record<string, string> = {};
    conn.fields.forEach((f: any) => { vals[f.k] = f.v; });
    setFExtra(JSON.stringify(vals));
  };

  const saveConfig = async () => {
    if (!configMode) return;
    try {
      const cfg = await apiGet<any>("/api/desktop/config");
      const platform_configs = cfg.platform_configs || {};
      let vals = {};
      try { vals = JSON.parse(fExtra); } catch {}
      platform_configs[configMode] = { ...vals, enabled: fEnabled };
      await apiPost("/api/desktop/config", { platform_configs });
      notify("已保存", "success");
      setConfigMode(null);
      loadConns();
    } catch { notify("保存失败", "error"); }
  };

  const testPlatform = async () => {
    if (!configMode) return;
    setTesting(true);
    setTestResult(null);
    const conn = conns.find(c => c.id === configMode);
    const urlKeys = new Set(["ws_url", "http_url", "host", "webhook", "endpoint", "imap_host", "imap_port", "proxy"]);
    const hasUrl = conn?.fields?.some((f: any) => urlKeys.has(f.k) || f.p?.startsWith("http") || f.p?.startsWith("ws"));
    if (!hasUrl) {
      setTestResult("该平台无 URL 测试端点，保存后接入使用即可");
      setTesting(false);
      return;
    }
    let vals: Record<string, string> = {};
    try { vals = JSON.parse(fExtra); } catch {}
    const testUrl = Object.values(vals).find(v => v && (v.startsWith("http") || v.startsWith("ws")));
    if (!testUrl) {
      setTestResult("请先填写地址再测试");
      setTesting(false);
      return;
    }
    try {
      const res = await apiPost<{ ok: boolean; error?: string; status?: number }>("/api/platform/test", { url: testUrl, config: vals });
      if (res.ok) setTestResult(`连通 (HTTP ${res.status})`);
      else setTestResult(res.error || "连接失败");
    } catch { setTestResult("测试失败"); }
    setTesting(false);
  };

  if (configMode) {
    const conn = conns.find(c => c.id === configMode);
    if (!conn) return null;
    let vals: Record<string, string> = {};
    try { vals = JSON.parse(fExtra); } catch {}
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <button onClick={() => setConfigMode(null)} className="p-1 rounded hover:bg-sakura-50 text-sakura-400"><ChevronLeft size={14} /></button>
          <p className="text-sm font-semibold text-sakura-600">{conn.name}</p>
        </div>
        <div className="bg-white border border-sakura-100 rounded-xl p-3 space-y-2.5">
          <p className="text-[10px] font-medium text-sakura-600">连接配置</p>
          {conn.fields.map((f: any, i: number) => (
            <div key={i}>
              <p className="text-[9px] text-sakura-500 mb-0.5">{f.l}</p>
              <input value={vals[f.k] || ""} onChange={e => { vals[f.k] = e.target.value; setFExtra(JSON.stringify(vals)); }}
                className="w-full px-2.5 py-1.5 border border-sakura-100 rounded-lg text-[10px] outline-none focus:border-sakura-300 bg-sakura-50 text-sakura-600 font-mono"
                placeholder={f.p} />
            </div>
          ))}
          <div className="flex items-center gap-2 pt-1">
            <button onClick={() => setFEnabled(!fEnabled)}
              className={`px-2.5 py-1 rounded text-[9px] font-medium transition-colors ${fEnabled ? "bg-sakura-100 text-sakura-600" : "bg-sakura-50 text-sakura-400"}`}>
              {fEnabled ? "已启用" : "已禁用"}
            </button>
            <div className="flex-1" />
            <button onClick={() => setConfigMode(null)} className="px-3 py-1.5 rounded text-[9px] text-sakura-400 hover:bg-sakura-50 border border-sakura-100">取消</button>
            <button onClick={saveConfig} className="px-3 py-1.5 rounded text-[9px] font-medium bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">保存</button>
            <button onClick={testPlatform} disabled={testing}
              className="px-3 py-1.5 rounded text-[9px] font-medium bg-teal-50 text-teal-600 hover:bg-teal-100 disabled:opacity-50 transition-colors">
              {testing ? <Loader2 size={9} className="animate-spin inline" /> : "测试"}
            </button>
          </div>
          {testResult && (
            <p className={`text-[9px] ${testResult.includes("连通") ? "text-green-600" : "text-red-500"}`}>{testResult}</p>
          )}
        </div>
        <p className="text-[9px] text-sakura-400 font-mono bg-sakura-50 px-2.5 py-1.5 rounded-lg">
          Webhook: /api/webhook/{configMode}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-sakura-600">连接</p>
      {loading ? (
        <div className="text-center py-8"><div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" /></div>
      ) : (
        <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
          <div className="px-3 py-2 border-b border-sakura-100 bg-sakura-50/30 flex items-center justify-between">
            <span className="text-[10px] font-medium text-sakura-500">平台连接</span>
            <span className="text-[8px] text-sakura-300">{conns.filter(c => c.enabled).length}/{conns.length} 已启用</span>
          </div>
          <div className="divide-y divide-sakura-50">
            {conns.map(conn => {
              const isQQ = conn.id === "napcat";
              const connected = isQQ ? (napcat?.connected ?? false) : conn.enabled;
              return (
                <div key={conn.id} className="flex items-center gap-2.5 px-3 py-2 hover:bg-sakura-50/30 transition-colors">
                  <MessageCircle size={13} className="text-sakura-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] font-medium text-sakura-600">{conn.name}</span>
                      <span className={`text-[8px] px-1 py-0.5 rounded ${connected ? "bg-sakura-100 text-sakura-600" : "bg-sakura-50 text-sakura-400"}`}>
                        {connected ? (isQQ ? "运行中" : "已启用") : "未启用"}
                      </span>
                    </div>
                    <p className="text-[8px] text-sakura-400 truncate">{conn.desc}</p>
                  </div>
                  <button onClick={() => openConfig(conn)}
                    className="px-2.5 py-1 rounded text-[9px] font-medium bg-white border border-sakura-100 text-sakura-400 hover:text-sakura-600 hover:border-sakura-300 transition-colors shrink-0">
                    配置
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
function OpsPage({ sys, health, dbStats, status, errors }:
  { sys: any; health: any; dbStats: any; status: any; errors: { msg: string; stack: string; time: number }[] }) {
  const [loading, setLoading] = useState(true);
  const [resources, setResources] = useState<any>(null);
  const [services, setServices] = useState<any>(null);
  const [tables, setTables] = useState<any[]>([]);
  const { notify } = useToast();

  useEffect(() => {
    Promise.all([
      apiGet<any>("/api/system/resources").then(setResources).catch(() => {}),
      apiGet<any>("/api/service/health").then(setServices).catch(() => {}),
      apiGet<any>("/api/database/stats").then(d => setTables(d.tables || [])).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const srvList = services ? [
    { n: "后端 API", k: "backend", p: "9845" },
    { n: "NapCat HTTP", k: "napcat_http", p: "3000" },
    { n: "NapCat WS", k: "napcat_ws", p: "3001" },
    { n: "Ollama", k: "ollama", p: "11434" },
    { n: "SearXNG", k: "searxng", p: "8898" },
  ].map(s => ({ ...s, ok: services[s.k] === true })) : [];

  const recentErrors = errors.slice(-5).reverse();
  const diskPct = resources?.disk ?? 0;
  const memPct = resources?.memory ?? 0;
  const cpuPct = resources?.cpu ?? 0;

  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-sakura-600">运维监控</p>
      {loading ? (
        <div className="text-center py-8"><div className="w-5 h-5 border-2 border-sakura-200 border-t-sakura-500 rounded-full animate-spin mx-auto" /></div>
      ) : (
        <>
          {/* 服务健康 */}
          <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-sakura-100 bg-sakura-50/30">
              <span className="text-[10px] font-medium text-sakura-500">服务健康</span>
            </div>
            <div className="divide-y divide-sakura-50">
              {srvList.map(s => (
                <div key={s.k} className="flex items-center gap-2.5 px-3 py-2">
                  <div className={`w-2 h-2 rounded-full shrink-0 ${s.ok ? "bg-green-500" : "bg-red-500"}`} />
                  <span className="text-[11px] font-medium text-sakura-600 min-w-[6rem]">{s.n}</span>
                  <span className="text-[8px] text-sakura-400 font-mono">:{s.p}</span>
                  <div className="flex-1" />
                  <span className={`text-[8px] px-1.5 py-0.5 rounded font-medium ${s.ok ? "bg-green-50 text-green-600" : "bg-red-50 text-red-500"}`}>
                    {s.ok ? "在线" : "离线"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* 系统资源 */}
          <div className="bg-white border border-sakura-100 rounded-xl p-3 space-y-2">
            <p className="text-[10px] font-medium text-sakura-500">系统资源</p>
            <Bar label="CPU" val={`${cpuPct.toFixed(1)}%`} w={cpuPct} />
            <Bar label="内存" val={`${memPct.toFixed(1)}%`} w={memPct} />
            <Bar label="磁盘" val={`${diskPct.toFixed(1)}%`} w={diskPct} />
          </div>

          {/* 数据库 */}
          <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
            <div className="px-3 py-2 border-b border-sakura-100 bg-sakura-50/30">
              <span className="text-[10px] font-medium text-sakura-500">数据库</span>
            </div>
            <div className="divide-y divide-sakura-50">
              {tables.slice(0, 10).map(t => (
                <div key={t.name} className="flex items-center justify-between px-3 py-1.5">
                  <span className="text-[9px] text-sakura-500 font-mono">{t.name}</span>
                  <span className="text-[9px] text-sakura-600 font-medium">{t.count.toLocaleString()} 条</span>
                </div>
              ))}
            </div>
          </div>

          {/* 最近错误 */}
          {recentErrors.length > 0 && (
            <div className="bg-white border border-red-200 rounded-xl overflow-hidden">
              <div className="px-3 py-2 border-b border-red-100 bg-red-50/30">
                <span className="text-[10px] font-medium text-red-500">最近错误 ({recentErrors.length})</span>
              </div>
              <div className="divide-y divide-red-50">
                {recentErrors.map((e, i) => (
                  <div key={i} className="px-3 py-1.5">
                    <p className="text-[9px] text-red-600 font-mono truncate">{e.msg}</p>
                    <p className="text-[8px] text-sakura-400">{new Date(e.time).toLocaleString("zh-CN")}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 系统信息 */}
          <div className="flex items-center gap-2 text-[9px] text-sakura-400 px-0.5">
            <span>版本 {status?.version || "?"}</span>
            <span className="text-sakura-200">|</span>
            <span>工具 {status?.tools || 0} 个</span>
            <span className="text-sakura-200">|</span>
            <span>技能 {status?.skills || 0}</span>
            <span className="text-sakura-200">|</span>
            <span>Agent {status?.agents || 0}</span>
          </div>
        </>
      )}
    </div>
  );
}

function LivePage() {
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">虚拟主播</p>
      <div className="bg-white border border-sakura-100 rounded-xl px-4 py-8 text-center">
        <p className="text-xs text-sakura-400">虚拟主播模块（5 Agent 串联）</p>
        <p className="text-[11px] text-sakura-300 mt-1">弹幕 → LLM → TTS → 立绘 → RTMP 推流</p>
        <p className="text-[11px] text-sakura-300 mt-1">B站开发者认证审核中，通过后配置即可上线</p>
      </div>
    </div>
  );
}

function SchedulerPage() {
  const safeParse = (s: any, fallback: any = {}) => {
    if (typeof s === "string") { try { return JSON.parse(s); } catch { return fallback; } }
    if (s && typeof s === "object") return s;
    return fallback;
  };
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [automations, setAutomations] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [showCreate, setShowCreate] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [showExecModal, setShowExecModal] = useState(false);
  const [execTarget, setExecTarget] = useState<any>(null);
  const [execRuns, setExecRuns] = useState<any[]>([]);
  const [execFilter, setExecFilter] = useState("");
  const [page, setPage] = useState(1);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formWorkflow, setFormWorkflow] = useState("");
  const [formTrigger, setFormTrigger] = useState("schedule");
  const [formConfig, setFormConfig] = useState("0 9 * * *");
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const PAGE_SIZE = 10;

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [wfRes, autoRes] = await Promise.all([
        apiGet<any>("/api/workflows"),
        apiGet<any>("/api/automations"),
      ]);
      if (wfRes?.workflows) setWorkflows(wfRes.workflows);
      if (autoRes?.automations) setAutomations(autoRes.automations);

      const allRuns: any[] = [];
      if (wfRes?.workflows) {
        const batch = wfRes.workflows.slice(0, 3);
        const runResults = await Promise.all(
          batch.map(async (w: any) => {
            try {
              const r = await apiGet<any>(`/api/workflows/${w.id}/runs?limit=5`);
              return (r?.runs || []).map((run: any) => ({ ...run, wf_name: w.name }));
            } catch { return []; }
          })
        );
        runResults.forEach((arr: any[]) => allRuns.push(...arr));
      }
      allRuns.sort((a, b) => ((b.started_at || b.created_at) || "").localeCompare((a.started_at || a.created_at) || ""));
      setRuns(allRuns.slice(0, 20));
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // 监听其他页面（Chat 自动化面板）的变更通知
  useEffect(() => {
    const handler = () => {
      apiGet<{ automations: any[] }>("/api/automations")
        .then(d => { if (d?.automations) setAutomations(d.automations); })
        .catch(() => {});
    };
    window.addEventListener("automation-changed", handler);
    return () => window.removeEventListener("automation-changed", handler);
  }, []);

  // 自动刷新：每 30 秒轮询（保底）
  useEffect(() => {
    const t = setInterval(() => {
      // 只在前台且可能显示时刷新
      apiGet<{ automations: any[] }>("/api/automations")
        .then(d => { if (d?.automations) setAutomations(d.automations); })
        .catch(() => {});
      apiGet<{ workflows: any[] }>("/api/workflows")
        .then(d => { if (d?.workflows) setWorkflows(d.workflows); })
        .catch(() => {});
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const refetch = useCallback(() => loadData(), [loadData]);

  const handleCreate = useCallback(async () => {
    if (!formName || !formWorkflow) return;
    try {
      const config = formTrigger === "schedule" ? { cron: formConfig } : { endpoint: formConfig, method: "POST" };
      await apiPost("/api/automations/save", {
        name: formName, description: formDesc, workflow_id: formWorkflow,
        trigger_type: formTrigger, config: JSON.stringify(config),
        schedule_type: formTrigger,  // 兼容旧字段
      });
      setShowCreate(false); setEditId(null);
      setFormName(""); setFormDesc(""); setFormWorkflow(""); setFormConfig("0 9 * * *");
      refetch();
    } catch {}
  }, [formName, formDesc, formWorkflow, formTrigger, formConfig, refetch]);

  const handleDelete = useCallback(async (id: string) => {
    try { await apiPost("/api/automations/delete", { id }); refetch(); } catch {}
  }, [refetch]);

  const handleRun = useCallback(async (id: string, auto?: any) => {
    if (auto?.workflow_id) {
      try {
        await apiPost<any>("/api/workflows/run", { id: auto.workflow_id, input: { silent_mode: true } });
        showToast("已触发工作流执行");
      } catch { showToast("工作流执行失败", "error"); }
      try { await apiPost("/api/automations/run", { id }); } catch {}
    } else {
      await apiPost<any>("/api/automations/run", { id }).then(() => showToast("已触发执行")).catch(() => showToast("执行失败", "error"));
    }
    // 静默刷新列表（不显示 loading 转圈，避免页面闪动）
    try {
      const res = await apiGet<{ automations: any[] }>("/api/automations");
      if (res?.automations) setAutomations(res.automations);
    } catch {}
  }, []);

  const handleToggle = useCallback(async (item: any) => {
    try { await apiPost("/api/automations/toggle", { id: item.id }); refetch(); } catch {}
  }, [refetch]);

  // 删除确认
  const confirmDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try { await apiPost("/api/automations/delete", { id: deleteTarget.id }); refetch(); } catch {}
    setShowDeleteModal(false); setDeleteTarget(null);
  }, [deleteTarget, refetch]);

  // 查看执行记录
  const openExecModal = useCallback(async (auto: any) => {
    setExecTarget(auto);
    setExecFilter("");
    try {
      // 来自 automation_list 的 history（该自动化的专属执行记录）
      let allRuns: any[] = (auto.history || []).map((h: any, idx: number) => ({
        id: `h_${auto.id}_${idx}_${h.time}`,
        started_at: h.time,
        status: h.status,
        wf_name: auto.name,
        duration: "",
        trigger: "auto",
      }));
      
      // 如果是工作流型，追加该工作流的执行记录
      if (auto.workflow_id) {
        try {
          const r = await apiGet<any>(`/api/workflows/${auto.workflow_id}/runs?limit=20`);
          (r?.runs || []).forEach((run: any) => allRuns.push({ ...run, wf_name: auto.name }));
        } catch {}
      }
      
      allRuns.sort((a, b) => ((b.started_at || b.created_at) || "").localeCompare((a.started_at || a.created_at) || ""));
      setExecRuns(allRuns);
    } catch { setExecRuns([]); }
    setShowExecModal(true);
  }, []);

  // 删除单条执行记录
  const handleDeleteRun = useCallback(async (runId: string) => {
    try {
      await apiPost("/api/workflows/delete-run", { id: runId });
      setExecRuns(prev => prev.filter(r => r.id !== runId));
      showToast("已删除");
    } catch { showToast("删除失败", "error"); }
  }, []);

  const filtered = automations.filter((a: any) => {
    if (filter !== "all" && a.trigger_type !== filter) return false;
    if (search && !a.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const todayRuns = runs.filter((r: any) => {
    if (!r.started_at && !r.created_at) return false;
    const today = new Date().toISOString().slice(0, 10);
    return (r.started_at || r.created_at).slice(0, 10) === today;
  });

  const triggerLabel = (a: any) => {
    // 工作流型
    if (a.workflow_id) return `工作流`;
    // Prompt 型
    if (a.prompt) {
      if (a.schedule_type === "once") return `一次 (${a.scheduled_at?.slice(5, 16) || "?"})`;
      if (a.rrule) {
        if (a.rrule.includes("DAILY")) return `每天`;
        if (a.rrule.includes("WEEKLY")) return `每周`;
        if (a.rrule.includes("HOURLY")) return `每小时`;
        return `定时`;
      }
      return `Prompt`;
    }
    if (a.trigger_type === "schedule") return `定时 (${safeParse(a.config).cron || "?"})`;
    if (a.trigger_type === "webhook") return `Webhook`;
    return "手动";
  };

  const showToast = (msg: string, type: "success" | "error" = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2500);
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-xs text-sakura-400">加载中...</p>
    </div>
  );

  const pageTotal = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="space-y-4 px-1">
      {/* ═══ 顶栏：标题 + 创建 ═══ */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-sakura-600">自动化</p>
          <p className="text-[10px] text-sakura-400 mt-0.5">定时执行任务，自动产出结果</p>
        </div>
        <button type="button" onClick={() => setShowCreate(true)}
          className="flex items-center gap-1 px-3.5 py-2 rounded-lg text-[11px] font-medium bg-sakura-500 text-white hover:bg-sakura-600 transition-colors shadow-sm">
          <Plus size={12} /> 创建
        </button>
      </div>

      {/* ═══ 统计卡片 ═══ */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "工作流", value: workflows.length, icon: <GitBranch size={14} /> },
          { label: "定时任务", value: automations.filter((a:any) => a.trigger_type === "schedule").length, icon: <Calendar size={14} /> },
          { label: "Webhook", value: automations.filter((a:any) => a.trigger_type === "webhook").length, icon: <Zap size={14} /> },
          { label: "今日执行", value: todayRuns.length, icon: <Clock size={14} /> },
        ].map((card, i) => (
          <div key={i} className="bg-white border border-sakura-100 rounded-xl px-4 py-3 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-sakura-50 flex items-center justify-center text-sakura-400">{card.icon}</div>
            <div>
              <p className="text-xl font-semibold text-sakura-600">{card.value}</p>
              <p className="text-[10px] text-sakura-400">{card.label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* ═══ 搜索 + 筛选 ═══ */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="w-full pl-7 pr-2.5 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-sakura-50/50 text-sakura-600 placeholder:text-sakura-300 transition-colors"
            placeholder="搜索自动化..." />
          <Search size={11} className="absolute left-2 top-1/2 -translate-y-1/2 text-sakura-300" />
        </div>
        <select value={filter} onChange={e => { setFilter(e.target.value); setPage(1); }}
          className="px-2 py-1.5 border border-sakura-100 rounded-lg text-[11px] outline-none focus:border-sakura-300 bg-white text-sakura-500">
          <option value="all">全部</option>
          <option value="schedule">定时</option>
          <option value="webhook">Webhook</option>
        </select>
      </div>

      {/* ═══ 创建面板（右滑式） ═══ */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex justify-end" onClick={() => setShowCreate(false)}>
          <div className="absolute inset-0 bg-black/20" />
          <div className="relative w-[420px] bg-white h-full shadow-2xl overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="p-5 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-sakura-600">新建自动化</p>
                <button onClick={() => setShowCreate(false)} className="p-1 hover:bg-sakura-50 rounded text-sakura-400"><X size={14} /></button>
              </div>
              <div>
                <label className="block text-[10px] text-sakura-500 font-medium mb-1">名称 <span className="text-red-400">*</span></label>
                <input value={formName} onChange={e => setFormName(e.target.value)} className="w-full px-3 py-2 border border-sakura-100 rounded-lg text-xs outline-none focus:border-sakura-300" placeholder="如：每日新闻摘要" />
              </div>
              <div>
                <label className="block text-[10px] text-sakura-500 font-medium mb-1">描述</label>
                <textarea value={formDesc} onChange={e => setFormDesc(e.target.value)} className="w-full px-3 py-2 border border-sakura-100 rounded-lg text-xs outline-none focus:border-sakura-300 resize-none" rows={2} placeholder="描述这个自动化任务做什么..." />
              </div>
              <div>
                <label className="block text-[10px] text-sakura-500 font-medium mb-1">关联工作流 <span className="text-red-400">*</span></label>
                <select value={formWorkflow} onChange={e => setFormWorkflow(e.target.value)} className="w-full px-3 py-2 border border-sakura-100 rounded-lg text-xs outline-none focus:border-sakura-300 bg-white">
                  <option value="">选择工作流...</option>
                  {workflows.map((w: any) => (<option key={w.id} value={w.id}>{w.name}</option>))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] text-sakura-500 font-medium mb-1">触发方式</label>
                <div className="flex gap-2">
                  {[
                    { key: "schedule", label: "定时", icon: <Calendar size={12} /> },
                    { key: "webhook", label: "Webhook", icon: <Zap size={12} /> },
                  ].map(t => (
                    <button key={t.key} onClick={() => setFormTrigger(t.key)}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-[11px] border transition-colors ${formTrigger === t.key ? "bg-sakura-100 border-sakura-300 text-sakura-600" : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"}`}>
                      {t.icon} {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-[10px] text-sakura-500 font-medium mb-1">{formTrigger === "schedule" ? "Cron 表达式" : "Webhook 端点"}</label>
                <input value={formConfig} onChange={e => setFormConfig(e.target.value)} className="w-full px-3 py-2 border border-sakura-100 rounded-lg text-xs outline-none focus:border-sakura-300 font-mono" placeholder={formTrigger === "schedule" ? "0 9 * * *" : "/webhook/xxx"} />
                {formTrigger === "schedule" && <p className="text-[9px] text-sakura-300 mt-1">分 时 日 月 周，如 0 9 * * * = 每天 9:00</p>}
              </div>
              <div className="flex items-center gap-2 pt-2">
                <button onClick={() => setShowCreate(false)} className="flex-1 px-3 py-2 rounded-lg text-xs border border-sakura-100 text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
                <button onClick={handleCreate} disabled={!formName || !formWorkflow}
                  className="flex-1 px-3 py-2 rounded-lg text-xs font-medium bg-sakura-500 text-white hover:bg-sakura-600 disabled:opacity-50 transition-colors">创建</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══ 任务列表 ═══ */}
      <div className="bg-white border border-sakura-100 rounded-xl overflow-hidden">
        <div className="grid grid-cols-[1.5fr_1fr_0.8fr_0.8fr_110px] gap-2 px-4 py-2.5 border-b border-sakura-100 text-[10px] text-sakura-400 font-medium bg-sakura-50/50">
          <span>名称</span><span>触发方式</span><span>状态</span><span>上次运行</span><span className="text-right">操作</span>
        </div>
        {paged.length === 0 ? (
          <div className="px-4 py-12 text-center">
            <div className="w-10 h-10 rounded-full bg-sakura-50 flex items-center justify-center mx-auto mb-2">
              <Calendar size={16} className="text-sakura-300" />
            </div>
            <p className="text-xs text-sakura-400 mb-1">{search ? "没有匹配的自动化" : "还没有自动任务"}</p>
            <p className="text-[10px] text-sakura-300">点击右上角「创建」添加</p>
          </div>
        ) : paged.map((a: any) => (
          <div key={a.id} className="border-b border-sakura-50 last:border-b-0">
            <div className="grid grid-cols-[1.5fr_1fr_0.8fr_0.8fr_110px] gap-2 px-4 py-3 hover:bg-sakura-50/30 transition-colors items-center">
              <div className="min-w-0">
                <span className="text-[12px] font-medium text-sakura-600 truncate block cursor-pointer hover:text-sakura-700" onClick={() => openExecModal(a)} title="查看执行记录">{a.name}</span>
                {a.description && <span className="text-[10px] text-sakura-400 truncate block mt-0.5">{a.description}</span>}
                {!a.description && a.prompt && <span className="text-[10px] text-sakura-300 truncate block mt-0.5">Prompt: {a.prompt.slice(0, 60)}</span>}
              </div>
              <div className="flex items-center gap-1.5 text-[11px]">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${a.trigger_type === "schedule" ? "bg-green-400" : a.trigger_type === "webhook" ? "bg-blue-400" : "bg-gray-300"}`} />
                <span className="text-sakura-500">{triggerLabel(a)}</span>
              </div>
              <div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" className="sr-only peer" checked={a.status === "active"} onChange={() => handleToggle(a)} />
                  <div className="w-7 h-4 bg-sakura-200 rounded-full peer peer-checked:bg-green-400 peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all" />
                </label>
              </div>
              <div className="text-[10px] text-sakura-400">
                <span className={a.last_result === "success" ? "text-green-500" : a.last_result === "failed" ? "text-red-400" : "text-sakura-300"}>
                  {a.last_result === "success" ? "成功" : a.last_result === "failed" ? "失败" : "—"}
                </span>
                {a.last_run && <span className="ml-1">{a.last_run.slice(5, 16)}</span>}
              </div>
              <div className="flex items-center justify-end gap-1">
                <button type="button" onClick={() => handleRun(a.id, a)} className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors" title="立即执行"><Play size={11} /></button>
                <button type="button" onClick={() => openExecModal(a)} className="p-1 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500 transition-colors" title="执行记录"><Clock size={11} /></button>
                <button type="button" onClick={() => setShowCreate(true)} className="p-1 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500 transition-colors" title="编辑"><Edit3 size={11} /></button>
                <button type="button" onClick={() => { setDeleteTarget(a); setShowDeleteModal(true); }} className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors" title="删除"><Trash2 size={11} /></button>
              </div>
            </div>
          </div>
        ))}
        {/* 分页 */}
        {pageTotal > 1 && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-sakura-50 text-[10px] text-sakura-400">
            <span>共 {filtered.length} 条</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} className="px-2 py-1 rounded hover:bg-sakura-50 disabled:opacity-30 transition-colors">上一页</button>
              {Array.from({ length: pageTotal }, (_, i) => i + 1).map(p => (
                <button key={p} onClick={() => setPage(p)} className={`w-5 h-5 rounded text-center ${page === p ? "bg-sakura-100 text-sakura-600 font-medium" : "hover:bg-sakura-50"}`}>{p}</button>
              ))}
              <button onClick={() => setPage(p => Math.min(pageTotal, p + 1))} disabled={page >= pageTotal} className="px-2 py-1 rounded hover:bg-sakura-50 disabled:opacity-30 transition-colors">下一页</button>
            </div>
          </div>
        )}
      </div>

      {/* ═══ 删除确认弹窗 ═══ */}
      {showDeleteModal && deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowDeleteModal(false)}>
          <div className="absolute inset-0 bg-black/20" />
          <div className="relative bg-white rounded-xl shadow-xl w-[380px] p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center shrink-0"><CircleAlert size={16} className="text-red-400" /></div>
              <div>
                <p className="text-sm font-semibold text-sakura-600">确认删除</p>
                <p className="text-[11px] text-sakura-400 mt-1">确定要删除「{deleteTarget.name}」吗？<br />此操作不可恢复。</p>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => { setShowDeleteModal(false); setDeleteTarget(null); }} className="px-3 py-1.5 rounded-lg text-[11px] border border-sakura-100 text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={confirmDelete} className="px-3 py-1.5 rounded-lg text-[11px] bg-red-500 text-white hover:bg-red-600">删除</button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ 执行记录弹窗 ═══ */}
      {showExecModal && execTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setShowExecModal(false)}>
          <div className="absolute inset-0 bg-black/20" />
          <div className="relative bg-white rounded-xl shadow-xl w-[700px] max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-sakura-100 shrink-0">
              <p className="text-sm font-semibold text-sakura-600">执行记录 - {execTarget.name}</p>
              <button onClick={() => setShowExecModal(false)} className="p-1 hover:bg-sakura-50 rounded text-sakura-400"><X size={14} /></button>
            </div>
            <div className="px-5 py-2 border-b border-sakura-50 shrink-0">
              <select value={execFilter} onChange={e => setExecFilter(e.target.value)} className="px-2 py-1 border border-sakura-100 rounded text-[10px] outline-none text-sakura-500">
                <option value="">全部状态</option>
                <option value="success">成功</option>
                <option value="failed">失败</option>
                <option value="running">执行中</option>
              </select>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-1.5">
              {execRuns.filter(r => !execFilter || r.status === execFilter).length === 0 ? (
                <p className="text-center text-[11px] text-sakura-300 py-8">暂无执行记录</p>
              ) : execRuns.filter(r => !execFilter || r.status === execFilter).map((r: any) => (
                <div key={r.id} className="flex items-center gap-3 text-[11px] py-1.5 px-2 rounded hover:bg-sakura-50 group">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${r.status === "success" ? "bg-green-400" : r.status === "failed" ? "bg-red-400" : "bg-amber-400"}`} />
                  <span className="text-sakura-500 min-w-[6rem] font-mono">{r.started_at?.slice(5, 16) || r.created_at?.slice(5, 16) || "--"}</span>
                  <span className={`font-medium ${r.status === "success" ? "text-green-600" : r.status === "failed" ? "text-red-500" : "text-amber-500"}`}>{r.status === "success" ? "成功" : r.status === "failed" ? "失败" : r.status}</span>
                  <span className="text-sakura-400 flex-1 truncate">{r.wf_name || r.workflow_id?.slice(0, 8) || "—"}</span>
                  <span className="text-sakura-300">{r.duration ? `${r.duration}ms` : ""}</span>
                  <button onClick={() => handleDeleteRun(r.id)} className="p-0.5 rounded text-sakura-200 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity" title="删除此记录"><Trash2 size={10} /></button>
                </div>
              ))}
            </div>
            {execRuns.length > 0 && (
              <div className="px-5 py-2 border-t border-sakura-50 text-[9px] text-sakura-300 shrink-0">
                共 {execRuns.length} 条记录
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══ 执行反馈 Toast ═══ */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-[100] animate-bounce-in">
          <div className={`flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg text-xs font-medium ${
            toast.type === "success" ? "bg-green-500 text-white" : "bg-red-500 text-white"
          }`}>
            {toast.type === "success" ? <Check size={13} /> : <CircleAlert size={13} />}
            {toast.msg}
          </div>
        </div>
      )}
    </div>
  );
}

function LogsPage() {
  const [logs, setLogs] = useState("");
  useEffect(() => {
    fetch("/api/logs").then(r => r.text().then(setLogs)).catch(() => setLogs("无法加载日志"));
  }, []);
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">日志</p>
      <pre className="bg-[#1a1a2e] text-green-400 text-[11px] p-4 rounded-xl overflow-auto max-h-[70vh] font-mono leading-relaxed">{logs || "加载中..."}</pre>
    </div>
  );
}
