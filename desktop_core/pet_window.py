"""桌宠窗口 — PySide6 + live2d.v3 透明置顶 Live2D 渲染

参考: yuuki-desktop (github.com/Rinisnotarobot/yuuki-desktop)
- QOpenGLWidget 直接当窗口，无外层包裹
- initializeGL 同步构造模型，paintGL 全权渲染
"""
import os, sys, json, logging, threading, time
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_OPENGL", "angle")

from OpenGL.GL import glViewport
from PySide6.QtCore import Qt, QPoint, QTimerEvent, QTimer
from PySide6.QtGui import QGuiApplication, QMouseEvent, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMenu, QFileDialog

from live2d import v3 as live2d

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


class PetWindow(QOpenGLWidget):
    """桌宠窗口 — QOpenGLWidget 本身就是窗口（参照 yuuki-desktop）"""

    def __init__(self, model_path: str = ""):
        super().__init__()
        self.model: Optional[live2d.LAppModel] = None
        self._mouth_target = 0.0
        self._mouth_current = 0.0
        self._model_path = model_path or ""
        self._drag_offset = QPoint()
        self._dragging = False
        # 表情/动作映射
        self._expression_map: dict[str, str] = {}  # "开心" → "1脸红.exp3.json"
        self._motion_groups: dict[str, int] = {}   # "Idle" → 3 (count)

        # 窗口属性：无边框 + 置顶 + 工具窗口 + 透明
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
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
        if self._model_path and os.path.exists(self._model_path):
            try:
                self.model = live2d.LAppModel()
                self.model.LoadModelJson(self._model_path)
                self.model.Resize(self.width(), self.height())
                self.model.SetAutoBreathEnable(True)
                self.model.SetAutoBlinkEnable(True)
                self.model.StartRandomMotion("Idle", 3)
                self._init_expression_map()
                log.info(f"模型加载成功: {self._model_path}")
            except Exception as e:
                log.warning(f"模型加载失败: {e}")
        self.startTimer(16)

    def _init_expression_map(self):
        """初始化表情映射：模型的表情ID → 中文名"""
        if not self.model:
            return
        try:
            ids = self.model.GetExpressionIds()
            self._expression_map = {}
            for eid in ids:
                # 表情文件一般是 "1脸红.exp3.json" 格式，取数字后的中文
                name = eid.replace(".exp3.json", "").lstrip("0123456789")
                self._expression_map[eid] = name
            # 反向映射：中文 → 表情ID
            self._emotion_to_expr = {v: k for k, v in self._expression_map.items()}
            # 默认映射（中文情绪 → 表情名）
            self._emotion_fallback = {
                "开心": "脸红", "欢迎": "心心眼", "惊讶": "心心眼",
                "悲伤": "可怜眼", "害羞": "脸红", "生气": "黑脸",
                "卖萌": "哇库哇库", "无奈": "空白眼",
            }
            log.info(f"表情已加载: {list(self._expression_map.keys())}")
            # 动作组
            motions = self.model.GetMotionGroups()
            self._motion_groups = motions if motions else {}
            log.info(f"动作组: {self._motion_groups}")
        except Exception as e:
            log.warning(f"表情/动作加载失败: {e}")

    def _resolve_expression(self, emotion: str) -> str:
        """把中文情绪转成模型的表情ID"""
        expr_name = self._emotion_fallback.get(emotion, "")
        if expr_name:
            for eid, ename in self._expression_map.items():
                if ename == expr_name:
                    return eid
        return ""

    def resizeGL(self, w: int, h: int):
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self):
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if not self.model:
            return
        # 口型平滑
        if abs(self._mouth_target - self._mouth_current) > 0.01:
            self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
            self.model.SetParameterValue("ParamMouthOpenY", self._mouth_current)
            self.model.SetParameterValue("ParamMouthForm", self._mouth_current)
        self.model.Update()
        self.model.Draw()

    def timerEvent(self, event: QTimerEvent):
        self.update()

    # ── 鼠标 ──

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(e)

    # ── 右键菜单 ──

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        models = find_model3()
        if models:
            sub = menu.addMenu("切换模型")
            for m in models:
                a = sub.addAction(m["name"])
                a.triggered.connect(lambda checked, p=m["path"]: self._reload_model(p))
        menu.addAction("导入模型文件...", self._import_model)
        menu.addSeparator()
        menu.addAction("退出", QApplication.quit)
        menu.exec(event.globalPos())

    def _import_model(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 Live2D 模型文件", "", "模型文件 (*.model3.json)")
        if p:
            self._reload_model(p)

    def _reload_model(self, path: str):
        """重新加载模型（在 OpenGL 线程中）"""
        self._model_path = path
        # 下一次 paintGL 时会重新创建 model
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
        except Exception as e:
            log.warning(f"模型切换失败: {e}")

    def set_mouth(self, v: float):
        self._mouth_target = max(0.0, min(1.0, v))

    # ── WebSocket 口型 ──

    def _ws_loop(self):
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
                        # 表情
                        expr = self._resolve_expression(d.get("emotion", ""))
                        if expr:
                            self.model.SetExpression(expr)
                        # 动作
                        mg = d.get("motion_group", "")
                        mi = d.get("motion_index", -1)
                        if mg and mi >= 0 and self.model:
                            self.model.StartMotion(mg, mi, 3)
                        # 口型
                        for m in d.get("mouth", []):
                            if not self._running:
                                break
                            self.set_mouth(m)
                            time.sleep(d.get("frame_ms", 80) / 1000)
                        self.set_mouth(0.0)
            except:
                if self._running:
                    time.sleep(3)
            finally:
                try:
                    ws.close()
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
    win = PetWindow(model_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_pet(sys.argv[1] if len(sys.argv) > 1 else "")
