/**
 * 统一的「复制到剪贴板」入口。
 *
 * ★ 为什么要抽这一层（2026-09-22 全量页面自测挖出的真实缺陷）：
 * 前端散落了 13 处 `navigator.clipboard.writeText(...)`，写法五花八门：
 *   · 裸调用（无 catch）→ 未捕获的 Promise 拒绝，控制台报
 *     `NotAllowedError: Failed to execute 'writeText' on 'Clipboard': Document is not focused.`
 *     而且往往紧接着就 `notify("已复制")` —— **失败却告诉用户成功了**；
 *   · `.catch(() => {})` → 不报错了，但用户点了没有任何反馈，静默失败；
 *   · 只有两处自己写了 textarea 兜底（各写一遍）。
 *
 * `writeText` 会失败的真实场景（不是测试环境专属）：窗口失焦时点击、WebView 尚未获得焦点、
 * 系统剪贴板被其它程序占用、安全上下文判定异常。用户视角就是「点了复制，粘出来是旧的/什么都没有」。
 *
 * 本入口的行为：
 *   1. 优先用异步 Clipboard API（有安全上下文与焦点时最可靠）；
 *   2. 失败则回退 `textarea + document.execCommand('copy')`（老办法，失焦时通常也能成）；
 *   3. **绝不抛异常**，统一返回 boolean，由调用方决定提示什么。
 *
 * 禁止再直接调用 `navigator.clipboard.writeText`。
 */
export async function copyText(text: string): Promise<boolean> {
  const s = String(text ?? "");
  if (!s) return false;

  // 1) 异步 Clipboard API
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(s);
      return true;
    }
  } catch {
    /* 常见于 Document is not focused / 权限被拒 —— 落到下面的兜底 */
  }

  // 2) 兜底：隐藏 textarea + execCommand
  try {
    const ta = document.createElement("textarea");
    ta.value = s;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
    document.body.appendChild(ta);
    const prevFocus = document.activeElement as HTMLElement | null;
    ta.select();
    ta.setSelectionRange(0, s.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    prevFocus?.focus?.();
    return ok;
  } catch {
    return false;
  }
}
