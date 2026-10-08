import { useState, useEffect, useCallback, useRef } from "react";
import {
  Cpu, Download, Trash2, Play, Square, Search, Loader2, Check, X,
  HardDrive, MessageSquare, RefreshCw, Package, AlertTriangle, Eye,
  SlidersHorizontal, FolderOpen, Globe, Copy,
} from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { useAppConfig } from "@/contexts/AppContext";

/* ── 本地模型页 ──────────────────────────────────────────────
   目标：让不熟悉 llama/Ollama 的用户也能像装软件一样用本地模型。
   流程：找模型 → 下载 → 启动 → 对话。四步都在这一页完成，
   不需要用户知道什么叫 GGUF、什么参数、怎么开命令行。 */

interface CatalogItem {
  id: string; name: string; owner: string; repo: string; file: string;
  size_gb: number; params: string; vision: boolean; note: string;
  tier: string; downloaded: boolean; local_size_gb: number;
}
interface LocalModel {
  path: string; name: string; size_gb: number; kind: string; source: string; dir?: string;
}
interface Engines { llamacpp: boolean; llamacpp_path: string; ollama: boolean; ollama_path: string; }
interface Status {
  ollama_running: boolean; llamacpp_running: boolean;
  self_managed: boolean; self_model: string; self_uptime_s: number;
  llamacpp_port: number;
  // 对外接入信息（OpenAI 兼容）：给第三方工具填 base_url 用
  endpoint?: {
    base_url: string; chat_url: string; models_url: string;
    api_key: string; bind: string; external_access: boolean;
    running: boolean; model: string; protocol: string;
    authenticated?: boolean;
  };
}
interface Progress {
  running: boolean; finished: boolean; file: string; done_mb: number;
  total_mb: number; percent: number; speed_mbps: number; error: string;
}
interface SearchHit {
  id: string; full: string; name: string; namespace: string;
  downloads: number; stars: number; desc: string; tasks: string[];
  size_gb: number; license: string; maybe_gguf: boolean;
  has_gguf?: boolean; gguf_count?: number;
  has_weights?: boolean; weight_count?: number; usable?: boolean;
}

const TIER_LABEL: Record<string, { text: string; cls: string }> = {
  light: { text: "轻量 · 4GB 显卡可加速", cls: "text-green-600 bg-green-50 border-green-100" },
  mid: { text: "中等 · 建议部分加速", cls: "text-yellow-600 bg-yellow-50 border-yellow-100" },
  heavy: { text: "较大 · 建议纯CPU", cls: "text-orange-600 bg-orange-50 border-orange-100" },
  vision: { text: "视觉 · 看图/视频", cls: "text-purple-600 bg-purple-50 border-purple-100" },
};

/** 本机能力档位：由用户自己选，不替用户决定（4GB 核显 ↔ 64GB 独显差几个数量级） */
const HW_TIERS = [
  { gb: 4, label: "≤4GB" },
  { gb: 8, label: "≤8GB" },
  { gb: 16, label: "≤16GB" },
  { gb: 32, label: "≤32GB" },
  { gb: 0, label: "不限" },
];

/** 下载量友好显示：1234 → 1.2k，1234567 → 1.2M */
function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/* ── 行式容器（对齐 SettingsPage 的行式范式，不用卡片堆） ── */
function Row({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    // shrink-0 必须有：外层是 flex 列容器，缺了它子项会被压扁
    //（列表容器高度不够时只显示前 2 行 —— 踩过：以为数据只返回 2 条）
    <div className={`flex items-center gap-3 px-3 py-2 border-b border-sakura-50
                    last:border-0 shrink-0 ${className}`}>
      {children}
    </div>
  );
}

/* 生成参数单行输入：label + 数值框，空串交给上层处理（→ undefined → 用 server 默认） */
function GenParam({ label, value, setter, hint, placeholder }: {
  label: string; value: string; setter: (v: string) => void;
  hint?: string; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] text-sakura-400">
        {label}{hint ? `（${hint}）` : ""}
      </span>
      <input value={value} onChange={(e) => setter(e.target.value)}
        inputMode="decimal" placeholder={placeholder}
        className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                   bg-sakura-50 border border-sakura-100 rounded
                   focus:outline-none focus:border-sakura-300" />
    </label>
  );
}

export default function LocalModelPage() {
  const { notify } = useToast();
  // ★ 本地模型启停后，必须让全局 config 重拉 —— Chat 页的模型下拉是从
  //   config.api_providers 构建的，而本地条目是后端按需注入的（非落库）。
  //   不刷新 → 前端停在本来启动时拉的那次快照 → 下拉永远没有本地模型
  //   （之前用户报「启动了本地模型但对话里选不到」就是这个）。
  const { refreshConfig } = useAppConfig();
  const [tab, setTab] = useState<"hub" | "installed">("hub");
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [downloadDir, setDownloadDir] = useState("");
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [engines, setEngines] = useState<Engines | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  // 推理引擎整体情况（随包下发 / Ollama / 自管目录），决定要不要提示用户装引擎
  const [engineInfo, setEngineInfo] = useState<any>(null);
  const [engineUrlInput, setEngineUrlInput] = useState("");
  const [installingEngine, setInstallingEngine] = useState(false);
  // 引擎版本管理：随包下发后用户不该为升级引擎重装软件，所以要有查更新/更新/切回
  const [engineUpd, setEngineUpd] = useState<any>(null);
  const [engineVersions, setEngineVersions] = useState<any>(null);
  const [checkingUpd, setCheckingUpd] = useState(false);
  const [updatingEngine, setUpdatingEngine] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);

  // 本机能力档位（用户自选，0=不限）
  // 默认"不限"：之前默认 ≤8GB，实测 19835 条里只剩 3 条 —— 页面看着像"只有两条"，
  // 那是过滤太严不是渲染坏了。默认给全量，让用户自己按机器收窄。
  const [maxSize, setMaxSize] = useState(0);
  // 下载目录（可改，持久化在后端）
  const [dirInput, setDirInput] = useState("");
  const [freeGb, setFreeGb] = useState<number | null>(null);
  const [savingDir, setSavingDir] = useState(false);
  // 模型扫描目录：程序猜不到用户把模型放哪了，必须让用户自己配（持久化）
  const [scanDirs, setScanDirs] = useState<string[]>([]);
  const [scanDirInput, setScanDirInput] = useState("");
  const [savingScanDir, setSavingScanDir] = useState(false);
  // 设置弹层（低频配置不该常驻占高度）
  const [showSetup, setShowSetup] = useState(false);
  // 每页条数：用户可选并记住（写死一个 20 是替用户做决定）
  const [pageSize, setPageSize] = useState<number>(() => {
    const v = Number(localStorage.getItem("naixi.local.pageSize"));
    return [10, 20, 30, 50].includes(v) ? v : 20;
  });

  // 启动参数（用户可改，给了安全默认）
  const [ctx, setCtx] = useState("4096");
  const [gpuLayers, setGpuLayers] = useState("0");
  const [threads, setThreads] = useState("0");   // 0 = 自动（llama.cpp 按 CPU 核数）
  const [batch, setBatch] = useState("512");
  // 局域网访问：默认关闭（只在自己电脑用）。放开就必须带令牌。
  const [lanAccess, setLanAccess] = useState(false);
  const [apiKey, setApiKey] = useState("");

  // 采样参数（对话级即时生效，无需重启）
  // 这些状态跨对话保持，每次发送都带进请求 payload 覆盖 server 默认。
  const [temperature, setTemperature] = useState("0.7");
  const [topP, setTopP] = useState("0.9");
  const [topK, setTopK] = useState("40");
  const [repeatPenalty, setRepeatPenalty] = useState("1.1");
  const [minP, setMinP] = useState("0.05");
  const [seed, setSeed] = useState("");   // 空 = 每次随机
  const [maxTokens, setMaxTokens] = useState("1500");
  const [showGenParams, setShowGenParams] = useState(true);  // 生成参数默认展开

  // 测试对话
  const [chatInput, setChatInput] = useState("");
  const [chatLog, setChatLog] = useState<{ role: "me" | "ai"; text: string }[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  // 搜索（真实搜魔搭全站 26 万+ 模型）
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [total, setTotal] = useState(0);
  // ★ 页数一律用后端给的**过滤后真实累积量**算，不用「上游未过滤 total ÷ 页大小」。
  // 那是「共 1984 页但每页只有 3 条」这种自相矛盾的根源（体积分档在拿结果之后才过滤，
  // 上游 total 根本不代表实际能给出多少条）。后端另给：
  const [pageMeta, setPageMeta] = useState<{
    returned: number; hasMore: boolean; exhausted: boolean;
    totalPages: number | null; upstreamTotal: number; scanned: number; note: string;
  }>({ returned: 0, hasMore: true, exhausted: false, totalPages: null,
      upstreamTotal: 0, scanned: 1, note: "" });
  // 没筛完 → 只知道"还有更多"，页数显示为「≥N」；筛完了 → 精确总页数。
  // 注意 meta 可能来自越界/空响应（字段齐全但 results 空），一律走 ?? 兜底，
  // 绝不能让 totalPages 变成 NaN（那会让页码显示 "NaN / NaN"）。
  const pagesKnown = pageMeta.exhausted && total > 0;
  const totalPages = Math.max(
    1,
    Math.ceil(total / Math.max(1, pageSize)) || pageMeta.totalPages || 1
  );
  const [page, setPage] = useState(1);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const loadCatalog = useCallback(async () => {
    try {
      const d = await apiGet<any>("/api/local/catalog");
      setDownloadDir(d?.download_dir || "");
      setFreeGb(d?.free_gb ?? null);
    } catch { /* 忽略 */ }
  }, []);

  const loadScanDirs = useCallback(async () => {
    try {
      const d = await apiGet<any>("/api/local/scan-dirs");
      setScanDirs(d?.user_dirs || []);
    } catch { /* 忽略 */ }
  }, []);

  const addScanDir = async () => {
    const p = scanDirInput.trim();
    if (!p) { notify("请填写目录路径", "error"); return; }
    setSavingScanDir(true);
    try {
      const r = await apiPost<any>("/api/local/scan-dirs", { path: p });
      if (r?.ok) {
        setScanDirs(r.user_dirs || r.scan_dirs || []);
        setScanDirInput("");
        notify(r.note || "已添加，现在就能扫到这个目录", "success");
        // 立刻重扫，让用户马上看到模型出现（而不是"改了但没反应"）
        loadLocal();
      } else {
        notify(`添加失败：${r?.error || "未知"}`, "error");
      }
    } catch (e) { notify(`添加失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setSavingScanDir(false); }
  };

  const removeScanDir = async (path: string) => {
    try {
      const r = await apiPost<any>("/api/local/scan-dirs", { path, remove: true });
      if (r?.ok) {
        setScanDirs(r.user_dirs || []);
        notify("已移除（文件没动）", "info");
        loadLocal();
      }
    } catch { notify("移除失败", "error"); }
  };

  const saveDir = async () => {
    const p = dirInput.trim();
    if (!p) { notify("请填写目录", "error"); return; }
    setSavingDir(true);
    try {
      const r = await apiPost<any>("/api/local/dir", { path: p });
      if (r?.ok) {
        setDownloadDir(r.download_dir);
        setFreeGb(r.free_gb ?? null);
        setDirInput("");
        notify(r.warning || "下载目录已更改", r.warning ? "info" : "success");
      } else notify(`更改失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`更改失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setSavingDir(false); }
  };

  const loadLocal = useCallback(async () => {
    try {
      const d = await apiGet<any>("/api/local/models");
      setLocalModels(d?.models || []);
      setEngines(d?.engines || null);
    } catch { /* 忽略 */ }
  }, []);

  const loadStatus = useCallback(async () => {
    try { setStatus(await apiGet<any>("/api/local/status")); } catch { /* 忽略 */ }
  }, []);

  const loadEngine = useCallback(async () => {
    try { setEngineInfo(await apiGet<any>("/api/local/engine")); } catch { /* 忽略 */ }
  }, []);

  const installEngine = async () => {
    setInstallingEngine(true);
    try {
      const r = await apiPost<any>("/api/local/engine", { url: engineUrlInput.trim() });
      if (r?.ok) {
        notify("推理引擎已就绪", "success");
        loadEngine(); loadLocal();
      } else {
        notify(`获取失败：${r?.error || "未知"}${r?.hint ? "（" + r.hint + "）" : ""}`, "error");
      }
    } catch (e) { notify(`获取失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setInstallingEngine(false); }
  };

  // ── 引擎版本管理 ──────────────────────────────────────────
  // 引擎随安装包下发后，升级引擎不必重装整个软件：下载新版本 → 校验 → 原子切换。
  const loadEngineVersions = useCallback(async () => {
    try { setEngineVersions(await apiPost<any>("/api/local/engine", { action: "versions" })); }
    catch { /* 忽略 */ }
  }, []);

  const checkEngineUpdate = async () => {
    setCheckingUpd(true);
    try {
      const r = await apiPost<any>("/api/local/engine", { action: "check_update", force: true });
      setEngineUpd(r);
      if (r?.has_update) notify(`发现新版本 ${r.remote?.tag}`, "info");
      else if (r?.remote?.error) notify(`检查失败：${r.remote.error}`, "error");
    } catch (e) { notify(`检查失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setCheckingUpd(false); }
  };

  const doUpdateEngine = async () => {
    setUpdatingEngine(true);
    notify("正在下载新引擎，约 30~60 秒…", "info");
    try {
      const r = await apiPost<any>("/api/local/engine", { action: "update" });
      if (r?.ok) {
        notify(`${r.note}（${r.version_text || r.tag}）`, "success");
        setEngineUpd(null);
        loadEngine(); loadEngineVersions();
      } else {
        notify(`更新失败：${r?.error || "未知"}${r?.hint ? "（" + r.hint + "）" : ""}`, "error");
      }
    } catch (e) { notify(`更新失败：${String(e).slice(0, 60)}`, "error"); }
    finally { setUpdatingEngine(false); }
  };

  const activateEngine = async (tag: string) => {
    try {
      const r = await apiPost<any>("/api/local/engine", { action: "activate", tag });
      if (r?.ok) { notify(r.note || "已切换", "success"); loadEngine(); loadEngineVersions(); }
      else notify(`切换失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`切换失败：${String(e).slice(0, 50)}`, "error"); }
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.all([loadCatalog(), loadScanDirs(), loadLocal(), loadStatus(), loadEngine(), loadEngineVersions()]);
      setLoading(false);
    })();
    // 首次进来就把热门 GGUF 拉出来（用户打开就有东西看，不是空页面）
    doSearch(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 有下载在跑就轮询进度
  useEffect(() => {
    if (!progress?.running) return;
    const t = setInterval(async () => {
      try {
        const p = await apiGet<any>("/api/local/download/progress");
        setProgress(p);
        if (p.finished) {
          if (p.error) notify(`下载失败：${p.error}`, "error");
          else notify(`下载完成：${p.file}`, "success");
          loadCatalog(); loadLocal();
        }
      } catch { /* 忽略 */ }
    }, 800);
    return () => clearInterval(t);
  }, [progress?.running, loadCatalog, loadLocal, notify]);

  const doDownload = async (owner: string, repo: string, file: string, name: string) => {
    setBusy(file);
    try {
      const r = await apiPost<any>("/api/local/download", { owner, repo, file });
      if (r?.ok) {
        if (r.already) { notify("已经下载过了", "info"); loadCatalog(); }
        else { setProgress({ running: true, finished: false, file: name, done_mb: 0, total_mb: 0, percent: 0, speed_mbps: 0, error: "" }); }
      } else notify(`下载失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`下载失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setBusy(""); }
  };

  const cancelDownload = async () => {
    try { await apiPost<any>("/api/local/download/cancel", {}); } catch { /* 忽略 */ }
  };

  const startModel = async (path: string, name: string) => {
    setBusy(path);
    notify(`正在启动 ${name}，加载模型可能要十几秒…`, "info");
    try {
      // 放开局域网却没填令牌 → 别等到后端拒绝，前端先说清楚
      if (lanAccess && apiKey.trim().length < 4) {
        notify("允许局域网访问必须填访问令牌（至少 4 位）", "error");
        setBusy("");
        return;
      }
      const r = await apiPost<any>("/api/local/start", {
        model_path: path,
        ctx: Number(ctx) || 4096,
        gpu_layers: Number(gpuLayers) || 0,
        threads: Number(threads) || 0,
        batch: Number(batch) || 512,
        host: lanAccess ? "0.0.0.0" : "",
        api_key: lanAccess ? apiKey.trim() : "",
      });
      // ★ 2026-10-08：后端不允许两个模型共存（/api/local/start 会返回「请先停止」）。
      //   原来前端把全局 running 当成禁用所有启动按钮的理由，导致「已下载的模型点不了启动」。
      //   改为：检测到已有模型在跑时，先停掉它再启动目标 —— 用户点「启动 X」的意图就是「现在跑 X」，
      //   不必先手动去停。running 为 false（无任何模型在跑）时直接启动，行为不变。
      if (!r?.ok && (r?.error || "").includes("请先停止")) {
        notify("已有模型在运行，先停止再启动…", "info");
        try { await apiPost<any>("/api/local/stop", {}); } catch { /* 忽略 */ }
        const r2 = await apiPost<any>("/api/local/start", {
          model_path: path,
          ctx: Number(ctx) || 4096,
          gpu_layers: Number(gpuLayers) || 0,
          threads: Number(threads) || 0,
          batch: Number(batch) || 512,
          host: lanAccess ? "0.0.0.0" : "",
          api_key: lanAccess ? apiKey.trim() : "",
        });
        if (r2?.ok) {
          notify(r2.ready === false ? "已启动，模型仍在加载中" : `${name} 已就绪`, "success");
          refreshConfig();
        } else notify(`启动失败：${r2?.error || "未知"}`, "error");
        return;
      }
      if (r?.ok) {
        notify(r.ready === false ? "已启动，模型仍在加载中" : `${name} 已就绪`, "success");
        // 本地模型已就绪 → 让 Chat 页下拉立刻出现这个模型（重拉全局 config）
        refreshConfig();
      } else notify(`启动失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`启动失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setBusy(""); loadStatus(); }
  };

  // busyKey：行内按钮传模型 path，使「正在停这个模型」只禁用当前这一行的按钮，
  // 不会把其它行的启动按钮也锁死（之前 header 用固定 "stop"，行内读不到自己的忙状态）。
  const stopModel = async (busyKey = "stop") => {
    setBusy(busyKey);
    try {
      await apiPost<any>("/api/local/stop", {});
      notify("已停止本地模型", "success");
      setChatLog([]);
      // 本地模型已停 → 让 Chat 页下拉立刻移除这个模型
      refreshConfig();
    } catch (e) { notify(`停止失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setBusy(""); loadStatus(); }
  };

  const delModel = async (name: string) => {
    setBusy(name);
    try {
      const r = await apiPost<any>("/api/local/delete", { name });
      if (r?.ok) { notify(`已删除，释放 ${r.freed_gb}GB`, "success"); loadCatalog(); loadLocal(); }
      else notify(`删除失败：${r?.error || "未知"}`, "error");
    } catch (e) { notify(`删除失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setBusy(""); }
  };

  const doChat = async () => {
    const text = chatInput.trim();
    if (!text) return;
    const msgs = [...chatLog.map((m) => ({
      role: m.role === "me" ? "user" : "assistant", content: m.text,
    })), { role: "user", content: text }];
    setChatLog((l) => [...l, { role: "me", text }]);
    setChatInput("");
    setChatBusy(true);
    try {
      // 采样参数：空串 → undefined → 后端不传，沿用 server 默认。
      // 传了就按用户输入覆盖 server 默认（即时生效，无需重启）。
      const num = (s: string): number | undefined => {
        const t = (s || "").trim();
        if (t === "") return undefined;
        const n = Number(t);
        return Number.isNaN(n) ? undefined : n;
      };
      // 推理模型思考过程较长，max_tokens 给足（否则回答会被截断成空）
      const r = await apiPost<any>("/api/local/chat", {
        messages: msgs,
        max_tokens: num(maxTokens) ?? 1500,
        temperature: num(temperature) ?? 0.7,
        top_p: num(topP),
        top_k: num(topK),
        repeat_penalty: num(repeatPenalty),
        min_p: num(minP),
        seed: num(seed),
      }, 180000);
      if (r?.ok) {
        const answer = r.content || r.fallback || "(没有内容)";
        setChatLog((l) => [...l, { role: "ai", text: answer }]);
        if (r.hint) notify(r.hint, "info");
      } else {
        setChatLog((l) => [...l, { role: "ai", text: `调用失败：${r?.error || "未知"}` }]);
      }
    } catch (e) {
      setChatLog((l) => [...l, { role: "ai", text: `调用失败：${String(e).slice(0, 60)}` }]);
    } finally { setChatBusy(false); }
  };

  // 关键词与体积分档都显式传参，**不读 state**。
  // 为什么：React setState 是异步的，`setMaxSize(8); doSearch(1)` 里 doSearch
  // 读到的仍是上一次的 maxSize —— 表现就是「点了 ≤8GB 但数据还是旧的」。
  // 这种 bug 只在真机点按钮才暴露，SSR/单测都测不出来。
  const doSearch = async (targetPage = 1, opts?: { q?: string; maxSize?: number; pageSize?: number }) => {
    const kw = (opts?.q !== undefined ? opts.q : q).trim();
    const mb = opts?.maxSize !== undefined ? opts.maxSize : maxSize;
    const ps = opts?.pageSize !== undefined ? opts.pageSize : pageSize;
    setSearching(true);
    setPage(targetPage);
    try {
      const r = await apiGet<any>(
        `/api/local/search?limit=${ps}&page=${targetPage}&max_size_gb=${mb}` +
        (kw ? `&q=${encodeURIComponent(kw)}` : ""), 60000);
      if (r?.ok) {
        // 翻过头（上游页数上限 / 档位筛完就没了）→ 退回最后一页，
        // 绝不留空白页让用户以为坏了。
        if (r.out_of_range && targetPage > 1) {
          const back = Math.max(1, r.total_pages || targetPage - 1);
          notify(r.note || "已经到底了，回到最后一页", "info");
          if (back !== targetPage) return doSearch(back, { q: kw, maxSize: mb, pageSize: ps });
        }
        setHits(r.results || []);
        // 过滤档位下 total 是"已筛出的真实条数"，不是上游全量 —— 不能混用
        setTotal(r.filtered_total ?? r.returned ?? r.total ?? 0);
        setPageMeta({
          returned: r.returned ?? (r.results || []).length,
          hasMore: r.has_more !== false,
          exhausted: !!r.exhausted,
          totalPages: r.total_pages ?? null,
          upstreamTotal: r.upstream_total ?? r.total ?? 0,
          scanned: r.scanned_pages ?? 1,
          note: r.note || "",
        });
        setSearched(true);
        if (!r.results?.length) notify(kw ? "没搜到这个关键词，换个词试试" : "暂时取不到热门列表", "info");
      } else {
        notify(`搜索失败：${r?.error || "未知"}`, "error");
      }
    } catch (e) { notify(`搜索失败：${String(e).slice(0, 50)}`, "error"); }
    finally { setSearching(false); }
  };

  // 从搜索结果取仓库里的 GGUF → 让用户挑量化版本下载
  const [filesOf, setFilesOf] = useState<{ hit: SearchHit; files: any[] } | null>(null);

  const openHitFiles = async (hit: SearchHit) => {
    const [owner, repo] = [hit.namespace, hit.name];
    setBusy(hit.full);
    try {
      const r = await apiGet<any>(`/api/local/files?owner=${owner}&repo=${encodeURIComponent(repo)}`);
      // ★ 别只留 .gguf —— safetensors 权重同样能下（首次启动由内置转换层转 GGUF）。
      //   以前这里 filter 掉权重，UI 上表现为「点进去只能查看」，把转换层白做了。
      const all = r?.files || [];
      const usable = all.filter((f: any) =>
        f.name.toLowerCase().endsWith(".gguf") || f.name.toLowerCase().endsWith(".safetensors"));
      if (usable.length) {
        setFilesOf({ hit, files: usable });
      } else {
        notify("这个仓库里没有 GGUF 或 safetensors 权重（可能是 ONNX / PyTorch .bin 等暂不支持的格式）", "info");
      }
    } catch { notify("获取文件列表失败", "error"); }
    finally { setBusy(""); }
  };

  const running = !!status?.self_managed;
  const hasEngine = !!engines?.llamacpp;

  return (
    <div className="h-full flex flex-col gap-2.5">
      {/* ── 头部（固定）───────────────────────────────────────── */}
      <div className="flex items-center justify-between shrink-0">
        <p className="text-sm font-semibold text-sakura-600">本地模型</p>
        <div className="flex items-center gap-1.5">
          {running ? (
            <>
              <span className="flex items-center gap-1 text-[11px] text-green-600">
                <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                运行中
              </span>
              <button onClick={() => stopModel()} disabled={busy === "stop"}
                className="flex items-center gap-1 px-2 py-0.5 text-[11px] rounded
                           bg-red-500 text-white hover:bg-red-600 transition-colors disabled:opacity-40">
                {busy === "stop" ? <Loader2 size={10} className="animate-spin" /> : <Square size={10} />}
                停止
              </button>
            </>
          ) : (
            <button onClick={() => { loadCatalog(); loadEngine(); }}
              className="p-1 rounded text-sakura-400 hover:bg-sakura-50 hover:text-sakura-600"
              title="刷新">
              <RefreshCw size={12} />
            </button>
          )}
        </div>
      </div>

      {/* ── 推理引擎状态（固定）────────────────────────────────── */}
      {engineInfo?.any_engine ? (
        <div className="shrink-0 rounded-xl border border-green-100 bg-green-50 px-3 py-1.5
                        space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] text-green-700">
            <Check size={11} className="shrink-0" />
            <span className="min-w-0 truncate">
              推理引擎就绪：
              {engineInfo.llamacpp?.found && "llama.cpp"}
              {engineInfo.ollama?.found && (engineInfo.llamacpp?.found ? " + Ollama" : "Ollama")}
              {!engineInfo.llamacpp?.found && engineInfo.ollama?.found &&
                "（本地模型功能用 Ollama 跑，部分格式需先转 GGUF）"}
              {engineInfo.needs_no_install && (
                <span className="ml-1 text-green-600">
                  · 奶昔自带，无需另装任何软件
                </span>
              )}
              {!engineInfo.needs_no_install && engineInfo.source === "system" && (
                <span className="ml-1 text-green-600">· 来自本机已安装的引擎</span>
              )}
              {engineInfo.version?.build ? (
                <span className="ml-1 font-mono text-green-600">
                  · build {engineInfo.version.build}
                </span>
              ) : null}
            </span>
            <span className="ml-auto flex items-center gap-1 shrink-0">
              <button onClick={checkEngineUpdate} disabled={checkingUpd}
                className="px-1.5 py-0.5 rounded text-green-700 hover:bg-green-100
                           disabled:opacity-50 flex items-center gap-0.5"
                title="检查 llama.cpp 官方最新引擎版本">
                {checkingUpd ? <Loader2 size={9} className="animate-spin" /> : <RefreshCw size={9} />}
                检查更新
              </button>
            </span>
          </div>
          {engineUpd?.has_update && (
            <div className="flex items-center gap-1.5 text-[10px]">
              <span className="text-green-800">
                可更新到 <span className="font-mono">{engineUpd.remote?.tag}</span>
                （当前 {engineUpd.local?.build}）
              </span>
              <button onClick={doUpdateEngine} disabled={updatingEngine}
                className="px-2 py-0.5 rounded bg-green-600 text-white hover:bg-green-700
                           disabled:opacity-50 flex items-center gap-0.5 shrink-0">
                {updatingEngine ? <Loader2 size={9} className="animate-spin" /> : <Download size={9} />}
                立即更新
              </button>
            </div>
          )}
          {engineUpd && !engineUpd.has_update && !engineUpd.remote?.error && (
            <div className="text-[10px] text-green-700">已是最新版本。</div>
          )}
          {engineUpd?.remote?.error && (
            <div className="text-[10px] text-amber-700">
              检查更新失败：{engineUpd.remote.error}
            </div>
          )}
          {engineVersions?.installed?.length ? (
            <div className="flex flex-wrap items-center gap-1 text-[10px]">
              <span className="text-green-700">已装版本：</span>
              {engineVersions.installed.map((v: any) => (
                <button key={v.dir} onClick={() => activateEngine(v.tag)}
                  disabled={engineVersions.current === v.tag}
                  className={`px-1.5 py-0.5 rounded border disabled:opacity-70 ${
                    engineVersions.current === v.tag
                      ? "border-green-500 bg-green-100 text-green-800"
                      : "border-green-200 text-green-700 hover:bg-green-100"}`}>
                  {v.tag}{v.build ? ` (${v.build})` : ""}
                </button>
              ))}
              {engineVersions.current && (
                <button onClick={() => activateEngine("")}
                  className="px-1.5 py-0.5 rounded border border-green-200 text-green-700 hover:bg-green-100">
                  切回自带
                </button>
              )}
            </div>
          ) : null}
        </div>
      ) : (
        engineInfo && (
          <div className="shrink-0 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 space-y-1.5">
            <div className="flex items-center gap-1.5 text-[11px] text-amber-700">
              <AlertTriangle size={12} className="shrink-0" />
              <span>未检测到本地推理引擎，无法在本地运行模型。</span>
            </div>
            <p className="text-[10px] text-amber-600 leading-relaxed">
              奶昔自带的推理引擎会随安装包下发（无需你另装）；若当前是精简版或干净环境，可：
              ① 重装时勾选「推理引擎」组件，或 ② 安装 Ollama，或 ③ 粘贴 llama.cpp 发布包地址一键获取。
            </p>
            <div className="flex items-center gap-1.5">
              <div className="flex-1 flex items-center gap-1 px-2 py-1 rounded bg-white
                              border border-amber-200 min-w-0">
                <input value={engineUrlInput} onChange={(e) => setEngineUrlInput(e.target.value)}
                  placeholder="llama.cpp 发布包 zip 地址（可选）"
                  className="flex-1 bg-transparent text-[10px] font-mono text-amber-800
                             min-w-0 placeholder:text-amber-300 focus:outline-none" />
              </div>
              <button onClick={installEngine} disabled={installingEngine}
                className="px-2.5 py-1 text-[10px] rounded bg-amber-500 text-white
                           hover:bg-amber-600 disabled:opacity-40 shrink-0 flex items-center gap-1">
                {installingEngine ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />}
                一键获取
              </button>
            </div>
          </div>
        )
      )}

      {/* ── 工具条（固定，不随结果滚动）─────────────────────────── */}
      <div className="shrink-0 bg-white border border-sakura-100 rounded-xl px-2.5 py-2 space-y-2">
        <div className="flex items-center gap-1.5">
          <div className="flex-1 flex items-center gap-1.5 px-2 py-1.5 rounded-lg
                          bg-sakura-50 border border-sakura-100 min-w-0">
            <Search size={12} className="text-sakura-400 shrink-0" />
            <input value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                // 回车时 q 可能刚被 onChange 改过，显式取值传进去
                doSearch(1, { q: (e.target as HTMLInputElement).value });
              }}
              placeholder="搜魔搭全站模型：Qwen3 / GLM / Phi / 视觉…"
              className="flex-1 bg-transparent text-[12px] text-sakura-700 min-w-0
                         placeholder:text-sakura-300 focus:outline-none" />
            {q && (
              <button onClick={() => { setQ(""); doSearch(1, { q: "" }); }}
                className="p-0.5 rounded text-sakura-300 hover:text-sakura-500 shrink-0"
                title="清空">
                <X size={11} />
              </button>
            )}
          </div>
          <button onClick={() => doSearch(1, { q })} disabled={searching}
            className="px-3 py-1.5 text-[11px] rounded-lg bg-sakura-500 text-white
                       hover:bg-sakura-600 transition-colors disabled:opacity-40 shrink-0 flex items-center gap-1">
            {searching ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
            搜索
          </button>
          <button onClick={() => setShowSetup((v) => !v)}
            title="下载设置"
            className={`p-1.5 rounded-lg border transition-colors shrink-0 ${
              showSetup
                ? "bg-sakura-500 text-white border-sakura-500"
                : "text-sakura-400 border-sakura-100 hover:bg-sakura-50"}`}>
            <SlidersHorizontal size={12} />
          </button>
        </div>

        {/* 当前生效的筛选条件 + 体积档位（一行，不单独占高度） */}
        <div className="flex items-center gap-1.5 text-[10px] text-sakura-400">
          <span className="shrink-0">能跑多大</span>
          <div className="flex gap-0.5">
            {HW_TIERS.map((t) => (
              <button key={t.gb} onClick={() => {
                  // 档位变了，游标分区也变了，必须回第 1 页重新扫，
                  // 且把新档位**显式传进** doSearch（setState 是异步的，读 state 会拿到旧值）。
                  setMaxSize(t.gb);
                  doSearch(1, { maxSize: t.gb });
                }}
                className={`px-1.5 py-0.5 rounded border transition-colors ${
                  maxSize === t.gb
                    ? "bg-sakura-500 text-white border-sakura-500"
                    : "text-sakura-500 border-sakura-100 hover:bg-sakura-50"}`}>
                {t.label}
              </button>
            ))}
          </div>
          {freeGb !== null && (
            <span className="ml-auto shrink-0 truncate" title={downloadDir}>
              存到 <span className="font-mono">{downloadDir?.split(/[/\\]/).pop()}</span>
              （可用 {freeGb}GB）
            </span>
          )}
        </div>

        {/* 设置面板（按需展开） */}
        {showSetup && (
          <div className="pt-2 border-t border-sakura-50 space-y-2">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-sakura-400 shrink-0 w-14">下载到</span>
              <div className="flex-1 flex items-center gap-1 px-2 py-1 rounded
                              bg-sakura-50 border border-sakura-100 min-w-0">
                <input value={dirInput} onChange={(e) => setDirInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && saveDir()}
                  placeholder={downloadDir || "自定义目录"}
                  className="flex-1 bg-transparent text-[11px] font-mono text-sakura-700
                             placeholder:text-sakura-300 focus:outline-none min-w-0" />
              </div>
              <button onClick={saveDir} disabled={savingDir}
                className="px-2 py-1 text-[10px] rounded bg-sakura-500 text-white
                           hover:bg-sakura-600 disabled:opacity-40 shrink-0">
                {savingDir ? "保存中" : "更改"}
              </button>
            </div>
            <p className="text-[10px] text-sakura-400 leading-relaxed">
              模型会放在你指定的目录（不在软件安装目录里）。剩余空间不足 5GB 会有提示。
            </p>

            {/* 模型目录：程序猜不到你把模型放哪了，必须让你自己配 */}
            <div className="pt-2 border-t border-sakura-50 space-y-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-sakura-400 shrink-0">扫描目录</span>
                <div className="flex-1 flex items-center gap-1 px-2 py-1 rounded
                                bg-sakura-50 border border-sakura-100 min-w-0">
                  <input value={scanDirInput}
                    onChange={(e) => setScanDirInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addScanDir()}
                    placeholder="已有模型放别处？粘贴路径添加，如 D:\我的模型"
                    className="flex-1 bg-transparent text-[11px] font-mono text-sakura-700
                               placeholder:text-sakura-300 focus:outline-none min-w-0" />
                </div>
                <button onClick={addScanDir} disabled={savingScanDir}
                  className="px-2 py-1 text-[10px] rounded bg-sakura-500 text-white
                             hover:bg-sakura-600 disabled:opacity-40 shrink-0">
                  {savingScanDir ? "添加中" : "添加"}
                </button>
              </div>
              {scanDirs.length > 0 && (
                <div className="space-y-0.5">
                  {scanDirs.map((d) => (
                    <div key={d}
                         className="flex items-center gap-1 text-[10px] text-sakura-500
                                    group">
                      <FolderOpen size={10} className="text-sakura-300 shrink-0" />
                      <span className="font-mono truncate flex-1" title={d}>{d}</span>
                      <button onClick={() => removeScanDir(d)}
                        className="p-0.5 rounded text-sakura-300 hover:text-red-500
                                   opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                        title="移除（不删除文件）">
                        <X size={10} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-[10px] text-sakura-400 leading-relaxed">
                程序只自动扫「下载目录」和各引擎的标准位置。你自己的模型放在别处时，
                在上面加一次就会一直记住。移除只是不再扫描，不会删你的文件。
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ── 下载进度（固定）────────────────────────────────────── */}
      {progress?.running && (
        <div className="shrink-0 px-3 py-2 rounded-xl border border-blue-100 bg-blue-50 text-[11px]">
          <div className="flex items-center gap-2 mb-1">
            <Download size={12} className="text-blue-500 shrink-0" />
            <span className="text-blue-700 font-medium truncate">{progress.file}</span>
            <span className="ml-auto text-blue-600 tabular-nums shrink-0">
              {progress.percent}% · {progress.speed_mbps}MB/s
            </span>
            <button onClick={cancelDownload}
              className="p-0.5 rounded text-blue-400 hover:bg-blue-100 shrink-0" title="取消">
              <X size={11} />
            </button>
          </div>
          <div className="h-1.5 rounded-full bg-blue-100 overflow-hidden">
            <div className="h-full bg-blue-500 transition-all"
                 style={{ width: `${progress.percent}%` }} />
          </div>
        </div>
      )}

      {/* ── 主体：左列表（独占滚动） + 右对话 ──────────────────── */}
      <div className="flex-1 min-h-0 flex gap-3">
        <div className="flex-1 min-w-0 min-h-0 flex flex-col bg-white
                        border border-sakura-100 rounded-xl overflow-hidden">
          {/* 页签（固定，压缩到 ~30px） */}
          <div className="flex items-center gap-0.5 pl-2 shrink-0 border-b border-sakura-50">
            {([["hub", "模型库"], ["installed", `已下载${localModels.length ? ` (${localModels.length})` : ""}`]] as const)
              .map(([k, label]) => (
                <button key={k} onClick={() => setTab(k)}
                  className={`px-2.5 py-1.5 text-[12px] border-b-2 -mb-px transition-colors ${
                    tab === k
                      ? "border-sakura-500 text-sakura-600 font-medium"
                      : "border-transparent text-sakura-400 hover:text-sakura-600"}`}>
                  {label}
                </button>
              ))}
            {searched && tab === "hub" && total > 0 && (
              <span className="ml-auto pr-2 text-[10px] text-sakura-400">
                {q.trim() ? `“${q.trim()}” ` : "热门 "}
                {/* 体积档位下 total 是筛后的量；未筛完就写「已找到」，不给假总数 */}
                {pagesKnown
                  ? `共 ${total.toLocaleString()} 个`
                  : `已找到 ${total.toLocaleString()} 个`}
              </span>
            )}
          </div>

          {/* 列表区：唯一滚动容器 —— 结果多少都不影响上方任何东西 */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {loading ? (
              <SkeletonList />
            ) : tab === "hub" ? (
              searching ? (
                <SkeletonList />
              ) : hits.length === 0 && searched ? (
                /* 空状态：给引导，不留空白 */
                <EmptyState
                  icon={<Search size={20} />}
                  title={q.trim() ? `没找到 “${q.trim()}”` : "暂时取不到模型列表"}
                  desc={q.trim()
                    ? "换个关键词试试，比如 Qwen3、GLM、Phi、gemma"
                    : "检查网络后重试，或到「已下载」页看看本机已有的模型"}
                  action={q.trim()
                    ? { label: "搜 Qwen3", onClick: () => { setQ("Qwen3"); doSearch(1, { q: "Qwen3" }); } }
                    : { label: "重新加载", onClick: () => doSearch(1) }}
                />
              ) : (
                <>
                  {!searched && <SkeletonList />}
                  {hits.map((h) => (
                    <Row key={h.id}>
                      <Package size={12} className="text-sakura-400 shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-[12px] text-sakura-700 truncate max-w-[200px]">
                            {h.name}
                          </span>
                          {h.has_gguf === true && (
                            <span className="text-[10px] px-1 py-px rounded border
                                             border-green-100 bg-green-50 text-green-600"
                                  title={`仓库里有 ${h.gguf_count} 个 GGUF 文件`}>
                              GGUF ×{h.gguf_count}
                            </span>
                          )}
                          {h.has_gguf === false && h.has_weights && (
                            <span className="text-[10px] px-1 py-px rounded border
                                             border-amber-100 bg-amber-50 text-amber-600"
                                  title="没有现成 GGUF，但含 safetensors 权重。可直接下载，首次启动时奶昔会自动转成 GGUF（内置转换层，无需装任何外部软件）。">
                              可转换 ×{h.weight_count}
                            </span>
                          )}
                          {h.has_gguf === false && !h.has_weights && (
                            <span className="text-[10px] px-1 py-px rounded border
                                             border-sakura-200 bg-sakura-50 text-sakura-400"
                                  title="这个仓库既没有 GGUF 也没有 safetensors 权重（可能是 ONNX / PyTorch .bin 等暂不支持的格式）">
                              无可用权重
                            </span>
                          )}
                          {h.size_gb > 0 && (
                            <span className="text-[10px] text-sakura-400 tabular-nums">
                              {h.size_gb >= 1024 ? `${(h.size_gb / 1024).toFixed(1)}TB` : `${h.size_gb}GB`}
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-sakura-400 font-mono truncate" title={h.full}>
                          {h.namespace}
                          {h.tasks.length > 0 && ` · ${h.tasks.slice(0, 2).join("/")}`}
                          {h.downloads > 0 && ` · ${fmtNum(h.downloads)} 下载`}
                        </p>
                      </div>
                      <button onClick={() => openHitFiles(h)} disabled={busy === h.full}
                        className="text-[10px] px-2 py-1 rounded shrink-0 transition-colors
                                   bg-sakura-50 text-sakura-500 hover:bg-sakura-100 disabled:opacity-40">
                        {busy === h.full ? "读取中"
                          : h.has_gguf === false && !h.has_weights ? "查看" : "下载"}
                      </button>
                    </Row>
                  ))}
                  {/* 翻页：固定在列表底部，不随内容抖动。
                      每页条数由用户选（不写死），并显示真实总数。 */}
                  {total > 0 && (
                    <div className="sticky bottom-0 flex items-center gap-2 px-3 py-1.5
                                    bg-white/95 backdrop-blur border-t border-sakura-50">
                      <span className="text-[10px] text-sakura-400 tabular-nums shrink-0"
                            title={pageMeta.note || undefined}>
                        本页 {pageMeta.returned} 条 ·{" "}
                        {pagesKnown
                          ? `共 ${total.toLocaleString()} 条`
                          : `已筛出 ${total.toLocaleString()} 条（还在继续找）`}
                      </span>
                      <div className="ml-auto flex items-center gap-1.5 shrink-0">
                        <select
                          value={pageSize}
                          onChange={(e) => {
                            const n = Number(e.target.value);
                            setPageSize(n);
                            localStorage.setItem("naixi.local.pageSize", String(n));
                            // 页大小是游标分区的一部分，换了必须回第 1 页重扫，
                            // 且显式传新值（否则读到的还是旧 pageSize）。
                            doSearch(1, { pageSize: n });
                          }}
                          className="px-1 py-0.5 text-[10px] text-sakura-500 bg-sakura-50
                                     border border-sakura-100 rounded focus:outline-none
                                     focus:border-sakura-300 cursor-pointer"
                          title="每页显示条数">
                          {[10, 20, 30, 50].map((n) => (
                            <option key={n} value={n}>{n} 条/页</option>
                          ))}
                        </select>
                        <button onClick={() => doSearch(Math.max(1, page - 1), { q, maxSize })}
                          disabled={page <= 1 || searching}
                          className="px-2 py-0.5 text-[11px] rounded text-sakura-500
                                     hover:bg-sakura-100 disabled:opacity-30">
                          上一页
                        </button>
                        <span className="text-[11px] text-sakura-400 tabular-nums"
                              title={pageMeta.note || undefined}>
                          {page} / {pagesKnown ? totalPages : `${totalPages}+`}
                        </span>
                        <button onClick={() => doSearch(page + 1, { q, maxSize })}
                          disabled={searching || (!pagesKnown ? false : page >= totalPages)}
                          title={pageMeta.hasMore ? undefined : "已经到底了"}
                          className="px-2 py-0.5 text-[11px] rounded text-sakura-500
                                     hover:bg-sakura-100 disabled:opacity-30">
                          下一页
                        </button>
                      </div>
                    </div>
                  )}
                  {/* 体积档位是「拿到结果后才过滤」的（上游没这能力），如实告诉用户扫了多少，
                      否则用户会以为「全站只有这几个」是自己机器太小。 */}
                  {maxSize > 0 && searched && pageMeta.note && (
                    <p className="px-3 py-1.5 text-[10px] text-sakura-400 border-t border-sakura-50">
                      {pageMeta.note}
                      {!pageMeta.exhausted && pageMeta.upstreamTotal > 0 && (
                        <> · 上游共 {pageMeta.upstreamTotal.toLocaleString()} 个匹配，尚未全部过滤</>
                      )}
                    </p>
                  )}
                </>
              )
            ) : localModels.length === 0 ? (
              <EmptyState
                icon={<HardDrive size={20} />}
                title="本机还没有模型"
                desc="到「模型库」搜一个下载，或者把 .gguf 文件放进下载目录"
                action={{ label: "去模型库", onClick: () => setTab("hub") }}
              />
            ) : (
              localModels.map((m) => {
                const isRunning = running && status?.self_model?.includes(m.name);
                // 三类都能由本地 llama.cpp 启动：
                //  · text   —— 文本模型直接跑
                //  · vision —— 视觉模型，自动配对同目录 mmproj（后端 find_mmproj_for）
                //  · mmproj —— 投影文件本身不能当主模型，但**可以点**：后端
                //               find_vision_for_mmproj 会反查视觉主模型，
                //               以「主模型 + mmproj」成对联合启动（后端已实测逻辑）。
                // 所以这里不再有"需搭配视觉模型"这种死提示。
                const canRun = m.kind === "text" || m.kind === "vision" || m.kind === "mmproj";
                return (
                  <Row key={m.path} className={isRunning ? "bg-green-50/40" : ""}>
                    <HardDrive size={12}
                      className={`shrink-0 mt-0.5 ${isRunning ? "text-green-500" : "text-sakura-400"}`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[12px] text-sakura-700 truncate">{m.name}</span>
                        {m.kind === "vision" && (
                          <span className="text-[10px] px-1 py-px rounded border border-purple-100
                                           bg-purple-50 text-purple-600">视觉</span>
                        )}
                        {m.kind === "mmproj" && (
                          <span className="text-[10px] px-1 py-px rounded border border-sakura-100
                                           bg-sakura-50 text-sakura-400"
                                title="视觉投影文件：不能单独跑，需与视觉主模型成对。点「启动」会自动找到同目录的视觉主模型，两者一起跑。">
                            投影文件
                          </span>
                        )}
                        {isRunning && (
                          <span className="text-[10px] px-1 py-px rounded border border-green-100
                                           bg-green-50 text-green-600">运行中</span>
                        )}
                      </div>
                      <p className="text-[10px] text-sakura-400 font-mono truncate" title={m.path}>
                        {m.size_gb}GB · {m.path}
                      </p>
                      {m.kind === "mmproj" && (
                        <p className="text-[10px] text-sakura-400 mt-0.5">
                          视觉投影文件，需与视觉主模型成对运行；点「启动」会自动配对同目录的视觉主模型。
                        </p>
                      )}
                    </div>
                    {canRun && (
                      <button
                        onClick={() => isRunning ? stopModel(m.path) : startModel(m.path, m.name)}
                        disabled={!!busy}
                        title={isRunning
                          ? "停止这个模型"
                          : (m.kind === "mmproj"
                              ? "与同目录的视觉主模型成对启动（自动配对）"
                              : m.kind === "vision" ? "启动视觉模型（自动配对 mmproj）"
                              : running ? "启动此模型会先停止当前运行的模型（本机只能同时跑一个）" : "启动模型")}
                        className={`flex items-center justify-center gap-1 w-14 h-6 px-0 text-[11px]
                                   rounded shrink-0 transition-colors disabled:opacity-40 ${
                                     isRunning
                                       ? "bg-red-500 text-white hover:bg-red-600"
                                       : "bg-green-500 text-white hover:bg-green-600"}`}>
                        {busy === m.path ? <Loader2 size={10} className="animate-spin" />
                          : isRunning ? <Square size={10} /> : <Play size={10} />}
                        {isRunning ? "停止" : "启动"}
                      </button>
                    )}
                    {!canRun && (
                      // 宽度与「启动」按钮一致(w-14 h-6)，否则这一行会因为占位文字宽度不同而错位
                      <span className="flex items-center justify-center w-14 h-6 shrink-0
                                       text-[11px] text-sakura-300">暂不支持</span>
                    )}
                  </Row>
                );
              })
            )}
          </div>
        </div>

        {/* ── 右栏：对话 / 启动参数（独立布局，不被列表影响）─── */}
        <div className="lg:w-[320px] lg:flex-shrink-0 bg-white border border-sakura-100
                        rounded-xl flex flex-col min-h-0 overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-sakura-100 shrink-0">
            <MessageSquare size={12} className="text-sakura-400" />
            <span className="text-xs font-semibold text-sakura-500">试一下</span>
            {running && (
              <span className="ml-auto text-[10px] text-green-600 truncate max-w-[130px]"
                    title={status?.self_model}>
                {status?.self_model?.split(/[/\\]/).pop()}
              </span>
            )}
          </div>

          {!running ? (
            <>
              {/* 未启动：给可操作入口，不是干巴巴一句话 */}
              <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
                <div className="rounded-lg bg-sakura-50 border border-sakura-100 px-3 py-2.5">
                  <p className="text-[11px] text-sakura-600 leading-relaxed">
                    还没启动模型。在左边选一个「已下载」的模型点启动，就能在这里直接对话。
                  </p>
                </div>

                {/* 对外接入说明：模型不能只装不用 —— 除了本页面和奶昔对话，
                    第三方 OpenAI 兼容客户端也能直接连这个地址用。 */}
                <EndpointCard status={status} />
                <div className="space-y-1.5">
                  <p className="text-[10px] text-sakura-400">启动参数</p>
                  <label className="block">
                    <span className="text-[10px] text-sakura-400">上下文长度</span>
                    <input value={ctx} onChange={(e) => setCtx(e.target.value)} inputMode="numeric"
                      className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </label>
                  <label className="block">
                    <span className="text-[10px] text-sakura-400">GPU 层数（0 = 纯 CPU）</span>
                    <input value={gpuLayers} onChange={(e) => setGpuLayers(e.target.value)}
                      inputMode="numeric"
                      className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </label>
                  <label className="block">
                    <span className="text-[10px] text-sakura-400">线程数（0 = 自动）</span>
                    <input value={threads} onChange={(e) => setThreads(e.target.value)}
                      inputMode="numeric"
                      className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </label>
                  <label className="block">
                    <span className="text-[10px] text-sakura-400">批大小（影响速度）</span>
                    <input value={batch} onChange={(e) => setBatch(e.target.value)}
                      inputMode="numeric"
                      className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                 bg-sakura-50 border border-sakura-100 rounded
                                 focus:outline-none focus:border-sakura-300" />
                  </label>

                  {/* 局域网访问：默认关（只在自己电脑用）。
                      放开就必须带令牌 —— llama-server 原生鉴权（实测无/错 token 401）。 */}
                  <div className="rounded border border-sakura-100 bg-sakura-50/50 px-2 py-1.5 space-y-1.5">
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={lanAccess}
                        onChange={(e) => setLanAccess(e.target.checked)}
                        className="accent-sakura-500" />
                      <span className="text-[10px] text-sakura-600">允许局域网访问</span>
                    </label>
                    {lanAccess && (
                      <label className="block">
                        <span className="text-[10px] text-sakura-400">
                          访问令牌（必填 · 至少 4 位）
                        </span>
                        <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                          placeholder="给第三方客户端填的令牌"
                          className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                     bg-white border border-sakura-200 rounded
                                     focus:outline-none focus:border-sakura-300" />
                        <span className="block mt-0.5 text-[10px] text-amber-600 leading-relaxed">
                          局域网内任何人都能调用你的模型，必须设令牌；不用就取消勾选。
                        </span>
                      </label>
                    )}
                  </div>
                  <p className="text-[10px] text-sakura-400 leading-relaxed">
                    {hasEngine
                      ? (gpuLayers === "0"
                          ? "填 0 用纯 CPU，最稳但慢。有独显可填 99 让它尽量用显卡。"
                          : "GPU 层数越多越快，显存不够会启动失败，可逐步调大。")
                      : "没检测到 llama-server。可在上方粘贴 llama.cpp 发布包地址点「一键获取」，或重装时勾选「推理引擎」组件。"}
                  </p>
                </div>
              </div>
            </>
          ) : (
            <>
              <div ref={logRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-2">
                {chatLog.length === 0 && (
                  <p className="text-[11px] text-sakura-400 text-center py-4">
                    问它点什么，试试它的水平
                  </p>
                )}
                {chatLog.map((m, i) => (
                  <div key={i}
                    className={`rounded-lg px-2.5 py-1.5 text-[12px] leading-relaxed whitespace-pre-wrap ${
                      m.role === "me"
                        ? "bg-sakura-500 text-white ml-6"
                        : "bg-sakura-50 text-sakura-700 mr-3"}`}>
                    {m.text}
                  </div>
                ))}
                {chatBusy && (
                  <div className="flex items-center gap-1.5 text-[11px] text-sakura-400 px-2">
                    <Loader2 size={11} className="animate-spin" /> 本地模型思考中…
                  </div>
                )}
                {/* 运行中：直接给出可复制的接入地址（第三方客户端 / 别的应用都能连） */}
                {status?.endpoint?.running && <EndpointCard status={status} />}
              </div>
              {/* 运行时也能改参数（折叠） */}
              <div className="border-t border-sakura-100 p-2 shrink-0">
                {/* 生成参数：对话级即时生效，无需重启。默认展开，对应常见调质量需求 */}
                <div className="mb-2">
                  <button onClick={() => setShowGenParams((v) => !v)}
                    className="flex items-center gap-1 text-[10px] text-sakura-500 hover:text-sakura-700">
                    <SlidersHorizontal size={10} />
                    生成参数 {showGenParams ? "▲" : "▼"}
                  </button>
                  {showGenParams && (
                    <div className="grid grid-cols-2 gap-1.5 mt-1.5">
                      <GenParam label="温度" value={temperature} setter={setTemperature} hint="高→发散，低→稳定" />
                      <GenParam label="Top-P" value={topP} setter={setTopP} />
                      <GenParam label="Top-K" value={topK} setter={setTopK} />
                      <GenParam label="重复惩罚" value={repeatPenalty} setter={setRepeatPenalty} hint="低→易复读" />
                      <GenParam label="Min-P" value={minP} setter={setMinP} />
                      <GenParam label="种子" value={seed} setter={setSeed} placeholder="空=随机" />
                      <label className="col-span-2 block">
                        <span className="text-[10px] text-sakura-400">最大生成长度</span>
                        <input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)}
                          inputMode="numeric"
                          className="w-full mt-0.5 px-2 py-1 text-[12px] font-mono text-sakura-700
                                     bg-sakura-50 border border-sakura-100 rounded
                                     focus:outline-none focus:border-sakura-300" />
                      </label>
                    </div>
                  )}
                </div>
                <div className="flex items-end gap-1.5">
                  <textarea value={chatInput} onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doChat(); } }}
                    rows={2} placeholder="问点什么…（Enter 发送）"
                    className="flex-1 px-2 py-1.5 text-[12px] text-sakura-700 bg-sakura-50
                               border border-sakura-100 rounded resize-none
                               focus:outline-none focus:border-sakura-300" />
                  <button onClick={doChat} disabled={chatBusy || !chatInput.trim()}
                    className="px-2.5 py-1.5 rounded bg-sakura-500 text-white
                               hover:bg-sakura-600 disabled:opacity-40 shrink-0">
                    {chatBusy ? <Loader2 size={12} className="animate-spin" /> : "发送"}
                  </button>
                </div>
                <p className="mt-1 text-[10px] text-sakura-400">
                  本地模型思考较慢，复杂问题可能需要几十秒
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── 量化版本选择弹层 ──────────────────────────────────── */}
      {filesOf && (
        <div className="fixed inset-0 z-50 flex items-center justify-center
                        bg-black/30 p-4" onClick={() => setFilesOf(null)}>
          <div className="bg-white rounded-xl border border-sakura-100 shadow-xl
                          w-full max-w-md max-h-[70vh] flex flex-col"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-sakura-100 shrink-0">
              <Package size={13} className="text-sakura-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-semibold text-sakura-700 truncate">{filesOf.hit.name}</p>
                <p className="text-[10px] text-sakura-400 font-mono truncate">{filesOf.hit.full}</p>
              </div>
              <button onClick={() => setFilesOf(null)}
                className="p-0.5 rounded text-sakura-300 hover:bg-sakura-50 shrink-0" title="关闭">
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <p className="px-4 pt-2.5 pb-1 text-[10px] text-sakura-400">
                {filesOf.files.some((f: any) => f.name.toLowerCase().endsWith(".gguf"))
                  ? "选一个版本下载（Q4_K_M 质量/体积最平衡，Q8 质量最好但更大）"
                  : "这个仓库提供 safetensors 权重：下载后到「已下载」点启动，奶昔会自动转成 GGUF（内置转换层，无需安装任何外部软件）"}
              </p>
              {filesOf.files.map((f: any) => (
                <div key={f.name}
                  className="flex items-center gap-2 px-4 py-2 border-b border-sakura-50
                             last:border-0 hover:bg-sakura-50/50">
                  <div className="flex-1 min-w-0">
                    <p className="text-[12px] text-sakura-700 font-mono truncate">{f.name}</p>
                    <p className="text-[10px] text-sakura-400">
                      {f.size_gb}GB
                      {f.kind === "mmproj" && " · 视觉投影文件（需配视觉主模型）"}
                      {f.name.toLowerCase().endsWith(".safetensors") && " · 启动时自动转 GGUF"}
                    </p>
                  </div>
                  <button onClick={() => {
                    doDownload(filesOf.hit.namespace, filesOf.hit.name, f.name, f.name);
                    setFilesOf(null);
                  }}
                    disabled={!!busy || progress?.running}
                    className="flex items-center gap-1 px-2.5 py-1 text-[11px] rounded shrink-0
                               bg-sakura-500 text-white hover:bg-sakura-600 disabled:opacity-40">
                    {busy === f.name ? <Loader2 size={11} className="animate-spin" /> : <Download size={11} />}
                    下载
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 骨架屏：加载时占位，避免空白闪烁 ────────────────────────── */
function SkeletonList() {
  return (
    <div className="p-3 space-y-2.5">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 animate-pulse">
          <div className="w-3 h-3 rounded bg-sakura-100" />
          <div className="flex-1 space-y-1">
            <div className="h-2.5 rounded bg-sakura-100"
                 style={{ width: `${45 + (i * 7) % 35}%` }} />
            <div className="h-2 rounded bg-sakura-50" style={{ width: `${25 + (i * 11) % 30}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── 空状态：给下一步动作，不留空白 ──────────────────────────── */
function EmptyState({ icon, title, desc, action }: {
  icon: React.ReactNode; title: string; desc: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-10">
      <div className="w-11 h-11 rounded-full bg-sakura-50 flex items-center justify-center
                      text-sakura-300 mb-2.5">
        {icon}
      </div>
      <p className="text-[12px] font-medium text-sakura-600">{title}</p>
      <p className="text-[11px] text-sakura-400 mt-1 max-w-[280px] leading-relaxed">{desc}</p>
      {action && (
        <button onClick={action.onClick}
          className="mt-3 px-3 py-1.5 text-[11px] rounded-lg bg-sakura-500 text-white
                     hover:bg-sakura-600 transition-colors">
          {action.label}
        </button>
      )}
    </div>
  );
}

/* ── 对外接入卡片 ─────────────────────────────────────────
   模型不能只装不用。除了本页面「试一下」和奶昔自己的对话，
   任何 OpenAI 兼容客户端（VS Code / Cursor / Cherry Studio / 自建脚本）
   把 base_url 填成下面这个地址就能直接用本机模型。
   所以把地址和"怎么填"明明白白摆出来，而不是让用户自己去猜端口。 */
function EndpointCard({ status }: { status?: Status | null }) {
  const ep = status?.endpoint;
  if (!ep) return null;
  const [copied, setCopied] = useState("");
  const copy = async (text: string, tag: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(tag);
      setTimeout(() => setCopied(""), 1500);
    } catch { /* 剪贴板不可用时静默：地址仍可选中手抄 */ }
  };
  const line = "flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded "
    + "bg-sakura-50 text-sakura-500 hover:bg-sakura-100 shrink-0";

  return (
    <div className="rounded-lg border border-sakura-100 bg-white px-3 py-2 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <Globe size={11} className="text-sakura-400" />
        <span className="text-[11px] font-semibold text-sakura-600">对外接入</span>
        <span className="text-[10px] text-sakura-300">{ep.protocol}</span>
        {ep.running && (
          <span className="ml-auto text-[10px] px-1 py-px rounded border border-green-100
                           bg-green-50 text-green-600">运行中</span>
        )}
      </div>
      <p className="text-[10px] text-sakura-400 leading-relaxed">
        第三方 OpenAI 兼容客户端填下面这个地址即可调用本机模型，无需联网。
      </p>
      <div className="space-y-1">
        <div className="flex items-center gap-1.5">
          <code className="flex-1 min-w-0 truncate text-[10px] font-mono text-sakura-700
                           bg-sakura-50 rounded px-1.5 py-1" title={ep.base_url}>
            {ep.base_url}
          </code>
          <button onClick={() => copy(ep.base_url, "base")} className={line}>
            <Copy size={9} />{copied === "base" ? "已复制" : "复制"}
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-sakura-400 shrink-0 w-12">API Key</span>
          <code className="flex-1 min-w-0 truncate text-[10px] font-mono text-sakura-700
                           bg-sakura-50 rounded px-1.5 py-1"
                title={ep.authenticated ? "第三方客户端填这个令牌" : "当前未设令牌，服务端不鉴权"}>
            {ep.api_key}
          </code>
          <button onClick={() => copy(ep.api_key, "key")} className={line}>
            <Copy size={9} />{copied === "key" ? "已复制" : "复制"}
          </button>
        </div>
        {ep.model && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-sakura-400 shrink-0 w-12">模型</span>
            <code className="flex-1 min-w-0 truncate text-[10px] font-mono text-sakura-700
                             bg-sakura-50 rounded px-1.5 py-1" title={ep.model}>
              {ep.model}
            </code>
          </div>
        )}
      </div>
      {ep.external_access ? (
        ep.authenticated ? (
          <p className="text-[10px] text-green-600 leading-relaxed">
            已放开局域网（{ep.bind}），且启用了令牌鉴权 —— 无令牌或错令牌会被拒。
          </p>
        ) : (
          <p className="text-[10px] text-red-600 leading-relaxed">
            已放开局域网（{ep.bind}）但**未设令牌**：任何人都能直接调用，建议停止后重开并设令牌。
          </p>
        )
      ) : (
        <p className="text-[10px] text-sakura-400 leading-relaxed">
          当前仅本机可访问（{ep.bind}），不对外暴露。
        </p>
      )}
    </div>
  );
}
