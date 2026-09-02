// face_worker.js —— classic Worker：推理搬出主线程，主线程只取帧喂 Worker。
// 解决主线程同步 detectForVideo(~24ms) 阻塞视频帧回调、把 30fps 摄像头漏成 16fps 的问题。
// Worker 内以 ~24ms 节奏消费主线程（transfer）来的最新帧 -> detect ≈ 30fps（对齐 VTS）。
// 必须用 classic worker（非 module worker）：MediaPipe WASM loader 内部用 importScripts 加载 wasm glue，
// 而 module worker 不支持 importScripts（2026-09-01 实锤：module worker + ESM vision_bundle.mjs 直接抛
// "Failed to execute 'importScripts' on 'WorkerGlobalScope': Module scripts don't support importScripts()"）。
// 故此处 importScripts UMD 版 vision_bundle.js（挂全局 self.Vision），由 classic worker 的 importScripts 支持。
// 诊断加固（2026-09-01）：importScripts 包 try/catch，失败即回传 IMPORT_SCRIPTS_FAIL，避免「脚本评估抛错→
// onerror 未必触发→静默卡死」；各阶段发 ack 日志回传主线程，定位「加载慢/路径错/静默崩」。
let _Vision = null;
try {
  importScripts('./vendor/mediapipe/vision_bundle.js');
  _Vision = self.Vision;
  self.postMessage({ type: 'log', msg: 'IMPORT_SCRIPTS_OK Vision=' + (typeof _Vision) });
} catch (e) {
  self.postMessage({ type: 'log', msg: 'IMPORT_SCRIPTS_FAIL: ' + (e && e.message || e) });
  throw e;
}
const { FaceLandmarker, PoseLandmarker, FilesetResolver } = _Vision || {};
if (!FaceLandmarker) self.postMessage({ type: 'log', msg: 'NO_FaceLandmarker_GLOBAL' });

let faceLM = null, poseLM = null, fileset = null;
let poseThrottleMs = 100, lastPoseMs = 0, usePose = false;

self.onmessage = async (e) => {
  const d = e.data;
  if (d.type === 'init') {
    const cfg = d.cfg || {};
    poseThrottleMs = cfg.poseThrottleMs || 100;
    usePose = !!cfg.usePose;
    self.postMessage({ type: 'log', msg: 'INIT_RECV wasmDir=' + cfg.wasmDir + ' modelPath=' + cfg.modelPath + ' pose=' + usePose });
    try {
      fileset = await FilesetResolver.forVisionTasks(cfg.wasmDir);
      self.postMessage({ type: 'log', msg: 'FILESET_OK' });
      const buildFace = (delegate, modelPath) => ({
        baseOptions: { modelAssetPath: modelPath, delegate },
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,
        runningMode: 'VIDEO',
        numFaces: cfg.numFaces || 1,
      });
      let delegateUsed = cfg.delegate || 'GPU';
      let ok = false;
      let lastErr = '';
      for (const del of [delegateUsed, 'CPU']) {
        try {
          faceLM = await FaceLandmarker.createFromOptions(fileset, buildFace(del, cfg.modelPath));
          delegateUsed = del;
          ok = true;
          break;
        } catch (err) {
          lastErr = String(err && err.message || err);
          self.postMessage({ type: 'log', msg: 'face delegate ' + del + ' 失败: ' + lastErr });
        }
      }
      if (!ok) { self.postMessage({ type: 'inited', delegate: 'FAIL', err: 'face 模型加载失败: ' + lastErr }); return; }
      self.postMessage({ type: 'log', msg: 'FACELM_OK delegate=' + delegateUsed });      if (usePose) {
        try {
          poseLM = await PoseLandmarker.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: cfg.poseModelPath, delegate: delegateUsed },
            runningMode: 'VIDEO', numPoses: 1,
          });
        } catch (err) {
          self.postMessage({ type: 'log', msg: 'Pose 加载失败（仅面部）: ' + err.message });
          poseLM = null;
        }
      }
      self.postMessage({ type: 'inited', delegate: delegateUsed });
    } catch (err) {
      self.postMessage({ type: 'inited', delegate: 'FAIL', err: String(err && err.message || err) });
    }
  } else if (d.type === 'frame') {
    if (!faceLM) return;
    const bmp = d.bitmap;
    const ts = d.ts;
    const t0 = performance.now();
    const raw = { ts, detected: false, inferMs: 0, res: null, pose: null, poseVis: null };
    try {
      const res = faceLM.detectForVideo(bmp, ts);
      raw.inferMs = +(performance.now() - t0).toFixed(2);
      if (res && res.faceBlendshapes && res.faceBlendshapes[0]) {
        raw.detected = true;
        raw.res = res;
      }
      if (usePose && poseLM) {
        const now = performance.now();
        if (now - lastPoseMs >= poseThrottleMs) {
          lastPoseMs = now;
          try {
            const pr = poseLM.detectForVideo(bmp, ts);
            if (pr && pr.poseLandmarks && pr.poseLandmarks[0]) {
              raw.pose = pr.poseLandmarks[0];
              raw.poseVis = pr.poseWorldLandmarks ? pr.poseWorldLandmarks[0] : null;
            }
          } catch (err) { self.postMessage({ type: 'log', msg: 'pose detect 失败: ' + err.message }); }
        }
      }
      if (bmp && bmp.close) { try { bmp.close(); } catch (_) {} }
      self.postMessage({ type: 'result', result: raw });
    } catch (err) {
      if (bmp && bmp.close) { try { bmp.close(); } catch (_) {} }
      self.postMessage({ type: 'log', msg: 'detect 失败: ' + err.message });
    }
  }
};
