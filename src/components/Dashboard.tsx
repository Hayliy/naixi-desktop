import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { AppShell, Sidebar, Header, Main } from "@/components/shell";
import { AppProvider } from "@/contexts/AppContext";
import { ToastProvider } from "@/components/Toast";
import { Card } from "@/components/ui";
import ChatPage from "@/components/Chat";
import WorkflowEditor from "@/components/WorkflowEditor";
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
  { key: "napcat",     icon: <Bot size={16} />,            label: "NapCat" },
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
          <div style={{ display: activeNav === "workflow" ? "block" : "none", height: "100%" }}><ErrorBoundary name="工作流"><WorkflowEditor /></ErrorBoundary></div>
          <div style={{ display: activeNav === "knowledge" ? "block" : "none", height: "100%" }}><ErrorBoundary name="知识库"><KbPage kb={kb} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "tools" ? "block" : "none", height: "100%" }}><ErrorBoundary name="工具"><ToolsPage toolsData={toolsData} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "memory" ? "block" : "none", height: "100%" }}><ErrorBoundary name="记忆"><MemPage memLayers={memLayers} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "napcat" ? "block" : "none", height: "100%" }}><ErrorBoundary name="NapCat"><NapcatPage napcat={napcat} /></ErrorBoundary></div>
          <div style={{ display: activeNav === "ops" ? "block" : "none", height: "100%" }}><ErrorBoundary name="运维"><OpsPage sys={sys} /></ErrorBoundary></div>
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
  const cats = kb?.categories ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">知识库 <span className="text-sakura-300 font-normal">({kb?.total ?? 0} 条目)</span></p>
      <div className="grid gap-2 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
        {cats.map((c, i) => (
          <div key={i} className="bg-white border border-sakura-100 rounded-xl px-4 py-3 flex items-center justify-between">
            <span className="text-xs text-sakura-600">{c.name}</span>
            <span className="text-xs font-semibold text-sakura-500">{c.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ToolsPage({ toolsData }: { toolsData: { tools: { name: string; desc: string }[] } | null }) {
  const tools = toolsData?.tools ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">工具列表 <span className="text-sakura-300 font-normal">({tools.length} 个)</span></p>
      <div className="space-y-1">
        {tools.map((t, i) => (
          <div key={i} className="bg-white border border-sakura-100 rounded-xl px-4 py-2.5 flex items-center gap-2 text-xs">
            <Wrench size={12} className="text-sakura-400 shrink-0" />
            <span className="text-sakura-600 font-medium w-48 shrink-0">{t.name}</span>
            <span className="text-sakura-400">{t.desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MemPage({ memLayers }: { memLayers: { name: string; desc: string; count: number; status: string }[] }) {
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">记忆系统</p>
      <div className="space-y-2">
        {memLayers.map((l, i) => (
          <div key={i} className="bg-white border border-sakura-100 rounded-xl px-4 py-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-sakura-600">{l.name}</p>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${l.status === "active" ? "bg-green-50 text-green-600" : "bg-sakura-50 text-sakura-400"}`}>{l.status}</span>
            </div>
            <p className="text-[11px] text-sakura-400 mt-0.5">{l.desc} · {l.count} 条</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function NapcatPage({ napcat }: { napcat: NapcatData | null }) {
  const ok = napcat?.connected ?? false;
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">NapCat 连接</p>
      <div className="bg-white border border-sakura-100 rounded-xl px-4 py-4">
        <div className="flex items-center gap-3">
          <div className={`w-12 h-12 rounded-full flex items-center justify-center ${ok ? "bg-green-100" : "bg-red-100"}`}>
            {ok ? <Wifi size={24} className="text-green-500" /> : <WifiOff size={24} className="text-red-500" />}
          </div>
          <div>
            <p className={`text-sm font-semibold ${ok ? "text-green-700" : "text-red-700"}`}>{ok ? "已连接" : "离线"}</p>
            <p className="text-xs text-sakura-400 mt-0.5">{ok ? `${napcat?.groups ?? 0} 个群` : "QQ 消息无法收发"}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function OpsPage({ sys }: { sys: SysData | null }) {
  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold text-sakura-500">运维监控</p>
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
        <div className="bg-white border border-sakura-100 rounded-xl px-4 py-4 space-y-3">
          <p className="text-xs font-medium text-sakura-500">系统资源</p>
          <Bar label="CPU" val={`${sys?.cpu ?? 0}%`} w={sys?.cpu ?? 0} />
          <Bar label="内存" val={`${sys?.memory ?? 0}%`} w={sys?.memory ?? 0} />
          <Bar label="磁盘" val={`${sys?.disk ?? 0}%`} w={sys?.disk ?? 0} />
          <Bar label="GPU" val={`${sys?.gpu_util ?? 0}%`} w={sys?.gpu_util ?? 0} />
        </div>
        <div className="bg-white border border-sakura-100 rounded-xl px-4 py-4 space-y-2">
          <p className="text-xs font-medium text-sakura-500">服务状态</p>
          <Row l="GPU 型号" v={sys?.gpu_name ?? "无"} />
          <Row l="显存" v={`${sys?.gpu_mem_used ?? 0} MB / ${sys?.gpu_mem_total ?? 0} MB`} />
          <Row l="后端口" v=":9845" />
          <Row l="NapCat" v=":3000 / :3001" />
          <Row l="Ollama" v=":11434" />
          <Row l="SearXNG" v=":8898" />
        </div>
      </div>
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
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formWorkflow, setFormWorkflow] = useState("");
  const [formTrigger, setFormTrigger] = useState("schedule");
  const [formConfig, setFormConfig] = useState("0 9 * * *");
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [wfRes, autoRes] = await Promise.all([
        apiGet<any>("/api/workflows"),
        apiGet<any>("/api/automations"),
      ]);
      if (wfRes?.workflows) setWorkflows(wfRes.workflows);
      if (Array.isArray(autoRes)) setAutomations(autoRes);

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

  const refetch = useCallback(() => loadData(), [loadData]);

  const handleCreate = useCallback(async () => {
    if (!formName || !formWorkflow) return;
    try {
      const config = formTrigger === "schedule" ? { cron: formConfig } : { endpoint: formConfig, method: "POST" };
      await apiPost("/api/automations/create", {
        name: formName, description: formDesc, workflow_id: formWorkflow,
        trigger_type: formTrigger, config,
      });
      setShowCreate(false);
      setFormName(""); setFormDesc(""); setFormWorkflow(""); setFormConfig("0 9 * * *");
      refetch();
    } catch {}
  }, [formName, formDesc, formWorkflow, formTrigger, formConfig, refetch]);

  const handleDelete = useCallback(async (id: string) => {
    try { await apiPost("/api/automations/delete", { id }); refetch(); } catch {}
  }, [refetch]);

  const handleRun = useCallback(async (id: string) => {
    try { await apiPost("/api/automations/run", { id }); refetch(); } catch {}
  }, [refetch]);

  const handleToggle = useCallback(async (item: any) => {
    const newStatus = item.status === "active" ? "paused" : "active";
    try { await apiPost("/api/automations/update", { id: item.id, status: newStatus }); refetch(); } catch {}
  }, [refetch]);

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

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-xs text-gray-400">加载中...</p>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3">
          <p className="text-[11px] text-gray-400">工作流</p>
          <p className="text-xl font-semibold text-gray-700 mt-1">{workflows.length}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3">
          <p className="text-[11px] text-gray-400">定时任务</p>
          <p className="text-xl font-semibold text-gray-700 mt-1">{automations.filter((a:any) => a.trigger_type === "schedule").length}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3">
          <p className="text-[11px] text-gray-400">Webhook</p>
          <p className="text-xl font-semibold text-gray-700 mt-1">{automations.filter((a:any) => a.trigger_type === "webhook").length}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3">
          <p className="text-[11px] text-gray-400">今日执行</p>
          <p className="text-xl font-semibold text-gray-700 mt-1">{todayRuns.length}</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <input value={search} onChange={e => setSearch(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300"
          placeholder="搜索自动化..." />
        <select value={filter} onChange={e => setFilter(e.target.value)}
          className="px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300">
          <option value="all">全部</option>
          <option value="schedule">定时</option>
          <option value="webhook">Webhook</option>
          <option value="manual">手动</option>
        </select>
        <button onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-sakura-100 text-sakura-600 rounded-lg text-xs hover:bg-sakura-200 transition-colors">
          + 新建
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="grid grid-cols-[2fr_1.2fr_1fr_1fr_100px] gap-3 px-4 py-2.5 border-b border-gray-100 text-[11px] text-gray-400 font-medium">
          <span>名称</span><span>触发方式</span><span>状态</span><span>上次运行</span><span />
        </div>
        {filtered.length === 0 && (
          <div className="px-4 py-10 text-center text-xs text-gray-400">
            {search ? "没有匹配的自动化" : "还没有自动任务，点击右上角新建"}
          </div>
        )}
        {filtered.map((a: any) => (
          <div key={a.id} className="grid grid-cols-[2fr_1.2fr_1fr_1fr_100px] gap-3 px-4 py-3 border-b border-gray-100 last:border-b-0 items-center hover:bg-gray-50 transition-colors">
            <div>
              <p className="text-sm font-medium text-gray-700 truncate">{a.name}</p>
              <p className="text-[11px] text-gray-400 truncate">{a.description}</p>
            </div>
            <span className="flex items-center gap-1.5 text-xs text-gray-600">
              <span className={`w-1.5 h-1.5 rounded-full ${a.trigger_type === "schedule" ? "bg-green-400" : a.trigger_type === "webhook" ? "bg-blue-400" : "bg-gray-400"}`} />
              {a.trigger_type === "schedule"
                ? `定时 (${safeParse(a.config).cron || "?"})`
                : a.trigger_type === "webhook"
                  ? `Webhook ${safeParse(a.config).method || "POST"}`
                  : "手动"}
            </span>
            <span>
              <button onClick={() => handleToggle(a)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
                  a.status === "active"
                    ? "bg-green-50 text-green-600 hover:bg-green-100"
                    : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                }`}>
                {a.status === "active" ? "运行中" : "已暂停"}
              </button>
            </span>
            <span className="text-[11px] text-gray-400">
              {a.last_result === "success" ? "成功" : a.last_result === "failed" ? "失败" : "--"}
              {a.last_run ? ` ${a.last_run.slice(5, 16)}` : ""}
            </span>
            <div className="flex items-center gap-1">
              <button onClick={() => handleRun(a.id)}
                className="px-2.5 py-1 rounded text-[11px] bg-sakura-50 text-sakura-600 hover:bg-sakura-100 transition-colors">
                执行
              </button>
              <button onClick={() => handleDelete(a.id)}
                className="px-2.5 py-1 rounded text-[11px] text-red-400 hover:bg-red-50 transition-colors">
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      <div>
        <p className="text-sm font-semibold text-gray-700 mb-2">执行历史</p>
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="grid grid-cols-[1.5fr_1fr_1fr_1.2fr] gap-3 px-4 py-2.5 border-b border-gray-100 text-[11px] text-gray-400 font-medium">
            <span>工作流</span><span>触发</span><span>状态</span><span>时间</span>
          </div>
          {runs.length === 0 && (
            <div className="px-4 py-10 text-center text-xs text-gray-400">暂无执行记录</div>
          )}
          {runs.slice(0, 15).map((r: any) => (
            <div key={r.id} className="grid grid-cols-[1.5fr_1fr_1fr_1.2fr] gap-3 px-4 py-2.5 border-b border-gray-100 last:border-b-0 text-xs text-gray-600 hover:bg-gray-50 transition-colors">
              <span className="truncate">{r.wf_name || r.workflow_id?.slice(0, 8)}</span>
              <span className="text-gray-400">{r.trigger || "manual"}</span>
              <span className={r.status === "success" ? "text-green-600" : r.status === "failed" ? "text-red-500" : "text-amber-500"}>
                {r.status === "success" ? "成功" : r.status === "failed" ? "失败" : r.status === "running" ? "执行中" : r.status}
              </span>
              <span className="text-gray-400">{r.started_at?.slice(5, 16) || r.created_at?.slice(5, 16) || "--"}</span>
            </div>
          ))}
        </div>
      </div>

      {showCreate && (
        <div className="fixed inset-0 bg-black/20 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[480px] p-6" onClick={e => e.stopPropagation()}>
            <p className="text-sm font-semibold text-gray-700 mb-4">新建自动化</p>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">名称</label>
                <input value={formName} onChange={e => setFormName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">描述</label>
                <input value={formDesc} onChange={e => setFormDesc(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">关联工作流</label>
                <select value={formWorkflow} onChange={e => setFormWorkflow(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300">
                  <option value="">选择工作流...</option>
                  {workflows.map((w: any) => (
                    <option key={w.id} value={w.id}>{w.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">触发方式</label>
                <select value={formTrigger} onChange={e => setFormTrigger(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300">
                  <option value="schedule">定时 (Cron)</option>
                  <option value="webhook">Webhook</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  {formTrigger === "schedule" ? "Cron 表达式" : "Webhook 端点"}
                </label>
                <input value={formConfig} onChange={e => setFormConfig(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs font-mono outline-none focus:border-sakura-300"
                  placeholder={formTrigger === "schedule" ? "0 9 * * *" : "/webhook/my-trigger"} />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setShowCreate(false)}
                className="px-4 py-2 border border-gray-200 rounded-lg text-xs text-gray-500 hover:bg-gray-50 transition-colors">取消</button>
              <button onClick={handleCreate}
                className="px-4 py-2 bg-sakura-100 text-sakura-600 rounded-lg text-xs hover:bg-sakura-200 transition-colors">创建</button>
            </div>
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
