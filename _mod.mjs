
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { createVRMAnimationClip, VRMAnimationLoaderPlugin, VRMLookAtQuaternionProxy } from '@pixiv/three-vrm-animation';

const MODEL_URL = "__MODEL_URL__";
const MOTION_URL = "__MOTION_URL__";
const DANCE = "__DANCE__" === "1";   // 服务端按 --dance 替换成 "1"
const LOOP_MOTION = "__LOOP_MOTION__";   // 服务端按 --loop <name> 替换成动作名（不含.vrma）或 ""
console.log('[VRM] three.js + three-vrm-animation module imported');

const canvas = document.getElementById('c');
const hint = document.getElementById('hint');

const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(0x000000, 0);
console.log('[VRM] WebGLRenderer created, context:', renderer.getContext() ? 'ok' : 'null');

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, window.innerWidth / window.innerHeight, 0.05, 100);
camera.position.set(0, 1.0, 5.0);
scene.add(new THREE.AmbientLight(0xffffff, 1.4));
const dir = new THREE.DirectionalLight(0xffffff, 1.6); dir.position.set(1, 2, 1.5); scene.add(dir);
const dir2 = new THREE.DirectionalLight(0x88aaff, 0.5); dir2.position.set(-1, 1, -1); scene.add(dir2);

let vrm = null;
let mixer = null, idleAction = null, lookAtProxy = null;
let mouthValue = 0, targetMouth = 0;
let expressionName = null;
let activeMotion = null;
let currentAction = null;     // 当前播放的真实 VRMA action
let savedHipsPos = null;      // 动作前 hips 位移快照（VRMA 含根位移时还原）
let danceMode = false;
let danceIdx = -1;
const motionClips = {};       // name -> THREE.AnimationClip（已编译）
const clock = new THREE.Clock();

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
loader.register((parser) => new VRMAnimationLoaderPlugin(parser));   // 支持加载 .vrma 动画

console.log('[VRM] start loading', MODEL_URL);
loader.load(MODEL_URL,
  (gltf) => {
    try {
      vrm = gltf.userData.vrm;
      console.log('[VRM] loaded. humanoid:', !!vrm.humanoid, 'springBone:', !!vrm.springBoneManager, 'expression:', !!vrm.expressionManager);
      if (VRMUtils.removeUnnecessaryVertices) VRMUtils.removeUnnecessaryVertices(gltf.scene);
      if (VRMUtils.combineSkeletons) { try { VRMUtils.combineSkeletons(gltf.scene); } catch (e) {} }
      if (VRMUtils.combineMorphs) { try { VRMUtils.combineMorphs(vrm); } catch (e) {} }
      vrm.scene.traverse((obj) => { obj.frustumCulled = false; });   // 官方示例关键：关闭视锥剔除，避免误裁
      vrm.scene.scale.setScalar(0.85);
      scene.add(vrm.scene);

      // 加载 VRMA（来自 three-vrm 官方示例）。建好 mixer 但默认不自动播放——
      // 模型默认站姿由官方 humanoid.resetNormalizedPose() 设为双臂自然下垂（非手写角度、非预设 idle）。
      loader.load(MOTION_URL,
        (g) => {
          try {
            const vrmAnim = g.userData.vrmAnimations && g.userData.vrmAnimations[0];
            if (vrmAnim) {
              // 先建并挂载 lookAt 代理，再编译 clip（消除自动创建警告，确保 lookAt 轨道生效）
              lookAtProxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
              lookAtProxy.name = 'lookAtQuaternionProxy';
              vrm.scene.add(lookAtProxy);
              const clip = createVRMAnimationClip(vrmAnim, vrm);
              mixer = new THREE.AnimationMixer(vrm.scene);
              idleAction = mixer.clipAction(clip);   // 仅建好，默认不播放（静止站姿）
              console.log('[VRM] VRMA 已加载（默认静止，双臂自然下垂）');
              if (LOOP_MOTION) startLoopMotion(LOOP_MOTION);
              else if (DANCE) startDance();
            } else {
              console.warn('[VRM] VRMA 无动画轨道');
            }
          } catch (e) {
            console.error('[VRM] 动画编译失败:', e && e.message);
          }
        },
        undefined,
        (e) => { console.error('[VRM] 动画加载失败:', e && (e.message || e)); }
      );

      // 默认站姿：双臂自然下垂。先 reset 回模型 rest，再按"手相对髋的几何距离"自动判定平举/张开并收拢到下垂
      autoDropArms();
      console.log('[VRM] 默认站姿：双臂自然下垂（测量自修正）');

      fitCamera();
      setTimeout(fitCamera, 300);    // 捕捉 springBone/初始稳定后的最终包围盒
      setTimeout(fitCamera, 800);
      hint.style.display = 'none';
      window.dispatchEvent(new Event('vrm-ready'));
      console.log('[VRM] ready. bbox=', bboxSizeStr());
      // 诊断截图：?diag=N 时把每帧画面 POST 回后端存盘，供离线肉眼核对（不依赖用户当显示器）
      const DIAG_N = new URLSearchParams(location.search).get('diag');
      if (DIAG_N) setTimeout(startDiagCapture, 1800);
    } catch (e) {
      console.error('[VRM] post-load setup error:', e && e.message ? e.message : e);
    }
  },
  (xhr) => { if (xhr.total) console.log('[VRM] progress', (xhr.loaded / xhr.total * 100).toFixed(1) + '%'); },
  (err) => {
    console.error('[VRM] load error:', err && err.message ? err.message : err);
    hint.textContent = 'VRM 加载失败：' + (err && err.message ? err.message : err);
  }
);

function bboxSizeStr() {
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const s = box.getSize(new THREE.Vector3());
  return s.x.toFixed(2) + ' ' + s.y.toFixed(2) + ' ' + s.z.toFixed(2);
}

// 迭代式取景：保证包围盒 8 个角投影后，脚(最小 y)与头(最大 y)都落在 NDC [-MARGIN, MARGIN] 内。
// 关键：测全部 8 角而非仅 box.min——脚尖在 z_max(更靠相机)，透视投影后 NDC y 比脚后跟更低，
// 只测 box.min 会漏掉脚尖被裁而误判"安全"。
function projectCornerExtents(box, cam) {
  let feetY = Infinity, topY = -Infinity;
  for (const sx of [box.min.x, box.max.x])
    for (const sy of [box.min.y, box.max.y])
      for (const sz of [box.min.z, box.max.z]) {
        const p = new THREE.Vector3(sx, sy, sz).project(cam);
        if (p.y < feetY) feetY = p.y;
        if (p.y > topY) topY = p.y;
      }
  return [feetY, topY];
}
function fitCamera() {
  if (!vrm) return;
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const fovV = THREE.MathUtils.degToRad(camera.fov);
  const MARGIN = 0.78;   // 脚/头 NDC 安全边界（留足余量对付脚尖透视更低 + 窗口位置/DPI 误差）
  let d = (size.y / 2 * 1.25) / Math.tan(fovV / 2);
  for (let i = 0; i < 16; i++) {
    camera.position.set(center.x, center.y, center.z + d);
    camera.lookAt(center.x, center.y, center.z);
    camera.updateMatrixWorld(true);
    camera.updateProjectionMatrix();
    const [feetY, topY] = projectCornerExtents(box, camera);
    if (feetY > -MARGIN && topY < MARGIN) break;
    d *= 1.05;
  }
  const [feetY, topY] = projectCornerExtents(box, camera);
  console.log(`[FIT] d=${d.toFixed(2)} feetNDC.y=${feetY.toFixed(3)} topNDC.y=${topY.toFixed(3)} (应在[-${MARGIN},${MARGIN}])`);
}

// ── 骨骼 helper ──
function bone(name) {
  try { return vrm.humanoid.getNormalizedBoneNode(name); } catch (e) { return null; }
}
// ── 自动判定并修正"双臂自然下垂" ──
// 数据驱动，不靠肉眼、不写死角度：
// 1) 先 reset 回模型 rest pose（多数 VRM 是 T-pose 平举，或 A-pose 微张）；
// 2) 测量左手/右手世界坐标相对 hips 的水平距离 dx 与垂直距离 dy；
// 3) 若手的水平距离明显大于垂直（即平举/张开），则把上臂旋到"肩->髋下略外"、前臂旋到"继续向下"，
//    让手落到 hips 正下方附近（自然下垂）；若手本就在髋下且贴身，则不动。
function worldPosOf(node) {
  const v = new THREE.Vector3();
  if (node) node.getWorldPosition(v);
  return v;
}
// 把一个骨骼的世界方向从 curDir 旋到 tgtDir（换算成该骨骼的 local 四元数，保持父级约束）
function rotateBoneWorldDir(boneNode, curDir, tgtDir) {
  const qDelta = new THREE.Quaternion().setFromUnitVectors(curDir, tgtDir);
  const parentWorld = new THREE.Quaternion();
  boneNode.parent.getWorldQuaternion(parentWorld);
  const invParent = parentWorld.clone().invert();
  const newLocal = invParent.multiply(qDelta).multiply(parentWorld).multiply(boneNode.quaternion.clone());
  boneNode.quaternion.copy(newLocal);
}
// 双臂下垂角度（明确参数，非 90° 垂直、非瞎猜）：
//   ARM_OUTWARD_DEG = 手臂与竖直方向的夹角（→ 与水平夹角 = 90-10 = 80°，即用户要求的"80° 量级"）。
//   参考社区 VRM rest-pose 量级（gunbark.dev: UPPER_ARM_Z≈1.15rad≈66°，相对 T-pose 水平）；
//   社区参考 gunbark.dev 的 UPPER_ARM_Z≈1.15rad≈66° 是"相对 T-pose 水平"的下垂角，
//   即与水平夹角 66° → 与竖直夹角 = 90-66 = 24°。此处取该社区值（贴身改小/外张改大只动此常量）。
const ARM_OUTWARD_DEG = 24;
const ARM_OUTWARD_RAD = THREE.MathUtils.degToRad(ARM_OUTWARD_DEG);
const ARM_FWD_RAD = 0.12;   // 手臂略朝前(相机+Z)，避免夹在身体正侧、更自然
function dropOneArm(upper, lower, hand, hipsW, side) {
  const aPos = worldPosOf(upper);
  const hPos = worldPosOf(hand);
  const curDir = hPos.clone().sub(aPos).normalize();
  const armLen = hPos.distanceTo(aPos);
  // 已下垂判定：手明显在髋下且贴近身体 → 不强行改（保留模型自带 A-pose 等自然姿态）
  if (hPos.y < hipsW.y - armLen * 0.5 && Math.abs(hPos.x - hipsW.x) < armLen * 0.45) return false;
  // 上臂目标方向：竖直向下，绕身体前后轴(Z)外张 ARM_OUTWARD 到体侧，再绕X略朝前
  const down = new THREE.Vector3(0, -1, 0);
  const qZ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), side * ARM_OUTWARD_RAD);
  const qX = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -ARM_FWD_RAD);
  const tgtDirUpper = down.clone().applyQuaternion(qZ).applyQuaternion(qX).normalize();
  rotateBoneWorldDir(upper, curDir, tgtDirUpper);
  upper.updateMatrixWorld(true);
  // 前臂：继续向下，略向中线 + 略朝前，消除 T-pose 水平外伸
  if (lower) {
    const ePos = worldPosOf(lower);
    const hPos2 = worldPosOf(hand);
    const curDirLower = hPos2.clone().sub(ePos).normalize();
    const tgtDirLower = tgtDirUpper.clone();  // 前臂续接上臂方向，整体手臂外张=ARM_OUTWARD_DEG（与水平66°），避免竖直前臂抵消外张
    rotateBoneWorldDir(lower, curDirLower, tgtDirLower);
    lower.updateMatrixWorld(true);
  }
  return true;
}
let _droppedPose = null;   // 首次 autoDropArms 算出的手臂下垂快照（local 四元数），后续直接复用
function autoDropArms() {
  if (!vrm || !vrm.humanoid) return;
  vrm.humanoid.resetNormalizedPose();
  vrm.scene.updateMatrixWorld(true);
  const hips = bone('hips');
  const lu = bone('leftUpperArm'), ru = bone('rightUpperArm');
  const ll = bone('leftLowerArm'), rl = bone('rightLowerArm');
  const hl = bone('leftHand'), hr = bone('rightHand');
  if (!hips || !lu || !ru || !hl || !hr) return;
  const hipsW = worldPosOf(hips);
  const haL0 = worldPosOf(hl), haR0 = worldPosOf(hr);
  const firstTime = !_droppedPose;
  if (firstTime) console.log(`[POSE] 修正前 handL(dx=${(haL0.x-hipsW.x).toFixed(2)},dy=${(haL0.y-hipsW.y).toFixed(2)}) handR(dx=${(haR0.x-hipsW.x).toFixed(2)},dy=${(haR0.y-hipsW.y).toFixed(2)})`);
  dropOneArm(lu, ll, hl, hipsW, +1);
  dropOneArm(ru, rl, hr, hipsW, -1);
  vrm.scene.updateMatrixWorld(true);
  if (vrm.humanoid.update) vrm.humanoid.update();
  // 缓存快照，避免后续每轮 demo 复位时重复计算 + 刷屏
  _droppedPose = {
    lu: lu.quaternion.clone(),
    ll: ll ? ll.quaternion.clone() : null,
    ru: ru.quaternion.clone(),
    rl: rl ? rl.quaternion.clone() : null,
  };
  if (firstTime) {
    const haL1 = worldPosOf(hl), haR1 = worldPosOf(hr);
    console.log(`[POSE] 修正后 handL(dx=${(haL1.x-hipsW.x).toFixed(2)},dy=${(haL1.y-hipsW.y).toFixed(2)}) handR(dx=${(haR1.x-hipsW.x).toFixed(2)},dy=${(haR1.y-hipsW.y).toFixed(2)})`);
  }
}
// 自然站立复位：有快照则直接复位全身 + 套用下垂手臂（不重算、不刷屏）；首次则测量自修正
function applyRestPose() {
  if (_droppedPose) {
    if (!vrm || !vrm.humanoid) return;
    vrm.humanoid.resetNormalizedPose();
    const lu = bone('leftUpperArm'), ll = bone('leftLowerArm'), ru = bone('rightUpperArm'), rl = bone('rightLowerArm');
    if (lu) lu.quaternion.copy(_droppedPose.lu);
    if (ll && _droppedPose.ll) ll.quaternion.copy(_droppedPose.ll);
    if (ru) ru.quaternion.copy(_droppedPose.ru);
    if (rl && _droppedPose.rl) rl.quaternion.copy(_droppedPose.rl);
    if (vrm.humanoid.update) vrm.humanoid.update();
  } else {
    autoDropArms();
  }
}

// ── 动作库（程序化拓展，播放时暂停 VRMA idle）──
// ── 真实 VRMA 动作库（motions/ 目录已下载的社区动作模组，非手写角度）──
const MOTION_FILES = [
  'Spin', 'Jump', 'Shoot', 'Squat', 'PeaceSign', 'Clapping', 'ShowFullBody',
  'Greeting', 'Angry', 'Surprised', 'ModelPose', 'Sleepy', 'Thinking',
  'LookAround', 'Relax', 'Goodbye', 'Sad', 'Blush', 'sample-mocopi'
];

function loadMotionClip(name, cb, stripRoot) {
  if (motionClips[name]) { cb && cb(true); return; }
  const url = `/motions/${name}.vrma`;
  loader.load(url, (g) => {
    try {
      const va = g.userData.vrmAnimations && g.userData.vrmAnimations[0];
      if (!va) { console.warn(`[VRM] 动作无轨道: ${name}`); cb && cb(false); return; }
      const clip = createVRMAnimationClip(va, vrm);
      if (stripRoot) {
        // 去根位移：去掉 hips 的 position 轨道，让角色原地循环、不漂移出画面（VRMA 常含走位根位移）
        clip.tracks = clip.tracks.filter((tr) => {
          const low = tr.name.toLowerCase();
          return !(low.includes('hip') && low.endsWith('.position'));
        });
      }
      motionClips[name] = clip;
      console.log(`[VRM] 动作已编译: ${name} dur=${clip.duration.toFixed(2)}s stripRoot=${!!stripRoot}`);
      cb && cb(true);
    } catch (e) { console.error(`[VRM] 动作编译失败 ${name}:`, e && e.message); cb && cb(false); }
  }, undefined, (e) => { console.error(`[VRM] 动作加载失败 ${name}:`, e && (e.message || e)); cb && cb(false); });
}

function startMotionClip(name) {
  if (!mixer) return;
  if (currentAction) { currentAction.stop(); currentAction = null; }
  const clip = motionClips[name];
  if (!clip) { console.warn('[VRM] 未就绪动作:', name); return; }
  const hips = bone('hips');
  savedHipsPos = hips ? hips.position.clone() : null;
  currentAction = mixer.clipAction(clip);
  currentAction.reset();
  currentAction.setLoop(THREE.LoopRepeat, 1);
  currentAction.clampWhenFinished = true;
  currentAction.play();
  if (idleAction) idleAction.paused = true;
  activeMotion = { name, dur: clip.duration, t: 0 };
  console.log('[VRM] motion ->', name);
}

function playMotion(name) {
  if (!vrm || !vrm.humanoid) return false;
  if (motionClips[name]) { startMotionClip(name); }
  else { loadMotionClip(name, (ok) => { if (ok) startMotionClip(name); }); }
  return true;
}

function nextDance() {
  danceIdx = (danceIdx + 1) % MOTION_FILES.length;
  const name = MOTION_FILES[danceIdx];
  if (motionClips[name]) startMotionClip(name);
  else loadMotionClip(name, (ok) => { if (ok) startMotionClip(name); });
}

function startDance() {
  if (!mixer) { console.warn('[VRM] mixer 未就绪，dance 延迟启动'); setTimeout(startDance, 200); return; }
  danceMode = true;
  danceIdx = -1;
  let firstStarted = false;
  MOTION_FILES.forEach((n) => loadMotionClip(n, () => {
    if (!firstStarted) { firstStarted = true; nextDance(); }
  }));
  console.log(`[DANCE] 已启动：循环播放真实 VRMA 动作库（${MOTION_FILES.length} 个）`);
}

function startLoopMotion(name) {
  if (!name) return;
  danceMode = false;
  const begin = () => {
    if (!mixer) { setTimeout(begin, 200); return; }
    if (!motionClips[name]) { loadMotionClip(name, begin, true); return; }
    if (currentAction) { currentAction.stop(); currentAction = null; }
    const clip = motionClips[name];
    const hips = bone('hips');
    savedHipsPos = hips ? hips.position.clone() : null;
    currentAction = mixer.clipAction(clip);
    currentAction.reset();
    currentAction.setLoop(THREE.LoopRepeat, Infinity);   // 无限循环，连续不停
    currentAction.play();
    if (idleAction) idleAction.paused = true;
    activeMotion = { name, dur: Infinity, t: 0 };   // dur=Infinity → frame 不切下一个，持续循环
    console.log('[LOOP] 连续动作循环播放 ->', name, '(去根位移, 原地无缝)');
  };
  begin();
}

// 诊断截图：把画面 POST 回后端存盘（base64 PNG），离线肉眼核对动作是否异常
function startDiagCapture() {
  const n = parseInt(new URLSearchParams(location.search).get('diag'), 10) || 16;
  let i = 0;
  const timer = setInterval(() => {
    i++;
    try {
      const url = renderer.domElement.toDataURL('image/png');
      fetch('/capture?i=' + i, { method: 'POST', body: url, headers: { 'Content-Type': 'text/plain' } });
    } catch (e) { console.warn('[DIAG] capture err', e.message); }
    if (i >= n) { clearInterval(timer); console.log('[DIAG] 截图完成 n=' + n); }
  }, 500);
}

function frame() {
  requestAnimationFrame(frame);
  const dt = clock.getDelta();
  const t = clock.elapsedTime;
  if (vrm) {
    mouthValue += (targetMouth - mouthValue) * Math.min(1, dt * 18);
    if (vrm.expressionManager) vrm.expressionManager.setValue('aa', mouthValue);
    if (activeMotion) {
      activeMotion.t += dt;
      if (activeMotion.t >= activeMotion.dur) {
        activeMotion = null;
        if (danceMode) {
          nextDance();
        } else {
          if (currentAction) { currentAction.stop(); currentAction = null; }
          if (savedHipsPos) { const h = bone('hips'); if (h) h.position.copy(savedHipsPos); savedHipsPos = null; }
          applyRestPose();   // 回到双臂自然下垂静止站姿
        }
      }
    }
    if (mixer) mixer.update(dt);   // 驱动 idle / 真实 VRMA 动作 clip
    vrm.update(dt);
  }
  renderer.render(scene, camera);
}
frame();

// ── 对外 API ──
window.__vrmSetEmotion = (name) => {
  expressionName = name;
  if (vrm && vrm.expressionManager) {
    for (const e of ['happy', 'angry', 'sad', 'relaxed', 'surprised']) vrm.expressionManager.setValue(e, e === name ? 1 : 0);
    console.log('[VRM] emotion ->', name);
  }
};
window.__vrmSetMouth = (v) => { targetMouth = Math.max(0, Math.min(1, v)); };
window.__vrmResetExpr = () => {
  expressionName = null;
  if (vrm && vrm.expressionManager) for (const e of ['happy', 'angry', 'sad', 'relaxed', 'surprised']) vrm.expressionManager.setValue(e, 0);
};
window.__vrmPlayMotion = (name) => playMotion(name);
window.__vrmStopMotion = () => {
  activeMotion = null;
  if (currentAction) { currentAction.stop(); currentAction = null; }
  if (idleAction) idleAction.paused = false;
  applyRestPose();
};
window.__vrmGetMotion = () => activeMotion ? activeMotion.name : null;
window.__vrmReady = () => !!vrm;
window.__vrmGetExpr = () => expressionName;
window.__vrmGetMouth = () => mouthValue;

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  if (vrm) fitCamera();
});
console.log('[VRM] animate loop started');
