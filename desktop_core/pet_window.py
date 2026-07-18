"""桌宠窗口 — PySide6 + live2d.v3 透明置顶 Live2D 渲染

参考: Soyoc-Pet (github.com/VKyuXr/Soyoc-Pet)
核心做法: QOpenGLWidget + initializeGL 同步加载模型，paintGL 全权渲染
"""
import os, sys, json, logging, threading, time
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_OPENGL", "angle")

from PySide6.QtWidgets import QApplication, QWidget, QFileDialog, QMenu
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from live2d import v3

log = logging.getLogger("pet_window")

SEARCH_ROOTS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "models"),
    r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels",
]


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


class Live2DWidget(QOpenGLWidget):
    """Live2D 渲染控件 — 同步加载模型，paintGL 全权渲染"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.model: Optional[v3.LAppModel] = None
        self._mouth_target = 0.0
        self._mouth_current = 0.0

    def initializeGL(self):
        """OpenGL 就绪后同步加载模型（Soyoc-Pet 做法）"""
        v3.glInit()
        # 加载模型
        path = getattr(self, '_load_path', '')
        if path and os.path.exists(path):
            self._do_load(path)
        # OpenGL 状态
        import OpenGL.GL as GL
        GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        # 渲染循环
        self.startTimer(16)  # ~60fps

    def timerEvent(self, event):
        self.update()

    def resizeGL(self, w, h):
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self):
        import OpenGL.GL as GL
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self.model:
            return
        # 口型平滑
        if abs(self._mouth_target - self._mouth_current) > 0.01:
            self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
            self.model.SetParameterValue("ParamMouthOpenY", self._mouth_current)
            self.model.SetParameterValue("ParamMouthForm", self._mouth_current)
        self.model.Update()
        self.model.Draw()

    def _do_load(self, path: str):
        """实际加载模型"""
        m = v3.LAppModel()
        m.LoadModelJson(path)
        m.SetAutoBreathEnable(True)
        m.SetAutoBlinkEnable(True)
        m.StartRandomMotion("Idle", 3)
        cw, ch = m.GetCanvasSize()
        if cw and ch:
            scale = min(self.width() / cw, self.height() / ch) * 0.9
            m.SetScale(scale)
            m.SetOffset(0, 0.1)
        self.model = m
        log.info(f"模型已加载: {path}")

    def load_model(self, path: str):
        """外部设置模型路径，等待 initializeGL 时加载"""
        self._load_path = path

    def set_mouth(self, v: float):
        self._mouth_target = max(0.0, min(1.0, v))


class PetWindow(QWidget):
    """桌宠主窗口 — 只负责包 OpenGL 控件"""

    def __init__(self, model_path: str = ""):
        super().__init__()
        self.setWindowTitle("奶昔桌宠")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(400, 500)

        # OpenGL 控件（全权渲染）
        self.l2d = Live2DWidget(self)
        self.l2d.setGeometry(0, 0, 400, 500)
        if model_path and os.path.exists(model_path):
            self.l2d.load_model(model_path)
        else:
            models = find_model3()
            if models:
                self.l2d.load_model(models[0]["path"])

        # 右下角定位
        from PySide6.QtGui import QScreen
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        self.move(screen.width() - 420, screen.height() - 520)

        # WS 口型接收
        self._running = True
        self._start_ws()

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _start_ws(self):
        def _run():
            import websocket
            while self._running:
                try:
                    ws = websocket.create_connection("ws://127.0.0.1:9845/api/live/live2d-stream", timeout=5)
                    while self._running:
                        raw = ws.recv()
                        if not raw:
                            break
                        d = json.loads(raw)
                        if d.get("type") == "speak":
                            for m in d.get("mouth", []):
                                if not self._running:
                                    break
                                self.l2d.set_mouth(m)
                                time.sleep(d.get("frame_ms", 80) / 1000)
                            self.l2d.set_mouth(0.0)
                except:
                    if self._running:
                        time.sleep(3)
                finally:
                    try:
                        ws.close()
                    except:
                        pass
        threading.Thread(target=_run, daemon=True).start()

    def _menu(self, pos):
        m = QMenu(self)
        models = find_model3()
        if models:
            sub = m.addMenu("切换模型")
            for md in models:
                a = sub.addAction(md["name"])
                a.triggered.connect(lambda checked, p=md["path"]: self.l2d.load_model(p))
        a_import = m.addAction("导入模型文件...")
        a_import.triggered.connect(self._import)
        m.addSeparator()
        a_exit = m.addAction("退出")
        a_exit.triggered.connect(self.close)
        m.exec(self.mapToGlobal(pos))

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型文件", "", "模型文件 (*.model3.json)")
        if p:
            self.l2d.load_model(p)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent):
        if e.buttons() == Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def closeEvent(self, e):
        self._running = False
        super().closeEvent(e)


def run_pet(model_path: str = ""):
    v3.init()
    app = QApplication.instance() or QApplication(sys.argv)
    win = PetWindow(model_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_pet(sys.argv[1] if len(sys.argv) > 1 else "")
