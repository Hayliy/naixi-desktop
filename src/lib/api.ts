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

export async function apiGet<T>(path: string, timeoutMs = 10000): Promise<T> {
  await waitUntilVisible();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { mode: "cors", signal: ctrl.signal });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

export async function apiPost<T>(path: string, body: unknown, timeoutMs = 30000): Promise<T> {
  await waitUntilVisible();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
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
