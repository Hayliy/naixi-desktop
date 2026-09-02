/**
 * MediaPipe Pose（身体关键点）-> VRM 上半身骨骼 的映射层（纯函数，可无头单测）。
 *
 * 输入：PoseLandmarker 的 worldLandmarks[0]（33 点，每点含 visibility）。
 * 输出：手臂的 3D 方向向量（已转到模型世界系）与躯干 pitch/roll，
 *       交给渲染端用 rotateBoneWorldDir 做世界方向对齐。
 *
 * 坐标转换推导（2026-08-30 真机实测定稿，改符号前先读完，别再左右横跳）：
 *  - MediaPipe world 实测（[AXIS] 真机数据，连续多帧完全一致）：
 *      x = **被摄者（真人）自身的右为正**，与图像 x **相反**
 *        —— 实测：真人右肩(MP 11，图像左侧) x 恒为正 +0.14/+0.03/+0.14/+0.12，
 *                  真人左肩(MP 12，图像右侧) x 恒为负 -0.19/-0.12/-0.21/-0.17。
 *      y = 向下为正（与图像一致）：实测 [AXIS] y向上=false，即 nose.y < hip.y。
 *      z = 越小越靠近相机。
 *  - VRM 模型面向 +Z：模型 left 在世界 +X、right 在 -X、y 向上
 *    （角色与观察者面对面 ⇒ 左右相反：角色 right = forward×up = (0,0,1)×(0,1,0) = -X）。
 *  - 因此：x **必须取反**（真人左手 x 为负 → 需映射到模型 left 的 +X；
 *          旧代码误以为"两侧都向右为正、符号本就一致"而沿用不取反 ⇒ 手臂左右整体反，
 *          这就是"有些关节反、改一处翻一处"的总根源）；
 *          y 取反（图像向下 → 模型向上）；
 *          z 取反 * zSign（朝相机 → 朝用户 +Z，实测躯干 pitch 修复已证）。
 *  - mirror 只决定「真人哪侧 → 模型哪侧」（照镜子：真人左手 → 模型 left），
 *    **绝不对单侧方向向量做 x 翻转** —— 只翻一侧 = 左右不对称，就是用户反复说的"动作都是反的"
 *    （2026-08-30 实锤 bug：旧代码只对 left 做 flipX，right 不动）。
 *  - 整体方向若仍不对，改 xSign / zSign 全局符号（_xAutoCalib / _zAutoCalib 物理先验自校准兜底）。
 */

/**
 * 【左右方向唯一真源】模型自身 left 所在的世界 X 符号 = +1。
 * 推导：相机在 +Z（fitCamera: camera.position.set(center.x, cy, center.z + d)），
 * three-vrm 模型面向 +Z ⇒ 角色 left = up × forward = (0,1,0)×(0,0,1) = (+1,0,0)。
 * 已由 window.__vrmArmProbe() 实测坐实（见 2026-08-30 日志）。
 *
 * 铁律：任何判断「left 外展该朝 +X 还是 -X」的代码都必须引用本常量，
 * 禁止就地写死 ±1、也禁止在注释里另立一套说法 —— 历史 bug 就是这么来的：
 * index.html 的 _xAutoCalib 注释写「left 在 -X」，与本文件相反，攒够样本后自动翻转
 * xSign，导致手臂「用着用着突然全反」（用户反复反馈「面捕动作都是反的」的真根因之一）。
 */
export const MODEL_LEFT_X_SIGN = 1;

export const POSE_DEFAULTS = {
  mirror: true,        // 与 FACE_MIRROR 保持一致（仅管 L/R 分配，不管 x 取反）
  xSign: -1,           // 手臂水平方向：MP world x 是「真人右为正」、模型 left 在 +X ⇒ 必须取反。
                       // 真机 [AXIS] 实测坐实（2026-08-30）；外展仍反则由 _xAutoCalib 再翻一次
  zSign: 1,            // 手臂/躯干前后方向（前伸变后仰就改 -1）
  chestYawGain: 0.35,  // 躯干跟随头 yaw 比例（**仅 Pose 不可见时**兜底；有 Pose 时躯干 yaw 走真实捕捉）
  chestPitchGain: 0.5, // 躯干 fallback（Pose 不可见）：跟随头 pitch
  chestRollGain: 0.5,  // 躯干 fallback（Pose 不可见）：跟随头 roll
  torsoGain: 1.0,      // 躯干 Pose 捕捉整体增益
  torsoPitchGain: 0.9, // 前倾/后仰（肩-髋向量 → 绕 X）
  torsoRollGain: 0.8,  // 侧倾（肩线倾角 → 绕 Z）
  torsoYawGain: 0.8,   // 左右转（肩线 z 分量差 → 绕 Y），2026-08-30 新增：此前躯干 yaw 完全靠头带动
};

const VIS_MIN = 0.5;

function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

/**
 * 手臂 3D 方向对齐：输出每侧 {visible, u, l}。
 *   u = 肩→肘 单位向量（模型世界系）；l = 肘→腕 单位向量。
 *   visible：肘/腕 visibility 达标才可信；不可见的侧不驱动（保持动画/下垂）。
 *   这同时解决 MediaPipe 检测不到手时输出外推默认骨架（近似 T-pose）导致的假「抬起」。
 *
 * 坐标转换：见文件顶部「坐标转换推导（2026-08-30 定稿）」，此处不再重复，避免两处注释打架。
 * 一句话：x 沿用、y 取反、z 取反*zSign；mirror 只管「真人哪侧 → 模型哪侧」，不翻单侧向量。
 */
export function poseArmDirections(lm, opts = {}) {
  const none = { visible: false, u: null, l: null };
  const out = { left: { ...none }, right: { ...none } };
  if (!lm) return out;
  const mirror = opts.mirror ?? POSE_DEFAULTS.mirror;
  const zSign = opts.zSign ?? POSE_DEFAULTS.zSign;
  const xSign = opts.xSign ?? POSE_DEFAULTS.xSign;
  // 置信度门控（抽搐头号根因的修复）：worldLandmarks（3D 米制）没有 visibility 字段，
  // 必须优先用 opts.vis（FaceTracker 从 landmarks 提取的 per-point visibility）。
  // 旧写法 `p.visibility === undefined 就放行` 在 worldLandmarks 下恒为 true → 门控完全失效，
  // 低置信/关键点丢失的帧照样驱动手臂 → 抽搐。现在改为：有 vis 数组就严格判定。
  const visArr = opts.vis;
  const visOf = (i) => {
    if (visArr && visArr[i] != null) return visArr[i];
    const p = lm[i];
    return p && p.visibility != null ? p.visibility : 1;
  };
  const okVis = (i) => visOf(i) >= VIS_MIN;
  const conv = (a, b) => {
    let x = b.x - a.x, y = b.y - a.y, z = b.z - a.z;
    const len = Math.hypot(x, y, z) || 1;
    x /= len; y /= len; z /= len;
    // x 水平符号由 xSign 统一控制（默认 -1：MP「真人右为正」→ 模型「left 为 +X」，两者相反故取反）。
    // mirror 只管 L/R 分配（out.left=mirror?R:L）：MP 的 R 在图像右侧 = 真人左侧 ⇒ 取 R 给模型 left 正确。
    // 推导（真机实测）：真人左手 x 为负 → 取反 → +X → 模型 left 外展朝 +X ✔；右手对称朝 -X ✔。
    return { x: x * xSign, y: -y, z: -z * zSign };
  };
  // 传索引而非点：门控要按索引查 visibility 数组
  const side = (shI, elI, wrI) => {
    const sh = lm[shI], el = lm[elI], wr = lm[wrI];
    if (!sh || !el || !wr) return { ...none };
    if (!okVis(shI) || !okVis(elI) || !okVis(wrI)) return { ...none };
    return { visible: true, u: conv(sh, el), l: conv(el, wr) };
  };
  const L = side(11, 13, 15);
  const R = side(12, 14, 16);
  // 【2026-08-30 实锤 bug 修复】这里曾经只对 left 做 flipX(x 取反)、right 不动 —— 左右不对称，
  // 必然导致一侧手臂方向是反的（用户反复反馈「面捕动作都是反的」，而自检误差却是 0°，
  // 因为目标反 + 模型忠实执行 = 误差 0°）。
  // 推导：MediaPipe world 的 x 向右为正；VRM 模型面向 +Z，其 left 在世界 +X、right 在 -X
  // （角色与观察者面对面，左右相反：角色 right = forward×up = -X）。
  // 真人左手出现在图像右侧 → MediaPipe x 为正 → 模型 left 应朝 +X → **符号本来就一致，无需 flip**。
  // 若整体方向仍不对，应由 xSign 全局统一翻转（_xAutoCalib 物理先验自校准兜底），
  // 绝不能只翻一侧 —— 只翻一侧必然造成左右不对称。
  const srcLeft = mirror ? R : L;
  const srcRight = mirror ? L : R;
  out.left = srcLeft;
  out.right = srcRight;
  return out;
}

/**
 * 躯干（胸/脊柱）捕捉：pitch / roll / yaw 三轴全部由肩-髋几何真实反推。
 *
 * 【2026-08-30 重写】旧实现有两处"假捕捉"（用户实锤："躯干的移动似乎只是模拟被带动的"）：
 *   1) **yaw 根本不算**：渲染端用 `头部 yaw × 0.35` 顶替，等于"头转带动身体"——
 *      真人只转肩/转身体而不转头时，躯干纹丝不动。
 *   2) **roll 用「左右肩高差 × 常数 2.0」当角度**：高差是**长度量**不是角度，
 *      还随人离相机的远近漂移（人远 ⇒ 肩宽小 ⇒ 同样倾斜算出更小角度），实测增益严重不足。
 * 现在三轴统一用**真实夹角**（asin/atan2 + 肩宽归一化），与距离无关、量纲正确。
 *
 * 索引（真机实测标定）：11 = 真人右肩（图像左侧），12 = 真人左肩（图像右侧）；23/24 = 髋。
 * 符号推导（模型面向 +Z ⇒ left 在 +X、right 在 -X）：
 *   yaw  ：真人右肩(11) 的 z 变大 = 真人转向自己的右侧 ⇒ 模型应转向模型 right(-X)；
 *          绕 Y 正转是朝 +X(left)，故需取负。
 *   roll ：真人左肩(12) 更低（y 更大，y 向下为正）= 真人向左倾 ⇒ 模型应朝 +X(left) 倾；
 *          绕 Z 正转让头顶朝 -X(right)，故需取负。
 *   pitch：真人前倾（朝相机弯腰）⇒ 肩 z < 髋 z ⇒ vFwd<0 ⇒ -atan2(vFwd,vUp)>0；
 *          绕 X 正转让头顶朝 +Z（朝相机）= 前倾，同号，不取反。
 * 注：pitch 不随 mirror 翻转（前后方向不受左右镜像影响）。
 */
export function torsoToVRM(lm, opts = {}) {
  const out = { pitch: 0, roll: 0, yaw: 0 };
  if (!lm) return out;
  const gain = opts.torsoGain ?? POSE_DEFAULTS.torsoGain;
  const shL = lm[11], shR = lm[12];      // 11 = 真人右肩，12 = 真人左肩
  const hpL = lm[23], hpR = lm[24];
  if (!shL || !shR || !hpL || !hpR) return out;

  // 肩宽（3D）作归一化基准：把长度量换算成与距离无关的角度
  const span = Math.hypot(shR.x - shL.x, shR.y - shL.y, shR.z - shL.z) || 1e-6;

  // yaw：躯干左右转 ⇒ 一侧肩靠近相机、另一侧远离 ⇒ 肩线出现 z 分量差
  let yawRaw = Math.asin(clamp((shL.z - shR.z) / span, -1, 1));
  // roll：肩线相对水平的倾角
  let rollRaw = Math.asin(clamp((shR.y - shL.y) / span, -1, 1));
  // pitch：躯干轴（髋中点 → 肩中点）相对竖直的前后倾角
  const vUp = ((hpL.y + hpR.y) / 2) - ((shL.y + shR.y) / 2);   // y 向下为正 ⇒ 恒正
  const vFwd = ((shL.z + shR.z) / 2) - ((hpL.z + hpR.z) / 2);  // 真人前倾（朝相机）时为负
  let pitchRaw = -Math.atan2(vFwd, vUp);

  // ── 中性基准（模拟 VTS "Set as Center"）──
  // 直接把 MediaPipe「绝对量」加到模型上，会让你相对摄像头的固定坐姿角变成 chest 的常驻偏移
  // （钉在限幅值、只有微小抖动）= 用户说的"只是被带动的模拟，不是真实捕捉"。
  // 必须在增益/限幅之前减掉启动/重校时采集的静止姿态原始量，只保留相对偏移驱动模型。
  if (opts.torsoCalib) {
    yawRaw   -= opts.torsoCalib.yawRaw   || 0;
    rollRaw  -= opts.torsoCalib.rollRaw  || 0;
    pitchRaw -= opts.torsoCalib.pitchRaw || 0;
  }

  const s = (opts.mirror ?? POSE_DEFAULTS.mirror) ? -1 : 1;
  out.yaw   = clamp(s * yawRaw   * (opts.torsoYawGain   ?? POSE_DEFAULTS.torsoYawGain)   * gain, -0.5, 0.5);
  out.roll  = clamp(s * rollRaw  * (opts.torsoRollGain  ?? POSE_DEFAULTS.torsoRollGain)  * gain, -0.5, 0.5);
  out.pitch = clamp(pitchRaw     * (opts.torsoPitchGain ?? POSE_DEFAULTS.torsoPitchGain) * gain, -0.45, 0.45);
  if (typeof window !== 'undefined') window.__lastTorso = { span: +span.toFixed(3), yawRaw: +yawRaw.toFixed(3), pitchRaw: +pitchRaw.toFixed(3), rollRaw: +rollRaw.toFixed(3), s, out: { pitch: +out.pitch.toFixed(3), roll: +out.roll.toFixed(3), yaw: +out.yaw.toFixed(3) } };
  out._raw = { yawRaw, pitchRaw, rollRaw };   // 供 index.html 采集中性基准（未减 calib 的原始量）
  return out;
}
