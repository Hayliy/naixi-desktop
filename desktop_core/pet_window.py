"""桌宠窗口 — PySide6 + live2d.v3 透明置顶 Live2D 渲染

参考: yuuki-desktop (github.com/Rinisnotarobot/yuuki-desktop)
- QOpenGLWidget 直接当窗口，无外层包裹
- initializeGL 同步构造模型，paintGL 全权渲染
"""
import os, sys, json, logging, threading, time, queue
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_OPENGL", "angle")

from OpenGL.GL import glViewport
from PySide6.QtCore import Qt, QPoint, QTimerEvent, QTimer, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QMouseEvent, QSurfaceFormat, QPainter, QColor, QFont, QPainterPath, QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMenu, QFileDialog, QWidget, QLineEdit, QLabel

from desktop_core.motion_engine import PoseEngine
from desktop_core.bone_rig import create_default_skeleton, create_default_animator

from live2d import v3 as live2d

log = logging.getLogger("pet_window")

# 模型目录：桌面端 data/models/ 为主，VTube Studio 为可选来源
_DESKTOP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_MODELS = os.path.join(_DESKTOP_ROOT, "data", "models")
VTS_MODELS = r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels"

SEARCH_ROOTS = [DATA_MODELS]
# VTube Studio 存在时才加入扫描
if os.path.exists(VTS_MODELS):
    SEARCH_ROOTS.append(VTS_MODELS)


class BubbleWindow(QWidget):
    """语言气泡 — 圆角矩形+小尾巴（参照 yuuki-desktop 实现）"""

    BG_COLOR = QColor(180, 160, 220, 230)
    TEXT_COLOR = QColor(50, 30, 70)
    BORDER_COLOR = QColor(150, 130, 200, 200)
    RADIUS = 18
    PADDING = 16
    MAX_WIDTH = 360
    DISPLAY_MS = 6000
    TAIL_SIZE = 12

    def __init__(self, pet: QWidget):
        super().__init__(None)
        self._pet = pet
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._label.setFont(QFont("Microsoft YaHei", 11))
        self._label.setStyleSheet(f"color: {self.TEXT_COLOR.name()}; background: transparent;")
        self._label.setMaximumWidth(self.MAX_WIDTH - 2 * self.PADDING)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._fade_anim: Optional[QPropertyAnimation] = None
        self.hide()

    def show_text(self, text: str, duration: int = 0):
        if duration == 0:
            duration = self.DISPLAY_MS
        self._hide_timer.stop()
        if self._fade_anim and self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()
        self.setWindowOpacity(1.0)
        self._label.setText(text)
        self._label.adjustSize()
        lw, lh = self._label.width(), self._label.height()
        bw, bh = lw + 2 * self.PADDING, lh + 2 * self.PADDING + self.TAIL_SIZE
        self.setFixedSize(bw, bh)
        self._label.move(self.PADDING, self.PADDING)
        self._reposition()
        self.show()
        self.raise_()
        self._hide_timer.start(duration)

    def _reposition(self):
        if self._pet is None:
            return
        pp = self._pet.pos()
        x = pp.x() + 20
        y = pp.y() - self.height() + 30
        if y < 0:
            y = pp.y() + 20
        self.move(x, y)

    def _fade_out(self):
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(500)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        body_h = h - self.TAIL_SIZE
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, body_h, self.RADIUS, self.RADIUS)
        tail_x = w - 50
        tail = QPainterPath()
        tail.moveTo(tail_x, body_h)
        tail.lineTo(tail_x + self.TAIL_SIZE, h)
        tail.lineTo(tail_x + 2 * self.TAIL_SIZE, body_h)
        tail.closeSubpath()
        path = path.united(tail)
        p.setPen(self.BORDER_COLOR)
        p.setBrush(self.BG_COLOR)
        p.drawPath(path)
        p.end()


def find_model3() -> list[dict]:
    models = []
    seen = set()
    for base in SEARCH_ROOTS:
        if not os.path.exists(base):
            continue
        for entry in os.listdir(base):
            d = os.path.join(base, entry)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.endswith(".model3.json") and f not in seen:
                    seen.add(f)
                    models.append({"name": entry, "modelFile": f, "path": os.path.join(d, f)})
                    break
    return models


class PetWindow(QOpenGLWidget):
    """桌宠窗口 — QOpenGLWidget 本身就是窗口"""

    def __init__(self, model_path: str = ""):
        super().__init__()
        self.model: Optional[live2d.LAppModel] = None
        self._mouth_target = 0.0
        self._mouth_current = 0.0
        self._model_path = model_path or ""
        self._drag_offset = QPoint()
        self._dragging = False
        # 表情/动作映射
        self._expression_map: dict[str, str] = {}
        self._motion_groups: dict[str, int] = {}
        self._idle_motion_groups: list[str] = []
        self._idle_interval = 15.0
        self._last_idle_ts = 0.0
        self._pose = PoseEngine(None)
        self._skeleton = create_default_skeleton()
        self._animator = create_default_animator(self._skeleton)
        self._capture_mode = False  # 直播捕获模式（不透明背景）

        # 语言气泡
        self._bubble = BubbleWindow(self)
        self._ws_queue = queue.Queue()
        # 测试对话输入（默认隐藏，右键菜单打开）
        self._chat_input = QLineEdit(self)
        self._chat_input.setPlaceholderText("输入测试消息，回车发送...")
        self._chat_input.setStyleSheet("background: rgba(40,30,60,200); color: #fff; border: 1px solid #5c4080; border-radius: 6px; padding: 4px 8px; font-size: 12px;")
        self._chat_input.setGeometry(4, self.height()-28, self.width()-8, 24)
        self._chat_input.hide()
        self._chat_input.returnPressed.connect(self._send_chat)
        self._ws_lock = threading.Lock()
        self._ws_instance = None

        # 窗口属性：无边框 + 置顶 + 工具窗口 + 透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.resize(400, 500)

        # 右下角定位
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 420, screen.height() - 520)

        # 如果没有指定模型，自动找第一个
        if not self._model_path or not os.path.exists(self._model_path):
            models = find_model3()
            if models:
                self._model_path = models[0]["path"]

        # 启动 WS 口型接收
        self._running = True
        threading.Thread(target=self._ws_loop, daemon=True).start()

    # ── OpenGL ──

    def initializeGL(self):
        live2d.glInit()
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        with open(r"D:\pet_init.log", "a") as f:
            f.write(f"{time.time():.0f} initializeGL _model_path={self._model_path!r}\n")
        if self._model_path and os.path.exists(self._model_path):
            try:
                self.model = live2d.LAppModel()
                self.model.LoadModelJson(self._model_path)
                self.model.Resize(self.width(), self.height())
                self.model.SetAutoBreathEnable(True)
                self.model.SetAutoBlinkEnable(True)
                self.model.StartRandomMotion("Idle", 3)
                self._init_expression_map()
                if self._pose is None or self._pose.model is None:
                    self._pose = PoseEngine(self.model)
                else:
                    self._pose.model = self.model
                self._pose.scan_model()
                # 生成动作文件并注册
                try:
                    motion_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_motions")
                    os.makedirs(motion_dir, exist_ok=True)
                    motion_files = self._pose.generate_motion_files(motion_dir)
                    for pose_name, fpath in motion_files.items():
                        if "_loop" in pose_name:
                            group = "Idle"
                        else:
                            group = "Pose"
                        self.model.LoadExtraMotion(group, 0, fpath)
                    # 更新 _motion_groups
                    real_motions = self.model.GetMotionGroups()
                    self._motion_groups = real_motions if real_motions else {}
                    self._idle_motion_groups = [g for g in self._motion_groups if g == "Idle"]  # 优先用 Idle
                    log.info(f"生成动作: {len(motion_files)} 个")
                except Exception as e:
                    log.warning(f"生成动作失败: {e}")
                # 初始化手动眨眼
                self._eye_state = 'open'
                self._next_blink_ts = time.time() + __import__('random').uniform(3, 6)
                if hasattr(self._pose, '_available'):
                    log.info(f"可用参数数: {len(self._pose._available)} 参数={list(self._pose._available)[:15]}")
                log.info(f"模型加载成功: {self._model_path}")
            # 动作→骨骼动画
            from desktop_core.bone_rig import create_default_animator
            self._animator = create_default_animator(self._skeleton)
            except Exception as e:
                log.warning(f"模型加载失败: {e}")
        self.startTimer(16)

    def _init_expression_map(self):
        """初始化表情映射：读取模型所有表情，自动匹配情绪"""
        if not self.model:
            return
        try:
            ids = self.model.GetExpressionIds()
            self._expression_map = {}
            for eid in ids:
                # 去掉扩展名和数字前缀，得到纯中文名
                name = eid.replace(".exp3.json", "").lstrip("0123456789")
                self._expression_map[eid] = name
            # 动作组
            motions = self.model.GetMotionGroups()
            self._motion_groups = motions if motions else {}
            self._idle_motion_groups = [g for g in self._motion_groups if g != "Idle"] or list(self._motion_groups.keys())
            log.info(f"表情({len(ids)}个): {list(self._expression_map.values())}")
            log.info(f"动作组: {self._motion_groups}")
        except Exception as e:
            log.warning(f"表情/动作加载失败: {e}")

    def _resolve_expression(self, emotion: str) -> str:
        """把情绪名匹配到模型的表情ID。优先精确匹配，再尝试包含匹配"""
        if not self.model or not emotion:
            return ""
        expr_name = emotion.strip()
        # 精确匹配：情绪名 == 表情名
        for eid, ename in self._expression_map.items():
            if ename == expr_name:
                return eid
        # 包含匹配：情绪名在表情名中
        for eid, ename in self._expression_map.items():
            if expr_name in ename or ename in expr_name:
                return eid
        return ""

    def resizeGL(self, w: int, h: int):
        if self.model:
            self.model.Resize(w, h)

    def _toggle_capture(self):
        """切换直播捕获模式：透明 ↔ 可捕获（去掉 Qt.Tool 标志）"""
        self._capture_mode = not self._capture_mode
        if self._capture_mode:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.show()
        log.info(f"[桌宠] 捕获模式: {'开启' if self._capture_mode else '关闭'}")

    def paintGL(self):
        now = time.time()
        dt = now - getattr(self, '_last_frame_ts', now)
        self._last_frame_ts = now
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        self._process_ws_queue()
        if not self.model:
            return
        # 骨骼动画更新
        self._skeleton.update(0.12)
        # 口型平滑（在 Update 前设，会被物理覆盖，需要放到 Update 后）
        if abs(self._mouth_target - self._mouth_current) > 0.01:
            self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
        # 先让模型算好呼吸/眨眼/物理
        self.model.Update()
        # 再叠加上我们的 Pose 参数（必须在 Update 之后，否则被覆盖）
        self._pose.update(dt)
        if abs(self._mouth_current) > 0.01:
            self.model.SetParameterValue("ParamMouthOpenY", self._mouth_current, 1.0)
            self.model.SetParameterValue("ParamMouthForm", self._mouth_current, 1.0)
        self.model.Draw()

    def timerEvent(self, event: QTimerEvent):
        self.update()
        if not self.model:
            return
        now = time.time()
        # 手动眨眼 — VTS 模型未注册眨眼参数，SetAutoBlinkEnable 不生效
        if getattr(self, '_eye_state', 'open') == 'closed' and now > getattr(self, '_eye_open_ts', 0):
            for eye in ("ParamEyeLOpen", "ParamEyeROpen"):
                self.model.SetParameterValue(eye, 1.0, 1.0)
            self._eye_state = 'open'
        elif getattr(self, '_eye_state', 'open') == 'open' and now > getattr(self, '_next_blink_ts', 0):
            for eye in ("ParamEyeLOpen", "ParamEyeROpen"):
                self.model.SetParameterValue(eye, 0.0, 1.0)
            self._eye_state = 'closed'
            self._eye_open_ts = now + 0.1  # 闭眼 100ms
            self._next_blink_ts = now + __import__('random').uniform(3, 6)
        # 空闲动作循环（每 15-30 秒随机）
        now = time.time()
        if now - getattr(self, '_last_idle_ts', 0) < self._idle_interval:
            return
        self._last_idle_ts = now
        self._idle_interval = __import__('random').uniform(12, 28)
        # 优先用模型自带动作组
        if self._idle_motion_groups:
            import random as _r
            g = _r.choice(self._idle_motion_groups)
            idx = _r.randint(0, self._motion_groups.get(g, 1) - 1)
            self.model.StartMotion(g, idx, 1)
        else:
            # 无动作组时用 Pose 引擎做微动
            import random as _r
            idle_poses = ["tilt", "nod", "smile"]
            self._pose.play_action(_r.choice(idle_poses))

    # ── 鼠标 ──

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def moveEvent(self, e):
        """窗口移动时同步更新气泡位置"""
        super().moveEvent(e)
        if hasattr(self, '_bubble'):
            self._bubble._reposition()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(e)

    # ── 右键菜单 ──

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("测试对话", lambda: self._chat_input.show() or self._chat_input.setFocus())
        menu.addSeparator()
        cap_label = "关闭捕获模式" if self._capture_mode else "直播捕获模式"
        menu.addAction(cap_label, self._toggle_capture)
        menu.addSeparator()
        models = find_model3()
        if models:
            sub = menu.addMenu("切换模型")
            for m in models:
                a = sub.addAction(m["name"])
                a.triggered.connect(lambda checked, p=m["path"]: self._reload_model(p))
        menu.addAction("导入模型文件...", self._import_model)
        menu.addSeparator()
        menu.addAction("管理模型", self._show_models)
        menu.addSeparator()
        menu.addAction("退出", QApplication.quit)
        menu.exec(event.globalPos())

    def _on_chat_response(self, emotion: str, reply: str):
        self._bubble.show_text(f"[{emotion}] {reply}", 4000)

    DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_debug.log")

    @classmethod
    def _log(cls, msg):
        import time
        try:
            with open(cls.DEBUG_LOG, "a") as f:
                f.write(f"{time.time():.0f} {msg}\n")
        except:
            pass

    def _send_chat(self):
        text = self._chat_input.text().strip()
        if not text:
            return
        self._chat_input.clear()
        self._chat_input.hide()
        ws = getattr(self, "_ws", None)
        import time as _t
        try:
            with open(type(self).DEBUG_LOG, "a") as f:
                f.write(f"{_t.time():.0f} _send_chat: ws={'OK' if ws else 'NONE'} text={text[:20]}\n")
        except:
            pass
        if not ws:
            self._bubble.show_text("等待连接...", 2000)
            return
        self._bubble.show_text("思考中...", 5000)
        self._ws_send(json.dumps({"type": "chat", "text": text}))

    def _show_models(self):
        """显示模型列表对话框"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle("模型管理")
        dlg.setFixedSize(300, 400)
        layout = QVBoxLayout(dlg)
        for m in find_model3():
            row = QHBoxLayout()
            row.addWidget(QLabel(m["name"]))
            btn = QPushButton("删除")
            btn.setFixedSize(50, 24)
            btn.clicked.connect(lambda checked, name=m["name"]: self._delete_model(name, dlg))
            row.addWidget(btn)
            layout.addLayout(row)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec()

    def _delete_model(self, name: str, dlg=None):
        """删除模型"""
        import shutil
        target = os.path.join(DATA_MODELS, name)
        if os.path.exists(target):
            shutil.rmtree(target)
            if dlg:
                dlg.accept()
            self._show_models()

    def _import_model(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型文件", "", "模型文件 (*.model3.json)")
        if not p:
            return
        # 复制到 data/models/ 目录
        model_dir = os.path.dirname(p)
        model_name = os.path.basename(model_dir)
        target_dir = os.path.join(DATA_MODELS, model_name)
        try:
            import shutil
            if os.path.exists(target_dir):
                import time
                target_dir += f"_imported_{int(time.time())}"
            shutil.copytree(model_dir, target_dir)
            new_path = os.path.join(target_dir, os.path.basename(p))
            log.info(f"模型已导入: {new_path}")
            notify = getattr(self, '_notify', None)
            if notify:
                notify(f"模型已导入: {model_name}")
            self._reload_model(new_path)
        except Exception as e:
            log.warning(f"模型导入失败: {e}")
            self._reload_model(p)  # 复制失败直接加载原路径

    def _reload_model(self, path: str):
        """重新加载模型（在 OpenGL 线程中）"""
        self._model_path = path
        QTimer.singleShot(0, self._init_model)

    def _init_model(self):
        """重建模型"""
        if not self._model_path or not os.path.exists(self._model_path):
            return
        try:
            self.model = live2d.LAppModel()
            self.model.LoadModelJson(self._model_path)
            self.model.Resize(self.width(), self.height())
            self.model.SetAutoBreathEnable(True)
            self.model.SetAutoBlinkEnable(True)
            self.model.StartRandomMotion("Idle", 3)
            log.info(f"模型切换: {self._model_path}")
            from desktop_core.motion_engine import PoseEngine
from desktop_core.bone_rig import create_default_skeleton, create_default_animator
            self._pose = PoseEngine(self.model)
            self._pose.scan_model()
        except Exception as e:
            log.warning(f"模型切换失败: {e}")

    def set_mouth(self, v: float):
        self._mouth_target = max(0.0, min(1.0, v))

    # ── WebSocket 口型 ──

    def _ws_send(self, text: str):
        ws = getattr(self, '_ws', None)
        if ws:
            try:
                ws.send(text)
                cls = type(self)
                import time as _t
                try:
                    with open(cls.DEBUG_LOG, "a") as f:
                        f.write(f"{_t.time():.0f} _ws_send: 已发送\n")
                except:
                    pass
            except Exception as e:
                import time as _t
                try:
                    with open(type(self).DEBUG_LOG, "a") as f:
                        f.write(f"{_t.time():.0f} _ws_send 异常: {e}\n")
                except:
                    pass

    def _ws_loop(self):
        import websocket
        while self._running:
            try:
                self._ws = websocket.create_connection("ws://127.0.0.1:9845/api/live/live2d-stream", timeout=5)
                # recv 超时设为 5 分钟，避免无消息时频繁断线
                self._ws.settimeout(300)
                while self._running:
                    raw = self._ws.recv()
                    if not raw:
                        break
                    d = json.loads(raw)
                    if d.get("type") == "speak":
                        txt = d.get("text", "")
                        expr = self._resolve_expression(d.get("emotion", ""))
                        mg = d.get("motion_group", "")
                        mi = d.get("motion_index", -1)
                        mouth = d.get("mouth", [])
                        ms = d.get("frame_ms", 80)
                        action = d.get("action", "")
                        self._ws_queue.put({"type":"speak","text":txt,"emotion":d.get("emotion",""),"motion_group":mg,"motion_index":mi,"action":action,"mouth":mouth,"frame_ms":ms})
            except:
                self._ws = None
                if self._running:
                    time.sleep(3)
            finally:
                try:
                    ws.close()
                except:
                    pass

    def _process_ws_queue(self):
        while not self._ws_queue.empty():
            try:
                msg = self._ws_queue.get_nowait()
                if msg.get("type") == "speak":
                    txt = msg.get("text", "")
                    if txt:
                        self._bubble.show_text(txt)
                    expr = self._resolve_expression(msg.get("emotion", ""))
                    if expr and self.model:
                        self.model.SetExpression(expr)
                    mg = msg.get("motion_group", "")
                    mi = msg.get("motion_index", -1)
                    # 优先 Pose 引擎驱动
                    action = msg.get("action", "")
                    if action:
                        # 骨骼动画驱动
                        self._animator.play(action)
                        if not self._pose.play_action(action):
                            # Pose 参数未匹配：尝试用 _motion_groups 里的动作组
                            if self.model and self._motion_groups:
                                import random as _r
                                candidates = [g for g in self._motion_groups if g != "Idle"]
                                if candidates:
                                    g = _r.choice(candidates)
                                    idx = _r.randint(0, self._motion_groups[g] - 1)
                                    self.model.StartMotion(g, idx, 2)
                    elif mg and mi >= 0 and self.model:
                        if mg in self._motion_groups:
                            self.model.StartMotion(mg, mi, 3)
                        else:
                            fallbacks = {"TapBody": "Idle", "TapHead": "Idle"}
                            fb = fallbacks.get(mg, "")
                            if fb in self._motion_groups:
                                self.model.StartMotion(fb, 0, 1)
            except:
                pass

    def closeEvent(self, event):
        self._running = False
        super().closeEvent(event)


def run_pet(model_path: str = ""):
    live2d.init()
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        win = PetWindow(model_path)
        win.show()
        win.raise_()
        win.activateWindow()
        log.info("[桌宠] 窗口已显示")
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        log.error(f"[桌宠] 启动失败: {e}\n{traceback.format_exc()}")
        # 写入文件方便排查
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_error.log"), "w") as f:
            f.write(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    run_pet(sys.argv[1] if len(sys.argv) > 1 else "")
