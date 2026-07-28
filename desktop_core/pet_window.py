"""桌宠窗口 — PySide6 + live2d.v3 透明置顶 Live2D 渲染

参考: yuuki-desktop (github.com/Rinisnotarobot/yuuki-desktop)
- QOpenGLWidget 直接当窗口，无外层包裹
- initializeGL 同步构造模型，paintGL 全权渲染
"""
import os, sys, json, logging, threading, time, queue, ctypes
from typing import Optional

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# 注意：QT_OPENGL=angle 是 Qt5 的值，Qt6 已移除会报 Invalid value 警告；
# Qt6 下留空走默认 desktop OpenGL 即可，软渲染兜底用 QT_OPENGL=software。

from OpenGL.GL import glViewport, GL_RGBA8
from PySide6.QtCore import Qt, QPoint, QTimerEvent, QTimer, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QMouseEvent, QSurfaceFormat, QPainter, QColor, QFont, QPainterPath, QImage, QCursor
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMenu, QFileDialog, QWidget, QLineEdit, QLabel

from desktop_core.motion_engine import PoseEngine
from desktop_core.idle_engine import IdleEngine
from desktop_core.engine.ecs import World
from desktop_core.engine.transform import Transform
from desktop_core.engine.skeleton import build_skeleton, set_pose, get_bone_angles, SkeletalAnimator, WalkCycle, WalkSystem, _collect_all

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
        # 注入时直接记录的表情/动作（不依赖 GetExpressionIds 回读，避免绑定不回显导致菜单空白）
        self._injected_expressions: list[tuple[str, str]] = []  # (eid, 中文名)
        self._injected_motion_groups: dict[str, int] = {}        # group -> 条数
        self._idle_motion_groups: list[str] = []
        self._active_manual_exprs: set[str] = set()  # 菜单勾选、常驻在场的表情（支持多表情并存）
        self._emotion_expr: str | None = None        # WS 自动触发的情绪表情（单槽，可替换，不碰常驻项）
        self._idle_interval = 15.0
        self._last_idle_ts = 0.0
        self._pose = PoseEngine(None)
        self._ecs_world = World()
        # 构建骨骼骨架
        self._skeleton_root = build_skeleton()
        all_bones = []
        _collect_all(self._skeleton_root, all_bones)
        for e in all_bones:
            self._ecs_world.add_entity(e)
        self._ecs_world.add_system(SkeletalAnimator())
        self._ecs_world.add_system(WalkSystem())
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
        self.resize(640, 800)

        # 右下角定位
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(max(0, screen.width() - 660), max(0, screen.height() - 820))

        # 滚轮缩放：当前缩放 / 目标缩放（timerEvent 每帧平滑 lerp）。
        # —— 架构（固定窗口 + 模型 transform SetScale + WM_NCHITTEST 像素穿透，根治三大老问题）——
        # · 窗口几何【固定】640×800，滚轮缩放只改模型的 SetScale（transform），绝不 setGeometry → 透明窗口 DWM 不再每帧重绘 → 零闪烁/零撕裂；
        # · 模型只在加载时 Resize 到 CANVAS/ZOOM_PAD（固定 400×500 离屏画布，留白），再整体贴到 640×800 窗口；SetScale 在 [ZOOM_MIN, ZOOM_MAX] 内模型始终不裁边、且可放大到铺满画布；
        # · 鼠标穿透用 Win32 WM_NCHITTEST（nativeEvent）：仅「模型不透明像素」命中窗口（可拖拽/右键），
        #   透明像素返回 HTTRANSPARENT 让点击穿透到桌面 —— 比 setMask 更优：setMask 会裁掉气泡/聊天等子控件，WM_NCHITTEST 只影响命中不影响绘制。
        self._zoom = 1.4
        self._target_zoom = 1.4
        self.BASE_W, self.BASE_H = 640, 800            # 窗口尺寸（滚轮缩放=模型 transform，不缩放窗口几何）；放大只为测试右击穿透
        # 模型画布固定 400×500，与窗口解耦：模型只在离屏画布里渲染，再整体贴到 640×800 窗口。
        # 窗口放大只增加透明边距，模型像素尺寸恒定（不再「窗口变大模型也变大」）。
        self.CANVAS_W, self.CANVAS_H = self.BASE_W, self.BASE_H  # 撤消解耦：画布=窗口尺寸，模型在窗口内正常大显示（7dbbd81 的 400x500 画布会让显示区域变小）
        self._draw_dx = (self.BASE_W - self.CANVAS_W) // 2
        self._draw_dy = (self.BASE_H - self.CANVAS_H) // 2
        self.ZOOM_MIN, self.ZOOM_MAX = 0.5, 2.0
        # 模型缩放留白：model.Resize 用 CANVAS/ZOOM_PAD，使 SetScale 在 [ZOOM_MIN, ZOOM_MAX] 内模型始终不裁边。
        # 须与 idle_engine.SCALE_MAX 相等（=2.2），否则放大裁边或留白浪费——改这里务必同步 idle_engine。
        self.ZOOM_PAD = 2.2
        # 透明窗口重绘时尽量保留旧内容（无害保留）
        self.setAttribute(Qt.WA_StaticContents, True)

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
                self._active_manual_exprs = set()
                self._emotion_expr = None
                self.model.LoadModelJson(self._model_path)
                self.model.Resize(int(self.CANVAS_W / self.ZOOM_PAD), int(self.CANVAS_H / self.ZOOM_PAD))
                self.model.SetAutoBreathEnable(True)
                self.model.SetAutoBlinkEnable(True)
                self.model.StartRandomMotion("Idle", 3)
                # VTS 模型的表情/动作普遍不写在 model3.json 里（散落 exp/ 子目录 + vtube.json），
                # LoadModelJson 只认 FileReferences → 表情恒空。与 web 宠物（api.py 注入）
                # 同源：复用 l2d_discovery 共享发现，把磁盘真实表情/动作注入模型。
                self._inject_discovered_actions()
                self._init_expression_map()
                self._apply_default_expressions()
                # 程序化 idle 动作引擎（下意识动作，不依赖模型 motion 文件）
                self._idle = IdleEngine()
                self._idle.reset(self.model)
                if self._pose is None or self._pose.model is None:
                    self._pose = PoseEngine(self.model)
                else:
                    self._pose.model = self.model
                self._pose.scan_model()
                # 生成动作文件并注册
                try:
                    # 优先写项目内 _motions（开发态）；打包态资源目录只读时回退到用户目录
                    motion_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_motions")
                    try:
                        os.makedirs(motion_dir, exist_ok=True)
                        _test = os.path.join(motion_dir, ".w")
                        with open(_test, "w") as _f:
                            _f.write("1")
                        os.remove(_test)
                    except Exception:
                        motion_dir = os.path.join(os.path.expanduser("~"), ".naixi_desktop", "motions")
                        os.makedirs(motion_dir, exist_ok=True)
                        log.info(f"动作目录改用用户目录: {motion_dir}")
                    motion_files = self._pose.generate_motion_files(motion_dir)
                    for pose_name, fpath in motion_files.items():
                        if "_loop" in pose_name:
                            group = "Idle"
                        else:
                            group = "Pose"
                        # live2d 0.7.x 起签名为 (group, motionJsonPath)，不再带序号参数
                        self.model.LoadExtraMotion(group, fpath)
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
                # 动作→骨骼动画（bone_rig 自带 Skeleton，与 engine.skeleton 的 _skeleton_root 是两套体系）
                from desktop_core.bone_rig import create_default_animator, create_default_skeleton
                self._animator = create_default_animator(create_default_skeleton())
            except Exception as e:
                log.warning(f"模型加载失败: {e}")
        self.startTimer(16)

    def _inject_discovered_actions(self):
        """把磁盘发现的表情/动作注入 live2d 模型（与 web 宠物后端注入同一套发现逻辑）。

        - 表情：LoadExtraExpression(表情名, exp3绝对路径)。表情名取 exp3 的 Name 字段
          （缺失回退文件名），与 _resolve_expression 的匹配口径一致。
        - 动作：LoadExtraMotion("Action", motion3绝对路径)。畸形 motion 已被共享发现剔除。
        """
        if not self.model or not self._model_path:
            return
        # 切换模型时重新注入前先清空上一份模型的记录，避免新旧表情/动作累积导致菜单死绑旧模型
        self._injected_expressions = []
        self._injected_motion_groups = {}
        try:
            from desktop_core.l2d_discovery import discover_model_actions
            acts = discover_model_actions(self._model_path)
        except Exception as e:
            log.warning(f"[桌宠] 表情/动作发现失败: {e}")
            return
        model_dir = os.path.dirname(self._model_path)
        n_exp = n_mot = 0
        already = set()
        try:
            already = set(self.model.GetExpressionIds() or [])
        except Exception:
            pass
        for ex in acts.get("expressions", []):
            name, rel = ex.get("name", ""), ex.get("file", "")
            fpath = os.path.join(model_dir, rel)
            if not name or name in already or not os.path.isfile(fpath):
                continue
            try:
                self.model.LoadExtraExpression(name, fpath)
                n_exp += 1
                # 直接记录注入项（与 _init_expression_map 的展示口径一致），菜单以此为主源
                _disp = name.replace(".exp3.json", "").lstrip("0123456789")
                self._injected_expressions.append((name, _disp))
            except Exception as e:
                log.warning(f"[桌宠] 表情注入失败 {name}: {e}")
        for m in acts.get("motions", []):
            grp, rel = m.get("group", "Action") or "Action", m.get("file", "")
            fpath = os.path.join(model_dir, rel)
            if not os.path.isfile(fpath):
                continue
            try:
                self.model.LoadExtraMotion(grp, fpath)
                n_mot += 1
                self._injected_motion_groups[grp] = self._injected_motion_groups.get(grp, 0) + 1
            except Exception as e:
                log.warning(f"[桌宠] 动作注入失败 {rel}: {e}")
        log.warning(f"[桌宠] 发现注入: 表情+{n_exp} 动作+{n_mot}")
        # 模型作者约定：水印(Watermark)表情默认就展示，靠按键/菜单才去掉 → 加载后默认开启
        self._apply_default_expressions()

    def _apply_default_expressions(self):
        """按模型作者约定，加载后自动叠加「水印」表情并设为常驻勾选。

        水印是演示水印，作者设计为默认展示、只有去掉操作才隐藏。因此宠物启动/
        切换模型后自动 AddExpression + 记入常驻集合（菜单里默认打勾）；用户仍可在
        右击「表情」子菜单取消（_toggle_expression 会 RemoveExpression 并移出集合）。
        幂等：已开启的不再重复 AddExpression（避免重复叠加异常）。
        """
        if not self.model:
            return
        # 同时查注入项与模型内置项，覆盖「水印」写在任一处的情况
        candidates = list(getattr(self, "_injected_expressions", []))
        candidates += list(getattr(self, "_expression_map", {}).items())
        for eid, disp in candidates:
            hay = f"{eid} {disp}".lower()
            if "水印" in eid or "水印" in disp or "watermark" in hay:
                if eid in getattr(self, "_active_manual_exprs", set()):
                    break  # 已默认开启，跳过
                try:
                    self.model.AddExpression(eid)
                    self._active_manual_exprs.add(eid)
                    log.warning(f"[桌宠] 默认开启水印表情: {eid}")
                except Exception as e:
                    log.warning(f"[桌宠] 默认开启水印表情失败 {eid}: {e}")
                break

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
        # 模型 fit 已固定在稳定 RENDER 画布（见 initializeGL / _init_model），窗口尺寸变化只影响
        # FBO→窗口的合成贴图（在 paintGL 内按当前 self.width/height 处理），不重建模型 fit / FBO，
        # 从而避免 OS 窗口异步 resize 与 FBO 错帧导致的撕裂/跳变。此处保持空实现。
        pass

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
        self._process_ws_queue()
        if not self.model:
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
            return
        # 骨骼动画更新
        self._ecs_world.update(dt)
        # 口型平滑
        if abs(self._mouth_target - self._mouth_current) > 0.01:
            self._mouth_current += (self._mouth_target - self._mouth_current) * 0.3
        # 模型状态更新
        self.model.Update()
        self._pose.update(dt)
        if abs(self._mouth_current) > 0.01:
            self.model.SetParameterValue("ParamMouthOpenY", self._mouth_current, 1.0)
            self.model.SetParameterValue("ParamMouthForm", self._mouth_current, 1.0)
        # 程序化 idle 动作（下意识动作：看鼠标/摇头/浮动/风吹/突脸），在 Update 后、Draw 前设置
        # 滚轮缩放 = 模型 transform(SetScale)：idle.update 内部把 self._zoom 并进 SetScale 合成（见 idle_engine），窗口几何固定不动。
        if getattr(self, "_idle", None) is not None:
            try:
                gp = QCursor.pos()
                tl = self.mapToGlobal(QPoint(0, 0))
                cx = tl.x() + self.width() / 2
                cy = tl.y() + self.height() / 2
                self._idle.update(self.model, {
                    "dt": dt,
                    "cursor": (gp.x(), gp.y()),
                    "pet_center": (cx, cy),
                    "pet_size": (self.width(), self.height()),
                    "zoom": self._zoom,
                })
            except Exception as e:
                log.warning(f"[桌宠] idle 更新失败: {e}")
        else:
            # 防御：无 idle 引擎时直接施加缩放（缩放=模型 transform，与 idle 路径一致）
            try:
                self.model.SetScale(self._zoom)
            except Exception:
                pass
        # ── 稳定离屏画布渲染 → 按比例贴到当前窗口 ──
        # 先清空屏幕
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        # 离屏画布 = 当前窗口尺寸（窗口固定，故仅分配一次，不需要随缩放重建 → 无错帧撕裂）
        if getattr(self, '_fbo', None) is None or self._fbo.size().width() != self.CANVAS_W or self._fbo.size().height() != self.CANVAS_H:
            from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setSamples(0)
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            # QOpenGLFramebufferObjectFormat 默认 internal format 即 GL_RGBA8（自带 8 位 alpha）；
            # Qt6 该格式类【没有】setAlpha/setAlphaBufferSize（那是 QSurfaceFormat 的方法），
            # 故用 setInternalTextureFormat 显式确保 alpha 通道 —— clearBuffer(0,0,0,0) 后透明边距
            # alpha=0，模型绘制处 alpha=255 → 供 WM_NCHITTEST 像素级穿透采样。
            fmt.setInternalTextureFormat(GL_RGBA8)
            self._fbo = QOpenGLFramebufferObject(self.CANVAS_W, self.CANVAS_H, fmt)
        self._fbo.bind()
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        self.model.Draw()
        self._fbo.release()
        img = self._fbo.toImage()
        # 缓存最近一帧用于 WM_NCHITTEST 像素级鼠标穿透（采样 alpha 判断是否点到模型）
        self._last_img = img
        # 窗口几何固定，离屏画布(400×500)整体贴到 640×800 窗口中央（先按骨骼偏移合成，再平移到窗口锚点）
        cw, ch = self.CANVAS_W, self.CANVAS_H
        dx, dy = self._draw_dx, self._draw_dy
        # 骨骼偏移
        root_t = self._skeleton_root.get(Transform) if hasattr(self, '_skeleton_root') and self._skeleton_root else None
        ox = root_t.world_x if root_t else 0
        oy = root_t.world_y if root_t else 0
        wa = get_bone_angles(self._skeleton_root) if hasattr(self, '_skeleton_root') and self._skeleton_root else {}
        arm_l = wa.get('arm_l_upper', 0)
        arm_r = wa.get('arm_r_upper', 0)
        # 行走方向——水平翻转
        wc = self._skeleton_root.get(WalkCycle) if hasattr(self, '_skeleton_root') and self._skeleton_root else None
        facing_left = (wc and wc.direction < 0)
        # 设置行走边界（画布边缘留 50px 内边距）
        if wc:
            wc.bound_left = -50
            wc.bound_right = cw - 50
        # 用 QPainter 绘制：身体 + 左臂（旋转）+ 右臂（旋转）
        arm_w = int(cw * 0.20)
        pivot_y = int(ch * 0.35)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(dx + ox + (cw if facing_left else 0), dy + oy)
        if facing_left:
            painter.scale(-1, 1)  # 水平翻转
        # 左臂
        painter.save()
        painter.translate(arm_w, pivot_y)
        painter.rotate(arm_l)
        painter.translate(-arm_w, -pivot_y)
        painter.drawImage(0, 0, img.copy(0, 0, arm_w, ch))
        painter.restore()
        # 身体
        painter.drawImage(arm_w, 0, img.copy(arm_w, 0, cw - 2 * arm_w, ch))
        # 右臂
        painter.save()
        painter.translate(cw - arm_w, pivot_y)
        painter.rotate(arm_r)
        painter.translate(-(cw - arm_w), -pivot_y)
        painter.drawImage(cw - arm_w, 0, img.copy(cw - arm_w, 0, arm_w, ch))
        painter.restore()
        painter.end()

    def timerEvent(self, event: QTimerEvent):
        self.update()
        # 滚轮缩放：_zoom 平滑趋近 _target_zoom；缩放 = 模型 transform(SetScale，由 paintGL→idle 应用)，
        # 不碰窗口几何 → 透明窗口 DWM 不重绘 → 零闪烁/零撕裂/完全跟手。
        if abs(self._target_zoom - self._zoom) > 1e-3:
            self._zoom += (self._target_zoom - self._zoom) * 0.35
            if abs(self._target_zoom - self._zoom) < 1e-3:
                self._zoom = self._target_zoom
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

    def resizeEvent(self, e):
        """窗口几何随 zoom 变化（timerEvent 驱动）时，同步输入框与气泡位置。

        注意：模型 fit 与 FBO 均为稳定 RENDER 画布，此处【不】重建模型 fit / FBO，
        只调整 UI 子控件布局，避免任何 GL 资源重分配引入撕裂。
        """
        super().resizeEvent(e)
        if hasattr(self, '_chat_input'):
            self._chat_input.setGeometry(4, max(4, self.height() - 28), max(40, self.width() - 8), 24)
        if hasattr(self, '_bubble'):
            self._bubble._reposition()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(e)

    # ── 右键菜单 ──

    def _toggle_expression(self, eid: str):
        """右键菜单点表情：以勾选方式在「常驻表情集合」里增删（支持多表情并存）。

        与 SetExpression(单槽替换，点第二个把第一个顶掉) 不同，这里用 live2d.v3 的
        AddExpression / RemoveExpression 维护一个多表情列表，多个表情可同时生效
        （如 水印 常驻 + 脸红 临时叠加）。再点一次相同项即移除。"""
        if not self.model or not eid:
            return
        try:
            if eid in self._active_manual_exprs:
                self.model.RemoveExpression(eid)
                self._active_manual_exprs.discard(eid)
                log.warning(f"[桌宠] 取消常驻表情: {eid}")
            else:
                self.model.AddExpression(eid)
                self._active_manual_exprs.add(eid)
                log.warning(f"[桌宠] 添加常驻表情: {eid}")
        except Exception as e:
            log.warning(f"[桌宠] 表情切换失败 {eid}: {e}")

    def _play_motion(self, group: str, count: int):
        """右键菜单点动作：随机抽取该组一个动作播放（对齐 web 动作热键）。"""
        if not self.model or not group:
            return
        try:
            import random as _r
            n = int(count) if count else 1
            idx = _r.randint(0, max(0, n - 1))
            self.model.StartMotion(group, idx, 3)
        except Exception as e:
            log.warning(f"[桌宠] 动作播放失败 {group}: {e}")

    def contextMenuEvent(self, event):
        # 诊断：若右击落在透明边距却仍弹出本菜单，说明 WM_NCHITTEST 穿透未生效，记到 pet_debug.log 便于排查
        _lx, _ly = event.x(), event.y()
        if self._alpha_at(_lx, _ly) < 24:
            try:
                import time as _t
                with open(type(self).DEBUG_LOG, "a") as f:
                    f.write(f"{_t.time():.0f} PENETRATION_FAIL: 透明边距右击却弹出宠物菜单 (lx={_lx}, ly={_ly})\n")
            except Exception:
                pass
        menu = QMenu(self)
        menu.addAction("测试对话", lambda: self._chat_input.show() or self._chat_input.setFocus())
        menu.addSeparator()
        cap_label = "关闭捕获模式" if self._capture_mode else "直播捕获模式"
        menu.addAction(cap_label, self._toggle_capture)
        menu.addSeparator()
        # 表情 / 动作 手动触发（对齐 web 宠物 HotkeySettings 的手动触发入口）
        # 以注入时记录的自有列表为主源（live2d.v3 的 GetExpressionIds 未必回显注入项），
        # 再合并 _init_expression_map 读到的内置项；始终显示子菜单，空时给占位项避免误判"没生效"。
        expr_items = list(getattr(self, "_expression_map", {}).items())
        for _eid, _disp in getattr(self, "_injected_expressions", []):
            if _eid not in self._expression_map:
                expr_items.append((_eid, _disp))
        if expr_items:
            expr_sub = menu.addMenu("表情")
            for _eid, _ename in expr_items:
                _label = _ename or _eid
                _a = expr_sub.addAction(_label)
                _a.setCheckable(True)
                _a.setChecked(_eid in getattr(self, "_active_manual_exprs", set()))
                _a.triggered.connect(lambda _checked, e=_eid: self._toggle_expression(e))
        else:
            expr_sub = menu.addMenu("表情")
            _d = expr_sub.addAction("（暂无表情）")
            _d.setEnabled(False)
        # 程序化下意识动作（不依赖模型 motion 文件）：勾选开关 + 突脸触发
        idle = getattr(self, "_idle", None)
        if idle is not None:
            mot_sub = menu.addMenu("动作")
            for _key, _zh in [
                ("body_float", "身体浮动"),
                ("look_cursor", "看鼠标"),
                ("head_sway", "摇头歪头"),
                ("wind", "被风吹"),
                ("scale_breath", "缩放呼吸"),
            ]:
                _a = mot_sub.addAction(_zh)
                _a.setCheckable(True)
                _a.setChecked(idle.enabled.get(_key, False))
                _a.triggered.connect(lambda _c, k=_key: idle.toggle(k))
            mot_sub.addSeparator()
            _poke_a = mot_sub.addAction("突脸一下")
            _poke_a.triggered.connect(lambda _c: idle.trigger_poke())
        else:
            mot_sub = menu.addMenu("动作")
            _d = mot_sub.addAction("（暂无动作）")
            _d.setEnabled(False)
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

    def wheelEvent(self, event):
        """鼠标滚轮缩放桌宠：仅更新目标缩放 _target_zoom，由 timerEvent 每帧平滑 lerp。

        缩放 = 模型 transform(SetScale)，窗口几何固定不动（见 timerEvent / paintGL→idle 合成），
        故不触发透明窗口 DWM 重绘 → 零闪烁/零撕裂/完全跟手；模型随 SetScale 放大且始终不裁边
        （model.Resize 用 CANVAS/ZOOM_PAD 留白）。鼠标穿透由 WM_NCHITTEST 实现，透明处穿透桌面。
        会话内生效（关窗即重置），不做持久化存储。
        """
        d = event.angleDelta().y()
        if d == 0:
            return
        factor = 1.1 if d > 0 else 1.0 / 1.1
        new_target = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self._target_zoom * factor))
        if abs(new_target - self._target_zoom) < 1e-6:
            return
        self._target_zoom = new_target
        event.accept()

    # ── 鼠标穿透（Win32 WM_NCHITTEST，像素级）──
    def _alpha_at(self, x: int, y: int) -> int:
        """采样最近一帧画布图像在窗口坐标 (x,y) 的 alpha（0=全透明,255=不透明），用于命中测试判断是否点到模型。

        (x,y) 是相对窗口左上角的坐标；先减去绘制偏移得到画布内坐标，超出画布范围(即窗口透明边距)直接视为透明。
        """
        dx, dy = getattr(self, '_draw_dx', 0), getattr(self, '_draw_dy', 0)
        cx, cy = x - dx, y - dy
        img = getattr(self, '_last_img', None)
        if img is None or img.isNull():
            return 255
        if 0 <= cx < img.width() and 0 <= cy < img.height():
            return img.pixelColor(cx, cy).alpha()  # 用 pixelColor 取 alpha，避免不同 QImage 格式下位运算错读
        return 0  # 窗口边距（画布之外）= 透明 → 穿透

    def nativeEvent(self, eventType, message):
        """Win32 原生消息：WM_NCHITTEST 时，若光标落在模型透明像素上则返回 HTTRANSPARENT，
        让点击穿透到桌面（不挡其他应用）；落在模型不透明像素上则正常命中（可拖拽/右键）。
        仅影响命中测试、不改变任何绘制 —— 气泡/聊天等子控件照常显示与交互。
        """
        if eventType == b"windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x84:  # WM_NCHITTEST
                    gp = QCursor.pos()
                    tl = self.mapToGlobal(QPoint(0, 0))
                    lx = gp.x() - tl.x()
                    ly = gp.y() - tl.y()
                    if 0 <= lx < self.width() and 0 <= ly < self.height():
                        if self._alpha_at(lx, ly) < 24:
                            # HTTRANSPARENT = -1：穿透到下层窗口
                            return ctypes.c_void_p(-1), True  # HTTRANSPARENT=-1：穿透到下层窗口。PySide6 nativeEvent 须返回 (c_void_p/int, bool)；返回 bytes 系统不采纳 → 点击不穿透（穿透失效根因）
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

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
            self._active_manual_exprs = set()
            self._emotion_expr = None
            self.model.LoadModelJson(self._model_path)
            self.model.Resize(int(self.CANVAS_W / self.ZOOM_PAD), int(self.CANVAS_H / self.ZOOM_PAD))
            self.model.SetAutoBreathEnable(True)
            self.model.SetAutoBlinkEnable(True)
            self.model.StartRandomMotion("Idle", 3)
            # 切换模型后必须重建表情/动作数据源，否则右击菜单会死绑上一份模型
            self._inject_discovered_actions()
            self._init_expression_map()
            self._apply_default_expressions()
            if getattr(self, "_idle", None) is not None:
                self._idle.reset(self.model)
            log.info(f"模型切换: {self._model_path}")
            from desktop_core.motion_engine import PoseEngine
            from desktop_core.engine.ecs import World
            from desktop_core.engine.transform import Transform
            from desktop_core.engine.skeleton import build_skeleton, set_pose, get_bone_angles, SkeletalAnimator, WalkCycle, WalkSystem, _collect_all
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
                        # 情绪表情用单槽替换，但用 Add/Remove 增量管理：
                        # 只替换上一句的情绪表情，绝不顶掉用户手动勾选的常驻表情（如 水印）
                        if self._emotion_expr and self._emotion_expr != expr:
                            try:
                                self.model.RemoveExpression(self._emotion_expr)
                            except Exception:
                                pass
                        if expr != self._emotion_expr:
                            try:
                                self.model.AddExpression(expr)
                                self._emotion_expr = expr
                            except Exception as e:
                                log.warning(f"[桌宠] 情绪表情失败 {expr}: {e}")
                    mg = msg.get("motion_group", "")
                    mi = msg.get("motion_index", -1)
                    # 优先 Pose 引擎驱动
                    action = msg.get("action", "")
                    if action:
                        # 骨骼动画驱动
                        set_pose(self._skeleton_root, action)
                        if action == "walk":
                            self._skeleton_root.add(WalkCycle())
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
