# -*- coding: utf-8 -*-
"""ui_grounding.py — UI 元素精确定位（模板匹配）+ 可靠点击 + 帧反应检测
====================================================================

基于被大量真实游戏 bot 验证的「OpenCV 模板匹配」轮子：

  参考项目（均使用 cv2.matchTemplate 做精确 UI 定位）：
    - xjskp-auto（向僵尸开炮）：多模板备份、阈值可配、fallback坐标、重试逻辑
      https://github.com/970253185/xjskp-auto
    - genshin-skip-animation：matchTemplate + MSS 截图、阈值/延迟全可配
      https://github.com/ace-trump-tech/genshin-skip-animation
    - blum-clicker：模板匹配 + PyAutoGUI、动态缩放适配
      https://github.com/yankkvx/blum-clicker
    - Audition-VTC-Autokey：实时按键触发、matchTemplate + Windows SendInput
      https://github.com/pravrilgreen/Audition-VTC-Autokey-Python
    - Python-Game-Bot（Clash of Clans）：sigmoid 人类化移动 + 模板匹配
      https://github.com/Tanmoy-Mondal-07/Python-Game-Bot

  架构参考：
    - Cradle（BAAI-Agents）：感知→决策→反思→执行→记忆，纯屏幕输入范式
      https://github.com/BAAI-Agents/Cradle
    - SerpentAI：游戏插件(Game)→代理(Agent)→帧处理器(FrameHandler)
      https://github.com/SerpentAI

  为什么不用 OmniParser / UI-TARS / YOLO-based 方案？
    - OmniParser V2 的 icon_detect 继承自 YOLO → AGPL-3.0 许可（用户红线禁止）
    - UI-TARS 需要部署 VLM 推理服务（~6.9s/元素，太慢且需 GPU）
    - 本模块零模型依赖、离线运行、<50ms/次定位、Apache-2.0 纯净许可

核心原理：
  对每个 UI 元素截取一次小模板图（推荐 40~80px 见方），之后每帧用
  cv2.matchTemplate(TM_CCOEFF_NORMED) 在屏幕截图中查找该模板的精确位置。
  返回屏幕绝对坐标（已处理 DPI 缩放 + 双显示器偏移）。
  不再猜坐标——坐标由视觉匹配决定。

用法示例：
  >>> engine = UIGroundingEngine("Mindustry", template_dir="ui_templates/mindustry")
  >>> engine.calibrate("pause_btn", (900, 8, 1020, 48))   # 截屏区域存为模板
  >>> result = engine.click("pause_btn")                     # 定位+点击+验证
  >>> print(result)  # MatchResult(ok=True, cx=960, cy=28, conf=0.97, method='menu_hold')

依赖：opencv-python (Apache-2.0), numpy (BSD), PIL (Pillow BSD)
无 AGPL 代码、无正则表达式、无需 VLM/模型推理。
"""

import ctypes
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List, Dict, Any

import numpy as np
import cv2
from PIL import ImageGrab

log = logging.getLogger("ui_grounding")

# ── Windows API 最小集合 ──
_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
_kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
_gdi32 = ctypes.windll.gdi32 if hasattr(ctypes, "windll") else None


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ── 数据结构 ──
@dataclass
class MatchResult:
    """模板匹配结果。"""
    ok: bool = False
    name: str = ""
    # 窗口内局部坐标（image space）
    cx: int = 0          # 匹配中心 X（窗口内）
    cy: int = 0          # 匹配中心 Y（窗口内）
    w: int = 0           # 匹配宽度
    h: int = 0           # 匹配高度
    confidence: float = 0.0   # TM_CCOEFF_NORMED 值 (0~1)
    # 屏幕绝对坐标（虚拟屏空间）
    screen_x: int = 0
    screen_y: int = 0
    method_used: str = ""     # 使用的匹配方法/缩放
    scale: float = 1.0        # 实际匹配时的缩放比


@dataclass
class ClickResult:
    """点击结果（含验证）。"""
    ok: bool = False
    name: str = ""
    match: MatchResult = field(default_factory=MatchResult)
    attempts: int = 0
    frame_diff: float = 0.0       # 点击前后帧差（变化量）
    method_used: str = ""         # 实际使用的点击方法
    detail: str = ""


@dataclass
class TemplateDef:
    """单个模板定义（manifest 中的一条）。"""
    name: str = ""
    file: str = ""                # PNG 文件名（相对 template_dir）
    # 点击偏移（相对于模板中心）。默认 (0,0)=点模板中心。
    # 设为 (dx,dy) 可微调（如按钮文字偏上，实际可点区域在文字下方）。
    click_offset: Tuple[int, int] = (0, 0)
    # 交互方式（不同 UI 层需要不同方法——这是从 Mindustry 导航中得出的关键经验）
    interaction: str = "auto"    # auto|menu_hold|planet_hold|double_click|postmsg|click
    hold_ms: int = 200           # 按住时长（ms）
    # 多模板备份（同名不同裁剪，提高识别率）
    alt_files: List[str] = field(default_factory=list)
    # fallback：模板完全找不到时按窗口比例计算的备选位置 (rx, ry, 0~1)
    fallback_ratio: Optional[Tuple[float, float]] = None
    # 匹配阈值（0~1，越高越严格）
    threshold: float = 0.8
    # 搜索区域限制（窗口比例 (x1,y1,x2,y2)，None=全屏搜索）
    search_region: Optional[Tuple[float, float, float, float]] = None


@dataclass
class EventResult:
    """事件检测结果（帧反应）。"""
    detected: bool = False
    name: str = ""
    confidence: float = 0.0
    location: Optional[Tuple[int, int]] = None


# ── 屏幕/DPI/双显示器 工具 ──
def set_dpi_aware():
    """设置进程为 Per-Monitor DPI Aware（必须在使用任何 Win32 API 前调用一次）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            _user32.SetProcessDPIAware() if _user32 else None
        except Exception:
            pass


def get_virtual_screen():
    """返回虚拟屏信息：(x_origin, y_origin, width, height)。"""
    if not _user32:
        return (0, 0, 1920, 1080)
    vx = _user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    vy = _user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    vw = _user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    vh = _user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
    return (vx, vy, vw, vh)


def get_window_rect(hwnd):
    """获取窗口矩形 (left, top, right, bottom)。失败返回 None。"""
    if not hwnd or not _user32:
        return None
    r = RECT()
    if _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return (r.left, r.top, r.right, r.bottom)
    return None


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_client_rect(hwnd):
    """返回客户端区域屏幕 bbox (x1, y1, x2, y2)（去掉标题栏/边框，准确对应游戏画布）。

    最大化窗口下即游戏实际可见画布；用它做截屏与坐标换算，避免 8px 边框/标题栏偏移。
    """
    if not hwnd or not _user32:
        return None
    r = RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = _POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + r.right, pt.y + r.bottom)


def capture_window(hwnd, region=None):
    """截取窗口【客户端区域】画面（DPI-aware，双显示器安全）。

    ⚠️ 关键修复（2026-08-05）：Mindustry 用 LWJGL/OpenGL 渲染，GDI 按窗口 DC 的
    ImageGrab.grab(bbox=client_rect) 抓到的是【空白/窗口背景色】——抓不到 OpenGL 表面
    （独立像素分析证实：窗口 DC 截图整帧全亮、零暗色按钮；而整屏截图 white=0.073 偏暗
    = 真实游戏画面）。因此改为「抓整屏（DWM 合成含游戏画面）→ 裁到客户区」。
    此方式已用独立监控交叉验证可行。

    Args:
        hwnd: 目标窗口句柄。
        region: 可选，(x1,y1,x2,y2) 窗口内局部区域。None=整个客户端区域。

    Returns:
        numpy.ndarray BGR 图像（shape: HxWx3）。
    """
    bbox = get_client_rect(hwnd)
    if bbox is None:
        return None
    try:
        try:
            full = ImageGrab.grab(all_screens=True)  # 整虚拟屏：DWM 合成含 OpenGL 游戏画面
        except TypeError:
            full = ImageGrab.grab()
        full_np = np.array(full)
    except Exception as e:
        log.warning(f"[ui_grounding] 全屏截图失败: {e}")
        return None
    H, W = full_np.shape[:2]
    fx1, fy1, fx2, fy2 = bbox
    # 防越界（多显示器/坐标异常）
    fx1 = max(0, min(int(fx1), W - 1)); fy1 = max(0, min(int(fy1), H - 1))
    fx2 = max(fx1 + 1, min(int(fx2), W)); fy2 = max(fy1 + 1, min(int(fy2), H))
    crop = full_np[fy1:fy2, fx1:fx2]
    if crop.size == 0:
        return None
    if region:
        bx1, by1, bx2, by2 = region
        crop = crop[by1:by2, bx1:bx2]
        if crop.size == 0:
            return None
    # PIL 给出 RGB，OpenCV 要 BGR
    return cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)


def capture_screen_region(x1, y1, x2, y2):
    """截取屏幕绝对坐标区域（虚拟屏空间）。用于校准时截取模板。

    注意：若目标是 OpenGL 游戏画面，bbox 截图同样抓不到（见 capture_window）；
    仅对 GDI/普通 UI 元素有效。游戏内元素请用 capture_window。
    """
    img = np.array(ImageGrab.grab(bbox=(x1, y1, x2, y2)))
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


# ── 窗口管理（遮挡处理 + LWJGL 激活） ──
def find_window(title_substr: str):
    """枚举顶层可见窗口，返回标题含 substr 的第一个 hwnd。"""
    if not _user32:
        return None
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def enum_cb(hwnd, _lp):
        if not _user32.IsWindowVisible(hwnd):
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value or ""
        if title_substr.lower() in title.lower():
            found.append(hwnd)
        return True

    _user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return found[0] if found else None


def focus_window_with_attach(hwnd):
    """用 AttachThreadInput 方法强制聚焦窗口到前台。

    重要：本函数【绝不】调用 ShowWindow(SW_RESTORE/SW_MINIMIZE 等)。
    原因：SW_RESTORE(9) 会把用户手动最小化的窗口恢复——用户一旦最小化浏览器，
    每次 focus 都把浏览器弹回来 = 骚扰用户桌面（已踩坑）。
    只做 SetForegroundWindow 改变 Z-order，不改变窗口的显示状态。
    """
    if not _user32 or not hwnd:
        return False
    try:
        fg = _user32.GetForegroundWindow()
        if fg == hwnd:
            return True
        fore_thread = _user32.GetWindowThreadProcessId(fg, None)
        app_thread = _kernel32.GetCurrentThreadId() if _kernel32 else 0
        if fore_thread != app_thread:
            _user32.AttachThreadInput(fore_thread, app_thread, True)
            time.sleep(0.05)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        # 注意：这里【不再】调 ShowWindow(hwnd, 9) 即 SW_RESTORE！
        # SW_RESTORE 会恢复用户已最小化的窗口（浏览器等），导致"我最小化你就给我打开"。
        # 若目标窗口确实被最小化了，应由调用方显式决定是否恢复（如 maximize_game_window 的 SW_MAXIMIZE 已隐含恢复）。
        time.sleep(0.15)
        if fore_thread != app_thread:
            _user32.AttachThreadInput(fore_thread, app_thread, False)
        return _user32.GetForegroundWindow() == hwnd
    except Exception as e:
        log.warning(f"[ui_grounding] 聚焦失败: {e}")
        return False


def activate_window_internal(hwnd):
    """LWJGL/SDL 游戏窗口内部激活：先点击窗口中心「唤醒」。

    经验教训：即使窗口在前台，LWJGL 可能未处理输入。
    需要先在窗口内做一次普通点击来激活内部输入状态。
    之后的长按/双击等操作才能生效。
    """
    if not _user32 or not hwnd:
        return False
    rect = get_window_rect(hwnd)
    if rect is None:
        return False
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    _user32.SetCursorPos(cx, cy)
    time.sleep(0.03)
    _user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.06)
    _user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
    time.sleep(0.6)  # 等待 LWJGL 内部激活
    return True


def ensure_window_ready(hwnd, title_substr=None):
    """窗口准备流程：聚焦到前台 → 激活内部 → 验证前台。

    重要：本函数【绝不】最小化/移动/触碰任何其它窗口（含浏览器）。
    仅对目标游戏窗口自身做置顶与内部激活，避免骚扰用户其它桌面窗口。

    Args:
        hwnd: 目标窗口句柄。
        title_substr: 用于 find_window 的标题子串（如果 hwnd 为 None 时自动查找）。

    Returns:
        bool: 窗口是否就绪（前台可见且激活）。
    """
    if hwnd is None and title_substr:
        hwnd = find_window(title_substr)
    if hwnd is None:
        log.error(f"[ui_grounding] 找不到窗口 '{title_substr}'")
        return False

    # Step 1: 聚焦到前台（AttachThreadInput 抢前台，不碰其它窗口）
    focus_window_with_attach(hwnd)
    time.sleep(0.2)

    # Step 2: 内部激活点击（LWJGL/SDL 输入唤醒）
    activate_window_internal(hwnd)

    # Step 3: 验证
    ready = _user32.GetForegroundWindow() == hwnd if _user32 else False
    if not ready:
        log.warning("[ui_grounding] 窗口可能未就绪（非前台）")
    return ready


# ── 输入方法（复用 action_lib 原语模式，扩展交互方式） ──
def input_set_cursor_and_click(screen_x, screen_y,
                                hold_ms: int = 200,
                                button: str = "left"):
    """SetCursorPos + mouse_event 点击（基础方法，适用于大多数场景）。

    Args:
        screen_x, screen_y: 虚拟屏绝对坐标。
        hold_ms: 按住时长(ms)。
        button: "left" 或 "right"。
    """
    if not _user32:
        return
    _user32.SetCursorPos(int(screen_x), int(screen_y))
    time.sleep(max(30, hold_ms * 0.1))
    if button == "right":
        _user32.mouse_event(0x0008, 0, 0, 0, 0)   # RIGHTDOWN
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(0x0010, 0, 0, 0, 0)   # RIGHTUP
    else:
        _user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def input_double_click(screen_x, screen_y, gap_ms: int = 80):
    """双击（适用于 Mindustry 扇区选择等需要双击的 UI）。"""
    if not _user32:
        return
    _user32.SetCursorPos(int(screen_x), int(screen_y))
    time.sleep(0.04)
    _user32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(0x0004, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(0x0002, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(0x0004, 0, 0, 0, 0)


def input_postmessage_click(hwnd, client_x, client_y):
    """PostMessage WM_LBUTTONDOWN/UP（适用于对话框按钮等标准 Win32 控件）。

    注意：对 LWJGL 自绘 UI 通常无效（只触发悬停不触发点击）。
    对标准对话框（如 Mindustry 的「确定」弹窗）有效。
    """
    if not _user32 or not hwnd:
        return
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    _user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
    time.sleep(0.15)
    _user32.PostMessageW(hwnd, 0x0202, 0x0000, lparam)  # WM_LBUTTONUP


def input_sendinput_click(screen_x, screen_y, hold_ms: int = 200):
    """SendInput 硬件级模拟（归一化双屏坐标）。

    适用于 SetCursorPos + mouse_event 无效的场景（某些游戏只接受硬件级输入）。
    自动处理双显示器虚拟屏尺寸（3840x1080 等）。
    """
    if not _user32:
        return
    vx, vy, vw, vh = get_virtual_screen()
    nx = int((screen_x - vx) * 65535 / vw)
    ny = int((screen_y - vy) * 65535 / vh)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long), ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]
    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        _anonymous_ = ("_input",)
        _fields_ = [("type", ctypes.c_ulong), ("_input", _U)]

    md = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000, 0, None)  # MOVEABSOLUTE | LEFTDOWN
    mu = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8002, 0, None)  # MOVEABSOLUTE | LEFTUP
    id_ = INPUT(0); id_.mi = md
    iu = INPUT(0); iu.mu = mu
    _user32.SendInput(1, ctypes.byref(id_), ctypes.sizeof(INPUT))
    time.sleep(hold_ms / 1000.0)
    _user32.SendInput(1, ctypes.byref(iu_), ctypes.sizeof(INPUT))


# ── 模板匹配引擎 ──
def match_template_single(screen_img, template_img, threshold=0.8):
    """单次模板匹配（无多尺度）。

    Returns:
        (cx, cy, w, h, confidence) 或 None（未找到）。
    """
    if screen_img is None or template_img is None:
        return None
    th, tw = template_img.shape[:2]
    sh, sw = screen_img.shape[:2]
    if th > sh or tw > sw:
        return None
    result = cv2.matchTemplate(screen_img, template_img, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    mx, my = max_loc
    cx, cy = mx + tw // 2, my + th // 2
    return (cx, cy, tw, th, float(max_val))


def match_template_multiscale(screen_img, template_img, threshold=0.8,
                               scales=(0.85, 0.92, 1.0, 1.08, 1.15)):
    """多尺度模板匹配（应对分辨率微小差异）。

    Returns:
        最佳 (cx, cy, w, h, confidence, scale) 或 None。
    """
    best = None
    for scale in scales:
        if scale == 1.0:
            resized = template_img
        else:
            new_w = int(template_img.shape[1] * scale)
            new_h = int(template_img.shape[0] * scale)
            resized = cv2.resize(template_img, (new_w, new_h),
                                 interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        m = match_template_single(screen_img, resized, threshold)
        if m is not None:
            cx, cy, tw, th, conf = m
            if best is None or conf > best[4]:
                best = (cx, cy, tw, th, conf, scale)
    return best


# ── 模板库管理 ──
class TemplateLibrary:
    """模板库：管理 PNG 模板文件 + JSON manifest。

    目录结构：
      template_dir/
        manifest.json          # 元数据（名称、交互方式、阈值等）
        pause_btn.png          # 模板图片
        launch_btn.png
        ...
    """

    def __init__(self, template_dir: str):
        self.template_dir = template_dir
        self.manifest_path = os.path.join(template_dir, "manifest.json")
        self.templates: Dict[str, TemplateDef] = {}
        os.makedirs(template_dir, exist_ok=True)
        self._load_manifest()

    def _load_manifest(self):
        if not os.path.exists(self.manifest_path):
            return
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("templates", []):
                td = TemplateDef(**{k: v for k, v in item.items()
                                   if k in TemplateDef.__dataclass_fields__})
                self.templates[td.name] = td
        except Exception as e:
            log.warning(f"[ui_grounding] manifest 加载失败: {e}")

    def save_manifest(self):
        data = {"templates": [asdict(t) for t in self.templates.values()]}
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"[ui_grounding] manifest 保存失败: {e}")

    def add_template(self, tdef: TemplateDef):
        self.templates[tdef.name] = tdef
        self.save_manifest()

    def get_template(self, name: str) -> Optional[TemplateDef]:
        return self.templates.get(name)

    def list_templates(self) -> List[str]:
        return list(self.templates.keys())

    def load_image(self, filename: str) -> Optional[np.ndarray]:
        path = os.path.join(self.template_dir, filename)
        if not os.path.exists(path):
            return None
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            log.warning(f"[ui_grounding] 无法读取模板图片: {path}")
        return img

    def calibrate(self, name: str, screen_img, x1: int, y1: int, x2: int, y2: int,
                 interaction: str = "auto", hold_ms: int = 200,
                 threshold: float = 0.8, click_offset: Tuple[int, int] = (0, 0)):
        """从当前截图中裁剪一个区域保存为模板。

        Args:
            name: 模板名称（唯一标识符）。
            screen_img: 当前屏幕截图（numpy BGR）。
            x1,y1,x2,y2: 裁剪区域（screen_img 的像素坐标，即窗口内局部坐标）。
            interaction: 交互方式。
            hold_ms: 按住时长。
            threshold: 匹配阈值。
            click_offset: 点击偏移（相对于模板中心）。
        """
        crop = screen_img[y1:y2, x1:x2]
        if crop.size == 0:
            raise ValueError(f"校准区域无效: ({x1},{y1},{x2},{y2})")

        filename = f"{name}.png"
        filepath = os.path.join(self.template_dir, filename)
        cv2.imwrite(filepath, crop)

        tdef = TemplateDef(
            name=name, file=filename, click_offset=click_offset,
            interaction=interaction, hold_ms=hold_ms,
            threshold=threshold,
        )
        self.add_template(tdef)
        log.info(f"[ui_grounding] 校准完成: '{name}' -> {filename} "
                  f"({x2-x1}x{y2-y1}px) interaction={interaction}")
        return tdef

    def calibrate_batch(self, items: List[Dict], screen_img):
        """批量校准。

        items: [{"name":str, "rect":(x1,y1,x2,y2), "interaction":str, ...}, ...]
        跳过无效区域（坐标超出屏幕范围），不中断批量操作。
        """
        results = []
        h, w = screen_img.shape[:2]
        for item in items:
            x1, y1, x2, y2 = item["rect"]
            if x1 < 0 or y1 < 0 or x2 > w or y2 > h or x2 <= x1 or y2 <= y1:
                log.warning(f"[ui_grounding] 校准跳过 '{item.get('name','?')}': "
                           f"区域({x1},{y1},{x2},{y2}) 超出图像({w}x{h})")
                continue
            try:
                tdef = self.calibrate(
                    name=item["name"], screen_img=screen_img,
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    interaction=item.get("interaction", "auto"),
                    hold_ms=item.get("hold_ms", 200),
                    threshold=item.get("threshold", 0.8),
                    click_offset=tuple(item.get("click_offset", (0, 0))),
                )
                results.append(tdef)
            except Exception as e:
                log.warning(f"[ui_grounding] 校准失败 '{item.get('name','?')}': {e}")
        return results


# ── 主引擎 ──
class UIGroundingEngine:
    """UI 精确定位 + 点击 + 帧反应引擎。

    把「截图→定位→点击→验证」封装成可靠的工作流。
    """

    def __init__(self, window_title: str, template_dir: str = None):
        self.window_title = window_title
        self.hwnd = None
        self.window_rect = None
        if template_dir is None:
            base = os.path.dirname(os.path.abspath(__file__))
            template_dir = os.path.join(base, "ui_templates", window_title.lower())
        self.library = TemplateLibrary(template_dir)
        set_dpi_aware()

    def _refresh_window(self):
        """刷新窗口句柄与【客户端】矩形（用于截屏与坐标换算）。"""
        self.hwnd = find_window(self.window_title)
        if self.hwnd:
            self.window_rect = get_client_rect(self.hwnd)
        return self.hwnd is not None

    def capture(self, region=None):
        """截图（自动处理 DPI + 双屏）。"""
        if not self._refresh_window():
            return None
        return capture_window(self.hwnd, region=region)

    def prepare(self):
        """完整窗口准备（聚焦→激活→验证）。绝不最小化/移动任何其它窗口。"""
        if not self._refresh_window():
            return False
        return ensure_window_ready(self.hwnd, title_substr=self.window_title)

    def locate(self, name: str, screen_img=None, threshold=None,
               multiscale: bool = True) -> MatchResult:
        """定位一个 UI 元素。

        Args:
            name: 模板名称。
            screen_img: 当前截图（None 则自动截取）。
            threshold: 匹配阈值（None 用模板定义值）。
            multiscale: 是否启用多尺度匹配。

        Returns:
            MatchResult（含窗口内坐标 + 屏幕绝对坐标）。
        """
        result = MatchResult(name=name)
        tdef = self.library.get_template(name)
        if tdef is None:
            log.warning(f"[ui_grounding] 未找到模板: '{name}'")
            return result

        if screen_img is None:
            screen_img = self.capture()
        if screen_img is None:
            return result

        thresh = threshold or tdef.threshold

        # 尝试主模板 + 备选模板
        candidates = [tdef.file] + tdef.alt_files
        best_match = None

        for fname in candidates:
            tpl = self.library.load_image(fname)
            if tpl is None:
                continue

            # 限定搜索区域
            search_img = screen_img
            offset_x, offset_y = 0, 0
            if tdef.search_region:
                rx1, ry1, rx2, ry2 = tdef.search_region
                h, w = screen_img.shape[:2]
                sx1, sy1 = int(rx1 * w), int(ry1 * h)
                sx2, sy2 = int(rx2 * w), int(ry2 * h)
                search_img = screen_img[sy1:sy2, sx1:sx2]
                offset_x, offset_y = sx1, sy1

            if multiscale:
                m = match_template_multiscale(search_img, tpl, thresh)
            else:
                m = match_template_single(search_img, tpl, thresh)

            if m is not None:
                cx, cy, tw, th, conf, scale = m if len(m) == 6 else (*m, 1.0)
                if best_match is None or conf > best_match[4]:
                    best_match = (cx + offset_x, cy + offset_y, tw, th, conf,
                                  scale, fname)

        if best_match is None:
            # Fallback：按比例计算
            if tdef.fallback_ratio and self.window_rect:
                rx, ry = tdef.fallback_ratio
                ww = self.window_rect[2] - self.window_rect[0]
                wh = self.window_rect[3] - self.window_rect[1]
                fx, fy = int(rx * ww), int(ry * wh)
                result.cx, result.cy = fx, fy
                result.screen_x = fx + self.window_rect[0]
                result.screen_y = fy + self.window_rect[1]
                result.confidence = 0.0
                result.method_used = "fallback_ratio"
                log.info(f"[ui_grounding] '{name}' 使用 fallback 位置 ({fx},{fy})")
            return result

        cx, cy, tw, th, conf, scale, used_file = best_match
        result.ok = True
        result.cx, result.cy = cx, cy
        result.w, result.w = tw, th
        result.confidence = conf
        result.scale = scale
        result.method_used = f"matchTemplate_{used_file}_scale{scale:.2f}"

        # 转换为屏幕绝对坐标
        if self.window_rect:
            result.screen_x = cx + self.window_rect[0]
            result.screen_y = cy + self.window_rect[1]

        ox, oy = tdef.click_offset
        result.screen_x += ox
        result.screen_y += oy

        log.debug(f"[ui_grounding] 定位 '{name}': "
                   f"img({cx},{cy}) screen({result.screen_x},{result.screen_y}) "
                   f"conf={conf:.3f} scale={scale:.2f}")
        return result

    def _pick_interaction_method(self, tdef: TemplateDef) -> str:
        """根据模板定义或启发式规则选择点击方法。"""
        method = tdef.interaction
        if method != "auto":
            return method
        # 启发式：根据名称推断
        name_lower = tdef.name.lower()
        if "sector" in name_lower or "hex" in name_lower:
            return "double_click"
        if "planet" in name_lower or "card" in name_lower:
            return "planet_hold"
        if "dialog" in name_lower or "confirm" in name_lower or "ok" in name_lower:
            return "postmsg"
        if "menu" in name_lower or "btn" in name_lower or "button" in name_lower:
            return "menu_hold"
        return "menu_hold"

    def click(self, name: str, *, hold_ms: int = None, method: str = None,
              verify: bool = True, verify_threshold: float = 3.0,
              max_retries: int = 3, retry_perturb: int = 5,
              prepare_window: bool = True) -> ClickResult:
        """定位并点击一个 UI 元素（含验证 + 重试）。

        这是主要对外接口。工作流：
          1. 准备窗口（可选）
          2. 截图前快照
          3. 模板匹配定位
          4. 选择并执行点击方法
          5. 截图后快照 + 帧差验证
          6. 若验证失败：轻微偏移重试（最多 N 次）

        Args:
            name: 模板名称。
            hold_ms: 按住时长（覆盖模板默认值）。
            method: 点击方法（覆盖自动选择）。
            verify: 是否做帧差验证。
            verify_threshold: 帧差判定阈值（>此值认为画面变了=点击生效）。
            max_retries: 最大重试次数。
            retry_perturb: 重试时随机偏移范围(px)。
            prepare_window: 是否先调用 prepare().

        Returns:
            ClickResult。
        """
        result = ClickResult(name=name)
        tdef = self.library.get_template(name)
        if tdef is None:
            result.detail = f"模板 '{name}' 不存在"
            return result

        if prepare_window:
            self.prepare()

        # 截图前快照
        img_before = self.capture()
        if img_before is None:
            result.detail = "截图失败"
            return result

        hold = hold_ms or tdef.hold_ms
        click_method = method or self._pick_interaction_method(tdef)

        for attempt in range(max_retries + 1):
            result.attempts = attempt + 1

            # 定位
            mr = self.locate(name, screen_img=img_before)
            result.match = mr

            if not mr.ok and mr.method_used != "fallback_ratio":
                result.detail = f"第{attempt+1}次: 未找到模板 (best_conf < {tdef.threshold})"
                time.sleep(0.3)
                continue

            sx, sy = mr.screen_x, mr.screen_y

            # 重试时加随机扰动
            if attempt > 0 and retry_perturb > 0:
                import random
                sx += random.randint(-retry_perturb, retry_perturb)
                sy += random.randint(-retry_perturb, retry_perturb)

            # 执行点击
            log.info(f"[ui_grounding] 点击 '{name}' 第{attempt+1}次 "
                     f"screen({sx},{sy}) method={click_method} hold={hold}ms")

            if click_method == "postmsg" and self.hwnd:
                # PostMessage 用客户端坐标
                cx_local = sx - self.window_rect[0] if self.window_rect else sx
                cy_local = sy - self.window_rect[1] if self.window_rect else sy
                input_postmessage_click(self.hwnd, cx_local, cy_local)
            elif click_method == "double_click":
                input_double_click(sx, sy)
            elif click_method == "planet_hold":
                input_set_cursor_and_click(sx, sy, hold_ms=max(hold, 500))
            elif click_method == "sendinput":
                input_sendinput_click(sx, sy, hold_ms=hold)
            else:  # menu_hold / click
                input_set_cursor_and_click(sx, sy, hold_ms=hold)

            result.method_used = click_method

            # 等待渲染
            time.sleep(0.5)

            # 验证
            if verify:
                img_after = self.capture()
                if img_after is not None:
                    diff = float(np.mean(np.abs(
                        img_after.astype(float) - img_before.astype(float))))
                    result.frame_diff = diff
                    if diff >= verify_threshold:
                        result.ok = True
                        result.detail = (f"第{attempt+1}次成功 "
                                        f"(conf={mr.confidence:.3f}, diff={diff:.1f})")
                        log.info(f"[ui_grounding] ✅ '{name}' 点击成功: "
                                 f"diff={diff:.1f} >= {verify_threshold}")
                        break
                    else:
                        log.info(f"[ui_grounding] ❌ 第{attempt+1}次未通过验证 "
                                 f"(diff={diff:.1f} < {verify_threshold})")
                        # 更新 before 截图以便下次比较
                        img_before = img_after
                else:
                    result.detail = "验证截图失败"
            else:
                result.ok = True
                break

        if not result.ok and not result.detail:
            result.detail = (f"全部 {max_retries+1} 次尝试均未通过验证 "
                             f"(最后一次 diff={result.frame_diff:.1f})")
        return result

    def detect_event(self, name: str, screen_img=None,
                     threshold: float = None) -> EventResult:
        """检测某个事件/状态是否出现（帧反应）。

        例如：检测"波次来袭"横幅、"核心受攻击"警告等。
        返回是否检测到及置信度/位置。
        """
        res = EventResult(name=name)
        mr = self.locate(name, screen_img=screen_img, threshold=threshold)
        res.detected = mr.ok
        res.confidence = mr.confidence
        if mr.ok:
            res.location = (mr.screen_x, mr.screen_y)
        return res

    def calibrate_from_screen(self, name: str, x1: int, y1: int, x2: int, y2: int,
                              **kwargs):
        """便捷方法：截取当前屏幕并校准一个模板。"""
        screen = self.capture()
        if screen is None:
            raise RuntimeError("无法截图")
        return self.library.calibrate(name, screen, x1, y1, x2, y2, **kwargs)

    def calibrate_many(self, items: List[Dict]):
        """批量校准多个模板。"""
        screen = self.capture()
        if screen is None:
            raise RuntimeError("无法截图")
        return self.library.calibrate_batch(items, screen)


# ── 便捷入口 ──
def create_engine(window_title: str, template_dir: str = None) -> UIGroundingEngine:
    """创建引擎实例（设置 DPI awareness）。"""
    set_dpi_aware()
    return UIGroundingEngine(window_title, template_dir=template_dir)
