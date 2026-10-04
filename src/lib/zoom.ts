/**
 * 界面缩放（2026-10-04）
 *
 * 为什么用 CSS `zoom` 而不是改字号：
 * - 项目里有 1154 处小于 12px 的字号（text-[10px] 63 处 / text-[10px] 136 处 /
 *   text-[11px] 363 处 / text-[12px] 116 处），逐个改不现实且易漏；
 * - 用户诉求是「很多字体变得非常小，需要调整」+「导航栏要能放大缩小」，
 *   本质要的是**一个全局可调的缩放档位**，而不是重排设计系统；
 * - `zoom` 会同时缩放布局尺寸与字号，一处生效全局一致，
 *   且能持久化、能被用户随时调整。
 *
 * 用 rem 做单位换算：html { font-size: calc(16px * scale) }，
 * 这样 Tailwind 的 rem 类（text-sm 等）会跟随缩放，
 * 而 px 类（text-[11px]）由 zoom 兜底一起放大。
 *
 * 跨窗口同步：主窗口/桌宠窗口/舞台窗口在同一origin，
 * 用 localStorage + storage 事件同步，避免各窗口缩放不一致。
 */

import { useCallback, useEffect, useState } from "react";

export const ZOOM_KEY = "naixi.ui.zoom";
/** 缩放档位范围。0.8 是最小（用户嫌字小，所以下限给到 0.8 而不是更小） */
export const ZOOM_MIN = 0.8;
export const ZOOM_MAX = 2.0;
export const ZOOM_STEP = 0.1;
export const ZOOM_DEFAULT = 1.0;

function clamp(z: number) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 100) / 100));
}

function read(): number {
  try {
    const v = localStorage.getItem(ZOOM_KEY);
    if (v) {
      const n = parseFloat(v);
      if (!Number.isNaN(n)) return clamp(n);
    }
  } catch {
    /* localStorage 不可用（隐私模式等）时用默认值 */
  }
  return ZOOM_DEFAULT;
}

/** 把缩放写到 <html> 上。zoom 与 font-size 双管齐下：
 *  zoom 负责 px 类与整体布局，html font-size 负责 rem 类（Tailwind 默认单位）。 */
export function applyZoom(z: number) {
  const scale = clamp(z);
  const html = document.documentElement;
  html.style.fontSize = `${16 * scale}px`;
  html.style.zoom = `${scale}`;
  // 同时挂一个 data 属性，方便 CSS 里做微调（比如缩放时加粗细边框）
  html.setAttribute("data-zoom", String(scale));
  try {
    localStorage.setItem(ZOOM_KEY, String(scale));
  } catch {
    /* 忽略写入失败 */
  }
}

export function getZoom(): number {
  return read();
}

/**
 * 在组件里使用缩放能力。
 * @returns [当前缩放, 放大, 缩小, 重置]
 */
export function useZoom() {
  const [zoom, setZoom] = useState<number>(() =>
    typeof window === "undefined" ? ZOOM_DEFAULT : read()
  );

  // 挂载即应用（覆盖 hot-reload / 新窗口首次打开）
  useEffect(() => {
    applyZoom(zoom);
  }, [zoom]);

  // 跨窗口同步：别的窗口改了缩放，这边跟着变
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== ZOOM_KEY) return;
      setZoom(read());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const zoomIn = useCallback(() => setZoom((z) => clamp(z + ZOOM_STEP)), []);
  const zoomOut = useCallback(() => setZoom((z) => clamp(z - ZOOM_STEP)), []);
  const zoomReset = useCallback(() => setZoom(ZOOM_DEFAULT), []);

  return [zoom, zoomIn, zoomOut, zoomReset] as const;
}

/**
 * 在 App 顶层挂一次，保证任何路由/窗口打开时缩放都已生效。
 * 放在 App.tsx 里用，不放到各页面——否则漏挂的窗口会是默认字号。
 */
export function ZoomInitializer() {
  useEffect(() => {
    applyZoom(read());
  }, []);
  return null;
}