# -*- coding: utf-8 -*-
"""game_agent_mindustry.py — Mindustry 看屏操控主 Agent（全链路打通）
================================================================

=== 路线定位（务实、不承诺通关）===
确定性 CV 感知（官方精灵 + HSV 资源）+ 规则策略 + 真实键鼠注入，全程不读内存、
不连服、不引游戏代码、零正则、单机离线。

=== 本文件把以下已验证模块打通成闭环 ===
  ① ui_grounding.UIGroundingEngine  —— 导航(主菜单→战役→扇区) + 游戏内 UI 精确点击
                                        （模板匹配 conf=1.000，已真机自验）
  ② Perception(官方精灵模板匹配)     —— 像素级识别核心/钻机/传送带/炮塔/资源
  ③ SemanticGrounding(三层)          —— 无标签资源「像素→语义」（铜/铅/煤 不靠标签）
  ④ Curriculum + Reflector           —— 「看不见的问题」元认知子系统
                                        (reflection.py：反馈/局部最优/问题发现/复盘
                                         借鉴 Reflexion/ToT·LATS/ExpeL/Voyager，许可干净)
  ⑤ action_lib                       —— 键鼠单一真实来源（安全中止护栏）
  ⑥ live_engine.react_to_scene       —— 边玩边解说吐槽（把反思/局势喂给奶昔）

=== 可行性分级（用户三次纠偏后固化）===
  A 层（主攻）：感知 UI + 精准落子 + 元认知反馈闭环。
  B 层（中）：凭感知资源/波次手调策略，通简单生存图。
  C 层（难、不保证）：稳通复杂图 —— 可能需更细策略或仍失败，绝不承诺。

=== 红线 ===
  零正则；不写 C 盘（路径经 __file__ 推导 / data 目录）；cv2=Apache2.0 / numpy=BSD；
  键鼠唯一来源=action_lib；游戏美术仅运行时从 assets.jar 提取，不进仓库。
"""

import json
import logging
import os
import subprocess as _sp
import threading
import time
import ctypes
from typing import Dict, List, Optional, Tuple

import numpy as np
import cv2
from PIL import ImageGrab

# 输入原语 + 动作注册表（单一真实来源，含「无窗口即安全中止」护栏）
from desktop_core.action_lib import safe_execute, click_at, find_window, focus_window, send_key, _user32
# UI 精确定位引擎（导航 + 游戏内按钮）
from desktop_core.ui_grounding import UIGroundingEngine, create_engine, input_set_cursor_and_click
# 无标签资源三层 grounding
from desktop_core.semantic_grounding import SemanticGrounding
# 元认知子系统（反馈/局部最优/问题发现/复盘）
from desktop_core.reflection import Reflector, ExperienceMemory, Curriculum, StepRecord

log = logging.getLogger("mindustry_agent")

# ── 路径推导（不写死 C 盘，经 __file__ 向上推导）──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
DATA_DIR = os.environ.get("NAIXI_MINDRY_DATA") or os.path.join(_PROJECT_ROOT, "data")
SPRITES_DIR = os.environ.get("NAIXI_MINDRY_SPRITES") or os.path.join(DATA_DIR, "mindustry_sprites")
ASSETS_JAR = os.environ.get("NAIXI_MINDRY_ASSETS")
CALIB_FILE = os.path.join(DATA_DIR, "mindustry_calib.json")
WINDOW_SUBSTR = os.environ.get("NAIXI_MINDRY_WIN") or "Mindustry"


def find_game_window(substr: str = "Mindustry") -> Optional[int]:
    """模块级进程过滤版 find_window：只匹配 java.exe 进程的窗口。

    这是修复「7 轮全在瞎点浏览器」的根因函数——普通 find_window('Mindustry')
    会匹配到用户浏览器标签页（标题含 Mindustry），导致 agent 以为游戏在运行、
    launch_if_needed 从不真正启动游戏、且全程操作浏览器。必须按进程名过滤。
    """
    if not _user32:
        return None
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    candidates = []

    def _cb(h, lp):
        n = _user32.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(h, buf, n + 1)
        t = buf.value or ""
        if substr in t:
            pid = ctypes.c_ulong()
            _user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            candidates.append((h, pid.value))
        return True

    _user32.EnumWindows(WNDENUMPROC(_cb), 0)
    for hwnd, pid in candidates:
        try:
            r = _sp.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True, timeout=3)
            if "java.exe" in r.stdout:
                return hwnd
        except Exception:
            continue
    return None


# 窗口策略：启动即「最大化」铺满屏幕（用户明确要求，优于钉死固定位置/尺寸）。
# 最大化后画布稳定、坐标无需随窗口漂移重算；游戏关了立即停止，绝不 MoveWindow 摆动其它窗口。
SW_MAXIMIZE = 3

KEY_BLOCKS = {
    "core":        ("storage",      "core-nucleus"),
    "drill":       ("drills",       "mechanical-drill"),
    "conveyor":    ("distribution", "phase-conveyor"),
    "router":      ("distribution", "router"),
    "duct":        ("distribution", "duct"),
    "turret_hail": ("turrets",      "hail"),
    "turret_arc":  ("turrets",      "arc"),
    "smelter":     ("production",   "silicon-smelter"),
    "generator":   ("power",        "combustion-generator"),
    "solar":       ("power",        "solar-panel"),
    "battery":     ("power",        "battery"),
    "wall":        ("walls",        "copper-wall"),
    "copper":      ("items",        "copper"),
    "lead":        ("items",        "lead"),
}


def _imread(path: str):
    try:
        with open(path, "rb") as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None


def ensure_sprites(sprites_dir: str = SPRITES_DIR, assets_jar: str = None) -> bool:
    """确保精灵模板库存在；缺失则从用户机器 assets.jar 提取（游戏资源不进仓库）。"""
    if os.path.isdir(os.path.join(sprites_dir, "blocks")) and \
       len(os.listdir(os.path.join(sprites_dir, "blocks"))) > 0:
        return True
    assets_jar = assets_jar or ASSETS_JAR
    if not assets_jar or not os.path.exists(assets_jar):
        log.warning("[mindustry] 精灵库缺失且无 assets.jar，无法提取。"
                    "请设置 NAIXI_MINDRY_ASSETS 指向 Mindustry 的 assets.jar。")
        return False
    try:
        import zipfile
        os.makedirs(sprites_dir, exist_ok=True)
        with zipfile.ZipFile(assets_jar) as z:
            for name in z.namelist():
                if name.startswith("assets-raw/sprites/") and name.endswith(".png"):
                    rel = name[len("assets-raw/sprites/"):]
                    dst = os.path.join(sprites_dir, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(dst, "wb") as f:
                        f.write(z.read(name))
        log.info(f"[mindustry] 已从 {assets_jar} 提取精灵到 {sprites_dir}")
        return True
    except Exception as e:
        log.warning(f"[mindustry] 提取精灵失败: {e}")
        return False


# ════════════════════════ 感知层（复用，略作精简） ════════════════════════
class Perception:
    """确定性 CV 感知：OpenCV 模板匹配官方精灵库。零 VLM/零正则/本地实时。"""

    def __init__(self, sprites_dir: str = SPRITES_DIR):
        self.sprites_dir = sprites_dir
        self.templates = {}
        self.template_paths = {}
        self._load_all()

    def _load_template(self, path: str):
        img = _imread(path)
        if img is None:
            return None, None
        if img.ndim == 3 and img.shape[2] == 4:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            mask = (img[:, :, 3] > 10).astype(np.uint8)
            return gray, mask
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return gray, None

    def _load_all(self):
        for name, (cat, base) in KEY_BLOCKS.items():
            cat_dir = os.path.join(self.sprites_dir, "blocks", cat)
            if not os.path.isdir(cat_dir):
                continue
            cand = [f for f in os.listdir(cat_dir) if f.startswith(base) and f.endswith(".png")]
            if not cand:
                continue
            cand.sort(key=lambda x: (len(x), x))
            p = os.path.join(cat_dir, cand[0])
            gray, mask = self._load_template(p)
            if gray is not None:
                self.templates[name] = (gray, mask)
                self.template_paths[name] = p

    @property
    def ready(self) -> bool:
        return len(self.templates) > 0

    def match_one(self, scene_gray, name: str, scales=(0.8, 1.0, 1.2), threshold: float = 0.18):
        tpl, mask = self.templates.get(name, (None, None))
        if tpl is None:
            return None
        sh, sw = scene_gray.shape[:2]
        th, tw = tpl.shape[:2]
        best = None
        for s in scales:
            nw, nh = max(1, int(tw * s)), max(1, int(th * s))
            if nw > sw or nh > sh:
                continue
            t = cv2.resize(tpl, (nw, nh), interpolation=cv2.INTER_AREA)
            m = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST) if mask is not None else None
            try:
                res = cv2.matchTemplate(scene_gray, t, cv2.TM_SQDIFF_NORMED, mask=m)
            except cv2.error:
                res = cv2.matchTemplate(scene_gray, t, cv2.TM_SQDIFF_NORMED)
            mn, _, mnloc, _ = cv2.minMaxLoc(res)
            if best is None or mn < best[0]:
                best = (mn, mnloc[0], mnloc[1], nw, nh, s)
        if best and best[0] <= threshold:
            x, y, w, h = best[1], best[2], best[3], best[4]
            return {"name": name, "conf": round(float(1.0 - best[0]), 3),
                    "x": int(x), "y": int(y), "w": w, "h": h,
                    "cx": int(x + w / 2), "cy": int(y + h / 2)}
        return None

    def detect(self, scene, names=None, scales=(0.8, 1.0, 1.2), threshold: float = 0.18):
        if scene is None:
            return []
        scene_gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY) if scene.ndim == 3 else scene
        names = names or list(self.templates.keys())
        return [r for r in (self.match_one(scene_gray, n, scales, threshold) for n in names) if r]


# ════════════════════════ 导航器（ui_grounding 驱动） ════════════════════════
class MindustryNavigator:
    """用 ui_grounding 把「主菜单 → 战役 → 星球 → 扇区 → 游戏」打通。

    定位不靠硬编码坐标猜——菜单项用「白字簇检测」按位置点（分辨率无关）；
    星球用「黄色名称标签」检测；扇区用「双击中心亮块」。
    已真机验证路径（159.7，本机）：开始游戏→战役模式→塞普罗→确定→双击扇区。
    """

    def __init__(self, engine: UIGroundingEngine):
        self.engine = engine

    @staticmethod
    def _white_text_clusters(bgr, left_frac: float = 0.6):
        """返回左侧白字簇中心列表 [(cx, cy), ...]，按 y 排序。"""
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        h, w = gray.shape[:2]
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if x > w * left_frac:
                continue
            if bw < 20 or bh < 6:
                continue
            out.append((int(x + bw / 2), int(y + bh / 2)))
        out.sort(key=lambda p: p[1])
        return out

    @staticmethod
    def _yellow_label_center(bgr):
        """黄色名称标签（HSV 15-40,70-255,170-255）→ 最大簇中心。"""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        m = cv2.inRange(hsv, np.array([15, 70, 170]), np.array([40, 255, 255]))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None
        c = max(cnts, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(c)
        return (int(x + bw / 2), int(y + bh / 2))

    def _click_window(self, wx: int, wy: int, hold_ms: int = 200, method: str = "menu_hold"):
        """窗口内坐标 → 屏幕坐标 → 点击（经由 ui_grounding 的输入原语）。"""
        rect = self.engine.window_rect
        if rect is None:
            self.engine._refresh_window()
            rect = self.engine.window_rect
        if rect is None:
            return False
        sx, sy = wx + rect[0], wy + rect[1]
        from desktop_core.ui_grounding import input_set_cursor_and_click, input_double_click
        if method == "double_click":
            input_double_click(sx, sy)
        else:
            input_set_cursor_and_click(sx, sy, hold_ms=hold_ms)
        return True

    def navigate_to_game(self, max_retries: int = 3) -> bool:
        """导航进入实际游戏。已处于游戏（检测到核心）则直接返回 True。"""
        for attempt in range(max_retries):
            self.engine.prepare()
            img = self.engine.capture()
            if img is None:
                log.warning("[nav] 截图失败")
                continue
            # 已进游戏？核心精灵 or 核心颜色出现
            found = self.engine  # 仅用颜色粗判：核心亮橙块存在即认为在游戏
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            core_mask = cv2.inRange(hsv, np.array([0, 180, 170]), np.array([9, 255, 255]))
            if core_mask.sum() > 500:
                log.info("[nav] 检测到核心，已在游戏中。")
                return True
            # 主菜单：点第 1 个白字簇（开始游戏）
            clusters = self._white_text_clusters(img)
            if clusters:
                self._click_window(clusters[0][0], clusters[0][1], hold_ms=200)
                time.sleep(1.0)
                # 子菜单：点第 2 个白字簇（战役模式；第 1 个通常是返回/标题）
                img2 = self.engine.capture()
                if img2 is not None:
                    clusters2 = self._white_text_clusters(img2)
                    if len(clusters2) >= 2:
                        self._click_window(clusters2[1][0], clusters2[1][1], hold_ms=200)
                        time.sleep(1.0)
                # 星球视图：点黄色名称标签（塞普罗），长按激活
                img3 = self.engine.capture()
                if img3 is not None:
                    yc = self._yellow_label_center(img3)
                    if yc:
                        self._click_window(yc[0], yc[1], hold_ms=500, method="planet_hold")
                        time.sleep(0.8)
                        # 确定按钮（白字「确定」）
                        img4 = self.engine.capture()
                        if img4 is not None:
                            # 找含「确定」字样的白字：取最右下的白字簇
                            cl = self._white_text_clusters(img4, left_frac=1.0)
                            if cl:
                                self._click_window(cl[-1][0], cl[-1][1], hold_ms=200)
                                time.sleep(0.8)
                        # 扇区：双击中心亮块进游戏
                        self._click_window(img3.shape[1] // 2, img3.shape[0] // 2,
                                           method="double_click")
                        time.sleep(2.0)
                        # 再判是否进游戏
                        img5 = self.engine.capture()
                        if img5 is not None:
                            hsv5 = cv2.cvtColor(img5, cv2.COLOR_BGR2HSV)
                            if cv2.inRange(hsv5, np.array([0, 180, 170]),
                                           np.array([9, 255, 255])).sum() > 500:
                                log.info("[nav] 已进入游戏。")
                                return True
            log.info(f"[nav] 第 {attempt+1} 次导航未到位，重试…")
            time.sleep(1.0)
        log.warning("[nav] 导航失败（可能需要手动进入游戏后重试）")
        return False


# ════════════════════════ 策略层（Curriculum + 反思驱动） ════════════════════════
class Strategy:
    """规则树（B/C 层）。基于 Curriculum 阶段 + SemanticGrounding 摘要 + 反思决策。

    诚实边界：仅覆盖「基础经济→防御」骨架；复杂图/高难不保证通关。
    决策产出结构化动作指令，由 Agent 落地（含屏幕目标坐标）。
    """

    def __init__(self):
        self.placed = set()

    def decide(self, phase: str, summary: dict, world_state: dict) -> dict:
        """返回动作指令 dict，例如 {"op":"place","block":"drill","target":(sx,sy)}。"""
        core = summary.get("core")
        mineable = summary.get("mineable", [])
        # 阶段守卫：威胁 → 优先炮塔
        if world_state.get("threat") and not world_state.get("has_defense"):
            return {"op": "place", "block": "turret_hail"}
        if phase == "init":
            if core:
                return {"op": "advance_phase"}
            return {"op": "wait"}
        if phase == "mining":
            # 在核心周边可采资源上放钻机（target=资源屏幕坐标）
            if mineable:
                m = mineable[0]
                return {"op": "place", "block": "drill",
                        "target": (m["cx"], m["cy"]), "cat": m["cat"]}
            return {"op": "advance_phase"}
        if phase == "logistics":
            # 在核心与最近矿之间放传送带（核心偏向矿 15%，形成一条合理料带）。
            # 注意：core/mineable 已是屏幕坐标，直接喂给 click_at。
            if core and mineable:
                m = mineable[0]
                tx = int(core[0] + (m["cx"] - core[0]) * 0.15)
                ty = int(core[1] + (m["cy"] - core[1]) * 0.15)
                return {"op": "place", "block": "conveyor", "target": (tx, ty)}
            return {"op": "advance_phase"}
        if phase == "defense":
            if core:
                return {"op": "place", "block": "turret_hail",
                        "target": (core[0] + 80, core[1] - 80)}
            return {"op": "advance_phase"}
        if phase == "sustain":
            if world_state.get("threat"):
                return {"op": "place", "block": "wall",
                        "target": (core[0] + 60, core[1]) if core else None}
            return {"op": "wait"}
        return {"op": "wait"}


# ════════════════════════ 主 Agent（闭环） ════════════════════════
class MindustryAgent:
    """看屏操控主循环：导航→感知→语义→课程→策略→键鼠→反思→吐槽。"""

    def __init__(self, window_substr: str = WINDOW_SUBSTR, on_scene=None):
        self.window_substr = window_substr
        self.engine = create_engine(window_substr, template_dir=None)
        self.perception = Perception()
        self.semantic = SemanticGrounding()
        self.curriculum = Curriculum()
        self.reflector = Reflector(ExperienceMemory())
        self.strategy = Strategy()
        self.on_scene = on_scene
        self._running = False
        self._step = 0
        self._max_steps = 999999
        self._loop_interval = 2.0
        self._latest_gray = None
        self._recent: List[StepRecord] = []
        self._build_icons: Dict[str, Tuple[int, int]] = {}  # 运行期校准的建造图标屏幕坐标
        self._build_open: bool = False
        self._selected_block: Optional[str] = None
        self._build_btn: Optional[Tuple[int, int]] = None    # 缓存的“建造”按钮屏幕坐标（免每次慢匹配）
        self._core_screen: Optional[Tuple[int, int]] = None   # 当前帧核心屏幕坐标（旋转朝向用）
        self._last_mineable_screen: Optional[Tuple[int, int]] = None  # 最近矿屏幕坐标（拖料带用）
        self._hints: List[str] = []                          # 读到的游戏内提示文本（OCR）
        self._ocr = None                                     # 懒加载 PaddleOCR
        self._lock_count = 0

    # ── 截屏（窗口内）──
    def _grab_window(self):
        img = self.engine.capture()
        if img is None:
            return None
        h, w = img.shape[:2]
        # 截屏尺寸异常（窗口还原/缩放中）→ 重新最大化再截一次，避免崩溃
        if h < 100 or w < 100:
            log.warning(f"[agent] 截屏尺寸异常 {w}x{h}，重新最大化窗口")
            self.maximize_game_window()
            img = self.engine.capture()
        return img

    def _find_game_window(self):
        """找 Mindistry 游戏窗口（只匹配 java.exe 进程，避免误匹配浏览器标签页）。

        委托模块级 find_game_window（进程过滤），防止误匹配浏览器标签页。
        """
        return find_game_window(self.window_substr)

    def maximize_game_window(self):
        """启动/异常时把游戏窗口【最大化并置顶】铺满屏幕。

        注意：只操作游戏窗口自身（最大化+置顶），【绝不】最小化/移动任何其它窗口
        （浏览器等用户窗口一律不动），避免骚扰用户桌面。
        """
        try:
            hwnd = self._find_game_window()
            if not hwnd or not _user32:
                return False
            _user32.ShowWindow(hwnd, SW_MAXIMIZE)
            time.sleep(0.25)
            _user32.SetForegroundWindow(hwnd)   # 置顶，确保用户能直接看到游戏
            time.sleep(0.15)
            self.engine._refresh_window()  # 刷新 client_rect（标题栏/边框已去掉）
            self._lock_count += 1
            return True
        except Exception as e:
            log.warning(f"[agent] 最大化窗口失败: {e}")
            return False

    # ── 建造菜单：运行期校准图标位置 ──
    def _calibrate_icons(self):
        """在当前（已打开）建造菜单画面用 Perception 找已知方块图标，记录屏幕坐标。"""
        img = self.engine.capture()
        if img is None:
            return
        rect = self.engine.window_rect
        ox, oy = (rect[0], rect[1]) if rect else (0, 0)
        found = self.perception.detect(img)
        self._build_icons = {}
        for f in found:
            self._build_icons[f["name"]] = (f["cx"] + ox, f["cy"] + oy)
        log.info(f"[agent] 建造菜单校准到图标: {sorted(self._build_icons.keys())}")

    def _is_build_menu_open(self) -> bool:
        """用独立视觉证据判断建造菜单是否开着（不靠状态标志，避免 toggle 误判）。

        Mindustry 建造菜单开着时，屏幕中央会铺开一整排【分类图标】；早期游戏尚未放置
        generator/smelter/battery/solar 等，若感知到这些精灵，必是菜单在显示它们。
        兜底：同时检测到 >=6 个不同方块图标也判为开着。
        """
        try:
            img = self.engine.capture()
            if img is None:
                return False
            found = self.perception.detect(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            names = {f["name"] for f in found}
            menu_only = {"generator", "smelter", "battery", "solar",
                         "turret_arc", "router", "duct"}
            if names & menu_only:
                return True
            if len(names) >= 6:
                return True
            return False
        except Exception:
            return False

    def _open_build_menu(self) -> bool:
        """用【位置法】点建造按钮（最大化后它在客户端底部正中）。

        不依赖缺失的 build_grid 模板；在底部中心一条竖直候选带里逐一尝试，
        每次都用【独立视觉检测】_is_build_menu_open() 判定是否真的开了，避免
        因为 y 偏移固定而永远点不到（建造按钮 toggle，点了关掉会误判）。
        """
        hwnd = self._find_game_window()
        if not hwnd or not focus_window(hwnd):
            return False
        rect = self.engine.window_rect
        if not rect:
            self.engine._refresh_window()
            rect = self.engine.window_rect
        if not rect:
            return False
        bx = (rect[0] + rect[2]) // 2
        # 底部中心竖直候选带（客户端坐标系，从底往上若干像素）
        candidates = [rect[3] - off for off in (14, 20, 26, 34, 44, 54)]
        for by in candidates:
            if self._is_build_menu_open():
                return True
            input_set_cursor_and_click(bx, by, hold_ms=120)
            time.sleep(0.5)
            if self._is_build_menu_open():
                return True
        return self._is_build_menu_open()

    def _ensure_build_open(self) -> bool:
        """确保建造菜单已打开（状态探测 + 位置法开菜单，避免依赖缺失的 build_grid 模板）。"""
        if self._build_open:
            return True
        if self._is_build_menu_open():
            self._build_open = True
            self._calibrate_icons()
            return True
        if self._open_build_menu():
            self._build_open = True
            self._calibrate_icons()
            return True
        log.warning("[agent] 打开建造菜单失败（位置法）")
        return False

    def _select_block(self, block: str) -> bool:
        """两级选择：先点【分类】图标展开，再点【具体方块】图标选中（Mindustry 菜单是两级）。

        选中后菜单关闭、进入放置模式；下次换方块需重新开菜单。
        """
        if self._selected_block == block and self._build_open:
            return True
        if not self._ensure_build_open():
            return False
        cat = KEY_BLOCKS.get(block, (None, None))[0]
        if not cat:
            log.warning(f"[agent] 未知方块 {block}")
            return False
        rect = self.engine.window_rect
        ox, oy = (rect[0], rect[1]) if rect else (0, 0)
        # ① 在已开菜单里找该分类的代表精灵，点它展开分类
        img = self.engine.capture()
        if img is None:
            return False
        found = self.perception.detect(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        cat_icon = None
        for f in found:
            if KEY_BLOCKS.get(f["name"], (None, None))[0] == cat:
                cat_icon = (f["cx"] + ox, f["cy"] + oy)
                break
        if not cat_icon:
            log.warning(f"[agent] 建造菜单未找到分类 {cat} 图标")
            return False
        input_set_cursor_and_click(cat_icon[0], cat_icon[1], hold_ms=120)
        time.sleep(0.5)
        # ② 在展开的分类里点具体方块（取离分类头最远的命中点，避开分类头本身）
        img2 = self.engine.capture()
        if img2 is None:
            return False
        found2 = self.perception.detect(cv2.cvtColor(img2, cv2.COLOR_BGR2RGB))
        hits = [(f["cx"] + ox, f["cy"] + oy) for f in found2 if f["name"] == block]
        if not hits:
            log.warning(f"[agent] 展开分类未找到具体方块 {block}，退回点分类图标")
            hits = [cat_icon]
        target = max(hits, key=lambda p: (p[0] - cat_icon[0]) ** 2 + (p[1] - cat_icon[1]) ** 2) \
            if len(hits) > 1 else hits[0]
        input_set_cursor_and_click(target[0], target[1], hold_ms=120)
        time.sleep(0.4)
        self._build_open = False       # 选中后菜单关闭，进入放置模式
        self._selected_block = block
        return True

    # ── 键盘原语（用户要求：鼠标+键盘同时进行，不能只点鼠标）──
    def _press_key(self, token: str, hold_ms: int = 60) -> bool:
        """向游戏窗口注入键盘（带聚焦护栏，避免打到别的窗口）。"""
        try:
            hwnd = self._find_game_window()
            if not hwnd or not focus_window(hwnd):
                return False
            return bool(send_key(token, hold_ms=hold_ms))
        except Exception as e:
            log.warning(f"[agent] 按键 {token} 失败: {e}")
            return False

    def _rotate_block(self, times: int = 1):
        """放置前用 R 旋转方块朝向（Mindustry 默认朝向常需调整，传送带/钻机尤其）。"""
        for _ in range(max(0, int(times) % 4)):
            self._press_key("r")
            time.sleep(0.08)

    def _pan_camera(self, token: str, hold_ms: int = 400):
        """用 WASD/方向键平移视角（键盘操控）。"""
        self._press_key(token, hold_ms=hold_ms)

    @staticmethod
    def _rotations_toward(a, b) -> int:
        """计算从 a 指向 b 的方向需要按几次 R（Mindustry 朝向 0=上，顺时针 90° 一步）。"""
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            return 0
        import math
        ang = (math.atan2(dx, -dy) * 180.0 / math.pi) % 360  # 0=上 90=右 180=下 270=左
        return int(round(ang / 90.0)) % 4

    def _place_drag(self, block: str, from_xy, to_xy) -> bool:
        """选中方块后，从 from 拖到 to 拉一条直线。

        Mindustry 玩法：拖动可一次放置一连串【同向】传送带/管道——正好是游戏提示
        “click and drag to place a line” 教的操作。比单点更稳、更贴近真实玩法。
        """
        if not self._select_block(block):
            return False
        hwnd = self._find_game_window()
        if hwnd and not focus_window(hwnd):
            log.warning("[agent] 拖动前聚焦失败，拖动可能无效")
        sx, sy = int(from_xy[0]), int(from_xy[1])
        ex, ey = int(to_xy[0]), int(to_xy[1])
        try:
            if not _user32:
                return False
            _user32.SetCursorPos(sx, sy)
            time.sleep(0.05)
            _user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
            dist = int(((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5)
            steps = max(2, dist // 36)
            for i in range(1, steps + 1):
                x = sx + (ex - sx) * i // steps
                y = sy + (ey - sy) * i // steps
                _user32.SetCursorPos(x, y)
                time.sleep(0.02)
            time.sleep(0.12)
            _user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
            return True
        except Exception as e:
            log.warning(f"[agent] 拖动放置失败: {e}")
            return False

    # ── 读取游戏内提示（用户要求：要看屏上的玩法提示）──
    def _read_hints(self, rgb) -> List[str]:
        """OCR 读取游戏内提示/控制条（best-effort，带超时护栏，离线无模型则安全禁用）。"""
        if getattr(self, "_ocr_disabled", False):
            return []
        try:
            import threading
            h, w = rgb.shape[:2]
            # 底部控制条区域（Mindustry 在底部显示 LMB/RMB/R/WASD 等控制提示）
            bar = rgb[int(h * 0.90):h, :]
            if bar.size == 0:
                return []
            bar_bgr = cv2.cvtColor(bar, cv2.COLOR_RGB2BGR)
            if self._ocr is None:
                done = []
                def _init():
                    from paddleocr import PaddleOCR
                    self._ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
                    done.append(True)
                t = threading.Thread(target=_init, daemon=True)
                t.start(); t.join(8.0)
                if not done:
                    self._ocr_disabled = True
                    log.warning("[agent] OCR 初始化超时（可能离线无模型），禁用提示读取")
                    return []
            res = self._ocr.ocr(bar_bgr, cls=False)
            out = []
            for line in (res or []):
                for box, (txt, conf) in line:
                    if conf >= 0.5 and txt.strip():
                        out.append(txt.strip())
            return out
        except Exception as e:
            self._ocr_disabled = True
            log.debug(f"[agent] 提示 OCR 禁用: {e}")
            return []

    # ── 执行（仅经 action_lib / ui_grounding 输入原语）──
    def _execute(self, cmd: dict) -> bool:
        op = cmd.get("op")
        if op in ("wait", None, "advance_phase"):
            if op == "advance_phase":
                self.curriculum.advance()
            return True
        if op == "retry_perturb":
            return True
        if op == "place":
            block = cmd.get("block")
            target = cmd.get("target")
            if not target:
                log.info(f"[agent] 无目标坐标，跳过放置 {block}")
                return False
            core = self._core_screen
            # 传送带：用「拖动」从矿拉一条直达核心的料带（游戏提示教的玩法，自动朝向核心）
            if block == "conveyor" and self._last_mineable_screen and core:
                ok = self._place_drag("conveyor", self._last_mineable_screen, core)
                log.info(f"[agent] 已拖放 conveyor(矿→核心) ok={ok}")
                return bool(ok)
            # 其余方块：开建造菜单选中 → 键盘 R 旋转朝向核心 → 鼠标点击放置
            if not self._select_block(block):
                return False
            sx, sy = int(target[0]), int(target[1])
            if core and block in ("drill", "turret_hail"):
                self._rotate_block(self._rotations_toward((sx, sy), core))
            res = click_at(sx, sy, window_substr=self.window_substr,
                           require_window=True, focus=True, hold_ms=40)
            self.strategy.placed.add((block, sx, sy))
            log.info(f"[agent] 已放置 {block} @屏幕({sx},{sy}) ok={res.get('ok')}（键盘旋转+R）")
            return bool(res.get("ok"))
        return False

    # ── 反思：用独立证据判定一步成败（禁止循环验证）──
    def _reflect_step(self, pre_motion, post_motion, pre_entities, post_entities,
                      decision, action_kind, situation, expected):
        rec = self.reflector.evaluate_step(
            step=self._step, phase=self.curriculum.phase, situation=situation,
            decision=decision, action_kind=action_kind,
            pre_motion=pre_motion, post_motion=post_motion,
            pre_entities=pre_entities, post_entities=post_entities,
            expected_delta=expected,
        )
        self._recent.append(rec)
        if len(self._recent) > 40:
            self._recent = self._recent[-40:]
        return rec

    # ── 对接 live_engine：边玩边解说吐槽 ──
    def emit_scene(self, text: str, scene_mode: str = "game"):
        if self.on_scene:
            try:
                self.on_scene(text, scene_mode)
            except Exception as e:
                log.warning(f"[agent] emit_scene 失败: {e}")

    # ── 主循环 ──
    async def start(self, navigate: bool = True, interval: float = None, max_steps: int = None):
        if self._running:
            return True
        if not self.perception.ready:
            if not ensure_sprites():
                log.warning("[agent] 感知层未就绪（无精灵库），无法启动。")
                return False
        if interval:
            self._loop_interval = interval
        if max_steps:
            self._max_steps = max_steps
        self._running = True
        self._step = 0
        # 导航进游戏（若尚未在游戏内）
        if navigate and not self._already_in_game():
            if not self.engine.prepare():
                log.warning("[agent] 窗口准备失败")
            nav = MindustryNavigator(self.engine)
            if not nav.navigate_to_game():
                log.warning("[agent] 导航未成功，将在当前画面尝试感知演示。")
        # 启动即最大化游戏窗口（铺满屏幕、画布稳定、坐标免重算），并校准“建造”按钮坐标（免每次慢匹配）
        self.maximize_game_window()
        try:
            mr = self.engine.locate("build_grid")
            if mr.ok:
                self._build_btn = (mr.screen_x, mr.screen_y)
                log.info(f"[agent] 已校准建造按钮屏幕坐标: {self._build_btn}")
        except Exception as e:
            log.warning(f"[agent] 校准建造按钮失败(将用慢速回退): {e}")
        log.info(f"[agent] 启动：window={self.window_substr} 间隔{self._loop_interval}s "
                 f"感知模板{len(self.perception.templates)}个 "
                 f"阶段={self.curriculum.phase}")
        return True

    def _already_in_game(self) -> bool:
        img = self._grab_window()
        if img is None:
            return False
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, np.array([0, 180, 170]),
                           np.array([9, 255, 255])).sum() > 500

    async def stop(self):
        self._running = False
        # 复盘落盘
        retro = self.reflector.mem.summarize_session()
        log.info(f"[agent] 停止。复盘:\n{retro}")
        self.emit_scene("这局先到这，我复盘一下今天哪步踩坑了。")

    async def _run_loop(self):
        try:
            while self._running and self._step < self._max_steps:
                await _sleep(self._loop_interval)
                self._step += 1
                # 游戏窗口存活检查：关了就立刻收手，绝不摆动其它窗口、也不僵尸空转
                if self._find_game_window() is None:
                    log.info("[agent] 游戏窗口已关闭，主动停止主循环。")
                    self._running = False
                    break
                img = self._grab_window()
                if img is None:
                    continue
                # 用 RGB 供感知/语义
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                rect = self.engine.window_rect
                ox, oy = (rect[0], rect[1]) if rect else (0, 0)
                # 窗口最大化防护：仅当被还原成常态窗口时才重新最大化；
                # 绝不 MoveWindow 钉死固定位置（那会跟用户抢窗口、一直抖动），最大化后画布即稳定。
                hwnd = self._find_game_window()
                if _user32 and hwnd and not _user32.IsZoomed(hwnd):
                    self.maximize_game_window()
                    rect = self.engine.window_rect
                    ox, oy = (rect[0], rect[1]) if rect else (0, 0)

                # ② 感知：官方精灵
                found = self.perception.detect(rgb)
                entity_counts = {}
                core_pos = None
                for f in found:
                    entity_counts[f["name"]] = entity_counts.get(f["name"], 0) + 1
                    if f["name"] == "core":
                        core_pos = (f["cx"], f["cy"])

                # ③ 语义：无标签资源（三层）
                sg_regions = self.semantic.analyze(rgb, core_pos=core_pos,
                                                  window_offset=(ox, oy))
                sg_summary = self.semantic.summarize(sg_regions)

                # 关键修复：semantic 返回的是【窗口内】坐标；click_at 需要【屏幕】坐标。
                # 统一换算成屏幕坐标再交给策略，避免传送带落到屏幕左上角(71,70)等死区。
                _core_scr = sg_summary.get("core")
                if _core_scr is None and core_pos is not None:
                    _core_scr = (core_pos[0] + ox, core_pos[1] + oy)
                elif _core_scr is not None:
                    _core_scr = (_core_scr[0] + ox, _core_scr[1] + oy)
                self._core_screen = _core_scr
                sg_summary_screen = {
                    "counts": sg_summary.get("counts", {}),
                    "core": _core_scr,
                    "mineable": [
                        {"cat": m["cat"], "cx": m["cx"] + ox, "cy": m["cy"] + oy,
                         "area": m["area"], "dist": m.get("dist")}
                        for m in sg_summary.get("mineable", [])
                    ],
                    "total_regions": sg_summary.get("total_regions", 0),
                }
                # 记住最近矿的屏幕坐标（拖料带用）
                self._last_mineable_screen = (sg_summary_screen["mineable"][0]["cx"],
                                              sg_summary_screen["mineable"][0]["cy"]) \
                    if sg_summary_screen.get("mineable") else None

                # 帧差（免费独立证据）：与上一帧比较；分辨率变化则重置（防崩溃）
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                pre_gray = gray
                if self._latest_gray is None or self._latest_gray.shape != gray.shape:
                    motion = 0.0
                    self._latest_gray = gray
                else:
                    motion = float(np.abs(gray.astype(float) - self._latest_gray.astype(float)).mean()) / 255.0
                    self._latest_gray = gray

                # 世界态（驱动 Curriculum 全局守卫 + 策略）
                world_state = {
                    "threat": motion > 0.05,
                    "has_defense": entity_counts.get("turret_hail", 0) > 0
                                   or entity_counts.get("turret_arc", 0) > 0,
                    "has_mineable": len(sg_summary.get("mineable", [])) > 0,
                    "phase": self.curriculum.phase,
                    "situation": f"{self.curriculum.phase}@{self._step}",
                }
                # ④ 课程（全局守卫 + 阶段推进）
                phase = self.curriculum.tick(world_state)

                # ⑤ 策略决策（用屏幕坐标摘要）
                cmd = self.strategy.decide(phase, sg_summary_screen, world_state)
                action_kind = f"{cmd.get('op','wait')}_{cmd.get('block','')}"
                expected = "放置建筑" if cmd.get("op") == "place" else ""

                log.info(f"[agent] step={self._step} 阶段={phase} 命中{len(found)}方块 "
                         f"资源{sg_summary.get('counts')} 动作={cmd.get('op')}/{cmd.get('block','')}")

                # 读取游戏内提示（每 3 步一次，OCR 底部控制条；best-effort）
                if self._step % 3 == 1:
                    try:
                        hints = self._read_hints(rgb)
                        for h in hints:
                            if h not in self._hints:
                                self._hints.append(h)
                                log.info(f"[agent] 读到游戏提示：{h}")
                    except Exception:
                        pass

                # ⑥ 执行
                if cmd.get("op") != "wait":
                    ok = self._execute(cmd)
                    # 反思：用「动作前后真帧差」作为独立证据判定成败（禁止循环验证）
                    time.sleep(0.4)  # 等放置动画/实体落盘，避免帧差误判成败
                    post_img = self._grab_window()
                    post_counts = entity_counts
                    post_motion = motion
                    if post_img is not None:
                        post_found = self.perception.detect(cv2.cvtColor(post_img, cv2.COLOR_BGR2RGB))
                        post_counts = {}
                        for f in post_found:
                            post_counts[f["name"]] = post_counts.get(f["name"], 0) + 1
                        pg = cv2.cvtColor(post_img, cv2.COLOR_BGR2GRAY)
                        if pg.shape == pre_gray.shape:
                            post_motion = float(np.abs(pg.astype(float) - pre_gray.astype(float)).mean()) / 255.0
                        else:
                            post_motion = 1.0   # 分辨率变化 = 必有变化
                        self._latest_gray = pg  # 下一帧以动后画面为基准
                    self._reflect_step(0.0, post_motion, entity_counts, post_counts,
                                       cmd, action_kind, world_state["situation"], expected)

                # ⑦ 反思汇总 + 吐槽
                refl = self.reflector.build_reflection(
                    self._recent, world_state, phase, action_kind,
                    global_progress=0.5 if world_state["has_defense"] else 0.1)
                if found or sg_regions:
                    names = "、".join(sorted(set(list(entity_counts.keys())
                                                + [r.cat for r in sg_regions])))
                    talk = f"场上看到：{names}。"
                    if self._hints:
                        talk += f"提示栏写着：{' / '.join(self._hints[-3:])}——我照着用键盘R转向、拖动画料带了。"
                    else:
                        talk += "（我照游戏教的来：键盘R转向、从矿拖到核心画料带、WASD平移视角。）"
                    if refl["local_optimum_trapped"]:
                        talk += "我好像卡在局部最优了，得换招。"
                    if refl["problems"]:
                        talk += "发现问题：" + "；".join(p["problem"] for p in refl["problems"])
                    self.emit_scene(talk)
                # 周期性把语义叠加图存盘（验证/复盘）
                if self._step % 10 == 0:
                    try:
                        out = os.path.join(DATA_DIR, f"_mindustry_step{self._step}.semantic.png")
                        self.semantic.render_overlay(rgb, sg_regions, out)
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"[agent] 循环异常: {e}")
        finally:
            self._running = False


async def _sleep(sec: float):
    try:
        import asyncio
        await asyncio.sleep(sec)
    except Exception:
        time.sleep(sec)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    p = Perception()
    print(f"感知模板已加载: {len(p.templates)} 个 -> {sorted(p.templates.keys())}")
    if not p.ready:
        print("（精灵库缺失：运行时会在用户机器从 assets.jar 提取）")
