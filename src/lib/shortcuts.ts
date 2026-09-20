/* 快捷键系统 — 单一真相源 localStorage["naixi_shortcuts"]。
   此前「快捷键列表」只有 desc 为「清空对话」的一条真正绑定，其余条目是纯展示
   （改键位 / 添加条目都不生效）——这是全功能测试里点名的占位假实现。
   现在全部动作真正绑定：
   - 全局动作（设置面板 / 清空对话 / 关闭弹窗）→ Chat.tsx 的 window keydown 分发
   - 输入框动作（发送消息 / 换行 / 上一条消息）→ ChatInput.tsx 的 textarea keydown
   键位格式：「Ctrl+Enter」「↑」「Escape」「Ctrl+Shift+K」（修饰键前缀 + 主键）。 */

export interface ShortcutItem { key: string; desc: string }

/** 动作注册表：desc 是动作唯一标识（历史数据兼容，不另设 id） */
export const SHORTCUT_ACTIONS: ShortcutItem[] = [
  { key: "Ctrl+Enter", desc: "发送消息" },
  { key: "Enter", desc: "换行" },
  { key: "Ctrl+,", desc: "打开/关闭设置面板" },
  { key: "Escape", desc: "取消/关闭当前弹窗" },
  { key: "Ctrl+L", desc: "清空对话" },
  { key: "↑", desc: "上一条消息" },
];

const LS_KEY = "naixi_shortcuts";
const CHANGED_EVENT = "naixi-shortcuts-changed";

/** 主键显示名 ↔ KeyboardEvent.key 双向映射（只列需要特判的） */
const KEY_DISPLAY: Record<string, string> = {
  ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→",
  Escape: "Escape", Enter: "Enter", Tab: "Tab", Backspace: "Backspace",
  Delete: "Delete", Insert: "Insert", Home: "Home", End: "End",
  PageUp: "PageUp", PageDown: "PageDown",
};
const KEY_FROM_DISPLAY: Record<string, string> = Object.fromEntries(
  Object.entries(KEY_DISPLAY).map(([k, v]) => [v, k])
);

/** 键事件的最小结构类型：同时兼容 DOM KeyboardEvent 与 React 合成事件 */
export interface ComboEvent { key: string; ctrlKey: boolean; shiftKey: boolean; altKey: boolean; metaKey: boolean }

/** e.key → 存储用主键名（字母/数字原样小写，方向键等转显示名） */
function eventKeyToName(e: ComboEvent): string {
  const k = e.key;
  if (KEY_DISPLAY[k]) return KEY_DISPLAY[k];
  return k.length === 1 ? k.toLowerCase() : k;
}

/** 把 KeyboardEvent 格式化为可存储的键位串；纯修饰键按下返回 null（忽略） */
export function eventToCombo(e: ComboEvent): string | null {
  if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return null;
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("Ctrl");
  if (e.shiftKey) parts.push("Shift");
  if (e.altKey) parts.push("Alt");
  parts.push(eventKeyToName(e));
  return parts.join("+");
}

/** 判断 KeyboardEvent 是否命中某个键位串（严格匹配修饰键状态） */
export function comboMatches(e: ComboEvent, combo: string): boolean {
  if (!combo) return false;
  const parts = combo.toLowerCase().split("+");
  const mainRaw = parts.pop() || "";
  const main = KEY_FROM_DISPLAY[mainRaw] ?? mainRaw;
  const want = { ctrl: parts.includes("ctrl"), shift: parts.includes("shift"), alt: parts.includes("alt") };
  if (want.ctrl !== (e.ctrlKey || e.metaKey)) return false;
  if (want.shift !== e.shiftKey) return false;
  if (want.alt !== e.altKey) return false;
  return eventKeyToName(e).toLowerCase() === main.toLowerCase();
}

/** 读取快捷键配置：孤儿条目（不在动作表内的 desc）丢弃，缺失动作补默认键位 */
export function loadShortcuts(): ShortcutItem[] {
  let saved: { key: string; desc: string }[] = [];
  try { saved = JSON.parse(localStorage.getItem(LS_KEY) || "null") || []; } catch { saved = []; }
  const savedByDesc = new Map(saved.map(s => [s.desc, s.key]));
  return SHORTCUT_ACTIONS.map(a => ({
    desc: a.desc,
    key: (savedByDesc.get(a.desc) || "").trim() || a.key,
  }));
}

export function saveShortcuts(items: ShortcutItem[]): void {
  localStorage.setItem(LS_KEY, JSON.stringify(items));
  window.dispatchEvent(new CustomEvent(CHANGED_EVENT));
}

/** 订阅快捷键变更（改键即刻生效，无需刷新）；返回取消订阅函数 */
export function onShortcutsChanged(cb: () => void): () => void {
  window.addEventListener(CHANGED_EVENT, cb);
  return () => window.removeEventListener(CHANGED_EVENT, cb);
}
