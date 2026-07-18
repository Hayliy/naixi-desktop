"""桌宠窗口 — PySide6 + live2d.v3 实现透明置顶 Live2D 渲染"""
import os, sys, json, logging, asyncio, threading
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_OPENGL", "angle")

from PySide6.QtWidgets import QApplication, QWidget, QFileDialog, QMenu
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QObject
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QFont, QAction, QPen, QBrush
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from live2d import v3

log = logging.getLogger("pet_window")

# ── 模型搜索路径 ──
SEARCH_ROOTS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "models"),
    r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels",
]


def find_model3() -> list[dict]:
    """扫描所有可用模型，返回 [{name, modelFile, path}]"""
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


class Live2DWidget(QOpenGLWidget):
    """Live2D 渲染控件（OpenGL）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model: Optional[v3.LAppModel] = None
        self.model_root = ""
        self._mouth_target = 0.0
        self._mouth_current = 0.0
        self._running = True
        self._pending_model = ""  # 等待 OpenGL 就绪后加载

    def initializeGL(self):
        v3.glInit()
        # OpenGL 就绪后加载等待的模型
        if self._pending_model and os.path.exists(self._pending_model):
            self._do_load_model(self._pending_model)
            self._pending_model = ""

    def resizeGL(self, w, h):
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self):
        if not self.model:
            # 模型未加载时显示提示文字
            v3.clearBuffer(0.2, 0.15, 0.25, 0.2)
            painter = QPainter(self)
            painter.setPen(QColor("#aaa"))
            painter.setFont(QFont("微软雅黑", 13))
            painter.drawText(self.rect(), Qt.AlignCenter, "正在加载模型...")
            painter.end()
            return
        v3.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if abs(self._mouth_target - self._mouth_current) > 0.01:
            self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
            self.model.SetParameterValue("ParamMouthOpenY", self._mouth_current)
            self.model.SetParameterValue("ParamMouthForm", self._mouth_current)
        self.model.Update()
        self.model.Draw()

    def load_model(self, model_path: str):
        """加载 Live2D 模型（延迟到 OpenGL 就绪）"""
        if not os.path.exists(model_path):
            log.warning(f"模型文件不存在: {model_path}")
            return
        if self.model:
            self.model = None
        if hasattr(self, 'context') and self.context():
            # OpenGL 已就绪，直接加载
            self._do_load_model(model_path)
        else:
            # OpenGL 未就绪，等 initializeGL 加载
            self._pending_model = model_path

    def _do_load_model(self, model_path: str):
        """在 OpenGL 上下文中加载模型"""
        model = v3.LAppModel()
        model.LoadModelJson(model_path)
        model.SetAutoBreathEnable(True)
        model.SetAutoBlinkEnable(True)
        model.StartRandomMotion("Idle", 3)
        canvas_w, canvas_h = model.GetCanvasSize()
        if canvas_w and canvas_h:
            win_w, win_h = self.width() or 400, self.height() or 500
            scale = min(win_w / canvas_w, win_h / canvas_h) * 0.9
            model.SetScale(scale)
            model.SetOffset(0, 0.1)
        self.model = model
        log.info(f"模型已加载: {model_path}")

    def set_mouth(self, value: float):
        """设置口型目标值 0.0~1.0"""
        self._mouth_target = max(0.0, min(1.0, value))

    def stop(self):
        self._running = False


class PetWindow(QWidget):
    """桌宠主窗口 — 透明置顶"""

    def __init__(self, model_path: str = ""):
        super().__init__()
        self.setWindowTitle("奶昔桌宠")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(400, 500)
        self._model_path = model_path

        # 默认放在屏幕右下角
        from PySide6.QtGui import QScreen
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        self.move(screen.width() - 420, screen.height() - 520)

        # 默认放在屏幕右下角
        from PySide6.QtGui import QScreen
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        self.move(screen.width() - 420, screen.height() - 520)

        # Live2D 渲染控件
        self.l2d = Live2DWidget(self)
        self.l2d.setGeometry(0, 0, 400, 500)

        # 拖拽
        self._drag_pos = QPoint()

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # 定时刷新 (~60fps)
        self._timer = QTimer()
        self._timer.timeout.connect(self.l2d.update)
        self._timer.start(16)

        # 定时打印位置（首次启动后 2s）
        QTimer.singleShot(2000, lambda: log.info(
            f"[桌宠] 当前位置: ({self.x()},{self.y()}), 可见: {self.isVisible()}, 激活: {self.isActiveWindow()}"
        ))

        # WebSocket 线程
        self._ws_thread: Optional[threading.Thread] = None
        self._running = True

        # 加载模型（延迟到 OpenGL 就绪）
        if model_path and os.path.exists(model_path):
            self._model_path = model_path
            self.l2d.load_model(model_path)
        else:
            models = find_model3()
            if models:
                self._model_path = models[0]["path"]
                self.l2d.load_model(models[0]["path"])

        # 启动 WS 接收
        self._start_ws()

    def _start_ws(self):
        """后台线程：连接后端 WebSocket 接收口型/表情数据"""

        def _run():
            import websocket
            url = "ws://127.0.0.1:9845/api/live/live2d-stream"
            while self._running:
                try:
                    ws = websocket.create_connection(url, timeout=5)
                    while self._running:
                        raw = ws.recv()
                        if not raw:
                            break
                        data = json.loads(raw)
                        if data.get("type") == "speak":
                            mouth_data = data.get("mouth", [])
                            frame_ms = data.get("frame_ms", 80)
                            for m in mouth_data:
                                if not self._running:
                                    break
                                self.l2d.set_mouth(m)
                                import time
                                time.sleep(frame_ms / 1000)
                            self.l2d.set_mouth(0.0)
                except Exception as e:
                    if self._running:
                        import time
                        time.sleep(3)
                finally:
                    try:
                        ws.close()
                    except:
                        pass

        self._ws_thread = threading.Thread(target=_run, daemon=True)
        self._ws_thread.start()

    def _show_menu(self, pos):
        menu = QMenu(self)
        # 切换模型
        models = find_model3()
        if models:
            sub = menu.addMenu("切换模型")
            for m in models:
                act = QAction(m["name"], self)
                act.triggered.connect(lambda checked, p=m["path"]: self.l2d.load_model(p))
                sub.addAction(act)
        # 导入模型
        act_import = QAction("导入模型文件...", self)
        act_import.triggered.connect(self._import_model)
        menu.addAction(act_import)
        # 退出
        menu.addSeparator()
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self.close)
        menu.addAction(act_exit)
        menu.exec(self.mapToGlobal(pos))

    def _import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型文件", "", "模型文件 (*.model3.json)")
        if path:
            self.l2d.load_model(path)

    # ── 鼠标拖拽 ──

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def closeEvent(self, event):
        self._running = False
        self.l2d.stop()
        self._timer.stop()
        v3.glRelease()
        super().closeEvent(event)


def run_pet(model_path: str = ""):
    """启动桌宠（阻塞）"""
    v3.init()
    app = QApplication.instance() or QApplication(sys.argv)
    win = PetWindow(model_path)
    # 记录窗口位置以便调试
    log.info(f"[桌宠] 窗口位置: ({win.x()}, {win.y()}), 大小: ({win.width()}, {win.height()})")
    log.info("[桌宠] 窗口已弹出，请查看屏幕")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    model_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    run_pet(model_arg)
