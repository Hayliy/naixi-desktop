/* 头像与昵称系统 — AI 生成二次元头像（方案2：预生成 + hash 分配）+ DiceBear 回退 */

const AVATAR_BASE = "https://api.dicebear.com/9.x";

/** 备用 DiceBear 风格列表（AI 头像未生成时用） */
const STYLES = [
  "open-peeps", "personas", "micah", "miniavs", "big-ears",
  "big-smile", "dylan", "croodles", "toon-head", "notionists-neutral",
] as const;

// ── 后端头像缓存（内存级，启动时从 API 拉取） ──
let _avatarMap: Record<string, string> | null = null;
let _avatarTotal = 0;

/** 从后端拉取所有已缓存的 AI 头像 */
export async function loadAvatarCache(): Promise<Record<string, string>> {
  if (_avatarMap) return _avatarMap;
  try {
    const res = await fetch("/api/avatar/list");
    const data = await res.json();
    if (data.ok && Array.isArray(data.avatars)) {
      _avatarMap = {};
      for (const a of data.avatars) {
        _avatarMap[a.seed] = a.url;
      }
      _avatarTotal = Object.keys(_avatarMap).length;
      return _avatarMap;
    }
  } catch {}
  _avatarMap = {};
  return _avatarMap;
}

/** 获取头像数量（用于 hash 映射） */
export function getAvatarTotal(): number {
  return _avatarTotal;
}

/** 触发后台批量预生成头像 */
export async function prefillAvatars(count = 50): Promise<boolean> {
  try {
    const res = await fetch("/api/avatar/prefill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count }),
    });
    const data = await res.json();
    return data.ok === true;
  } catch {
    return false;
  }
}

/** 刷新头像缓存（预生成完成后调用） */
export async function refreshAvatarCache(): Promise<void> {
  _avatarMap = null;
  await loadAvatarCache();
}

// ── hash 工具 ──

function hashCode(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

// ── 头像 URL 解析 ──

/** 从 seed 获取 DiceBear URL（回退用） */
export function getDiceBearUrl(name: string, styleIndex?: number): string {
  const idx = styleIndex ?? hashCode(name) % STYLES.length;
  const style = STYLES[idx];
  return `${AVATAR_BASE}/${style}/svg?seed=${encodeURIComponent(name)}&size=40`;
}

/** 解析最终头像 URL：优先 AI 生成缓存，其次 DiceBear，最后 localStorage 自定义 */
export function resolveAvatarUrl(storageKey: string, fallbackName: string): string {
  // 1. localStorage 自定义
  try {
    const custom = localStorage.getItem(storageKey);
    if (custom) return custom;
  } catch {}

  // 2. AI 生成缓存（hash 映射到预生成的 avatar-N）
  const ai = getAiAvatarUrl(fallbackName);
  if (ai) return ai;

  // 3. DiceBear 回退
  return getDiceBearUrl(fallbackName);
}

/**
 * 旧版兼容名：根据名字获取头像 URL
 * 优先 AI 缓存，其次 DiceBear
 */
export function getAvatarUrl(name: string, styleIndex?: number): string {
  const ai = getAiAvatarUrl(name);
  if (ai) return ai;
  return getDiceBearUrl(name, styleIndex);
}

/** 解析最终显示名称：优先 localStorage 自定义 */
export function resolveDisplayName(key: string, fallbackName: string): string {
  try {
    const custom = localStorage.getItem(key);
    if (custom) return custom;
  } catch {}
  return fallbackName;
}

/** 直接根据名称获取 AI 头像 URL（不进 localStorage，用于批量场景） */
export function getAiAvatarUrl(name: string): string | null {
  if (_avatarTotal > 0) {
    const seed = `avatar-${hashCode(name) % _avatarTotal}`;
    return _avatarMap?.[seed] ?? null;
  }
  return null;
}

/* ─── 预设存储 key ─── */
export const AVATAR_KEYS = {
  USER_AVATAR: "naixi_user_avatar",
  USER_NAME: "naixi_user_name",
  BOT_AVATAR: "naixi_bot_avatar",
  BOT_NAME: "naixi_bot_name",
} as const;
