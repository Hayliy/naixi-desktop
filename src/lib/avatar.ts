/* 专家头像生成 — 基于 DiceBear 免费 API */
const AVATAR_BASE = "https://api.dicebear.com/9.x";

const STYLES = [
  "adventurer-neutral",
  "avataaars",
  "bottts",
  "lorelei",
  "notionists",
  "fun-emoji",
  "identicon",
  "thumbs",
  "icons",
  "rings",
] as const;

/** 根据名称生成确定性头像 URL */
export function getAvatarUrl(name: string, styleIndex?: number): string {
  const idx = styleIndex ?? hashCode(name) % STYLES.length;
  const style = STYLES[idx];
  return `${AVATAR_BASE}/${style}/svg?seed=${encodeURIComponent(name)}&size=40`;
}

/** 简单哈希 */
function hashCode(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}
