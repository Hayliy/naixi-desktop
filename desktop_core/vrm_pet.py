#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qt 桌宠 VRM 模式实验（Path A 实测）：QWebEngineView + three-vrm 渲染 VRM 模型。

- 透明置顶无边框壳，几何 WM_NCHITTEST 鼠标穿透（复用 pet_window 的穿透思路）。
- 本地起 ThreadingHTTPServer 给 webview 提供 index.html 与 VRM 模型，规避 file:// CORS。
- 后端 WS（ws://127.0.0.1:9845/api/live/live2d-stream）推送 speak(emotion, mouth)
  → 注入 webview 驱动 VRM 表情(预设) / 口型(aa morph)。
- 不依赖 live2d / Cubism，隔离于现有 Live2D 宠，互不干扰。

用法：
  python vrm_pet.py                 # 自动找 godot_renderer 下首个 .vrm，连后端
  python vrm_pet.py --no-ws         # 测试模式：不连后端，VRM 载入后自动播放 idle/spring
  python vrm_pet.py --vrm 路径.vrm  # 指定模型
"""
from __future__ import annotations

import sys
import os
import time
import json
import argparse
import threading
import logging
import ctypes

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
VRM_LOG = os.path.join(LOG_DIR, "pet_vrm.log")
HTML_PATH = os.path.join(HERE, "vrm_html", "index.html")


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(VRM_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 本地 HTTP 服务（提供 index.html + VRM 模型）──
class _VrmHttpHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path.startswith("/capture"):
            try:
                import re as _re, base64
                length = int(self.headers.get("Content-Length", 0))
                body = b""
                while len(body) < length:
                    chunk = self.rfile.read(min(65536, length - len(body)))
                    if not chunk:
                        break
                    body += chunk
                body = body.decode("utf-8", "ignore")
                m = _re.search(r"[?&]i=(\d+)", self.path)
                idx = int(m.group(1)) if m else 0
                capdir = os.path.join(LOG_DIR, "capture")
                os.makedirs(capdir, exist_ok=True)
                comma = body.find(",")
                b64 = body[comma + 1:] if comma >= 0 else body
                data = base64.b64decode(b64)
                with open(os.path.join(capdir, f"frame_{idx:03d}.png"), "wb") as f:
                    f.write(data)
                log(f"[CAPTURE] 保存帧 #{idx} ({len(data)} bytes)")
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception as e:
                log(f"[CAPTURE] 失败: {e}")
                try:
                    self.send_error(500, str(e))
                except Exception:
                    pass
        elif self.path.startswith("/metrics"):
            try:
                import re as _re, json as _json
                length = int(self.headers.get("Content-Length", 0))
                body = b""
                while len(body) < length:
                    chunk = self.rfile.read(min(65536, length - len(body)))
                    if not chunk:
                        break
                    body += chunk
                obj = _json.loads(body.decode("utf-8", "ignore"))
                m = _re.search(r"[?&]name=([^&]+)", self.path)
                raw = (m.group(1) if m else "default")
                name = _re.sub(r"[^A-Za-z0-9_.\-]", "_", raw)
                mdir = os.path.join(LOG_DIR, "metrics")
                os.makedirs(mdir, exist_ok=True)
                with open(os.path.join(mdir, f"metrics_{name}.jsonl"), "a", encoding="utf-8") as f:
                    f.write(_json.dumps(obj, ensure_ascii=False) + "\n")
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception as e:
                log(f"[METRICS] 失败: {e}")
                try:
                    self.send_error(500, str(e))
                except Exception:
                    pass
        else:
            self.send_error(404)

    def do_GET(self):
        srv = self.server
        path0 = self.path.split("?", 1)[0]   # 去掉 query string（?diag= 等）再做路由匹配
        if path0.startswith("/model"):
            self._serve(srv.vrm_path, "model/gltf-binary")
        elif path0.startswith("/motions/"):
            # 必须排在 "/motion" 之前！"/motions/xxx.vrma" 同样以 "/motion" 开头，
            # 若被下面的 /motion 前缀分支抢先匹配，就会返回 srv.motion_path
            # （= vrm_html/test.vrma，仅 3 条轨道：腕R.quaternion + happy + lookAt），
            # 表现为「身体完全不动、只有右臂在动」——曾据此误判为 three-vrm
            # 跨版本映射失败 / 解析 bug，排查数轮。勿再调整这两个分支的先后顺序。
            rel = path0[len("/motions/"):]
            if ".." in rel or rel.startswith("/") or not rel.endswith(".vrma"):
                self.send_error(404); return
            p = os.path.join(srv.html_dir, "motions", rel)
            if os.path.isfile(p):
                self._serve(p, "model/gltf-binary")
            else:
                self.send_error(404)
        elif path0.startswith("/motion"):
            self._serve(srv.motion_path, "model/gltf-binary")
        elif path0.startswith("/vendor/"):
            rel = path0[len("/vendor/"):]
            p = os.path.join(srv.html_dir, "vendor", rel)
            if os.path.isfile(p):
                self._serve(p, _guess_ctype(p))
            else:
                self.send_error(404)
        elif _is_safe_static(path0):
            # 根目录下的静态资源（face_tracker.js / arkit_to_vrm.js 等）
            p = os.path.join(srv.html_dir, path0.lstrip("/"))
            if os.path.isfile(p):
                self._serve(p, _guess_ctype(p))
            else:
                self.send_error(404)
        elif path0 in ("/", "/index.html"):
            try:
                with open(srv.html_path, "r", encoding="utf-8") as f:
                    data = (f.read()
                            .replace("__MODEL_URL__", srv.model_url)
                            .replace("__MOTION_URL__", srv.motion_url)
                            .replace("__DANCE__", "1" if getattr(srv, "dance", False) else "")
                            .replace("__LOOP_MOTION__", getattr(srv, "loop_motion", "") or "")
                            .replace("__FACE__", "1" if getattr(srv, "face", False) else ""))
                payload = data.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                self.send_error(500, str(e))
        else:
            self.send_error(404)

    def _serve(self, path: str, ctype: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, *args):
        pass


# 静态资源 MIME 白名单：WASM 必须是 application/wasm，否则 instantiateStreaming 会因 MIME 不符直接失败
_CTYPE_BY_EXT = {
    ".wasm": "application/wasm",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".task": "application/octet-stream",
    ".vrma": "model/gltf-binary",
    ".vrm": "model/gltf-binary",
    ".png": "image/png",
}


def _guess_ctype(path: str) -> str:
    return _CTYPE_BY_EXT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _is_safe_static(path0: str) -> bool:
    """只允许 html_dir 根目录下的白名单静态文件：禁止 .. 穿越、子目录与隐藏文件。
    index.html 刻意不在白名单内，避免绕过模板替换把未替换的 __MODEL_URL__ 直接吐出去。"""
    rel = (path0 or "").lstrip("/")
    if not rel or ".." in rel or "/" in rel or rel.startswith("."):
        return False
    return os.path.splitext(rel)[1].lower() in _CTYPE_BY_EXT


def start_http_server(vrm_path: str, port: int, motion_path: str = "", dance: bool = False, loop_motion: str = "", face: bool = False) -> int:
    """起本地 HTTP 服务，返回实际使用的端口（端口被占则顺序自增，避免旧进程静默服务旧内容）。"""
    html_dir = os.path.dirname(HTML_PATH)
    httpd = None
    actual = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), _VrmHttpHandler)
            actual = p
            break
        except OSError as e:
            log(f"[HTTP] 端口 {p} 不可用: {e}, 尝试下一个")
    if httpd is None:
        log(f"[HTTP] 端口 {port}~{port+9} 均不可用，退出。")
        sys.exit(1)
    httpd.vrm_path = vrm_path
    httpd.html_path = HTML_PATH
    httpd.html_dir = html_dir
    httpd.motion_path = motion_path
    httpd.dance = dance
    httpd.loop_motion = loop_motion
    httpd.face = face
    httpd.model_url = f"http://127.0.0.1:{actual}/model.vrm"
    httpd.motion_url = f"http://127.0.0.1:{actual}/motion"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log(f"[HTTP] serving vrm={os.path.basename(vrm_path)} on http://127.0.0.1:{actual}/ (请求端口 {port})")
    return actual


def build_html(model_url: str, motion_url: str = "", face: bool = False) -> str:
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        return (f.read()
                .replace("__MODEL_URL__", model_url)
                .replace("__MOTION_URL__", motion_url)
                .replace("__FACE__", "1" if face else ""))


# ── 情绪 → VRM 预设 映射（对齐 avatar_backends._EMOTION_TO_BLEND）──
_EMOTION_MAP = {
    "开心": "happy", "高兴": "happy", "喜": "happy", "笑": "happy",
    "生气": "angry", "愤怒": "angry",
    "伤心": "sad", "难过": "sad", "哭": "sad",
    "惊讶": "surprised", "惊": "surprised",
    "轻松": "relaxed", "调皮": "relaxed",
}


def map_emotion(emotion: str):
    if not emotion:
        return None
    for kw, preset in _EMOTION_MAP.items():
        if kw in emotion:
            return preset
    return None


# ── 面捕灵敏度配置（右键菜单「面捕灵敏度…」可调，运行时实时生效 + 持久化）──
# 各增益语义见 desktop_core/vrm_html/pose_to_vrm.js::POSE_DEFAULTS 与 index.html::applyFaceCapture。
# masterGain 为全局倍率，叠加在各项之上；smooth 统一映射到 FACE/HEAD/ARM 三个平滑 tau（越大越稳越「肉」）。
FACECAP_DEFAULTS = {
    "masterGain": 1.0,      # 总灵敏度（0.2~3.0）
    "torsoGain": 1.0,       # 躯干整体跟随
    "torsoPitchGain": 0.9,  # 前倾/后仰
    "torsoRollGain": 0.8,   # 侧倾
    "torsoYawGain": 0.8,    # 转身（左右转）
    "armGain": 1.0,         # 手臂
    "expressionGain": 1.0,  # 表情
    "headGain": 0.8,        # 头部
    "smooth": 0.13,         # 平滑（0.05~0.4）
}


# ── Qt 窗口 ──
def _start_ui(vrm_path: str, ws_url: str, port: int, no_ws: bool, selftest: bool = False, demo: bool = False, diag: int = 0, metrics: int = 0, loop_name: str = "", no_skirt: bool = False, verify: bool = False, kneedebug: bool = False, inject_js: str = ""):
    from PySide6.QtWidgets import QApplication, QWidget, QMenu
    from PySide6.QtCore import Qt, QPoint, QRect, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QCursor, QColor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

    # 真机默认用 ANGLE 硬件后端（D3D11），流畅；无头/无 GPU 自验用 NAIXI_SWIFTSHADER=1 切回软件渲染
    gl_backend = ["--use-gl=angle", "--use-angle=swiftshader"] if os.environ.get("NAIXI_SWIFTSHADER") else ["--use-gl=angle"]
    app = QApplication(sys.argv + [
        "--ignore-gpu-blocklist", "--enable-webgl",
        "--autoplay-policy=no-user-gesture-required",
    ] + gl_backend)


    class _VrmPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
            tag = {0: "INFO", 1: "WARN", 2: "ERR"}.get(level, "LOG")
            log(f"[JS:{tag}] {message}")
            # idle 动画加载完成后再启动 demo，避免页面未就绪时抢跑命令
            win = getattr(self, "win", None)
            if win is not None and getattr(win, "_demo", False) and not win._demo_started \
                    and "[VRM] ready" in message:
                win._demo_started = True
                win._start_demo_loop()

        def _grant_camera(self, permission):
            # Qt WebEngine 摄像头权限必须显式 grant，否则 getUserMedia 默认被拒（NotAllowedError）。
            try:
                from PySide6.QtWebEngineCore import QWebEnginePermission
                if permission.permissionType() == QWebEnginePermission.PermissionType.MediaVideoCapture:
                    permission.grant()
                    log("[VRM] 摄像头权限已授予（面捕可用）")
            except Exception as e:
                log(f"[VRM] 摄像头权限授予异常: {e}")

    class VrmPetWindow(QWidget):
        def __init__(self, selftest: bool = False, demo: bool = False, loop_name: str = "", inject_js: str = ""):
            super().__init__()
            self._vrm_path = vrm_path
            self._ws_url = ws_url
            self._no_ws = no_ws
            self._selftest = selftest
            self._demo = demo
            self._selftest_done = False
            self._demo_started = False
            # 自验注入：READY 后把整段 JS 丢进 webview 执行，脚本内的 console.log 会经
            # _on_js_console 落到日志 —— 这样「方向对不对」能无头自证，不必让用户在镜头前配合。
            self._inject_js = inject_js or ""
            self._inject_done = False
            self._queue = []
            self._qlock = threading.Lock()
            self._current_motion = (loop_name or "dance")
            self._paused = False
            self._vrm_face_on = False
            self._facecap_loaded = False

            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            geo = QGuiApplication.primaryScreen().availableGeometry()
            # 窗口尺寸自适应屏幕（availableGeometry 已扣任务栏/OS 栏）；显式用 geo.x()/geo.y()
            # 处理主屏偏移与多屏，确保窗口底部贴在可视区底、不被任务栏或 OS 裁掉（脚被裁的隐藏根因）。
            _sz = os.environ.get('NAIXI_VRM_SIZE', '')
            if _sz and 'x' in _sz:
                _sw, _sh = _sz.split('x', 1)
                w = max(320, int(_sw.strip()))
                h = max(320, int(_sh.strip()))
            else:
                w = min(720, max(360, geo.width() - 40))
                h = min(900, max(480, geo.height() - 40))
            self.resize(w, h)
            x = geo.x() + geo.width() - w - 20
            y = geo.y() + geo.height() - h - 20
            self.move(max(geo.x(), x), max(geo.y(), y))
            # 命中矩形（模型可拖/可右键区；其余穿透桌面）。VRM 取景偏中下，给个居中偏下矩形。
            self._hit_rect = QRect(self.width() // 4, int(self.height() * 0.15),
                                   self.width() // 2, int(self.height() * 0.75))

            self._view = QWebEngineView(self)
            self._view.setGeometry(0, 0, self.width(), self.height())
            self._view.setAttribute(Qt.WA_TranslucentBackground, True)
            # 接管右键：禁用 Chromium 默认英文菜单，改用中文自定义菜单
            self._view.setContextMenuPolicy(Qt.CustomContextMenu)
            self._view.customContextMenuRequested.connect(self._on_context_menu)
            page = _VrmPage(self)
            page.win = self
            self._view.setPage(page)
            # Qt WebEngine 摄像头权限：必须显式授予，否则 getUserMedia 会被默认拒绝。
            page.permissionRequested.connect(page._grant_camera)
            page.setBackgroundColor(QColor(0, 0, 0, 0))
            settings = page.settings()
            for _attr in ("WebGLEnabled", "Accelerated2DCanvasEnabled", "LocalStorageEnabled"):
                try:
                    settings.setAttribute(getattr(QWebEngineSettings, _attr), True)
                except Exception:
                    pass
            page.loadFinished.connect(lambda ok: log(f"[UI] page loadFinished ok={ok}"))

            qs = []
            if diag: qs.append(f"diag={diag}")
            if metrics: qs.append(f"metrics={metrics}")
            if loop_name: qs.append(f"loop={loop_name}")
            if no_skirt: qs.append("noskirt=1")
            if verify: qs.append("verify=1")
            if kneedebug: qs.append("kneedebug=1")
            qstr = ("?" + "&".join(qs)) if qs else ""
            self._view.setUrl(QUrl(f"http://127.0.0.1:{port}/index.html{qstr}"))
            log("[UI] QWebEngineView 已加载 VRM 页面，等待 three-vrm 初始化…")

            # 探针：每 3s 回报 webview 内 JS 全局状态（绕开 importmap 模块作用域不可外部探测的限制）
            self._probe = QTimer(self)
            self._probe.timeout.connect(self._probe_js)
            self._probe.start(3000)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._flush_queue)
            self._timer.start(50)

            if not self._no_ws:
                threading.Thread(target=self._ws_loop, daemon=True).start()
            else:
                log("[UI] 测试模式：不连后端，VRM 载入后自动 idle/spring")

        # ── JS 控制台桥 ──
        def _on_js_console(self, level, message, line, source):
            tag = {0: "INFO", 1: "WARN", 2: "ERR"}.get(level, "LOG")
            log(f"[JS:{tag}] {message}")

        def _enqueue_js(self, js: str):
            with self._qlock:
                self._queue.append(js)

        def _flush_queue(self):
            with self._qlock:
                items = self._queue
                self._queue = []
            for js in items:
                try:
                    self._view.page().runJavaScript(js)
                except Exception as e:
                    log(f"[UI] runJavaScript 失败: {e}")

        def _probe_js(self):
            try:
                self._view.page().runJavaScript(
                    "window.__vrmReady ? (window.__vrmReady() ? 'READY' : 'PAGE-LOADED') : 'JS-NOT-RUN'",
                    lambda r: self._on_probe(r),
                )
            except Exception as e:
                log(f"[PROBE] err {e}")

        def _on_probe(self, r):
            log(f"[PROBE] webview status = {r}")
            if r == "READY" and self._inject_js and not self._inject_done:
                self._inject_done = True
                self._enqueue_js(self._inject_js)
                log(f"[INJECT] 注入自验 JS（{len(self._inject_js)} 字符）")
            # 页面 READY 后加载灵敏度配置（用户上次在「面捕灵敏度…」里调的值），运行时注入生效
            if r == "READY" and not self._facecap_loaded:
                self._facecap_loaded = True
                self._apply_facecap(self._load_facecap_config(), persist=False)
                log("[FACECAP] 已加载灵敏度配置并注入页面")
            if r == "READY" and self._no_ws and self._selftest and not self._selftest_done:
                self._selftest_done = True
                self._enqueue_js("window.__vrmSetEmotion('happy')")
                log("[SELFTEST] 注入 emotion=happy")
                QTimer.singleShot(1200, self._selftest_check)

        def _selftest_check(self):
            self._view.page().runJavaScript(
                "window.__vrmGetExpr ? window.__vrmGetExpr() : null",
                lambda v: log(f"[SELFTEST] 表情读回 = {v}"),
            )
            self._enqueue_js("window.__vrmSetMouth(0.9)")
            QTimer.singleShot(400, lambda: self._view.page().runJavaScript(
                "window.__vrmGetMouth ? window.__vrmGetMouth() : null",
                lambda v: log(f"[SELFTEST] 口型读回 = {v}"),
            ))
            QTimer.singleShot(900, lambda: self._enqueue_js("window.__vrmSetMouth(0)"))

        # ── 面捕灵敏度配置：加载 / 保存 / 实时应用 / 设置对话框 ──
        def _facecap_config_path(self):
            return os.path.join(os.path.dirname(os.path.abspath(__file__)), "facecap_config.json")
    
        def _load_facecap_config(self):
            try:
                p = self._facecap_config_path()
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    out = dict(FACECAP_DEFAULTS)
                    out.update({k: v for k, v in d.items() if k in FACECAP_DEFAULTS})
                    return out
            except Exception as e:
                log(f"[FACECAP] 读配置失败: {e}")
            return dict(FACECAP_DEFAULTS)
    
        def _save_facecap_config(self, cfg):
            try:
                p = self._facecap_config_path()
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                log("[FACECAP] 灵敏度配置已保存")
            except Exception as e:
                log(f"[FACECAP] 保存失败: {e}")
    
        def _apply_facecap(self, cfg, persist=False):
            """把本地灵敏度配置翻译成页面 __vrmPoseConfig / __vrmFaceConfig 调用并注入。
            masterGain 为全局倍率，叠加在各项增益之上；smooth 统一映射到三个平滑 tau。"""
            m = float(cfg.get("masterGain", 1.0))
            pose_cfg = {
                "torsoGain": cfg["torsoGain"] * m,
                "torsoPitchGain": cfg["torsoPitchGain"] * m,
                "torsoRollGain": cfg["torsoRollGain"] * m,
                "torsoYawGain": cfg["torsoYawGain"] * m,
                "armGain": cfg["armGain"] * m,
                "faceSmooth": cfg["smooth"], "headTau": cfg["smooth"], "armTau": cfg["smooth"],
            }
            face_cfg = {
                "expressionGain": cfg["expressionGain"] * m,
                "headGain": {"x": cfg["headGain"] * m, "y": cfg["headGain"] * m, "z": cfg["headGain"] * m},
            }
            self._enqueue_js(f"window.__vrmPoseConfig({json.dumps(pose_cfg)})")
            self._enqueue_js(f"window.__vrmFaceConfig({json.dumps(face_cfg)})")
            if persist:
                self._save_facecap_config(cfg)
    
        def _open_sensitivity_dialog(self):
            from PySide6.QtWidgets import (QDialog, QFormLayout, QDoubleSpinBox,
                                           QPushButton, QHBoxLayout, QVBoxLayout, QLabel)
            cfg = self._load_facecap_config()
            dlg = QDialog(self)
            dlg.setWindowTitle("面捕灵敏度设置")
            dlg.setMinimumWidth(360)
            form = QFormLayout()
            spins = {}
            fields = [
                ("总灵敏度", "masterGain", 0.2, 3.0, 0.05),
                ("躯干跟随", "torsoGain", 0.0, 2.0, 0.05),
                ("前倾灵敏度", "torsoPitchGain", 0.0, 2.0, 0.05),
                ("侧倾灵敏度", "torsoRollGain", 0.0, 2.0, 0.05),
                ("转身灵敏度", "torsoYawGain", 0.0, 2.0, 0.05),
                ("手臂灵敏度", "armGain", 0.0, 2.0, 0.05),
                ("表情灵敏度", "expressionGain", 0.0, 2.0, 0.05),
                ("头部灵敏度", "headGain", 0.0, 2.0, 0.05),
                ("平滑（越大越稳）", "smooth", 0.05, 0.4, 0.01),
            ]
    
            def collect():
                cur = dict(FACECAP_DEFAULTS)
                for k, sb in spins.items():
                    cur[k] = sb.value()
                return cur
    
            def live_apply():
                self._apply_facecap(collect(), persist=False)
    
            for label, key, lo, hi, step in fields:
                sb = QDoubleSpinBox()
                sb.setRange(lo, hi)
                sb.setSingleStep(step)
                sb.setDecimals(2)
                sb.setValue(float(cfg.get(key, FACECAP_DEFAULTS[key])))
                sb.valueChanged.connect(lambda *_: live_apply())
                spins[key] = sb
                form.addRow(label, sb)
            tip = QLabel("拖动即时预览；点「保存并关闭」永久生效，点「恢复默认」还原出厂值。")
            tip.setWordWrap(True)
            btn_save = QPushButton("保存并关闭")
            btn_reset = QPushButton("恢复默认")
            btn_cancel = QPushButton("取消")
            row = QHBoxLayout()
            row.addWidget(btn_save); row.addWidget(btn_reset); row.addWidget(btn_cancel)
            vbox = QVBoxLayout()
            vbox.addLayout(form); vbox.addLayout(row); vbox.addWidget(tip)
            dlg.setLayout(vbox)
    
            def on_save():
                self._apply_facecap(collect(), persist=True)
                dlg.accept()
            def on_reset():
                for k, sb in spins.items():
                    sb.setValue(FACECAP_DEFAULTS[k])
                self._apply_facecap(collect(), persist=True)
                dlg.accept()
            btn_save.clicked.connect(on_save)
            btn_reset.clicked.connect(on_reset)
            btn_cancel.clicked.connect(dlg.reject)
            dlg.exec()

        def _run_js(self, js: str):
            try:
                self._view.page().runJavaScript(js)
            except Exception as e:
                log(f"[UI] 右键菜单执行 JS 失败: {e}")

        def _toggle_pause(self):
            """暂停/继续当前动作：停止时记录当前动作，继续时恢复原动作。"""
            if getattr(self, "_paused", False):
                name = getattr(self, "_current_motion", "dance")
                if name == "dance":
                    self._run_js("window.__vrmStartDance && window.__vrmStartDance()")
                else:
                    self._run_js(f"window.__vrmLoop && window.__vrmLoop('{name}')")
                self._paused = False
                log("[MENU] 继续动画")
            else:
                self._run_js("window.__vrmStopMotion && window.__vrmStopMotion()")
                self._paused = True
                log("[MENU] 暂停动画")

        def _on_context_menu(self, pos):
            """中文右键菜单：切换动作 / 暂停继续 / 重新加载 / 退出。"""
            menu = QMenu(self)
            motion_menu = menu.addMenu("切换动作")
            # (中文显示, JS 动作名)；dance 走合集，其余走无限循环
            motions = [
                ("舞蹈合集", "dance"),
                ("深蹲", "Squat"),
                ("跳跃", "Jump"),
                ("拍手", "Clapping"),
                ("旋转", "Spin"),
                ("全身展示", "ShowFullBody"),
                ("射击", "Shoot"),
                ("比心", "PeaceSign"),
                ("问候", "Greeting"),
                ("生气", "Angry"),
                ("惊讶", "Surprised"),
                ("摆拍", "ModelPose"),
                ("困倦", "Sleepy"),
                ("思考", "Thinking"),
                ("环顾", "LookAround"),
                ("放松", "Relax"),
                ("再见", "Goodbye"),
                ("悲伤", "Sad"),
                ("脸红", "Blush"),
                ("动作捕捉", "sample-mocopi"),
            ]
            for label, name in motions:
                act = motion_menu.addAction(label)
                act.setData(name)
            pause_label = "继续" if getattr(self, "_paused", False) else "暂停"
            pause_act = menu.addAction(pause_label)
            # 摄像头面捕（3D）：运行时开关；开启后由摄像头驱动表情与头部位移
            face_act = menu.addAction("摄像头面捕")
            face_act.setCheckable(True)
            face_act.setChecked(getattr(self, "_vrm_face_on", False))
            menu.addSeparator()
            reload_act = menu.addAction("重新加载")
            quit_act = menu.addAction("退出桌宠")
            action = menu.exec(self._view.mapToGlobal(pos))
            if action is None:
                return
            if action is pause_act:
                self._toggle_pause()
            elif action is face_act:
                if getattr(self, "_vrm_face_on", False):
                    self._run_js("window.__vrmFaceStop && window.__vrmFaceStop()")
                    self._vrm_face_on = False
                    log("[MENU] 摄像头面捕 关闭")
                else:
                    self._run_js("window.__vrmFaceStart && window.__vrmFaceStart()")
                    self._vrm_face_on = True
                    log("[MENU] 摄像头面捕 开启")
            elif action is reload_act:
                self._view.reload()
            elif action is quit_act:
                QApplication.instance().quit()
            else:
                name = action.data()
                if name == "dance":
                    self._run_js("window.__vrmStartDance && window.__vrmStartDance()")
                else:
                    self._run_js(f"window.__vrmLoop && window.__vrmLoop('{name}')")
                self._current_motion = name
                self._paused = False
                log(f"[MENU] 切换动作 -> {name}")

        def _start_demo_loop(self):
            """演示：表情每 2.6s 轮播 + 口型正弦起伏，肉眼可见 3D 形象在动。"""
            import math
            self._demo_emotions = ["happy", "angry", "sad", "surprised", "relaxed"]
            self._demo_idx = 0
            self._demo_timer = QTimer(self)
            self._demo_timer.setInterval(2600)

            def _tick():
                e = self._demo_emotions[self._demo_idx % len(self._demo_emotions)]
                self._demo_idx += 1
                self._enqueue_js(f"window.__vrmSetEmotion('{e}')")
                log(f"[DEMO] 表情轮播 -> {e}")
            self._demo_timer.timeout.connect(_tick)
            self._demo_timer.start()

            self._mouth_t = 0.0
            self._mouth_timer = QTimer(self)
            self._mouth_timer.setInterval(110)

            def _mtick():
                self._mouth_t += 0.18
                m = max(0.0, 0.35 * math.sin(self._mouth_t * 2.4) + 0.18)
                self._enqueue_js(f"window.__vrmSetMouth({m:.2f})")
            self._mouth_timer.timeout.connect(_mtick)
            self._mouth_timer.start()

            self._demo_motions = ["wave", "nod", "shake", "bow", "jump", "dance"]
            self._motion_idx = 0
            self._motion_timer = QTimer(self)
            self._motion_timer.setInterval(4200)

            def _motion_demo_tick():
                m = self._demo_motions[self._motion_idx % len(self._demo_motions)]
                self._motion_idx += 1
                self._enqueue_js(f"window.__vrmPlayMotion('{m}')")
                log(f"[DEMO] 动作轮播 -> {m}")
            self._motion_timer.timeout.connect(_motion_demo_tick)
            self._motion_timer.start()
            log("[DEMO] 已启动表情轮播 + 口型起伏 + 动作轮播演示")

        # ── 后端 WS：speak(emotion, mouth) → VRM ──
        def _ws_loop(self):
            try:
                import websocket
            except Exception as e:
                log(f"[WS] websocket 模块不可用，转测试模式: {e}")
                return
            while True:
                try:
                    ws = websocket.create_connection(self._ws_url, timeout=5)
                    ws.settimeout(300)
                    log(f"[WS] 已连接 {self._ws_url}")
                    while True:
                        raw = ws.recv()
                        if not raw:
                            break
                        d = json.loads(raw)
                        if d.get("type") == "motion":
                            mname = d.get("name") or d.get("motion") or ""
                            if mname:
                                self._enqueue_js(f"window.__vrmPlayMotion('{mname}')")
                            continue
                        if d.get("type") != "speak":
                            continue
                        emotion = d.get("emotion", "")
                        preset = map_emotion(emotion)
                        if preset:
                            self._enqueue_js(f"window.__vrmSetEmotion('{preset}')")
                            # 情绪表情 3s 后复位（对齐 VmcBackend 行为）
                            threading.Timer(3.0, lambda: self._enqueue_js("window.__vrmResetExpr()")).start()
                        mouth = d.get("mouth") or []
                        frame_ms = d.get("frame_ms", 80)
                        if mouth:
                            def _play(seq, fms):
                                for v in seq:
                                    try:
                                        v = float(v)
                                    except Exception:
                                        v = 0.0
                                    self._enqueue_js(f"window.__vrmSetMouth({v})")
                                    time.sleep(max(0.01, fms / 1000.0))
                                self._enqueue_js("window.__vrmSetMouth(0)")
                            threading.Thread(target=_play, args=(mouth, frame_ms), daemon=True).start()
                except Exception as e:
                    log(f"[WS] 断开/错误: {e}")
                    time.sleep(3)

        # ── 鼠标穿透（几何 WM_NCHITTEST，不依赖 GL 读像素）──
        def _nchittest_result(self, x: int, y: int) -> int:
            hr = getattr(self, "_hit_rect", None)
            if hr is None or hr.contains(x, y):
                return 1     # HTCLIENT：可拖/可右键
            return -1        # HTTRANSPARENT：穿透桌面

        def nativeEvent(self, eventType, message):
            try:
                et = eventType if isinstance(eventType, str) else bytes(eventType)
                if et in (b"windows_generic_MSG", "windows_generic_MSG"):
                    if not message:
                        return super().nativeEvent(eventType, message)
                    import ctypes as _ct
                    addr = message.__int__() if hasattr(message, "__int__") else int(message)
                    if not addr:
                        return super().nativeEvent(eventType, message)
                    _arr = _ct.cast(addr, _ct.POINTER(_ct.c_uint))
                    if _arr[2] == 0x84:  # WM_NCHITTEST
                        lp = self.mapFromGlobal(QCursor.pos())
                        return self._nchittest_result(lp.x(), lp.y()), True
            except Exception:
                pass
            return super().nativeEvent(eventType, message)

        # ── 右击菜单（手动测试表情/口型，无需后端）──
        def contextMenuEvent(self, event):
            menu = QMenu(self)
            for label, preset in [("开心", "happy"), ("生气", "angry"),
                                  ("伤心", "sad"), ("惊讶", "surprised"),
                                  ("轻松", "relaxed")]:
                menu.addAction(label, lambda p=preset: self._enqueue_js(f"window.__vrmSetEmotion('{p}')"))
            actMenu = menu.addMenu("动作")
            for label, mname in [("挥手", "wave"), ("点头", "nod"), ("摇头", "shake"),
                                 ("鞠躬", "bow"), ("跳跃", "jump"), ("跳舞", "dance")]:
                actMenu.addAction(label, lambda m=mname: self._enqueue_js(f"window.__vrmPlayMotion('{m}')"))
            actMenu.addSeparator()
            actMenu.addAction("停止动作", lambda: self._enqueue_js("window.__vrmStopMotion()"))
            menu.addSeparator()
            menu.addAction("张嘴测试", lambda: (self._enqueue_js("window.__vrmSetMouth(1)"),
                                                   threading.Timer(0.5, lambda: self._enqueue_js("window.__vrmSetMouth(0)")).start()))
            menu.addAction("复位表情", lambda: self._enqueue_js("window.__vrmResetExpr()"))
            menu.addAction("重置面捕原点", lambda: self._enqueue_js("window.__vrmRecenter()"))
            menu.addAction("面捕灵敏度…", self._open_sensitivity_dialog)
            menu.addSeparator()
            menu.addAction("退出桌宠", self.close)
            menu.exec(event.globalPos())

    win = VrmPetWindow(selftest, demo,  loop_name, inject_js)
    win.show()
    # 缓解 Windows 分层透明窗口（QWebEngineView 嵌在透明 QWidget 内）的子控件合成闪烁：
    # 启用 WS_EX_COMPOSITED，让 DWM 对整个窗口树做双缓冲合成，避免动作重绘时出现整窗瞬闪。
    try:
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_COMPOSITED = 0x02000000
        hwnd = int(win.winId())
        cur = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if cur != 0:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, cur | WS_EX_COMPOSITED)
            log("[WIN] 已启用 WS_EX_COMPOSITED（DWM 双缓冲，缓解透明合成闪烁）")
        else:
            log("[WIN] 获取窗口扩展样式失败，跳过 WS_EX_COMPOSITED")
    except Exception as e:
        log(f"[WIN] WS_EX_COMPOSITED 设置失败（非致命）: {e}")
    log("[UI] 窗口已 show()，进入事件循环")
    app.exec()


def _find_default_vrm() -> str:
    # 优先 godot_renderer 下首个 .vrm
    cand = []
    for base in (os.path.join(ROOT, "godot_renderer"), ROOT):
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if fn.lower().endswith(".vrm"):
                    cand.append(os.path.join(root, fn))
        if cand:
            break
    return cand[0] if cand else ""


def main():
    ap = argparse.ArgumentParser(description="Qt 桌宠 VRM 模式（Path A 实测）")
    ap.add_argument("--vrm", default="", help="VRM 模型路径（默认自动找 godot_renderer 下首个 .vrm）")
    ap.add_argument("--ws", default="ws://127.0.0.1:9845/api/live/live2d-stream", help="后端 WS 地址")
    ap.add_argument("--port", type=int, default=9876, help="本地 HTTP 服务端口")
    ap.add_argument("--no-ws", action="store_true", help="测试模式：不连后端")
    ap.add_argument("--selftest", action="store_true", help="自检：就绪后注入表情/口型并读回验证")
    ap.add_argument("--demo", action="store_true", help="演示：持续表情轮播 + 口型起伏")
    ap.add_argument("--dance", action="store_true", help="动作演示：循环播放真实 VRMA 动作库（Spin/Jump/Shoot 等）")
    ap.add_argument("--loop", default="", help="连续循环播放单一动作（如 fullbody-show），验证全身骨骼参与（去根位移原地循环）")
    ap.add_argument("--diag", type=int, default=0, help="诊断：加载后每 0.5s 截图 N 帧 POST 回后端存盘（肉眼核对动作）")
    ap.add_argument("--metrics", type=int, default=0, help="数值指标探针：每 0.2s 采手臂抬起角+各部位世界Y位移 N 次 POST 回后端 jsonl（可读数字自证，不靠看 PNG）")
    ap.add_argument("--noskirt", action="store_true", help="隐藏裙摆类网格（本模型腿部被多层裙摆遮住，肉眼看不到腿在动；开此开关露出腿部便于核对）")
    ap.add_argument("--verify", action="store_true", help="修复验证：循环动作中采样蒙皮变形骨/网格最低点世界Y振幅，证明腿真的在动（写 [VERIFY] 日志）")
    ap.add_argument("--kneedebug", action="store_true", help="膝盖关节诊断：输出 normalized/raw/deform 三链的局部关节角，排除根运动干扰")
    ap.add_argument("--inject", default="", help="自验：READY 后把该 JS 文件整段注入 webview 执行（脚本内 console.log 会落到本进程日志，用于无头端到端断言，不依赖摄像头与用户在场）")
    ap.add_argument("--face", action="store_true", help="面捕：摄像头驱动表情与头部姿态（身体仍走 VRMA 动作轨），资源已本地 vendored，运行时零外网请求")
    args = ap.parse_args()

    vrm_path = args.vrm or _find_default_vrm()
    if not vrm_path or not os.path.isfile(vrm_path):
        log(f"[启动] 未找到 VRM 模型（{vrm_path}），退出。可用 --vrm 指定。")
        return
    log(f"[启动] VRM 模型: {vrm_path}")

    motion_path = os.path.join(HERE, "vrm_html", "test.vrma")
    actual_port = start_http_server(vrm_path, args.port, motion_path, args.dance, args.loop, args.face)
    # --inject：读 JS 文件，READY 后整段注入 webview（自验闭环用）
    inject_js = ""
    if getattr(args, "inject", ""):
        try:
            with open(args.inject, "r", encoding="utf-8") as f:
                inject_js = f.read()
            log(f"[启动] 自验注入脚本: {args.inject}（{len(inject_js)} 字符）")
        except Exception as e:
            log(f"[启动] 读取注入脚本失败: {e}")
    _start_ui(vrm_path, args.ws, actual_port, args.no_ws, args.selftest, args.demo, args.diag, args.metrics, args.loop, getattr(args, "noskirt", False), getattr(args, "verify", False), getattr(args, "kneedebug", False), inject_js)


if __name__ == "__main__":
    main()
