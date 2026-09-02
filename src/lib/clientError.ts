import { API_BASE } from "./api";

let _inited = false;

/**
 * 全局错误上报：把前端运行时 error / 未捕获 Promise / console.error
 * 自动 POST 到后端 /api/client-error，写入应用日志。
 * 这样无头环境下 AI 也能直接读到首条 error 文本精准定位，
 * 无需用户开 DevTools 手动贴字。
 */
export function initClientErrorReporter() {
  if (_inited) return;
  _inited = true;

  const send = (payload: Record<string, unknown>) => {
    try {
      fetch(`${API_BASE}/api/client-error`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    } catch {
      /* 上报失败静默，不二次污染 */
    }
  };

  // 1) 运行时错误 / 资源加载失败（img/script/model 404 等会触发）
  window.addEventListener("error", (e: any) => {
    send({
      kind: "error",
      message: e?.message ?? String(e),
      source: e?.filename ?? "",
      lineno: e?.lineno ?? 0,
      colno: e?.colno ?? 0,
      stack: e?.error?.stack ?? "",
      t: Date.now(),
    });
  });

  // 2) 未捕获 Promise 拒绝
  window.addEventListener("unhandledrejection", (e: any) => {
    const r = e?.reason;
    send({
      kind: "unhandledrejection",
      message: r?.message ?? String(r),
      stack: r?.stack ?? "",
      t: Date.now(),
    });
  });

  // 3) 覆写 console.error：捕获第三方库（Live2DSprite 等）内部 console.error
  const orig = console.error.bind(console);
  console.error = (...args: any[]) => {
    try {
      const msg = args
        .map((a) => (typeof a === "string" ? a : JSON.stringify(a)))
        .join(" ");
      if (!msg.includes("[client-error-reporter]")) {
        send({ kind: "console.error", message: msg, t: Date.now() });
      }
    } catch {
      /* ignore */
    }
    orig(...args);
  };
}
