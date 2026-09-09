import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const API_BASE = typeof import.meta !== 'undefined' && (import.meta as any).env?.DEV ? "" : "http://127.0.0.1:9845";

// ── 应用可见性守卫 ─────────────────────────────────────────────
// 常驻托盘：窗口被 hide 到托盘时，WebView2 的网络会被 Windows 挂起，
// 此时仍在跑的轮询请求会卡在 net::ERR_NETWORK_IO_SUSPENDED，10s 后
// AbortController 超时 abort → 抛 AbortError，OpsPage catch 打「运维加载失败」。
// 治本：窗口隐藏期间让 apiGet/apiPost 挂起、不发起真实请求；
// 窗口恢复可见后再发，既消除红日志又省资源，且数据不丢、不闪空。
let appVisible = true;
let visInit = false;
const visListeners: Array<() => void> = [];

function markVisible(v: boolean) {
  if (appVisible === v) return;
  appVisible = v;
  if (v) visListeners.splice(0).forEach((l) => l());
}

async function initVisibility() {
  if (visInit) return;
  visInit = true;
  try {
    if (typeof document !== "undefined") {
      const onVis = () => markVisible(document.visibilityState !== "hidden");
      document.addEventListener("visibilitychange", onVis);
      onVis();
    }
    const w = window as any;
    // isTauri 守卫：仅在 Tauri 运行时接入窗口可见性（动态 import，不在渲染期同步调 getCurrentWindow）
    if (w.__TAURI__ || w.__TAURI_INTERNALS__) {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const win = getCurrentWindow();
      const sync = async () => { try { markVisible(await win.isVisible()); } catch { /* noop */ } };
      await sync();
      win.onFocusChanged(() => { sync(); }).catch(() => {});
      // 兜底定时同步（个别 Tauri 版本 hide 不触发 onFocusChanged）
      if (typeof window !== "undefined") window.setInterval(sync, 2000);
    }
  } catch {
    markVisible(true);
  }
}
initVisibility();

// 不可见时挂起，直到可见（带 30s 兜底，避免极端情况下永久挂起）
function waitUntilVisible(timeoutMs = 30000): Promise<void> {
  if (appVisible) return Promise.resolve();
  return new Promise((resolve) => {
    visListeners.push(resolve);
    setTimeout(resolve, timeoutMs);
  });
}

// 自愈重试：网络错误 / AbortError(超时) / 5xx / 429 指数退避重试；4xx 业务错误不重试。
// 防「配置页在后端未就绪/偶发抖动时挂载→一次性 fetch 失败→字段永久空白不自愈」（15:32 根因，曾因白屏回滚丢失，本次恢复）。
async function fetchWithRetry<T>(path: string, init: RequestInit, timeoutMs: number): Promise<T> {
  const delays = [500, 1500, 4000];
  let lastErr: unknown;
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      let res: Response;
      try {
        res = await fetch(`${API_BASE}${path}`, { ...init, mode: "cors", signal: ctrl.signal });
      } finally {
        clearTimeout(timer);
      }
      if (res.ok) return (await res.json()) as T;
      // 4xx 业务错误：不重试，直接抛出（避免掩盖真实业务错误）
      if (res.status >= 400 && res.status < 500) {
        throw new Error(`API ${res.status}: ${res.statusText}`);
      }
      // 5xx / 429：落到 catch 走重试
      lastErr = new Error(`API ${res.status}: ${res.statusText}`);
    } catch (e) {
      // 4xx 已在上面显式抛出，这里捕获的是网络错误 / 超时(AbortError) / 5xx，全部可重试
      if (e instanceof Error && /^API 4\d\d:/.test(e.message)) throw e;
      lastErr = e;
    }
    if (attempt < delays.length) {
      await new Promise((r) => setTimeout(r, delays[attempt]));
    }
  }
  throw lastErr;
}

export async function apiGet<T>(path: string, timeoutMs = 10000): Promise<T> {
  await waitUntilVisible();
  return fetchWithRetry<T>(path, {}, timeoutMs);
}

export async function apiPost<T>(path: string, body: unknown, timeoutMs = 30000): Promise<T> {
  await waitUntilVisible();
  return fetchWithRetry<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    timeoutMs,
  );
}

export interface StatusData {
  napcat_connected: boolean;
  version: string;
  trust_total: number;
  trust_rate: number;
  knowledge_items: number;
  knowledge_cats: number;
  tools: number;
  skills: number;
  trust_level: number;
  experiences: number;
  agents: number;
  cases: number;
}
