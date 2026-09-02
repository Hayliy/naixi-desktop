# -*- coding: utf-8 -*-
"""action_lib.py — 动作技能库 + 自校验（Voyager 思路，对齐单机约束）
================================================================

单机范式（见 naixi-game-agent-paradigm）：AI「看屏 + 像真人注入键鼠操控用户角色」，
绝不读游戏内部、绝不连服务端、绝不塞 bot。本模块把动作层抽成可复用、可单测的库：

  - 输入原语：press_key / click / move_mouse / find_window / focus_window（ctypes，零依赖）
  - 动作注册表 ACTION_DEFS：动作名 → 输入描述（单一真实来源，game_agent._execute 委托于此）
  - 安全护栏：safe_execute(require_window=True) 默认在无目标窗口时「安全中止」，
    绝不把键鼠打进用户当前的任意前台窗口（旧版 game_agent._execute 的隐患已修）
  - Voyager 式技能库：Skill(name, steps, verify) + SkillLibrary（持久化到 D 盘 data，不写 C 盘）
  - 自校验原语：verify_* 一律吃「独立第二证据源」（截图帧差 / 世界态 diff），
    不认动作模块自报——满足「禁止循环验证」铁则
"""
import ctypes
import json
import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger("action_lib")

# ── Windows 键鼠（ctypes，零依赖）──
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MOVE = 0x0001
ASFW_ANY = 0xFFFFFFFF

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
_kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None

# 虚拟键码：动作 token → VK（唯一真实来源）
VK_MAP = {
    "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "space": 0x20,
    "e": 0x45, "q": 0x51, "shift": 0x10, "ctrl": 0x11, "tab": 0x09,
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "f": 0x46, "r": 0x52,
    "esc": 0x1B, "enter": 0x0D, "left_click": "MOUSE_LEFT", "right_click": "MOUSE_RIGHT",
}

# 转视角相对鼠标位移（以典型灵敏度估算）：水平 350≈转约 45°，垂直 220≈抬头/低头约 30°
CAMERA = {
    "look_left": (-350, 0),
    "look_right": (350, 0),
    "look_up": (0, -220),
    "look_down": (0, 220),
}

# 动作注册表：单一真实来源。每个动作 = 一串输入描述。
# 描述格式：{"key": token, "hold": ms} / {"mouse": "MOUSE_LEFT"|"MOUSE_RIGHT", "hold": ms} / {"look": (dx, dy)}
# hold 默认 60ms；移动类 400ms（持续按住）；攻击/使用 600ms（长按以破坏方块）
ACTION_DEFS = {
    "forward": [{"key": "w", "hold": 400}],
    "back": [{"key": "s", "hold": 400}],
    "left": [{"key": "a", "hold": 400}],
    "right": [{"key": "d", "hold": 400}],
    "jump": [{"key": "space", "hold": 60}],
    "interact": [{"key": "e", "hold": 60}],
    "inventory": [{"key": "e", "hold": 60}],
    "attack": [{"mouse": "MOUSE_LEFT", "hold": 600}],
    "use": [{"mouse": "MOUSE_RIGHT", "hold": 600}],
    "drop": [{"key": "q", "hold": 60}],
    "slot1": [{"key": "1", "hold": 60}],
    "slot2": [{"key": "2", "hold": 60}],
    "slot3": [{"key": "3", "hold": 60}],
    "slot4": [{"key": "4", "hold": 60}],
    "look_left": [{"look": CAMERA["look_left"]}],
    "look_right": [{"look": CAMERA["look_right"]}],
    "look_up": [{"look": CAMERA["look_up"]}],
    "look_down": [{"look": CAMERA["look_down"]}],
    "wait": [],
    "screenshot_only": [],
}

# 安全白名单：只允许这些动作经 safe_execute 发出
ALLOWED_ACTIONS = set(ACTION_DEFS.keys())


# ───────────────────────── 窗口定位（只作用于找到的目标窗口） ─────────────────────────
def find_window(title_substr):
    """枚举顶层可见窗口，返回标题含 title_substr（小写）的第一个 hwnd，否则 None。"""
    if not _user32:
        return None
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def enum_cb(hwnd, _lparam):
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


def focus_window(hwnd):
    """把游戏窗口设为前台（keybd_event/mouse_event 只作用于前台窗口）。返回是否成功。"""
    if not _user32 or not hwnd:
        return False
    try:
        fg = _user32.GetForegroundWindow()
        if fg == hwnd:
            return True  # 已是前台，不破坏指针锁定
        if _kernel32:
            _user32.AllowSetForegroundWindow(ASFW_ANY)
            cur = _kernel32.GetCurrentThreadId()
            tgt = ctypes.c_int()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(tgt))
            if cur != tgt.value:
                _user32.AttachThreadInput(cur, tgt.value, True)
            _user32.SetForegroundWindow(hwnd)
            _user32.SetActiveWindow(hwnd)
            _user32.BringWindowToTop(hwnd)
            if cur != tgt.value:
                _user32.AttachThreadInput(cur, tgt.value, False)
        return _user32.GetForegroundWindow() == hwnd
    except Exception as e:
        log.warning(f"[action_lib] 聚焦窗口失败: {e}")
        return False


# ───────────────────────── 输入原语 ─────────────────────────
def move_mouse(dx: int, dy: int, hold_ms: int = 200):
    """相对鼠标移动（转视角）。分小步注入模拟连续移动，feed 进游戏的 raw input。"""
    if not _user32:
        return False
    steps = max(1, int(hold_ms / 20))
    sx, sy = int(dx / steps), int(dy / steps)
    for _ in range(steps):
        _user32.mouse_event(MOUSEEVENTF_MOVE, sx, sy, 0, 0)
        time.sleep(0.02)
    return True


def send_key(token: str, hold_ms: int = 60):
    """按下 token 对应 VK 并保持 hold_ms 后抬起（持续移动用）。"""
    vk = VK_MAP.get(token)
    if vk is None or not _user32:
        return False
    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(max(20, hold_ms) / 1000.0)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    return True


def send_mouse(button: str, hold_ms: int = 60):
    """按下/抬起鼠标键（MOUSE_LEFT / MOUSE_RIGHT）。"""
    if not _user32:
        return False
    if button == "MOUSE_LEFT":
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    elif button == "MOUSE_RIGHT":
        _user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    return True


# ── 扩展交互原语（供 ui_grounding 等上层模块使用） ──
def double_click_at(x: int, y: int, *, window_substr: str = "PlantsVsZombies",
                    require_window: bool = True, focus: bool = True,
                    gap_ms: int = 80):
    """双击绝对坐标（适用于扇区选择等需要双击的 UI 元素）。"""
    if not _user32:
        return {"ok": False, "reason": "no_user32"}
    hwnd = None
    if require_window:
        hwnd = find_window(window_substr)
        if hwnd is None:
            return {"ok": False, "reason": "no_window", "aborted": True}
        if focus and not focus_window(hwnd):
            log.warning("[action_lib] 聚焦失败")
    _user32.SetCursorPos(int(x), int(y))
    time.sleep(0.04)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0); time.sleep(gap_ms / 1000.0)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return {"ok": True, "reason": "double_clicked", "x": x, "y": y}


def postmsg_click_at(hwnd, client_x: int, client_y: int):
    """PostMessage WM_LBUTTONDOWN/UP 点击（适用于标准 Win32 对话框按钮）。

    注意：对 LWJGL 自绘 UI 通常无效（只触发悬停不触发点击）。
    对 Mindustry 的「确定」弹窗等对话框有效。
    """
    if not _user32 or not hwnd:
        return {"ok": False, "reason": "no_user32_or_hwnd"}
    lparam = (client_y << 16) | (client_x & 0xFFFF)
    _user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
    time.sleep(0.15)
    _user32.PostMessageW(hwnd, 0x0202, 0x0000, lparam)  # WM_LBUTTONUP
    return {"ok": True, "reason": "postmsg_clicked", "client": (client_x, client_y)}


def sendinput_click_at(x: int, y: int, *, hold_ms: int = 200):
    """SendInput 硬件级绝对坐标点击（归一化双屏坐标）。

    适用于 SetCursorPos + mouse_event 无效的场景。
    自动处理双显示器虚拟屏尺寸。
    """
    if not _user32:
        return {"ok": False, "reason": "no_user32"}
    vx = _user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    vy = _user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    vw = _user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    vh = _user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN

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

    nx = int((x - vx) * 65535 / vw)
    ny = int((y - vy) * 65535 / vh)
    md = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000, 0, None)
    mu = MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8002, 0, None)
    id_ = INPUT(0); id_.mi = md
    iu = INPUT(0); iu.mu = mu
    _user32.SendInput(1, ctypes.byref(id_), ctypes.sizeof(INPUT))
    time.sleep(hold_ms / 1000.0)
    _user32.SendInput(1, ctypes.byref(iu_), ctypes.sizeof(INPUT))
    return {"ok": True, "reason": "sendinput_clicked", "x": x, "y": y,
            "hold_ms": hold_ms}


def activate_window_internal(hwnd):
    """LWJGL/SDL 游戏内部激活：点击窗口中心唤醒输入状态。

    经验：即使窗口在前台，LWJGL 可能未处理外部注入的输入。
    需先在窗口内做一次普通点击来激活内部状态，之后操作才生效。
    """
    if not _user32 or not hwnd:
        return False
    r = RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    cx = (r.left + r.right) // 2
    cy = (r.top + r.bottom) // 2
    _user32.SetCursorPos(cx, cy)
    time.sleep(0.03)
    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.6)
    return True


def click_at(x: int, y: int, *, window_substr: str = "PlantsVsZombies",
             require_window: bool = True, focus: bool = True, button: str = "MOUSE_LEFT",
             hold_ms: int = 40):
    """绝对坐标点击（UI 固定游戏如 PvZ 用）。带窗口护栏：找不到目标窗口即安全中止。

    与 safe_execute 区别：动作是「移动到屏幕绝对坐标 (x,y) 并点击」，而非离散动作名。
    坐标须为屏幕绝对坐标（调用方负责把「窗口内相对坐标 + 窗口偏移」换算好）。
    返回结构化结果 dict，沿用 safe_execute 的安全中止语义。
    """
    if not _user32:
        return {"ok": False, "reason": "no_user32"}
    hwnd = None
    if require_window:
        hwnd = find_window(window_substr)
        if hwnd is None:
            return {"ok": False, "reason": "no_window", "aborted": True,
                    "detail": f"未找到标题含 '{window_substr}' 的窗口，安全中止"}
        if focus and not focus_window(hwnd):
            log.warning("[action_lib] 聚焦目标窗口失败，点击可能无效")
    _user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    if button == "MOUSE_RIGHT":
        _user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    else:
        _user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(max(20, hold_ms) / 1000.0)
        _user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return {"ok": True, "reason": "clicked", "x": x, "y": y, "hwnd": hwnd}


def safe_execute(action, *, window_substr: str = "minecraft", require_window: bool = True, focus: bool = True):
    """执行单个动作。返回结构化结果 dict（不负责「证明」自己成功——证明交给独立证据）。

    - require_window=True（默认，安全护栏）：找不到标题含 window_substr 的目标窗口就
      **安全中止**，绝不把键鼠打进用户当前的任意前台窗口（旧版 _execute 的隐患已修）。
    - focus：找到窗口是否置顶聚焦（键鼠只作用于前台窗口）。

    返回值示例：
      {"ok": True, "reason": "sent", "action": "forward", "hwnd": 123}
      {"ok": False, "reason": "no_window", "action": "forward", "aborted": True, ...}   # 安全中止
      {"ok": False, "reason": "not_allowed", "action": "rm -rf"}                        # 白名单拦截
    """
    if action not in ALLOWED_ACTIONS:
        return {"ok": False, "reason": "not_allowed", "action": action}
    defs = ACTION_DEFS.get(action, [])
    if not defs:
        return {"ok": True, "reason": "noop", "action": action}
    # 目标窗口：默认要求存在，否则安全中止
    hwnd = None
    if require_window:
        hwnd = find_window(window_substr)
        if hwnd is None:
            return {"ok": False, "reason": "no_window", "action": action, "aborted": True,
                    "detail": f"未找到标题含 '{window_substr}' 的窗口，安全中止（不注入任意前台窗口）"}
        if focus and not focus_window(hwnd):
            log.warning("[action_lib] 聚焦目标窗口失败，输入可能无效")
    # 发输入
    for d in defs:
        if "look" in d:
            dx, dy = d["look"]
            move_mouse(dx, dy)
        elif "mouse" in d:
            send_mouse(d["mouse"], hold_ms=d.get("hold", 60))
        elif "key" in d:
            send_key(d["key"], hold_ms=d.get("hold", 60))
    return {"ok": True, "reason": "sent", "action": action, "hwnd": hwnd}


# ───────────────────────── Voyager 式技能库 + 自校验 ─────────────────────────
@dataclass
class Skill:
    """一个可复用技能：一串动作 + 一个自校验策略。
    verify 取值："" / "screen_motion" / "threat_reduced" / "window_focus"。
    自校验的证据由调用方在动作前后采集（独立第二证据源），本类不自证。"""
    name: str
    steps: list = field(default_factory=list)        # 动作名列表
    verify: str = ""
    description: str = ""
    created_at: float = 0.0

    def to_dict(self):
        return {"name": self.name, "steps": self.steps, "verify": self.verify,
                "description": self.description, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d["name"], steps=d.get("steps", []), verify=d.get("verify", ""),
                   description=d.get("description", ""), created_at=d.get("created_at", 0.0))


class SkillLibrary:
    """技能持久化库（JSON，存 D 盘 data，不写 C 盘）。进程内去重，按 name 索引。"""

    def __init__(self, path: str = None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "action_skills.json")
        self._skills = {}
        self.load()

    def register(self, skill: Skill):
        self._skills[skill.name] = skill
        self.save()
        return skill

    def get(self, name: str):
        return self._skills.get(name)

    def list(self):
        return list(self._skills.values())

    def load(self):
        self._skills = {}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for d in json.load(f):
                    s = Skill.from_dict(d)
                    self._skills[s.name] = s
        except Exception as e:
            log.warning(f"[action_lib] 技能库加载失败: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([s.to_dict() for s in self._skills.values()],
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"[action_lib] 技能库保存失败: {e}")


def default_skills():
    """开箱即用的可复用技能（Voyager 思路：把常见玩法封装成原语组合）。"""
    return [
        Skill("turn_and_advance", ["look_right", "forward", "forward"],
              verify="screen_motion", description="转视角找路后前进两步"),
        Skill("strafe_left", ["left", "left"], verify="screen_motion", description="左移两步"),
        Skill("attack_and_collect", ["attack", "use"], verify="screen_motion",
              description="攻击/采矿后使用"),
        Skill("retreat", ["back", "back", "jump"], verify="screen_motion",
              description="后撤两步并跳，脱离威胁"),
    ]


# ───────────────────────── 自校验原语（独立证据，纯函数，可单测） ─────────────────────────
def verify_screen_motion(before_motion: float, after_motion: float, min_delta: float = 0.006):
    """独立证据：动作前后「画面运动强度」差值（来源：截图帧差，非动作模块自报）。"""
    delta = abs(after_motion - before_motion)
    passed = delta >= min_delta
    return passed, f"delta={delta:.4f} min={min_delta} passed={passed}"


def verify_threat_reduced(before_threats, after_threats):
    """独立证据：威胁数量是否下降（来源：grounding 世界态 diff）。"""
    b = len(before_threats or [])
    a = len(after_threats or [])
    passed = a < b
    return passed, f"threats {b}->{a} passed={passed}"


def verify_window_focused(hwnd):
    if not _user32 or not hwnd:
        return False, "no_hwnd"
    ok = _user32.GetForegroundWindow() == hwnd
    return ok, f"foreground==hwnd -> {ok}"


def _run_verify(verify: str, before: dict, after: dict):
    before = before or {}
    after = after or {}
    if verify == "screen_motion":
        passed, info = verify_screen_motion(before.get("motion", 0.0), after.get("motion", 0.0))
    elif verify == "threat_reduced":
        passed, info = verify_threat_reduced(before.get("threats"), after.get("threats"))
    elif verify == "window_focus":
        passed, info = verify_window_focused(after.get("hwnd"))
    else:
        return {"verify": verify, "passed": None, "info": "no_such_verify"}
    return {"verify": verify, "passed": passed, "info": info}


def run_skill(skill: Skill, *, window_substr: str = "minecraft", require_window: bool = True,
              evidence_before: dict = None, evidence_after: dict = None, focus: bool = True):
    """执行技能：逐个动作 safe_execute；若技能带 verify 且提供 evidence，返回独立证据校验结果。
    绝不依赖动作模块自报成功。返回 {"executed":[...], "verify": {...}|None}。

    安全：require_window=True（默认）下，无目标窗口时所有动作安全中止，不会把键鼠打进
    用户任意前台窗口——本函数可在无头环境安全调用做自测。
    """
    executed = []
    for step in skill.steps:
        action = step if isinstance(step, str) else (step.get("action") or step.get("name"))
        if action in ("wait", "screenshot_only"):
            executed.append({"action": action, "result": {"ok": True, "reason": "noop"}})
            continue
        res = safe_execute(action, window_substr=window_substr,
                           require_window=require_window, focus=focus)
        executed.append({"action": action, "result": res})
    vres = None
    if skill.verify and evidence_before is not None and evidence_after is not None:
        vres = _run_verify(skill.verify, evidence_before, evidence_after)
    return {"executed": executed, "verify": vres}
