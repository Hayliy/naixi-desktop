/* 头像与昵称系统 — DiceBear 免费 API + 自定义设置 */

const AVATAR_BASE = "https://api.dicebear.com/9.x";

const STYLES = [
  "adventurer-neutral", "avataaars", "bottts", "lorelei",
  "notionists", "fun-emoji", "identicon", "thumbs", "icons", "rings",
] as const;

/** 原始 DiceBear URL 生成 */
export function getAvatarUrl(name: string, styleIndex?: number): string {
  const idx = styleIndex ?? hashCode(name) % STYLES.length;
  const style = STYLES[idx];
  return `${AVATAR_BASE}/${style}/svg?seed=${encodeURIComponent(name)}&size=40`;
}

/** 解析最终头像 URL：优先 localStorage 自定义，其次 DiceBear */
export function resolveAvatarUrl(key: string, fallbackName: string): string {
  try {
    const custom = localStorage.getItem(key);
    if (custom) return custom;
  } catch {}
  return getAvatarUrl(fallbackName);
}

/** 解析最终显示名称：优先 localStorage 自定义 */
export function resolveDisplayName(key: string, fallbackName: string): string {
  try {
    const custom = localStorage.getItem(key);
    if (custom) return custom;
  } catch {}
  return fallbackName;
}

function hashCode(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

/* ─── 预设存储 key ─── */
export const AVATAR_KEYS = {
  USER_AVATAR: "naixi_user_avatar",
  USER_NAME: "naixi_user_name",
  BOT_AVATAR: "naixi_bot_avatar",
  BOT_NAME: "naixi_bot_name",
} as const;
