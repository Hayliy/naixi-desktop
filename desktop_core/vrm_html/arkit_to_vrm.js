/**
 * ARKit blendshape -> VRM 表情 / 头部姿态 的映射层（纯函数，无任何外部依赖）。
 *
 * 单独成文件的原因：
 *   1. 可独立无头单测（不加载 MediaPipe、不需要摄像头与浏览器环境）；
 *   2. Live2D 链路只需映射、不一定要引 MediaPipe，可单独 import 本文件复用。
 */

/** 映射层默认值（face_tracker.js 以此为默认，单一真相源） */
export const MAPPING_DEFAULTS = {
  mirror: true,          // 前置摄像头镜像：交换左右眼/嘴角
  expressionGain: 1.0,   // 表情总增益
};

/**
 * ARKit 52 blendshape -> VRM 1.0 预设表情的映射规则表。
 * vrm: three-vrm expressionManager 的表情名
 * src: 参与计算的 ARKit 源（mirror 开启时自动交换 Left/Right）
 * mode: 'avg' 平均 | 'max' 取最大 | 'sum' 求和
 * mul:  额外乘子（软性加权，避免全 0 时结果归零）
 * gain: 该条增益
 */
export const ARKIT_TO_VRM = [
  { vrm: 'blinkLeft',  src: ['eyeBlinkLeft'],                                        mode: 'max', gain: 1.0  },
  { vrm: 'blinkRight', src: ['eyeBlinkRight'],                                       mode: 'max', gain: 1.0  },
  { vrm: 'blink',      src: ['eyeBlinkLeft', 'eyeBlinkRight'],                       mode: 'max', gain: 1.0  },
  // 口型（viseme）：按元音拆，真人说话时由 jawOpen / 嘴角 / 噘嘴共同决定
  { vrm: 'aa',         src: ['jawOpen'],                                             mode: 'max', gain: 1.35 },
  { vrm: 'ih',         src: ['mouthStretchLeft', 'mouthStretchRight'],               mode: 'avg', gain: 0.90 },
  { vrm: 'ou',         src: ['mouthPucker', 'mouthFunnel'],                          mode: 'max', gain: 1.00 },
  { vrm: 'ee',         src: ['mouthSmileLeft', 'mouthSmileRight'],                   mode: 'avg', gain: 0.80 },
  { vrm: 'oh',         src: ['jawOpen'],                                             mode: 'max', gain: 0.70, mul: ['mouthFunnel'] },
  // 情绪
  { vrm: 'happy',      src: ['mouthSmileLeft', 'mouthSmileRight'],                   mode: 'avg', gain: 0.85 },
  { vrm: 'angry',      src: ['browDownLeft', 'browDownRight'],                       mode: 'avg', gain: 0.90 },
  { vrm: 'sad',        src: ['mouthFrownLeft', 'mouthFrownRight'],                   mode: 'avg', gain: 0.90 },
  { vrm: 'surprised',  src: ['browInnerUp', 'browOuterUpLeft', 'browOuterUpRight',
                             'eyeWideLeft', 'eyeWideRight'],                         mode: 'max', gain: 0.75 },
  // 视线（眼动）：镜像时左右需反查，故关掉该条的自动交换
  { vrm: 'lookUp',     src: ['eyeLookUpLeft', 'eyeLookUpRight'],                     mode: 'avg', gain: 0.60, mirrorSwap: false },
  { vrm: 'lookDown',   src: ['eyeLookDownLeft', 'eyeLookDownRight'],                 mode: 'avg', gain: 0.60, mirrorSwap: false },
  { vrm: 'lookLeft',   src: ['eyeLookInLeft', 'eyeLookOutRight'],                    mode: 'avg', gain: 0.60 },
  { vrm: 'lookRight',  src: ['eyeLookInRight', 'eyeLookOutLeft'],                    mode: 'avg', gain: 0.60 },
];

export const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
export const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/** 交换 ARKit 名字里的 Left/Right（用空格占位避免二次替换） */
export function swapLR(name) {
  if (!/Left$|Right$/.test(name)) return name;
  return name.replace(/Left$/, ' L').replace(/Right$/, 'Left').replace(/ L$/, 'Right');
}

/** 4x4 列主序矩阵 -> YXZ 欧拉角（弧度），与 three.js Euler.setFromRotationMatrix('YXZ') 一致 */
export function matrixToEulerYXZ(a) {
  if (!a || a.length < 16) return null;
  const m00 = a[0], m02 = a[8];
  const m10 = a[1], m11 = a[5], m12 = a[9];
  const m20 = a[2], m22 = a[10];
  const x = Math.asin(clamp(-m12, -1, 1));
  let y, z;
  if (Math.abs(m12) < 0.9999999) {
    y = Math.atan2(m02, m22);
    z = Math.atan2(m10, m11);
  } else {
    y = Math.atan2(-m20, m00);
    z = 0;
  }
  return { x, y, z };   // x=pitch(俯仰) y=yaw(左右转) z=roll(歪头)
}

/**
 * ARKit blendshapes -> VRM 表情权重
 * @param {Object} bs  { [arkitName]: 0..1 }
 * @param {Object} opts { mirror, expressionGain }
 * @returns {Object} { [vrmExpressionName]: 0..1 }
 */
export function arkitToVRM(bs, opts = {}) {
  const mirror = opts.mirror ?? MAPPING_DEFAULTS.mirror;
  const gainAll = opts.expressionGain ?? MAPPING_DEFAULTS.expressionGain;
  const out = {};
  for (const rule of ARKIT_TO_VRM) {
    if (!rule.src || rule.src.length === 0) continue;
    const doSwap = mirror && rule.mirrorSwap !== false;
    const names = doSwap ? rule.src.map(swapLR) : rule.src;
    let v;
    if (rule.mode === 'max') {
      v = Math.max(...names.map((n) => bs[n] || 0));
    } else if (rule.mode === 'sum') {
      v = names.reduce((acc, n) => acc + (bs[n] || 0), 0);
    } else {
      v = names.reduce((acc, n) => acc + (bs[n] || 0), 0) / names.length;
    }
    if (rule.mul && rule.mul.length) {
      const m = Math.max(...rule.mul.map((n) => bs[n] || 0));
      v = v * (0.35 + 0.65 * m);
    }
    out[rule.vrm] = clamp01(v * (rule.gain ?? 1) * gainAll);
  }
  return out;
}
