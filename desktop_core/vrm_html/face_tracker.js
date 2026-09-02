/**
 * 面捕模块（离线）—— 与渲染引擎解耦，VRM 与 Live2D 两条渲染链路都可复用。
 *
 * 依赖：vendor/mediapipe/vision_bundle.mjs（主线程回退用 ESM）+ vision_bundle.js（Worker 用 UMD）
 *       + vendor/mediapipe/wasm/* + face_landmarker.task / pose_landmarker_lite.task
 * 全部本地 vendored，运行时零外网请求，符合「单机/离线」硬约束。
 * 全部本地 vendored，运行时零外网请求，符合「单机/离线」硬约束。
 *
 * 阶段一（2026-09-01）：推理搬 Web Worker（face_worker.js），与摄像头 video 回调解耦。
 *   主线程（本文件）只做：gUM 取流 + rVFC 取帧 createImageBitmap 喂 Worker + 收 Worker 结果
 *   做 blendshape/头部平滑打包。detect 从「同步推理漏帧 14fps」提到「模型硬上限 ~30fps」。
 *   Worker 创建/加载失败 → 自动回退主线程同步推理（detect ~14，功能不坏，风险最低）。
 *
 * 输出：
 *   - ARKit 52 项 blendshape（已平滑）
 *   - 头部姿态：原始 4x4 矩阵（列主序）+ 解出的欧拉角（YXZ，弧度）
 *
 * 映射规则（ARKit -> VRM 表情）单独放在 arkit_to_vrm.js：纯函数、可无头单测。
 *
 * 注意：页面必须经 http(s) 打开（如 vrm_pet.py --port 起的本地服务），
 *       file:// 协议下浏览器会拦截 WASM/模型的 fetch，导致初始化失败。
 */

import { ARKIT_TO_VRM, arkitToVRM, matrixToEulerYXZ, clamp, MAPPING_DEFAULTS } from './arkit_to_vrm.js';

export { ARKIT_TO_VRM, arkitToVRM, matrixToEulerYXZ };

/** 默认配置：所有可调项集中在此，禁止在逻辑里散落硬编码 */
export const FACE_DEFAULTS = {
  wasmDir: './vendor/mediapipe/wasm',
  modelPath: './vendor/mediapipe/face_landmarker.task',
  poseModelPath: './vendor/mediapipe/pose_landmarker_lite.task',
  usePose: true,               // 是否启用身体姿态（上半身/手臂）追踪
  delegate: 'GPU',            // 'GPU' | 'CPU'，GPU 失败自动回退 CPU
  numFaces: 1,
  videoWidth: 320,            // gUM ideal（实际协商；推理内部固定 256×256，分辨率不影响 infer_ms）
  videoHeight: 240,
  facingMode: 'user',
  smoothing: 0.45,            // blendshape 平滑系数，0=不平滑 0.9=极平滑
  headSmoothing: 0.30,        // 头部姿态平滑
  mirror: MAPPING_DEFAULTS.mirror,                // 前置摄像头镜像：交换左右
  expressionGain: MAPPING_DEFAULTS.expressionGain, // 表情总增益
  // 头部姿态：增益 / 符号（实机方向不对时改 sign）/ 限幅（防扭断脖子）
  headGain: { yaw: 0.8, pitch: 0.8, roll: 0.8 },
  headSign: { yaw: 1, pitch: 1, roll: 1 },
  headLimitRad: { yaw: 0.70, pitch: 0.52, roll: 0.44 },
  throttleMs: 16,             // 仅主线程 fallback 用（Worker 模式不节流，速率由视频帧率决定）
  useWorker: true,             // 推理搬 Web Worker（默认启用）：主线程只取帧喂 Worker，detect 不阻塞视频帧 -> 吃满 30fps；Qt WebEngine 不支持 module worker / Worker 内 GPU 失败则 5s 超时或 inited FAIL 自动回退主线程
  poseThrottleMs: 200,        // 身体姿态独立降频（~5fps）：躯干俯仰是低频动作，降频可显著压低单帧推理成本，避免 worker 消费率掉到喂帧率以下导致队列堆积（2026-09-02 延迟播放根因之一）
  // 运行模式（阶段二 2026-09-01 官方机制实锤改 LIVE_STREAM）：
  // 官方文档原文：「When running in the image or the video mode, the Face Landmarker task blocks
  // the current thread until it finishes processing the input image or frame. When running in the
  // live stream mode, the Face Landmarker task returns immediately and doesn't block the current
  // thread... If the detection function is called when the task is busy, the task will ignore the
  // new input frame.」
  // 此前用 VIDEO 在 rVFC 回调里同步 detectForVideo → 31ms 阻塞帧回调 → 30fps 摄像头每 33ms
  // 出帧却被占住 → 漏掉一半帧 → detect 只有 14fps（facecap_perf.log 实证）。
  // LIVE_STREAM 由 MediaPipe 内部异步流水线接管：提交立即返回、结果走 resultCallback、busy 时
  // 自动丢帧（保最新帧、低延迟）→ 理论 detect 回到模型硬上限 ~32fps。
  // ⚠ 2026-09-01 真机 DIAG 实锤：本 Qt QWebEngineView 环境下 LIVE_STREAM **创建成功但回调不触发**
  //   （DIAG: mode=LIVE_STREAM live=True liveResults=0，且 video.currentTime 卡在 0.128 不推进），
  //   看门狗 3s 无结果后自动回退 VIDEO 才恢复（detected=True fps=13~16）。
  //   故默认改回 VIDEO：启动即刻可用，不再有 3s 空窗期（用户会以为又坏了）。
  //   LIVE_STREAM 代码路径与看门狗全部保留，供显式 cfg.runningMode='LIVE_STREAM' 或将来 Qt 升级后启用。
  runningMode: 'VIDEO',        // 'VIDEO'（同步，本环境实测可用）| 'LIVE_STREAM'（异步，本环境回调不触发）
};

export class FaceTracker {
  constructor(opts = {}) {
    this.cfg = { ...FACE_DEFAULTS, ...opts };
    this.landmarker = null;
    this.poseLandmarker = null;
    this.stream = null;
    this.video = null;
    this.running = false;
    this.lastVideoTime = -1;
    this._lastDetectMs = 0;
    this._bsSmooth = new Map();
    this._headSmooth = null;
    this._fpsCount = 0;
    this._fpsTs = 0;
    this.fps = 0;
    this._inferMs = 0;           // 单帧人脸推理耗时（ms），供 Python 侧写 PERF 日志量化 GPU 争抢
    this._lastPoseMs = 0;        // pose 独立降频的时间戳闸门
    this._poseCache = null;      // 最近一次 pose worldLandmarks（非 pose 帧复用，torsoPitch 略旧无损）
    this._poseVisCache = null;   // 最近一次 pose visibility
    this._rvfcActive = false;    // rVFC 检测循环是否真在跑（确证隐藏页 video 是否被节流）
    this._negotiatedFps = 0;     // gUM 实际协商帧率（区分「硬件/协商上限 15」 vs 「后台节流 15」）
    this._videoW = 0; this._videoH = 0;  // 实际协商分辨率
    this.result = { detected: false, blendshapes: null, headMatrix: null, headEuler: null, landmarks: null, ts: 0 };
    this.lastError = null;
    // ── 阶段一 Worker 相关 ──
    this._useWorker = false;     // true=Worker 推理模式；false=主线程同步推理 fallback
    this.worker = null;
    this.onResult = null;        // html 设 (r)=>window.__faceResult=__packFace(r)
    this._MP = null;             // 主线程 fallback 的 MediaPipe 类（动态 import）
    this._onInited = null;       // init 等待 Worker ready 的 resolve
    this._workerErrs = [];       // Worker 启用失败原因链（onerror/超时/inited_FAIL/catch），DIAG 暴露，避免被 _initMain 清 lastError 掩盖
    this._workerLogs = [];       // Worker 内运行日志（importScripts/收到init/fileset/lm 各阶段 ack），DIAG 暴露，定位「加载慢/路径错/静默崩」
    this._feedFps = 0;            // 主线程实际喂帧率（postMessage frame 频率）
    this._createMs = 0;           // createImageBitmap 平均耗时（定位 detect_fps<源 是否主线程转换瓶颈）
    this._feedCount = 0; this._feedTs = 0; this._createSum = 0; this._createN = 0;
    // ── 阶段二：LIVE_STREAM 异步流水线 ──
    this._liveMode = false;      // true=FaceLandmarker 以 LIVE_STREAM 模式运行（提交不阻塞、结果走回调）
    this._submitAt = 0;          // 最近一次帧提交时刻（算端到端延迟）
    this._poseTimer = null;      // pose 独立降频 timer（LIVE_STREAM 下不占 rVFC 帧回调）
    this._liveResultCount = 0;   // LIVE_STREAM 回调已产出结果数（看门狗判定「回调是否真工作」）
    this._startTs = 0;           // 启动时刻（看门狗计时起点）
    this._liveFallbackDone = false; // LIVE_STREAM→VIDEO 自动回退是否已执行（只做一次）
    this._fileset = null;        // MediaPipe fileset（供运行时回退重建 landmarker）
    this._warmed = false;       // GPU shader 预热是否已完成（preload 后台编译，避免首帧卡 5~6s）
    this._startWall = 0;        // start() 时刻（量「开面捕→首帧真·检出」的延迟）
    this._gumMs = null;         // getUserMedia 耗时（区分「摄像头开慢」vs「首帧推理慢」）
    this._firstReported = false;
    this._firstDetectSec = null;
    this._rvfcCount = 0;        // rVFC 实际触发次数（=摄像头实际向页面投帧率，区分「摄像头只给 15」vs「我们漏半帧」）
    this._rvfcFps = 0;
    this._rvfcTs = 0;
    this._rvfcTimer = null;      // 统一投帧率计时器（_startRvfcMeter）
  }

  /** 初始化：优先 Web Worker（推理不阻塞主线程 video 帧），失败回退主线程同步推理 */
  async init() {
    if (this.landmarker || this._useWorker) return true;
    // Worker 模式已真正实现（face_worker.js，classic worker）。默认启用（FACE_DEFAULTS.useWorker=true）：
    // 主线程只从摄像头 track 直拉帧喂 Worker，detect 在 Worker 跑 -> 主线程不阻塞 -> 吃满 30fps（对齐 VTS）。
    // 用 classic worker（非 module worker）：MediaPipe WASM loader 内部 importScripts 加载 glue，module worker
    // 不支持 importScripts（2026-09-01 实锤静默失败根因，已改 classic + UMD vision_bundle.js 修复）。
    // 若 Worker 内 GPU delegate 初始化失败，则 onerror / inited(FAIL) / 5s 超时 触发回退主线程同步推理
    // （功能不坏，仅回落 16fps）。
    if (!this.cfg.useWorker) {
      await this._initMain();
      return true;
    }
    try {
      // classic worker（不要 {type:'module'}）：MediaPipe WASM loader 内部 importScripts 加载 glue，
      // module worker 不支持 importScripts（2026-09-01 实锤静默失败根因）。
      this.worker = new Worker(new URL('./face_worker.js', import.meta.url));
      this.worker.onmessage = (e) => this._onWorker(e.data);
      this.worker.onerror = (e) => {
        const _m = (e && (e.message || (e.filename + ':' + e.lineno))) || String(e);
        this.lastError = 'worker 错误: ' + _m;
        this._workerErrs.push('onerror: ' + _m);
        if (this._onInited) { this._onInited('FAIL'); this._onInited = null; }
      };
      // 超时兜底：Qt QWebEngineView 下 module worker 可能静默失败（既不发 inited 也不触发
      // onerror），导致本 Promise 永久不 resolve → start() 卡在 await init() → getUserMedia 永不
      // 调用 → 摄像头不开（2026-09-01 实锤回归）。超时强制作废 → 进 catch 回退主线程，
      // 面捕照常可开（detect ~14，功能不坏，风险最低）。
      // 把相对资源路径解析成绝对 URL 再发给 Worker：Worker 内 fetch/importScripts 相对解析以 worker 脚本 URL
      // 为基准，不同环境可能歧义；传绝对 URL 彻底消除（2026-09-01 加固）。
      const _abs = (rel) => { try { return new URL(rel, import.meta.url).href; } catch (_) { return rel; } };
      const _initCfg = Object.assign({}, this.cfg, {
        wasmDir: _abs(this.cfg.wasmDir),
        modelPath: _abs(this.cfg.modelPath),
        poseModelPath: _abs(this.cfg.poseModelPath),
      });
      let _ivT = null;
      const ready = await new Promise((resolve) => {
        this._onInited = resolve;
        this.worker.postMessage({ type: 'init', cfg: _initCfg });
        _ivT = setTimeout(() => {
          if (this._onInited) { this._onInited = null; this._workerErrs.push('FAIL_TIMEOUT(15s 无 inited：Worker 内 importScripts 失败 / wasm 路径 404 / GPU delegate 初始化卡死)'); resolve('FAIL_TIMEOUT'); }
        }, 15000);
      });
      if (_ivT) clearTimeout(_ivT);
      this._onInited = null;
      if (ready === 'FAIL' || ready === 'FAIL_TIMEOUT') throw new Error('Worker 初始化失败: ' + String(ready));
      this._useWorker = true;
      console.log('[FaceTracker] Worker 模式初始化');
    } catch (e) {
      const _m = 'Worker 失败，回退主线程: ' + (e && e.message || e);
      this.lastError = _m;
      this._workerErrs.push('catch: ' + _m);
      this._useWorker = false;
      if (this.worker) { try { this.worker.terminate(); } catch (_) {} this.worker = null; }
      await this._initMain();   // 主线程同步推理兜底（detect ~14，功能不坏）
    }
    return true;
  }

  /** 主线程 fallback：直接加载 WASM + 模型（Worker 不可用/创建失败时） */
  async _initMain() {
    const { FaceLandmarker, PoseLandmarker, FilesetResolver } = await import('./vendor/mediapipe/vision_bundle.mjs');
    this._MP = { FaceLandmarker, PoseLandmarker, FilesetResolver };
    const fileset = await FilesetResolver.forVisionTasks(this.cfg.wasmDir);
    this._fileset = fileset;   // 供 LIVE_STREAM→VIDEO 运行时回退重建 landmarker
    // mode 优先 LIVE_STREAM（异步不阻塞）；创建失败自动回退 VIDEO（同步，功能不坏，仅 detect 回落 14）
    const buildFace = (delegate, modelPath, mode) => ({
      baseOptions: { modelAssetPath: modelPath, delegate },
      outputFaceBlendshapes: true,
      outputFacialTransformationMatrixes: true,
      runningMode: mode,
      numFaces: this.cfg.numFaces,
      ...(mode === 'LIVE_STREAM' ? { resultCallback: (res, ts) => this._onLiveResult(res, ts) } : {}),
    });
    // 只试真实存在的模型：`face_landmarker_lite.task` 官方不存在（2026-09-01 二次查证 +
    // 真机 DIAG 日志实锤 404）。先前把它放在首位"前向兼容探测"，代价是每次启动白产生一次 404，
    // 并把 lastError 污染成 404 文本、掩盖后续真实错误（排查时被误导过）。已移除。
    const _faceModels = [this.cfg.modelPath];
    const _modes = this.cfg.runningMode === 'LIVE_STREAM' ? ['LIVE_STREAM', 'VIDEO'] : ['VIDEO'];
    let _faceOk = false;
    for (const mode of _modes) {
      for (const mp of _faceModels) {
        for (const del of [this.cfg.delegate, 'CPU']) {
          try {
            this.landmarker = await FaceLandmarker.createFromOptions(fileset, buildFace(del, mp, mode));
            this.cfg.delegate = del;
            this.cfg.modelPath = mp;
            this.cfg.runningMode = mode;
            this._liveMode = (mode === 'LIVE_STREAM');
            this.lastError = null;   // 加载成功：清掉过程中记录的可恢复错误，避免污染诊断日志
            _faceOk = true;
            break;
          } catch (e) {
            this.lastError = 'face 模型加载失败: ' + mp + ' delegate=' + del + ' mode=' + mode + ' ' + e.message;
          }
        }
        if (_faceOk) break;
      }
      if (_faceOk) break;
    }
    if (!_faceOk) throw new Error('face 模型全部加载失败: ' + _faceModels.join(', '));
    console.log('[FaceTracker] 主线程就绪 delegate=' + this.cfg.delegate + ' faceModel=' + this.cfg.modelPath);
    if (this.cfg.usePose) {
      try {
        this.poseLandmarker = await PoseLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: this.cfg.poseModelPath, delegate: this.cfg.delegate },
          runningMode: 'VIDEO',
          numPoses: 1,
        });
        console.log('[FaceTracker] Pose 就绪');
      } catch (e) {
        console.warn('[FaceTracker] Pose 加载失败（仅面部可用）:', e.message);
        this.poseLandmarker = null;
      }
    }
    return this.landmarker;
  }

  /** 打开摄像头并开始逐帧检测 */
  async start(opts = {}) {
    await this.init();
    if (!this.video) {
      const v = document.createElement('video');
      v.playsInline = true;
      v.muted = true;
      v.autoplay = true;
      // 桌宠只做采集，不显示画面：隐藏且不吃鼠标事件
      v.style.cssText = 'position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none;';
      document.body.appendChild(v);
      this.video = v;
    }
    // 帧率确证探针（2026-09-01）：先前误把「检测卡 15fps」归因为渲染抢 GPU，实测 GPU 解耦仍 15fps
    // → 瓶颈在摄像头出帧率本身 / 同步推理漏帧。故放宽分辨率约束（ideal 320×240，多数摄像头原生
    // 30fps），显式请求 60fps，并记录 track.getSettings().frameRate（实际协商帧率）+ rVFC 是否真在跑。
    const video = {
      facingMode: this.cfg.facingMode,
      width: { ideal: 320 },
      height: { ideal: 240 },
      frameRate: { ideal: 60, max: 60 },
    };
    if (opts.deviceId) video.deviceId = { exact: opts.deviceId };
    const _gumT0 = performance.now();
    this.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    this._gumMs = +(performance.now() - _gumT0).toFixed(2);
    this.video.srcObject = this.stream;
    await this.video.play();
    // 直拉帧读取器：若环境支持 MediaStreamTrackProcessor，从摄像头 track 直接读 VideoFrame，
    // 绕开 video 元素与 Chromium 可见性节流（window opacity:0 隐藏捕获页时 video 不投 rVFC 帧→15fps）。
    // 不支持则 _useTrackReader=false，由 start() 末尾回退 _startMainLoop（rVFC 路径）。
    this._track = this.stream.getVideoTracks()[0] || null;
    this._useTrackReader = false;
    this._trackReaderErr = null;   // TrackProcessor 不可用/失败原因（DIAG 暴露，定位真机直拉为何不生效）
    this._trackReader = null;
    try {
      if (this._track && typeof MediaStreamTrackProcessor !== 'undefined') {
        const _proc = new MediaStreamTrackProcessor({ track: this._track });
        this._trackReader = _proc.readable.getReader();
        this._useTrackReader = true;
        console.log('[FaceTracker] MediaStreamTrackProcessor 就绪（将直拉帧绕开 video 可见性）');
      } else {
        this._trackReaderErr = 'MediaStreamTrackProcessor undefined（环境不支持，回退 rVFC）';
        console.log('[FaceTracker] 环境无 MediaStreamTrackProcessor，回退 rVFC 路径');
      }
    } catch (e) {
      this._trackReaderErr = e.message;
      console.log('[FaceTracker] TrackProcessor 创建失败，回退 rVFC: ' + e.message);
      this._useTrackReader = false;
      this._trackReader = null;
    }
    // 记录实际协商帧率/分辨率（确证 H1/H2 用）
    try {
      const tk = this.stream.getVideoTracks()[0];
      const st = (tk && tk.getSettings) ? tk.getSettings() : {};
      this._negotiatedFps = st.frameRate || 0;
      this._videoW = st.width || 0; this._videoH = st.height || 0;
      console.log('[FaceTracker] gUM 协商: ' + this._videoW + 'x' + this._videoH + ' @' + this._negotiatedFps + 'fps');
    } catch (e) { this.lastError = 'getSettings 失败: ' + e.message; }
    this.running = true;
    this._fpsTs = performance.now();
    this._fpsCount = 0;
    this._startTs = performance.now();
    this._startWall = performance.now();   // 量「开面捕 → 首帧真·检出」延迟（含首次 GPU 编译）
    this._liveResultCount = 0;
    this._liveFallbackDone = false;
    this._lastPoseMs = performance.now();
    // 若 preload 阶段已 GPU 预热则此处为 no-op；否则兜底在此编译（首帧会慢，等同旧行为）。
    await this._warmupGpu();
    console.log('[FaceTracker] 摄像头已开启（' + (this._useWorker ? 'Worker' : '主线程') + '模式）');
    // 检测循环：Worker 模式由主线程 rVFC 取帧喂 Worker；主线程模式直接 rVFC 调 update() 同步推理。
    // 2026-09-01 回归修复：此前主线程 fallback 没有启动任何检测循环（_startPump 仅在 uw=True 调），
    // 导致 tracker.update() 永不调用 → onResult 不触发 → 面捕零数据（detect_fps=0）。
    if (this._useWorker) {
      if (this._useTrackReader) this._startPumpWorker();
      else this._startPump();
    } else if (this._useTrackReader) this._startTrackLoop();
    else this._startMainLoop();
    this._startRvfcMeter();   // 统一 1s 定时器：从 _rvfcCount 算 rvfcFps（覆盖 Worker/主线程所有路径，避免 rvfcFps 恒 0 假象）
    return this.stream;
  }

  /** 统一摄像头投帧率计：所有模式的泵循环都自增 _rvfcCount，这里每 1s 归算 rvfcFps，与推理回调时序解耦 */
  _startRvfcMeter() {
    this._rvfcTs = performance.now();
    this._rvfcTimer = setInterval(() => {
      const now = performance.now();
      const dt = now - this._rvfcTs;
      if (dt >= 500) {
        this._rvfcFps = Math.round((this._rvfcCount * 1000) / dt);
        this._rvfcCount = 0;
        this._rvfcTs = now;
      }
    }, 500);
  }

  /**
   * 阶段一核心：主线程 rVFC 循环只取帧喂 Worker（不推理）。
   * busy 哨兵保证一次只处理一帧 createImageBitmap，喂帧严格顺序 → Worker 收到顺序帧、
   * detectForVideo 的 ts 单调递增。推理 31ms 在 Worker 跑，主线程 video 帧连续出 30fps，
   * Worker 以 31ms 节奏推理最新帧 → detect ≈ 30fps（原主线程同步推理漏掉一半帧才 14fps）。
   */
  _startPump() {
    const v = this.video;
    let busy = false;
    const pump = () => {
      if (!this.running) return;
      if (v.readyState >= 2 && v.currentTime !== this.lastVideoTime) {
        this.lastVideoTime = v.currentTime;
        const ts = performance.now();
        if (!busy) {
          busy = true;
          createImageBitmap(v).then((bmp) => {
            try {
              // transfer ImageBitmap 所有权到 Worker（主线程侧副本失效，Worker 用完 close）
              this.worker.postMessage(
                { type: 'frame', bitmap: bmp, ts, poseNow: (ts - this._lastPoseMs) >= this.cfg.poseThrottleMs },
                [bmp]
              );
            } catch (e) { this.lastError = 'postMessage frame 失败: ' + e.message; }
            busy = false;
          }).catch(() => { busy = false; });
        }
      }
      if ('requestVideoFrameCallback' in v && v.requestVideoFrameCallback) {
        window.__rvfcActive = 'rvfc';
        v.requestVideoFrameCallback(pump);
      } else {
        window.__rvfcActive = 'timer';
        setTimeout(pump, 16);
      }
    };
    if ('requestVideoFrameCallback' in v && v.requestVideoFrameCallback) v.requestVideoFrameCallback(pump);
    else setTimeout(pump, 16);
  }

  /**
   * Worker + TrackProcessor 直拉喂帧：主线程从摄像头 track 直接读 VideoFrame，
   * drawImage 到复用 canvas -> createImageBitmap 异步 transfer 给 Worker（不阻塞主线程读帧循环）。
   * 隐藏窗口下 video 被节流，但 TrackProcessor 直拉绕开 video 可见性（2026-09-01 实测 rvfc=track 生效）。
   */
  _startPumpWorker() {
    const w = this._videoW || 320, h = this._videoH || 240;
    const useOff = (typeof OffscreenCanvas !== 'undefined');
    let canvas = useOff ? new OffscreenCanvas(w, h) : document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d');
    // 多帧在途背压：inflight 计的是「已投递给 Worker、尚未处理完」的帧数（在 Worker 回传 result 时才 --），
    // 这才是真正的背压信号。旧写法在 createImageBitmap 完成后立即 --（位图转换仅 ~0.1ms），等于没有限流，
    // Worker 收到全部 30fps 帧、推理慢于采集时队列无界堆积 → 渲染滞后渐进增大 = 用户说的「延迟播放」。
    // 正确做法：主线程只在 inflight < MAX_INFLIGHT 时投递，Worker 慢则喂帧率被自然压到消费率，不堆积。
    const MAX_INFLIGHT = 2;
    this._inflight = 0;
    const loop = async () => {
      if (!this.running || !this._trackReader) return;
      while (this.running && this._trackReader) {
        while (this._inflight >= MAX_INFLIGHT) { await new Promise((r) => setTimeout(r, 1)); }
        let frame, done;
        try { ({ value: frame, done } = await this._trackReader.read()); }
        catch (e) { this.lastError = 'trackReader.read 失败: ' + e.message; break; }
        if (done) { if (frame) frame.close(); break; }
        if (!frame) continue;
        ctx.drawImage(frame, 0, 0, w, h);
        frame.close();
        const ts = performance.now();
        this._inflight++;
        const _c0 = performance.now();
        createImageBitmap(canvas).then((bmp) => {
          const _cdt = performance.now() - _c0;
          this._createSum += _cdt; this._createN++;
          try {
            this.worker.postMessage({ type: 'frame', bitmap: bmp, ts }, [bmp]);
            this._rvfcCount++;
            this._feedCount++;
            const _now = performance.now();
            if (_now - this._feedTs >= 1000) {
              this._feedFps = Math.round((this._feedCount * 1000) / (_now - this._feedTs));
              this._feedCount = 0; this._feedTs = _now;
              this._createMs = this._createN ? this._createSum / this._createN : 0;
              this._createSum = 0; this._createN = 0;
            }
            // 注意：this._inflight 在此【不】递减——它只在 Worker 回传 result(_onWorker 'result')时 --，
            // 这样 inflight 才是「已投递未处理完」的真实背压计数（2026-09-02 延迟播放根因修复）。
          } catch (e) {
            this.lastError = 'postMessage frame 失败: ' + e.message;
            this._inflight--;
          }
        }).catch(() => { this._inflight--; });
      }
    };
    loop();
  }

  /**
   * 主线程 fallback 检测循环（useWorker=false）：rVFC 逐帧调 update()（同步推理 + 平滑 + 打包），
   * 结果经 _emit → onResult 回传 html 打包。逻辑等价于改造前 face_capture.html 内的 rVFC 循环，
   * 只是下沉到 tracker 自身，保证无论 Worker 是否启用检测循环都存在（修复 detect_fps=0 回归）。
   * 注：同步推理 31ms 会阻塞主线程 video 帧 → detect ~14fps（模型硬上限），渲染侧 60fps 插值补偿观感。
   */
  _startMainLoop() {
    const v = this.video;
    const tick = () => {
      if (!this.running) return;
      this._rvfcCount++;  // rVFC 实际触发率（摄像头真实投帧率），用于定位 detect 15fps 是「摄像头只给 15」还是「我们仍漏半帧」
      // 看门狗：LIVE_STREAM 启动 3s 内一帧结果都没收到 → 判定异步回调在本环境不工作，
      // 自动重建为 VIDEO 同步模式（回退到已验证可用的 detect~14），绝不停在「零数据」状态。
      // 2026-09-01 实锤需求：Qt WebEngine 下模块行为不可预期，必须自愈而非等用户重启排查。
      if (this._liveMode && !this._liveFallbackDone && this._liveResultCount === 0
          && performance.now() - this._startTs > 3000) {
        this._liveFallbackDone = true;
        this._fallbackToVideo();
      }
      // ⚠ 帧率治本（2026-09-01 收尾）：rVFC 续注册 **提前到推理之前**。
      // 旧逻辑先同步 detectForVideo(阻塞~33ms)再续注册 → 推理 33ms 期间 video 新帧的 rVFC 回调尚未
      // 注册而丢失 → 30fps 摄像头每 33ms 出一帧却只推理一半 → detect 钉 15fps（VIDEO 模式漏半帧）。
      // 续注册提前：推理前 rVFC 已注册，推理 33ms 期间 video 新帧回调入队、推理完立即触发 →
      // 每帧都进推理 → detect 冲 ~30fps（对齐 VTS 的 MediaPipe webcam 30fps，不再漏半帧）。
      // LIVE_STREAM 下 _submitFrame 立即返回(不阻塞)，提前续注册无害；worker 模式不走此 tick。
      if ('requestVideoFrameCallback' in v && v.requestVideoFrameCallback) {
        window.__rvfcActive = 'rvfc';
        v.requestVideoFrameCallback(tick);
      } else {
        window.__rvfcActive = 'timer';
        setTimeout(tick, 16);
      }
      try { this._submitFrame(); } catch (e) { this.lastError = '主线程帧提交失败: ' + e.message; }
    };
    if ('requestVideoFrameCallback' in v && v.requestVideoFrameCallback) v.requestVideoFrameCallback(tick);
    else setTimeout(tick, 16);
    // LIVE_STREAM 下 pose 走独立 timer：pose 是 VIDEO 模式同步推理（~15ms），若留在 rVFC 回调里
    // 会重新阻塞帧提交，把阶段二的收益抵消。VIDEO 回退模式保持原内联 pose 逻辑不变。
    if (this._liveMode && this.poseLandmarker) {
      this._poseTimer = setInterval(() => this._poseTick(), this.cfg.poseThrottleMs);
    }
  }

  /**
   * 主线程直拉帧循环（VIDEO 模式 + 支持 MediaStreamTrackProcessor 的环境）：
   * 用 MediaStreamTrackProcessor 从摄像头 track 直接读 VideoFrame（绕过 video 元素与 Chromium
   * 可见性判定），转 ImageBitmap 喂 detectForVideo。这是帧率治本最终方案——
   * window opacity:0 隐藏捕获页时 Chromium 对 video 元素不投 rVFC 帧（→15fps），但 track 解码
   * 独立于渲染合成，TrackProcessor 不受页面可见性影响 → 满 30fps 对齐 VTS。环境不支持时
   * _useTrackReader=false，由 start() 回退 _startMainLoop（rVFC 路径）。
   */
  async _startTrackLoop() {
    window.__rvfcActive = 'track';
    console.log('[FaceTracker] TrackProcessor 直拉帧：read() 同步 drawImage 到复用 canvas，detectForVideo 直接吃 canvas（去掉 createImageBitmap 开销）');
    // 优化 2026-09-01：旧双循环每帧 createImageBitmap(VideoFrame)（~15ms）串行绑死推理定时器拖慢消费。
    // 改 drawImage 到持久 canvas（~2ms）已落地，但实测 rvfcFps 仍 16~17（与 VTS 30 差距未消除），
    // 说明瓶颈不在 createImageBitmap，而在主线程同步 detect 被 Chromium 对透明/隐藏窗口的 GPU 降权拖慢
    // （详见 face_bridge.py NAIXI_FACECAP_VISIBLE 开关与帧率排查记录）。
    // 单循环用 await read() 做让出点（Promise 不受隐藏页 timer 节流），比 setTimeout 更稳。
    const w = this._videoW || 320, h = this._videoH || 240;
    let canvas;
    try { canvas = (typeof OffscreenCanvas !== 'undefined') ? new OffscreenCanvas(w, h) : document.createElement('canvas'); }
    catch (e) { canvas = document.createElement('canvas'); }
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) { this.lastError = 'TrackProcessor canvas 2d 上下文获取失败'; return; }
    while (this.running && this._trackReader) {
      let frame, done;
      try {
        ({ value: frame, done } = await this._trackReader.read());
      } catch (e) {
        this.lastError = 'TrackProcessor read 失败: ' + e.message;
        break;
      }
      if (done) { if (frame) frame.close(); break; }
      if (!frame) continue;
      try { ctx.drawImage(frame, 0, 0, w, h); }
      catch (e) { frame.close(); continue; }
      frame.close();
      const tsMs = performance.now();
      try { this._updateMain(tsMs, canvas); this._rvfcCount++; }
      catch (e) { this.lastError = 'track 推理失败: ' + e.message; }
    }
    console.log('[FaceTracker] TrackProcessor 循环结束');
  }

  /** 预热：仅建 MediaPipe 模型（不 getUserMedia、不起检测循环），供捕获页 load 后静默调用。
   *  把 WASM 编译 + 模型 fetch 的 ~16s 从「用户点开面捕」挪到后台，点面捕时只差 gUM（几百 ms）。 */
  async preload() {
    if (this.landmarker) return true;
    if (this._useWorker) { await this.init(); return true; }
    await this._initMain();
    // GPU 预热：在后台（app 启动、页面 load 后）就把整图 shader 编译掉，用户点面捕时首帧直接快。
    // 否则编译被推迟到首帧 detectForVideo → 表现为「模型已加载却还要卡 5~6s 才动」。
    await this._warmupGpu();
    this._preloaded = true;
    console.log('[FaceTracker] 预热完成（主线程模型就绪，待 getUserMedia）');
    return true;
  }

  /** GPU 预热：模型建好后用离屏哑帧跑几次 detectForVideo，强制 MediaPipe 在后台编译 GPU shader
   *  （face+pose 各一次编译，典型 3~6s）。只在 VIDEO 同步模式做（默认）；LIVE_STREAM 异步模式
   *  由 3s 看门狗兜底，不在此预热。哑帧无脸，detectForVideo 抛「无脸」可忽略。 */
  async _warmupGpu() {
    if (this._warmed) return;
    if (!this.landmarker) return;
    try {
      const cv = document.createElement('canvas');
      cv.width = 256; cv.height = 256;
      const ctx = cv.getContext('2d');
      ctx.fillStyle = '#808080';
      ctx.fillRect(0, 0, 256, 256);
      let t = 1;
      if (!this._liveMode) {
        for (let i = 0; i < 3; i++) {
          try { this.landmarker.detectForVideo(cv, t++); } catch (e) { /* 哑帧无脸，忽略 */ }
        }
        if (this.poseLandmarker) {
          for (let i = 0; i < 3; i++) {
            try { this.poseLandmarker.detectForVideo(cv, t++); } catch (e) {}
          }
        }
      }
      this._warmed = true;
      console.log('[FaceTracker] GPU 预热完成（shader 已编译，首帧不再卡）');
    } catch (e) {
      this.lastError = 'GPU 预热失败(可忽略，仅首帧会慢): ' + e.message;
    }
  }

  _onWorker(d) {
    if (d.type === 'inited') {
      if (d.delegate === 'FAIL') {
        const _m = 'Worker 内模型加载失败（将回退主线程）: ' + (d.err || '');
        this.lastError = _m;
        this._workerErrs.push('inited_FAIL: ' + _m);
        if (this._onInited) { this._onInited('FAIL'); this._onInited = null; }
      } else {
        this.cfg.delegate = d.delegate;
        if (this._onInited) { this._onInited('OK'); this._onInited = null; }
      }
    } else if (d.type === 'result') {
      if (this._inflight > 0) this._inflight--;   // Worker 回传一帧结果 → 在途计数 -1（真实背压信号）
      this._processWorker(d.result);
    } else if (d.type === 'log') {
      console.log('[FaceWorker] ' + d.msg);
      this._workerLogs.push(d.msg);
    }
  }

  /** Worker 回传原始推理结果 → 主线程平滑 + 头部欧拉 + 打包（与渲染零耦合） */
  _processWorker(raw) {
    this._inferMs = raw.inferMs;
    this._fpsCount++;
    const now = performance.now();
    // 帧 age 诊断：从摄像头采集(raw.ts)到主线程应用结果(now)的端到端延迟（含队列堆积+推理+回传）。
    // age 持续偏大 = worker 队列堆积（消费率<喂帧率）= 用户说的「延迟播放」。
    if (raw.ts != null) {
      const _age = now - raw.ts;
      if (this._ageWinMax == null || _age > this._ageWinMax) this._ageWinMax = _age;
      this._ageSum = (this._ageSum || 0) + _age;
      this._ageN = (this._ageN || 0) + 1;
    }
    if (now - this._fpsTs >= 1000) {
      this.fps = Math.round((this._fpsCount * 1000) / (now - this._fpsTs));
      this._fpsCount = 0;
      this._fpsTs = now;
      this._ageAvg = this._ageN ? this._ageSum / this._ageN : 0;   // 窗口均值（常态延迟）
      this._ageMax = this._ageWinMax != null ? this._ageWinMax : 0;  // 窗口峰值（瞬时堆积）
      this._ageSum = 0; this._ageN = 0; this._ageWinMax = 0;
    }
    // pose 缓存（Worker 按 poseThrottleMs 周期性回传，主线程复用）
    if (raw.pose) {
      this._poseCache = raw.pose;
      this._poseVisCache = raw.poseVis;
    }
    const poseLandmarks = this._poseCache;
    const poseVis = this._poseVisCache;

    if (!raw.detected) {
      this.result = {
        detected: false, blendshapes: null, headMatrix: null, headEuler: null,
        pose: poseLandmarks, poseVis, landmarks: null, ts: raw.ts,
        fps: this.fps, inferMs: this._inferMs, cam: this._cam(),
      };
      this._emit();
      return;
    }

    // blendshapes 一阶平滑
    const bs = {};
    const k = this.cfg.smoothing;
    const cats = raw.res.faceBlendshapes[0].categories;
    for (const c of cats) {
      const prev = this._bsSmooth.get(c.categoryName);
      const v = prev === undefined ? c.score : prev + (c.score - prev) * (1 - k);
      this._bsSmooth.set(c.categoryName, v);
      bs[c.categoryName] = v;
    }

    // 头部姿态：4x4 列主序 -> 欧拉角 -> 增益/符号/限幅/平滑
    let headEuler = null;
    let headMatrix = null;
    const m = raw.res.facialTransformationMatrixes && raw.res.facialTransformationMatrixes[0];
    if (m && m.data) {
      headMatrix = m.data;
      const e = matrixToEulerYXZ(m.data);
      if (e) {
        const { headGain: g, headSign: s, headLimitRad: lim } = this.cfg;
        const rE = {
          x: clamp(e.x * g.pitch * s.pitch, -lim.pitch, lim.pitch),
          y: clamp(e.y * g.yaw * s.yaw, -lim.yaw, lim.yaw),
          z: clamp(e.z * g.roll * s.roll, -lim.roll, lim.roll),
        };
        const ks = this.cfg.headSmoothing;
        if (!this._headSmooth) this._headSmooth = rE;
        else {
          this._headSmooth.x += (rE.x - this._headSmooth.x) * (1 - ks);
          this._headSmooth.y += (rE.y - this._headSmooth.y) * (1 - ks);
          this._headSmooth.z += (rE.z - this._headSmooth.z) * (1 - ks);
        }
        headEuler = { ...this._headSmooth };
      }
    }

    this.result = {
      detected: true, blendshapes: bs, headMatrix,
      headEuler, pose: poseLandmarks, poseVis,
      landmarks: raw.res.faceLandmarks ? raw.res.faceLandmarks[0] : null,
      ts: raw.ts, fps: this.fps, inferMs: this._inferMs, cam: this._cam(),
    };
    this._emit();
  }

  _cam() {
    return {
      fps: this.fps,
      neg: this._negotiatedFps,
      rvfc: (typeof window !== 'undefined' && window.__rvfcActive) || false,
      w: this._videoW, h: this._videoH,
    };
  }

  _emit() {
    // 把背压/延迟/喂帧率字段并回 result 回包，否则 Python 侧 PERF 日志从这些字段读到的全是 0（回包不含），
    // 延迟播放就无法被量化（2026-09-02 自测实锤：feedFps/inflight/age 在 getDiagnostics 有值、回包无值 → PERF 恒 0）。
    try {
      this.result.feedFps = this._feedFps || 0;
      this.result.inflight = this._inflight || 0;
      this.result.ageMax = this._ageMax || 0;
      this.result.ageAvg = this._ageAvg || 0;
    } catch (e) { /* result 不可写时忽略（不影响检测） */ }
    if (this.onResult) {
      try { this.onResult(this.result); } catch (e) { this.lastError = 'onResult 失败: ' + e.message; }
    }
  }

  /** 每帧调用（Python poll→__faceTick）。Worker 模式只读；LIVE_STREAM 只读；VIDEO 同步推理 */
  update(nowMs) {
    // LIVE_STREAM：结果由 resultCallback 异步写入 this.result，此处只读。
    // 帧提交由 _submitFrame 负责——若在此调 _updateMain 会重复提交同一帧（VIDEO 语义）而丢结果。
    if (this._liveMode) return this.result;
    if (!this._useWorker && this.landmarker) return this._updateMain(nowMs);
    return this.result;
  }

  /**
   * 主线程每帧入口：
   * - LIVE_STREAM：只提交帧（detectForVideo 立即返回，不阻塞；busy 时 MediaPipe 自动丢帧），
   *   结果由 _onLiveResult 异步打包 → 这是阶段二提 detect 帧率的关键（不再漏帧）。
   * - VIDEO（回退）：调 update() 同步推理并直接打包。
   */
  _submitFrame() {
    const nowMs = performance.now();
    if (this._liveMode) {
      if (!this.landmarker || !this.video || this.video.readyState < 2) return;
      if (this.video.currentTime === this.lastVideoTime) return;
      this.lastVideoTime = this.video.currentTime;
      this._submitAt = nowMs;
      this.landmarker.detectForVideo(this.video, nowMs);
      return;
    }
    this.update(nowMs);
  }

  /** 主线程 fallback 推理（Worker 不可用/创建失败时），逻辑同原 update() */
  _updateMain(nowMs, image) {
    if (!this.running || !this.landmarker) return this.result;
    const img = image || this.video;
    if (!img) return this.result;
    if (nowMs - this._lastDetectMs < this.cfg.throttleMs) return this.result;
    if (img === this.video) {
      // video 元素路径：依赖 readyState + currentTime 去重（rVFC 投帧语义）
      if (this.video.readyState < 2) return this.result;
      if (!image && this.video && this.video.currentTime === this.lastVideoTime) return this.result;
      this.lastVideoTime = this.video.currentTime;
    } else {
      // bitmap 直拉路径（MediaStreamTrackProcessor）：每帧都是新 VideoFrame，无 currentTime，
      // 用 ts 单调去重（detectForVideo 要求 timestamp 严格递增）。
      this.lastVideoTime = nowMs;
    }
    this._lastDetectMs = nowMs;

    if (this.poseLandmarker && nowMs - this._lastPoseMs >= this.cfg.poseThrottleMs) {
      try {
        const pr = this.poseLandmarker.detectForVideo(img, nowMs);
        if (pr && pr.worldLandmarks && pr.worldLandmarks.length) {
          this._poseCache = pr.worldLandmarks[0];
          if (pr.landmarks && pr.landmarks[0]) {
            this._poseVisCache = pr.landmarks[0].map((p) => (p.visibility != null ? p.visibility : 1));
          }
        }
      } catch (e) { this.lastError = 'pose detect 失败: ' + e.message; }
      this._lastPoseMs = nowMs;
    }
    const poseLandmarks = this._poseCache;
    const poseVis = this._poseVisCache;

    this._fpsCount++;
    if (nowMs - this._fpsTs >= 1000) {
      this.fps = Math.round((this._fpsCount * 1000) / (nowMs - this._fpsTs));
      this._fpsCount = 0;
      this._fpsTs = nowMs;
    }
    // 注：_rvfcFps（摄像头真实投帧率）不再在此处算——_rvfcCount 在 Worker 模式由 _startPumpWorker
    // 自增、主线程模式由 rVFC/track 循环自增，但本回调每结果触发一次、与 _rvfcCount 累加时序错位
    // 会导致除出来恒 0（2026-09-01 实测 worker 模式 rvfcFps 恒 0 假象）。统一改由 start() 内的
    // 1s 定时器从 _rvfcCount 计算（覆盖所有模式），见 _startRvfcMeter()。

    let res;
    const _t0 = performance.now();
    try {
      res = this.landmarker.detectForVideo(img, nowMs);
    } catch (e) {
      this.lastError = 'detect 失败: ' + e.message;
      return this.result;
    }
    this._inferMs = performance.now() - _t0;

    if (!res || !res.faceBlendshapes || res.faceBlendshapes.length === 0) {
      this.result = {
        detected: false, blendshapes: null, headMatrix: null, headEuler: null,
        pose: poseLandmarks, poseVis, landmarks: null, ts: nowMs,
        fps: this.fps, inferMs: this._inferMs, cam: this._cam(),
      };
      this._emit();
      return this.result;
    }

    // 首帧→首次真·检出的延迟（验证「模型加载完还卡 5~6s」是否消失）：preload 已 GPU 预热则≈0.2s
    if (!this._firstReported && this._startWall) {
      this._firstDetectSec = +((performance.now() - this._startWall) / 1000).toFixed(2);
      this._firstReported = true;
      console.log('[FaceTracker] 开面捕→首帧检出耗时 ' + this._firstDetectSec + 's');
    }
    return this._packAndEmit(res, nowMs);
  }

  /**
   * 结果打包 + 回调：VIDEO 同步路径与 LIVE_STREAM 异步回调路径共用，避免两条链逻辑漂移。
   * 含 blendshape 一阶平滑 → 头部矩阵解欧拉（增益/符号/限幅/平滑）→ 打包 result → _emit。
   */
  _packAndEmit(res, nowMs) {
    if (!res || !res.faceBlendshapes || res.faceBlendshapes.length === 0) {
      this.result = {
        detected: false, blendshapes: null, headMatrix: null, headEuler: null,
        pose: this._poseCache, poseVis: this._poseVisCache, landmarks: null, ts: nowMs,
        fps: this.fps, inferMs: this._inferMs, cam: this._cam(),
      };
      this._emit();
      return this.result;
    }

    const bs = {};
    const k = this.cfg.smoothing;
    for (const c of res.faceBlendshapes[0].categories) {
      const prev = this._bsSmooth.get(c.categoryName);
      const v = prev === undefined ? c.score : prev + (c.score - prev) * (1 - k);
      this._bsSmooth.set(c.categoryName, v);
      bs[c.categoryName] = v;
    }

    let headEuler = null;
    let headMatrix = null;
    const m = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0];
    if (m && m.data) {
      headMatrix = m.data;
      const e = matrixToEulerYXZ(m.data);
      if (e) {
        const { headGain: g, headSign: s, headLimitRad: lim } = this.cfg;
        const rE = {
          x: clamp(e.x * g.pitch * s.pitch, -lim.pitch, lim.pitch),
          y: clamp(e.y * g.yaw * s.yaw, -lim.yaw, lim.yaw),
          z: clamp(e.z * g.roll * s.roll, -lim.roll, lim.roll),
        };
        const ks = this.cfg.headSmoothing;
        if (!this._headSmooth) this._headSmooth = rE;
        else {
          this._headSmooth.x += (rE.x - this._headSmooth.x) * (1 - ks);
          this._headSmooth.y += (rE.y - this._headSmooth.y) * (1 - ks);
          this._headSmooth.z += (rE.z - this._headSmooth.z) * (1 - ks);
        }
        headEuler = { ...this._headSmooth };
      }
    }

    this.result = {
      detected: true, blendshapes: bs, headMatrix,
      headEuler, pose: this._poseCache, poseVis: this._poseVisCache,
      landmarks: res.faceLandmarks ? res.faceLandmarks[0] : null,
      ts: nowMs, fps: this.fps, inferMs: this._inferMs, cam: this._cam(),
    };
    this._emit();
    return this.result;
  }

  /**
   * LIVE_STREAM 异步结果回调（阶段二核心）：MediaPipe 内部推理完成后调用，与帧提交解耦。
   * detectForVideo 提交立即返回 → rVFC 循环继续接下一帧不漏；本回调按 MediaPipe 自身节奏
   * （31ms/帧 → ~32fps 模型硬上限）产出，busy 时 MediaPipe 自动丢帧保最新帧（低延迟）。
   */
  _onLiveResult(res, timestamp) {
    if (!this.running) return this.result;
    this._liveResultCount++;
    const nowMs = (typeof timestamp === 'number' && timestamp > 0) ? timestamp : performance.now();
    // 端到端延迟（提交→回调）≈ 单帧推理 + 排队；LIVE_STREAM 下测不到纯推理耗时，用此近似
    if (this._submitAt) {
      this._inferMs = Math.max(0, performance.now() - this._submitAt);
      this._submitAt = 0;
    }
    // fps 统计：回调频率 = 实际检测帧率
    this._fpsCount++;
    if (nowMs - this._fpsTs >= 1000) {
      this.fps = Math.round((this._fpsCount * 1000) / (nowMs - this._fpsTs));
      this._fpsCount = 0;
      this._fpsTs = nowMs;
    }
    try {
      return this._packAndEmit(res, nowMs);
    } catch (e) {
      this.lastError = 'LIVE_STREAM 结果处理失败: ' + e.message;
      return this.result;
    }
  }

  /** pose 独立降频检测：LIVE_STREAM 模式下不占 rVFC 帧回调，避免阻塞 face 帧提交 */
  _poseTick() {
    if (!this.running || !this.poseLandmarker || !this.video) return;
    if (this.video.readyState < 2) return;
    try {
      const pr = this.poseLandmarker.detectForVideo(this.video, performance.now());
      if (pr && pr.worldLandmarks && pr.worldLandmarks.length) {
        this._poseCache = pr.worldLandmarks[0];
        if (pr.landmarks && pr.landmarks[0]) {
          this._poseVisCache = pr.landmarks[0].map((p) => (p.visibility != null ? p.visibility : 1));
        }
      }
    } catch (e) { this.lastError = 'pose detect 失败: ' + e.message; }
  }

  /**
   * LIVE_STREAM 看门狗的止损动作：异步回调在本环境不产出结果时，重建 landmarker 为 VIDEO 同步模式。
   * 代价是 detect 回落 ~14fps，但保证「摄像头开了就一定有面捕」——绝不停在零数据状态。
   */
  async _fallbackToVideo() {
    if (!this._liveMode) return;
    console.warn('[FaceTracker] LIVE_STREAM 3s 内无结果回调，自动回退 VIDEO 同步模式');
    this._liveMode = false;
    this.lastError = 'LIVE_STREAM 回调未触发，已自动回退 VIDEO';
    if (this.landmarker) { try { this.landmarker.close(); } catch (e) {} this.landmarker = null; }
    try {
      const { FaceLandmarker } = this._MP || {};
      if (!FaceLandmarker || !this._fileset) throw new Error('MediaPipe 上下文缺失，无法重建');
      this.landmarker = await FaceLandmarker.createFromOptions(this._fileset, {
        baseOptions: { modelAssetPath: this.cfg.modelPath, delegate: this.cfg.delegate },
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,
        runningMode: 'VIDEO',
        numFaces: this.cfg.numFaces,
      });
      this.cfg.runningMode = 'VIDEO';
      this.lastVideoTime = -1;      // VIDEO 路径用 currentTime 去重，重置以立即出第一帧
      this._lastDetectMs = 0;
      this._startTs = performance.now();
      // pose 回到 VIDEO 内联逻辑（_updateMain 内按 poseThrottleMs 降频），撤掉独立 timer
      if (this._poseTimer) { clearInterval(this._poseTimer); this._poseTimer = null; }
      this.lastError = 'LIVE_STREAM 回调未触发，已回退 VIDEO（detect ~14）';
    } catch (e) {
      this.lastError = '回退 VIDEO 失败: ' + e.message;
    }
  }

  stop() {
    this.running = false;
    if (this._rvfcTimer) { clearInterval(this._rvfcTimer); this._rvfcTimer = null; }
    if (this._poseTimer) { clearInterval(this._poseTimer); this._poseTimer = null; }
    if (this.worker) { try { this.worker.terminate(); } catch (e) {} this.worker = null; }
    if (this._trackTimer) { clearTimeout(this._trackTimer); this._trackTimer = null; }
    if (this._trackReader) { try { this._trackReader.cancel(); } catch (e) {} this._trackReader = null; }
    if (this.stream) { this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
    if (this.video) { this.video.srcObject = null; }
    this._bsSmooth.clear();
    this._headSmooth = null;
    this.result = { detected: false, blendshapes: null, headMatrix: null, headEuler: null, landmarks: null, ts: 0 };
    console.log('[FaceTracker] 已停止');
  }

  /** 诊断：给自验与排障用 */
  getDiagnostics() {
    const bs = this.result.blendshapes;
    const sample = {};
    if (bs) for (const n of ['eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'mouthSmileLeft', 'browInnerUp']) sample[n] = +(bs[n] || 0).toFixed(3);
    return {
      running: this.running,
      delegate: this.cfg.delegate,
      useWorker: this._useWorker,
      // 阶段二排障字段：零数据时 DIAG 日志是唯一可观测通道（result 不生成 → PERF 字段全 0）
      runningMode: this.cfg.runningMode,
      liveMode: this._liveMode,
      liveResults: this._liveResultCount,
      rvfc: (typeof window !== 'undefined' && window.__rvfcActive) || false,
      useTrackReader: this._useTrackReader,   // 是否走 TrackProcessor 直拉（绕开 video 可见性节流→30fps）；false=回退 rVFC（隐藏页被节流）
      negotiatedFps: this._negotiatedFps,     // gUM 协商帧率
      lastVideoTime: this.lastVideoTime,
      fps: this.fps,
      inflight: this._inflight || 0,   // Worker 在途帧数（背压信号：持续==MAX_INFLIGHT 即队列堵）
      ageMax: this._ageMax || 0,      // 端到端延迟窗口峰值(ms)：持续数百ms=延迟播放
      ageAvg: this._ageAvg || 0,      // 端到端延迟窗口均值(ms)
      detected: this.result.detected,
      headEuler: this.result.headEuler
        ? { pitchDeg: +(this.result.headEuler.x * 57.2958).toFixed(1), yawDeg: +(this.result.headEuler.y * 57.2958).toFixed(1), rollDeg: +(this.result.headEuler.z * 57.2958).toFixed(1) }
        : null,
      sample,
      lastError: this.lastError,
      warmed: this._warmed,            // GPU shader 预热是否已完成（preload 后台编译）
      firstDetectSec: this._firstDetectSec,  // 开面捕→首帧真·检出延迟（秒），验证「卡 5~6s」是否消失
      gumMs: this._gumMs,              // getUserMedia 耗时（区分摄像头开慢 vs 首帧推理慢）
      rvfcFps: this._rvfcFps,          // rVFC 实际触发率=摄像头真实投帧率（定位 detect 15fps 真因）
      feedFps: this._feedFps,          // 主线程实际喂帧率（postMessage frame 频率）
      createMs: this._createMs,        // createImageBitmap 平均耗时
      workerErrs: this._workerErrs,    // Worker 启用失败原因链（onerror/超时/inited_FAIL/catch），定位 Qt WebEngine 是否支持 module worker
      workerLogs: this._workerLogs,    // Worker 内运行日志（诊断用）
      trackReaderErr: this._trackReaderErr,   // TrackProcessor 不可用/失败原因（真机直拉为何被限到 16fps）
    };
  }
}
