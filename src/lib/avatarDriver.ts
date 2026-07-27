/**
 * Live2D 角色驱动公共库 — PetWindow（单角色桌宠）与 StageWindow（多角色舞台）共用。
 * 包含：情绪/动作关键词映射、口型与参数注入、表情/动作模糊匹配、脚本加载。
 */

// 情绪(中文) → 英文关键词（用于模糊匹配模型的表情名）
export const EMOTION_KEYWORDS: Record<string, string[]> = {
  "开心": ["happy", "smile", "joy"],
  "欢迎": ["welcome", "greeting", "hello", "hi"],
  "惊讶": ["surprise", "shock", "amaze"],
  "悲伤": ["sad", "cry", "grief", "blue"],
  "害羞": ["shy", "blush", "embarrass", "red"],
  "生气": ["angry", "mad", "rage"],
  "卖萌": ["love", "moe", "cute", "heart", "like"],
  "无奈": ["hopeless", "sigh", "helpless", "tired"],
};

// 动作标签 → 英文关键词（用于模糊匹配模型的 motion 组/名）
export const ACTION_KEYWORDS: Record<string, string[]> = {
  "wave": ["wave", "greet", "hello", "hi", "bye"],
  "bye": ["bye", "wave", "greet"],
  "nod": ["nod", "yes"],
  "think": ["think", "ponder"],
  "surprise": ["surprise", "shock"],
  "shake": ["shake", "no"],
  "kime": ["kime", "pose"],
  "sing": ["sing", "song"],
  "angry": ["angry", "mad"],
  "cry": ["cry", "sad", "tear"],
  "smile": ["smile", "happy", "joy"],
  "sad": ["sad", "cry", "blue"],
};

// 口型参数名（兼容不同 Cubism 模型命名）
export const MOUTH_PARAMS = ["ParamMouthOpenY", "ParamMouthOpen"];

// 后端逻辑参数名 → Cubism 标准参数 ID 别名表（avatar_params 消息用）
export const PARAM_ALIASES: Record<string, string[]> = {
  "MouthOpen": ["ParamMouthOpenY", "ParamMouthOpen"],
  "MouthSmile": ["ParamMouthForm"],
  "FaceAngleX": ["ParamAngleX"],
  "FaceAngleY": ["ParamAngleY"],
  "FaceAngleZ": ["ParamAngleZ"],
  "EyeOpenLeft": ["ParamEyeLOpen"],
  "EyeOpenRight": ["ParamEyeROpen"],
  "EyeLeftX": ["ParamEyeBallX"],
  "EyeLeftY": ["ParamEyeBallY"],
  "BodyAngleX": ["ParamBodyAngleX"],
  "BodyAngleY": ["ParamBodyAngleY"],
  "BodyAngleZ": ["ParamBodyAngleZ"],
  "Breath": ["ParamBreath"],
};

export function setMouth(sprite: any, v: number) {
  const val = Math.max(0, Math.min(1, v));
  for (const p of MOUTH_PARAMS) {
    try { sprite.setParameterValueById(p, val, 1); } catch {}
  }
}

export function applyEmotion(sprite: any, expressions: any[], emotion?: string) {
  if (!emotion || !expressions.length) return;
  const e = emotion.trim();
  // 1) 精确名匹配（模型文件里原本写的真实表情名，如「右手掏耳朵」「脸红」）
  const exact = expressions.find(x => String(x.name).toLowerCase() === e.toLowerCase());
  if (exact) {
    try { sprite.setExpression({ expressionId: exact.name }); } catch {}
    return;
  }
  // 2) 位置索引：index:N → expressions[N]（用于默认热键跨模型稳定触发）
  if (e.toLowerCase().startsWith("index:")) {
    const idx = parseInt(e.slice(6), 10);
    const t = expressions[idx];
    if (t) { try { sprite.setExpression({ expressionId: t.name }); } catch {} }
    return;
  }
  // 3) 语义关键词模糊匹配（backend 广播的「开心」等通用情绪标签）
  const kws = EMOTION_KEYWORDS[e] || [];
  if (kws.length) {
    const hit = expressions.find(x => kws.some(k => String(x.name).toLowerCase().includes(k)));
    if (hit) { try { sprite.setExpression({ expressionId: hit.name }); } catch {} }
  }
}

export function applyAction(sprite: any, motions: any[], action?: string) {
  if (!action || !motions.length) return;
  const a = action.trim();
  // 1) 精确名匹配（模型文件里原本写的真实动作名，如「Idle」「Tap」）
  const exact = motions.find(m => m.group.toLowerCase() === a.toLowerCase() || m.name.toLowerCase() === a.toLowerCase());
  if (exact) {
    try { sprite.startMotion({ group: exact.group, no: exact.no, priority: 3 }); } catch {}
    return;
  }
  // 2) 位置索引：index:N → motions[N]
  if (a.toLowerCase().startsWith("index:")) {
    const idx = parseInt(a.slice(6), 10);
    const t = motions[idx];
    if (t) { try { sprite.startMotion({ group: t.group, no: t.no, priority: 3 }); } catch {} }
    return;
  }
  // 3) 语义关键词模糊匹配（「wave」「nod」等通用动作标签）
  const kws = ACTION_KEYWORDS[a] || [];
  if (kws.length) {
    const hit = motions.find(m => kws.some(k => (m.group + " " + m.name).toLowerCase().includes(k)));
    if (hit) { try { sprite.startMotion({ group: hit.group, no: hit.no, priority: 3 }); } catch {} return; }
  }
  // 4) 无匹配时随机播一个，保证有表现力
  const r = motions[Math.floor(Math.random() * motions.length)];
  try { sprite.startMotion({ group: r.group, no: r.no, priority: 2 }); } catch {}
}

// avatar_params 消息：参数字典批量注入（逻辑名经 PARAM_ALIASES 映射）
export function applyParams(sprite: any, params: any) {
  if (!params || typeof params !== "object") return;
  for (const [key, val] of Object.entries(params)) {
    const v = Number(val);
    if (!Number.isFinite(v)) continue;
    for (const pid of PARAM_ALIASES[key] || [key]) {
      try { sprite.setParameterValueById(pid, v, 1); } catch {}
    }
  }
}

export function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = () => resolve();
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

export function sleep(ms: number) {
  return new Promise(r => setTimeout(r, ms));
}
