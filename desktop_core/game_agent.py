"""自主游戏 Agent（奶昔真人感主播·C 自主游玩）

=== 核心认知：让一维文本模型"理解"三维事物 ===
旧版"每 2.5 秒抓一张静止图送云模型描述"失败的根因不是"截图"本身，
而是**喂给模型的表征错了**：
  - 给原始像素 + 自由描述 → 一维文本模型在二维图上 hallucinate 空间关系，
    看不出"敌人在前-右方 4 米、正在靠近"，自然玩不了。
  - B 站那些能真玩的 demo，本质是做了「3D → 1D 文本的 grounding」：
    把画面翻译成**带空间坐标的结构化状态**，再让 LLM 在它母语模态里推理。

本模块架构（三层，全部保留"每帧都在看"，但把看的结果变成可推理的状态）：
  1) 本地层（每帧都看，免费）：独立线程 LOCAL_FPS 抓屏，numpy 帧差算实时运动强度，
     维护最近 RING_K 帧环形缓冲。这一步不联网、不花钱、跑满帧率。
  2) 感知 grounding 层（云端 VL，只在关键节点调）：把环形缓冲拼成运动片段送视觉模型，
     但要求它输出**严格结构化场景图 JSON**（self 状态 / 威胁含相对方向+距离+运动 /
     物体 / 准星 / 局势），而不是自由描述。这是"三维→一维"的翻译。
     —— 对 Minecraft 这类可直读游戏内存的，还可经 mc_state_read() 直接拿实体坐标文本，
        这是最强形式的 grounding（像素都不需要），由外部 Minescript/Mineflayer 桥写入。
  3) 持久世界状态（本地）：跨帧维护 _world（物体恒存：威胁 last-seen 3s 内保留），
     LLM 决策拿到的是**有记忆的跟踪状态**，不是孤立快照。
  4) 本地反射（兜底 LLM 1~3s 决策延迟）：若"云端刚报某方向有敌"且"本地运动仍升"，
     直接 sub-100ms 侧闪/后撤，不等 LLM。策略靠 LLM，反射靠本地——成功 demo 的分工。

动作层：移动类（forward/back/left/right）持续按住；瞬时类（跳/攻击/交互）瞬时发。
安全护栏：白名单动作；单局步数上限；超时/异常自动停；不抢焦点。
"""

import asyncio
import collections
import json
import logging
import os
import threading
import time
from io import BytesIO

import numpy as np
from PIL import Image, ImageGrab

# 输入原语 + 动作注册表已抽到 action_lib（单一真实来源，含「无窗口即安全中止」护栏）
from desktop_core.action_lib import safe_execute, move_mouse

log = logging.getLogger("game_agent")

# 临时拼图目录（拼运动片段送视觉模型用）
_TMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(_TMP_DIR, exist_ok=True)

# ── 输入原语 + 动作注册表已抽到 desktop_core/action_lib（单一真实来源）──
# 本模块只从 action_lib 取 safe_execute / move_mouse，避免键鼠逻辑双份维护，
# 并继承其「无目标窗口即安全中止」护栏（不再把键鼠打进用户任意前台窗口）。


# 输入原语见 action_lib（move_mouse / send_key / send_mouse）；本模块不再重复。


class GameAgent:
    """自主游戏 agent：本地每帧感知 → 云端空间 grounding → 持久世界态 → LLM 决策 → 键鼠。"""

    LOCAL_FPS = 10          # 本地捕捉帧率：每帧都看
    RING_K = 6              # 环形缓冲帧数（拼成一段连续画面送云）
    SMALL = (240, 135)      # 帧差用小图尺寸（省 CPU）
    WORLD_TTL = 3.0         # 物体恒存：威胁/物体 last-seen 超过此秒数才丢弃
    REFLEX_GAP = 2.0        # 本地反射窗口：云端报威胁后多久内允许本地反射撤离
    REFLEX_COOLDOWN = 0.8   # 本地反射后冷却，避免狂按

    # 安全白名单
    ALLOWED_ACTIONS = {
        "forward", "back", "left", "right", "jump", "interact", "inventory",
        "attack", "use", "drop", "slot1", "slot2", "slot3", "slot4",
        "look_left", "look_right", "look_up", "look_down",
        "screenshot_only", "wait",
    }
    # 持续动作（按住一段时间，用于移动/探索）
    HOLD_ACTIONS = {"forward", "back", "left", "right"}
    # 反方向映射（本地反射撤离用）
    OPPOSITE = {"forward": "back", "back": "forward", "left": "right", "right": "left"}

    def __init__(self, game: str = "minecraft"):
        self.game = game
        self._bot_mode = False   # 已废弃：机器人模式被用户否决——统一走「看屏+键鼠操控真实角色」，不再塞独立 bot
        self._running = False
        self._task = None
        self._cap_thread = None
        self._step = 0
        self._max_steps = 600
        self._loop_interval = 0.5     # 主循环节拍（秒）
        self._cloud_interval = 2.5    # 常态巡检间隔（秒）
        self._cloud_min_gap = 1.5     # 突变触发最小间隔（秒）
        self._high_motion = 0.05      # 突变阈值（帧差均值/255）
        # 本地感知共享状态
        self._lock = threading.Lock()
        self._ring = collections.deque(maxlen=self.RING_K)   # 最近小帧（用于拼运动片段）
        self._latest = None           # 最近一帧全分辨率（备用）
        self._motion = 0.0            # 平滑运动强度 0~1
        self._last_static = time.time()
        self._last_cloud = 0.0
        self._last_reflex = 0.0
        # 持久世界状态（grounding 层写入，决策层读取）
        self._world = {
            "self_hp": None,          # 0~100 或 None（未知）
            "situation": "",          # 探索/战斗/建造/菜单/死亡
            "crosshair": "",          # 准星对准物
            "threats": [],            # [{type,dir,distance,motion,seen}]
            "objects": [],            # [{type,dir,distance}]
            "updated_at": 0.0,
        }
        # 执行反思（闭环纠偏，对标 Cradle 自我反思模块）
        self._stuck = 0            # 连续卡住/撞墙计数
        self._reflect_text = ""    # 上一步执行反馈，注入下一轮决策
        self._reflect_tick = 0     # 视觉确认节流计数
        # 观察者真相（作弊级 grounding）：只读世界观察者写入的文件
        self._aim = None           # 当前瞄准鼠标增量 (mx, my)
        self._aim_cat = None       # 瞄准目标类别 hostile/animal/resource
        self._aim_dist = 99        # 瞄准目标距离
        self._last_aim = (0, 0)
        self._grounding_path = os.environ.get("NAIXI_GROUNDING") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "naixi_grounding.json")
        # 客户端只读 Mod API（用户已批准，2026-08-03）：默认本机只读端点；动作仍走键鼠注入同一客户端
        self._mc_api_url = os.environ.get("NAIXI_MC_API_URL") or "http://127.0.0.1:25566/state"
        self._grounding_src = os.environ.get("NAIXI_GROUNDING_SRC", "auto")  # auto|http|vision
        self._grounding_ok = False

    # ───────────────────────── 本地感知（每帧都看，免费） ─────────────────────────
    def _grab(self):
        """抓一帧，返回 (全分辨率 ndarray, 小图 ndarray)。失败返回 (None, None)。"""
        try:
            img = ImageGrab.grab()            # 全屏 RGB
            full = np.asarray(img)
            small = np.asarray(img.resize(self.SMALL))
            return full, small
        except Exception as e:
            log.warning(f"[游戏agent] 抓屏失败: {e}")
            return None, None

    def _capture_loop(self):
        """独立线程：以 LOCAL_FPS 每帧抓屏、算帧差运动、维护环形缓冲。"""
        prev = None
        while self._running:
            try:
                full, small = self._grab()
                if small is None:
                    time.sleep(0.2)
                    continue
                gray = small.mean(axis=2)               # 灰度
                diff = 0.0 if prev is None else float(np.abs(gray - prev).mean()) / 255.0
                prev = gray
                self._motion = 0.8 * self._motion + 0.2 * diff   # 指数平滑
                with self._lock:
                    self._latest = full
                    self._ring.append(small)
                    if self._motion < 0.01:
                        self._last_static = time.time()
                time.sleep(1.0 / self.LOCAL_FPS)
            except Exception as e:
                log.warning(f"[游戏agent] 本地捕捉异常: {e}")
                time.sleep(0.5)

    def _build_strip_image(self):
        """把环形缓冲里最近的帧横向拼成一段连续画面，返回 PNG 字节（无帧返回 None）。"""
        with self._lock:
            frames = [f.copy() for f in self._ring]
        if not frames:
            return None
        strip = np.hstack(frames)              # (H, W*K, 3)
        buf = BytesIO()
        Image.fromarray(strip).save(buf, format="PNG")
        return buf.getvalue()

    # ───────────────────────── 感知 grounding 层：3D → 1D 文本 ─────────────────────────
    def _grounding_prompt(self, motion: float) -> str:
        """要求视觉模型输出结构化空间场景图（而非自由描述）——这是三维→一维的翻译。"""
        return (
            f"这是游戏最近若干连续帧（图中从左到右是时间先后顺序），"
            f"本地测算画面运动强度约 {motion:.2f}（0=静止，越大越剧烈）。\n"
            "请只输出一段 JSON（不要任何解释、不要 markdown 代码块），描述空间状态：\n"
            "{\n"
            '  "self_hp": 0到100的整数或null（看不到血量条写null）,\n'
            '  "situation": "探索|战斗|建造|菜单|死亡|加载"之一,\n'
            '  "crosshair": "准星当前对准的事物（如 敌人/方块/天空/地面/无）",\n'
            '  "threats": [{"type":"敌人或危险类型","dir":"前|后|左|右|上|下|前-左|前-右等相对方向","distance":"近|中|远","motion":"靠近|远离|静止"}],\n'
            '  "objects": [{"type":"方块/物品/目标","dir":"相对方向","distance":"近|中|远"}]\n'
            "}\n"
            "方向以游戏角色自身为原点（第一人称视角）。只输出 JSON。"
        )

    def _vision_ground(self, motion: float) -> dict:
        """拼运动片段送视觉模型，解析出结构化场景图；解析失败回退为空态。"""
        try:
            png = self._build_strip_image()
            if not png:
                return {}
            tmp = os.path.join(_TMP_DIR, "_game_strip.png")
            with open(tmp, "wb") as f:
                f.write(png)
            from desktop_core.live_engine import engine
            raw = engine._vision_describe(tmp, question=self._grounding_prompt(motion))
            if not raw:
                return {}
            return self._parse_grounding(raw)
        except Exception as e:
            log.warning(f"[游戏agent] 视觉 grounding 失败: {e}")
            return {}

    @staticmethod
    def _parse_grounding(raw: str) -> dict:
        """从模型回复里抠出第一个 JSON 对象并解析；宽容处理 markdown/多余文字。"""
        try:
            s = raw.strip()
            # 定位最外层 { ... }：首个 { 到最后一个 }。
            # markdown 围栏（```json ... ```）在花括号之外，切片时自然被排除，
            # 无需正则去围栏（正则边界坑多易暴雷）。
            start = s.find("{")
            if start < 0:
                return {}
            end = s.rfind("}")
            if end <= start:
                return {}
            frag = s[start:end + 1]
            obj = json.loads(frag)
            if not isinstance(obj, dict):
                return {}
            # 规范化字段
            out = {
                "self_hp": obj.get("self_hp"),
                "situation": str(obj.get("situation", "")),
                "crosshair": str(obj.get("crosshair", "")),
                "threats": obj.get("threats") if isinstance(obj.get("threats"), list) else [],
                "objects": obj.get("objects") if isinstance(obj.get("objects"), list) else [],
            }
            return out
        except Exception:
            return {}

    def _merge_world(self, new_state: dict):
        """把新 grounding 结果合并进持久世界态（物体恒存：保留近期未见项）。"""
        now = time.time()
        with self._lock:
            if new_state:
                # 威胁：用 (type,dir) 近似去重，更新或新增，刷新 seen
                seen_keys = set()
                for t in new_state.get("threats", []):
                    key = (str(t.get("type", "")), str(t.get("dir", "")))
                    seen_keys.add(key)
                    exist = next((x for x in self._world["threats"]
                                  if (str(x.get("type", "")), str(x.get("dir", ""))) == key), None)
                    if exist:
                        exist.update(t)
                        exist["seen"] = now
                    else:
                        t = dict(t)
                        t["seen"] = now
                        self._world["threats"].append(t)
                # 物体同理
                for o in new_state.get("objects", []):
                    key = (str(o.get("type", "")), str(o.get("dir", "")))
                    exist = next((x for x in self._world["objects"]
                                  if (str(x.get("type", "")), str(x.get("dir", ""))) == key), None)
                    if exist:
                        exist.update(o)
                        exist["seen"] = now
                    else:
                        o = dict(o)
                        o["seen"] = now
                        self._world["objects"].append(o)
                # 标量字段
                if new_state.get("self_hp") is not None:
                    self._world["self_hp"] = new_state["self_hp"]
                if new_state.get("situation"):
                    self._world["situation"] = new_state["situation"]
                if new_state.get("crosshair"):
                    self._world["crosshair"] = new_state["crosshair"]
                self._world["updated_at"] = now
            # 过期清理（物体恒存窗口外丢弃）
            self._world["threats"] = [t for t in self._world["threats"]
                                      if now - t.get("seen", 0) <= self.WORLD_TTL]
            self._world["objects"] = [o for o in self._world["objects"]
                                      if now - o.get("seen", 0) <= self.WORLD_TTL]

    def _world_to_text(self) -> str:
        """把持久世界态序列化为紧凑文本，喂给决策 LLM（母语模态，可推理）。"""
        with self._lock:
            w = self._world
            threats = "; ".join(
                f"{t.get('type','?')} {t.get('dir','?')} {t.get('distance','?')} {t.get('motion','?')}"
                for t in w["threats"]
            ) or "无"
            objects = "; ".join(
                f"{o.get('type','?')} {o.get('dir','?')} {o.get('distance','?')}"
                for o in w["objects"]
            ) or "无"
            hp = w["self_hp"] if w["self_hp"] is not None else "未知"
            res = "; ".join(
                f"{r.get('type','?')} {self._dist_label(r.get('dist'))}"
                for r in w.get("resources", [])
            ) or "无"
            return (
                f"自身血量={hp} 局势={w['situation'] or '未知'} 准星={w['crosshair'] or '未知'}\n"
                f"威胁=[{threats}] 物体=[{objects}] 可采集=[{res}]"
            )

    def _dist_label(self, d):
        try:
            d = float(d)
        except Exception:
            return "?"
        if d < 3:
            return "近"
        if d < 10:
            return "中"
        return "远"

    def _ingest_mc_state(self, raw: str):
        """解析 Mineflayer 桥导出的结构化状态 JSON，写入持久世界态。
        这是'三维→一维文本'的最强 grounding：桥已把实体坐标转成'以玩家为原点'的相对方向+距离。"""
        try:
            obj = json.loads(raw)
            now = time.time()
            with self._lock:
                if obj.get("health") is not None:
                    try:
                        self._world["self_hp"] = int(obj["health"])
                    except Exception:
                        pass
                if obj.get("situation"):
                    self._world["situation"] = obj["situation"]
                self._world["threats"] = []
                self._world["objects"] = []
                for e in obj.get("entities", []):
                    item = {
                        "type": str(e.get("type", "?")),
                        "dir": str(e.get("dir", "?")),
                        "distance": str(e.get("distance_label") or self._dist_label(e.get("distance"))),
                        "motion": str(e.get("motion", "未知")),
                        "hostile": bool(e.get("hostile")),
                        "seen": now,
                    }
                    if e.get("hostile"):
                        self._world["threats"].append(item)
                    else:
                        self._world["objects"].append(item)
                self._world["updated_at"] = now
        except Exception as e:
            log.warning(f"[游戏agent] Mineflayer 状态解析失败: {e}")

    def _mc_state_read(self) -> bool:
        """可选：Minecraft 直接读游戏内存状态（最强 grounding）。
        需 mc_bridge.js（Mineflayer）把结构化状态写入 NAIXI_MC_STATE 指向的文件。
        读到并写入世界态返回 True；未配置/读取失败返回 False，自动回退到视觉 grounding。"""
        path = os.environ.get("NAIXI_MC_STATE") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mc_state.json")
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return False
            self._ingest_mc_state(raw)
            return True
        except Exception:
            return False

    # ───────────────────────── 观察者真相（作弊级 grounding） ─────────────────────────
    @staticmethod
    def _bearing_to_dir(bearing: float) -> str:
        """相对方位角(度,0=正前,正=右) → 中文方位词，供威胁/物体标注与反射撤离用。"""
        b = bearing if bearing is not None else 0
        if abs(b) <= 30:
            return "前"
        if 30 < abs(b) <= 120:
            return "右" if b > 0 else "左"
        return "后"

    def _grounding_read(self) -> bool:
        """读取只读世界观察者写出的 naixi_grounding.json（作弊级真相：精确坐标/实体/方块/瞄准增量）。
        默认开启——这是用户要的「像外挂一样握有世界真相」的能力；观察者没跑时返回 False，
        自动回退到视觉 grounding（看屏兜底）。观察者只读不写，绝不生成独立 bot。"""
        if not os.path.exists(self._grounding_path):
            self._grounding_ok = False
            return False
        try:
            with open(self._grounding_path, "r", encoding="utf-8") as f:
                g = json.load(f)
            p = g.get("player", {})
            ents = g.get("entities", [])
            now = time.time()
            with self._lock:
                self._world["self_hp"] = p.get("hp") if p.get("hp") is not None else self._world["self_hp"]
                self._world["self_pos"] = (p.get("x"), p.get("y"), p.get("z"))
                self._world["self_yaw"] = p.get("yaw")
                self._world["self_pitch"] = p.get("pitch")
                self._world["on_ground"] = p.get("on_ground")
                self._world["in_water"] = p.get("in_water")
                self._world["threats"] = [
                    {"type": e["type"], "dir": self._bearing_to_dir(e.get("rel_bearing", 0)),
                     "distance": self._dist_label(e.get("dist")), "distance_num": e.get("dist"),
                     "motion": "逼近", "seen": now, "dy": e.get("dy")}
                    for e in ents if e.get("category") == "hostile" and (e.get("dist") or 99) <= 14
                ]
                self._world["objects"] = [
                    {"type": e["type"], "dir": self._bearing_to_dir(e.get("rel_bearing", 0)),
                     "distance": self._dist_label(e.get("dist"))}
                    for e in ents if e.get("category") in ("animal", "item")
                ]
                self._world["resources"] = g.get("resources", []) or []
                self._world["updated_at"] = now
            aim = g.get("aim")
            if aim:
                self._aim = (float(aim.get("mx", 0)), float(aim.get("my", 0)))
                self._aim_cat = aim.get("category")
                self._aim_dist = float(aim.get("dist") or 99)
            else:
                self._aim = None
                self._aim_cat = None
                self._aim_dist = 99
            self._grounding_ok = True
            return True
        except Exception as e:
            log.warning(f"[游戏agent] grounding 读取失败: {e}")
            self._grounding_ok = False
            return False

    # ───────────────────────── 客户端只读 Mod API（首选 grounding，2026-08-03 批准） ─────────────────────────
    def _ingest_api_state(self, obj: dict):
        """把 Mod 暴露的只读 API 状态 JSON 归一化进持久世界态（与 _grounding_read 同构）。
        这是单机下结构化真相的最强 grounding——精确坐标/实体/方块/瞄准增量，免 VL 费用。
        Mod 只读不写，不生成独立实体（不是 bot，只是传感器）。"""
        try:
            now = time.time()
            p = obj.get("player", {}) or {}
            ents = obj.get("entities", []) or []
            with self._lock:
                if p.get("hp") is not None:
                    try:
                        self._world["self_hp"] = float(p["hp"])
                    except Exception:
                        pass
                self._world["self_pos"] = (p.get("x"), p.get("y"), p.get("z"))
                self._world["self_yaw"] = p.get("yaw")
                self._world["self_pitch"] = p.get("pitch")
                self._world["on_ground"] = p.get("on_ground")
                self._world["in_water"] = p.get("in_water")
                self._world["threats"] = [
                    {"type": str(e.get("type", "?")), "dir": self._bearing_to_dir(e.get("rel_bearing", 0)),
                     "distance": self._dist_label(e.get("dist")), "distance_num": e.get("dist"),
                     "motion": "逼近", "seen": now, "dy": e.get("dy")}
                    for e in ents if e.get("hostile") and (e.get("dist") or 99) <= 14
                ]
                self._world["objects"] = [
                    {"type": str(e.get("type", "?")), "dir": self._bearing_to_dir(e.get("rel_bearing", 0)),
                     "distance": self._dist_label(e.get("dist"))}
                    for e in ents if (not e.get("hostile")) and e.get("category") in ("animal", "item", None)
                ]
                self._world["resources"] = [
                    {"type": str(r.get("type", "?")), "dist": r.get("dist"),
                     "dir": self._bearing_to_dir(r.get("rel_bearing", 0))}
                    for r in (obj.get("resources", []) or [])
                ]
                self._world["updated_at"] = now
            aim = obj.get("aim")
            if aim:
                self._aim = (float(aim.get("mx", 0)), float(aim.get("my", 0)))
                self._aim_cat = aim.get("category")
                self._aim_dist = float(aim.get("dist") or 99)
            else:
                self._aim = None
                self._aim_cat = None
                self._aim_dist = 99
            self._grounding_ok = True
        except Exception as e:
            log.warning(f"[游戏agent] API 状态归一化失败: {e}")
            self._grounding_ok = False

    def _grounding_http(self) -> bool:
        """读取客户端只读 Mod 暴露的 localhost 只读 API（默认 http://127.0.0.1:25566/state）。
        这是用户批准的「客户端只读 Mod」例外：Mod 只暴露用户自己客户端的世界态，动作仍由键鼠注入同一客户端。
        读到并归一化返回 True；Mod 没装/没跑/连不上 → 返回 False，自动回退视觉 grounding。
        **绝不**依赖任何 multiplayer 服务端 / Open to LAN / 连服观察者。"""
        try:
            import urllib.request
            req = urllib.request.Request(self._mc_api_url, headers={"User-Agent": "naixi-game-agent"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            obj = json.loads(raw)
            self._ingest_api_state(obj)
            return True
        except Exception as e:
            log.info(f"[游戏agent] Mod API 不可用（回退视觉）: {e}")
            self._grounding_ok = False
            return False

    # ───────────────────────── 本地反射：兜底 LLM 决策延迟 ─────────────────────────
    def _reflex(self) -> bool:
        """若云端刚报某方向有威胁且本地运动仍升 → 直接 sub-100ms 撤离，不等 LLM。
        返回 True 表示触发了反射动作。"""
        now = time.time()
        if now - self._last_reflex < self.REFLEX_COOLDOWN:
            return False
        with self._lock:
            threats = self._world["threats"]
            fresh = [t for t in threats if now - t.get("seen", 0) <= self.REFLEX_GAP]
        if not fresh:
            return False
        # 取最近的、正在靠近的威胁方向，反方向撤离
        threat = max(fresh, key=lambda t: t.get("seen", 0))
        dir_word = str(threat.get("dir", ""))
        # 方位撤离映射（以玩家为原点，第一人称）：
        #   前/前-右/前-左 → 后撤；左→右移；右→左移；上→后撤（头顶威胁退远）；
        #   下/后/中/未知 → 后撤（脚下/身后威胁优先拉开距离，侧移无效时退最稳）
        if "左" in dir_word and "前" not in dir_word:
            evade = "right"
        elif "右" in dir_word and "前" not in dir_word:
            evade = "left"
        else:
            evade = "back"   # 前/前-左/前-右/上/下/后/中/未知 一律后撤
        if self._motion > self._high_motion * 0.5:   # 运动仍升，确有东西在动
            self._execute(evade)
            if "前" in dir_word:
                self._execute("jump")   # 前方威胁顺带跳一下拉开距离
            self._last_reflex = now
            log.info(f"[游戏agent] 本地反射撤离：威胁方向={dir_word} 动作={evade}")
            return True
        return False

    # ───────────────────────── 规则驱动（作弊级真相 → 确定性目标行为） ─────────────────────────
    def _policy_grounded(self) -> str:
        """基于观察者真相的【规则驱动】玩法——这正是外挂脚本的核心：握有精确世界状态，
        用确定性逻辑去导航/采集/战斗，而不是靠 LLM 瞎猜。
        目标完全由观察者选定（self._aim 携带类别/距离），策略只负责「对准→接近→动手」。"""
        with self._lock:
            hp = self._world.get("self_hp")
            aim = self._aim
            aim_cat = self._aim_cat
            aim_dist = self._aim_dist
        # 1) 低血量优先保命（撤离+跳）
        if hp is not None and hp < 6:
            return "jump" if (self._step % 2 == 0) else "back"
        # 2) 有瞄准目标 → 对准优先（每帧闭环修正，偏转越大转越多）；对准后接近/动手
        if aim is not None:
            mx, my = aim
            if abs(mx) > 12 or abs(my) > 12:
                self._last_aim = (mx, my)
                return "aim"
            # 已对准：近身就动手（攻击或采矿通用左键），否则继续接近
            if aim_dist <= 3.2:
                return "attack"
            return "forward"
        # 3) 无目标 → 探索（前进为主，撞墙由 reflect 纠偏）
        return self._decide_fallback()

    # ───────────────────────── 决策：LLM 产出下一步动作 ─────────────────────────
    def _decide(self, world_text: str, motion: float) -> str:
        """复用 live_engine._raw_llm_call，喂**结构化世界态文本**产出动作词。"""
        # bot 模式：无威胁时本地探索（保证持续移动可做演示），有威胁才交给 LLM 决策攻击/撤离
        if self._bot_mode and not self._world.get("threats"):
            return self._decide_fallback()
        try:
            game_ctx = {
                "minecraft": "你在玩 Minecraft（键鼠第一人称）。动作：forward前进/back后退/left左移/right右移/jump跳/look_left左转视角/look_right右转视角/look_up抬头/look_down低头/interact交互(E)/attack攻击(左键)/use使用(右键)/inventory背包(E)/slot1~4切换物品栏/drop丢弃/wait等待/screenshot_only只截图不操作。forward等移动会持续一小段时间；若前方被挡（墙/方块）就先 look_left/look_right 转视角找路，别一直撞墙。",
            }.get(self.game, "你在玩一个键鼠游戏。")
            sys_p = (
                f"你是游戏AI助手，正在{game_ctx}\n"
                f"只允许输出以下单个动作之一：{', '.join(sorted(self.ALLOWED_ACTIONS))}。\n"
                "不要解释、不要标点，只输出一个英文动作词。若画面信息不足或处于加载/菜单，输出 wait。"
                "若看到敌人/危险靠近或处于不利状态，优先避让或攻击；若血量低优先撤离并回血。"
                "依据下方空间状态推理，而非凭空想象。"
            )
            from desktop_core.live_engine import engine
            reply = asyncio.run(engine._raw_llm_call([
                {"role": "system", "content": sys_p},
                {"role": "user", "content":
                 f"画面运动强度={motion:.2f}。空间状态：{world_text}"},
            ]))
            if not reply:
                return self._decide_fallback()
            act = reply.strip().lower().split()[0] if reply.strip() else "wait"
            if act not in self.ALLOWED_ACTIONS:
                return self._decide_fallback()
            return act
        except Exception as e:
            log.warning(f"[游戏agent] 决策失败(走本地兜底): {e}")
            return self._decide_fallback()

    def _decide_fallback(self) -> str:
        """无 LLM / LLM 不可用时本地随机游走，保证机器人持续移动可做演示。
        以前进为主，偶尔转向或跳，避免在 peaceful 世界里原地发呆。"""
        import random
        r = random.random()
        if r < 0.62:
            return "forward"
        elif r < 0.78:
            return "look_right"
        elif r < 0.94:
            return "look_left"
        else:
            return "jump"

    # ───────────────────────── 执行：把动作发给键鼠 ─────────────────────────
    def _execute(self, action: str):
        if action in ("wait", "screenshot_only"):
            return
        if action == "aim":
            # 瞄准：Mod 已算出「看向目标」所需鼠标增量，闭环逐帧修正
            a = getattr(self, "_last_aim", None) or self._aim
            if a:
                sign = int(os.environ.get("NAIXI_AIM_SIGN", "1"))  # 若越转越偏改 1→-1
                mx = max(-260, min(260, int(a[0] * sign)))
                my = max(-200, min(200, int(a[1] * sign)))
                move_mouse(mx, my, hold_ms=120)   # 见 action_lib
            return
        # 其余动作统一委托 action_lib.safe_execute：
        # 默认 require_window=True —— 找不到游戏窗口就「安全中止」，
        # 绝不把键鼠打进用户当前的任意前台窗口（旧版隐患已修）。
        res = safe_execute(action, window_substr="minecraft", require_window=True, focus=True)
        if not res.get("ok") and res.get("aborted"):
            log.warning(f"[游戏agent] 动作 {action} 安全中止：{res.get('detail')}")

    def _execute_bot(self, action: str):
        """已废弃：机器人模式被用户否决。动作统一经 _execute 的键鼠分支操控真实角色。"""
        log.warning(f"[游戏agent] _execute_bot 已废弃，忽略机器人动作={action}")

    # ───────────────────────── 执行后反思：闭环纠偏 ─────────────────────────
    def _reflect(self, action: str):
        """执行动作后反思：角色到底动没动 / 卡没卡 / 死没死。对标 Cradle 自我反思模块。
        主要用帧差（免费、实时）判断移动结果；节流用视觉确认死亡/菜单等关键时刻。
        结果写入 self._reflect_text，下一轮决策会带上它做纠偏。"""
        try:
            time.sleep(0.6)  # 等动作生效
            after = self._motion
            parts = []
            if action in self.HOLD_ACTIONS:
                if after < 0.006:   # 画面几乎没动 → 卡住/撞墙
                    self._stuck = min(self._stuck + 1, 9)
                    parts.append(f"上一步[{action}]后角色疑似卡住/撞墙（连续{self._stuck}次画面未动）")
                else:
                    if self._stuck:
                        parts.append(f"已脱困（上一步[{action}]后画面运动={after:.3f}）")
                    self._stuck = 0
            # 节流视觉确认死亡/菜单（每 3 次 reflect 才调一次视觉模型，省 LLM）
            self._reflect_tick = (self._reflect_tick + 1) % 3
            if self._reflect_tick == 0:
                st = self._vision_ground(self._motion)
                sit = str(st.get("situation", ""))
                if sit in ("死亡", "菜单", "加载"):
                    parts.append(f"画面状态={sit}")
                    if sit == "死亡":
                        self._stuck = 9  # 死亡：交给决策层处理（重生/退出菜单）
            self._reflect_text = "; ".join(parts) if parts else "上一步执行未见异常"
        except Exception as e:
            log.warning(f"[游戏agent] 反思异常: {e}")
            self._reflect_text = ""

    # ───────────────────────── 主循环 + 线程控制 ─────────────────────────
    async def start(self, interval: float = None, max_steps: int = None):
        if self._running:
            return True
        self._running = True
        self._step = 0
        if interval:
            self._loop_interval = interval
        if max_steps:
            self._max_steps = max_steps
        if not self._bot_mode:
            self._cap_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._cap_thread.start()
        self._task = asyncio.create_task(self._run_loop())
        log.info(f"[游戏agent] 启动：game={self.game} 本地{self.LOCAL_FPS}fps 云端巡检{self._cloud_interval}s "
                 f"突变阈值{self._high_motion} 主循环{self._loop_interval}s 单局上限{self._max_steps} "
                 f"世界态恒存{self.WORLD_TTL}s 反射窗口{self.REFLEX_GAP}s")
        return True

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        if self._cap_thread:
            self._cap_thread.join(timeout=2.0)
            self._cap_thread = None
        log.info("[游戏agent] 已停止")

    async def _run_loop(self):
        try:
            while self._running and self._step < self._max_steps:
                await asyncio.sleep(self._loop_interval)
                self._step += 1
                now = time.time()
                motion = 0.0 if self._bot_mode else self._motion
                # 本地反射：云报威胁 + 本地运动仍升 → sub-100ms 撤离（不等 LLM）
                if self._reflex():
                    continue
                # 是否需要云端 grounding：bot 模式无屏幕，纯按巡检节拍；否则到点巡检或画面突变
                if self._bot_mode:
                    need_cloud = (now - self._last_cloud >= self._cloud_interval)
                else:
                    need_cloud = (
                        (now - self._last_cloud >= self._cloud_interval)
                        or (motion > self._high_motion and now - self._last_cloud >= self._cloud_min_gap)
                    )
                if not need_cloud:
                    continue
                self._last_cloud = now
                # 1) 首选：客户端只读 Mod 的 localhost API（用户已批准，结构化世界真相最精准）
                #    —— 这是外挂脚本级能力：握有精确坐标/实体/方块 + 瞄准增量，规则驱动确定性玩法。
                #    Mod 只读不写、不生成 bot；它没跑时自动回退到视觉 grounding（看屏兜底）。
                ground_ok = False
                if self._grounding_src in ("auto", "http"):
                    ground_ok = await asyncio.to_thread(self._grounding_http)
                if ground_ok:
                    world_text = await asyncio.to_thread(self._world_to_text)
                    world_text = f"[世界真相-Mod API]\n{world_text}\n[上一步反馈] {self._reflect_text}"
                    action = await asyncio.to_thread(self._policy_grounded)   # 规则驱动，无需 LLM
                    if self._stuck >= 2 and action in self.HOLD_ACTIONS:
                        action = "look_right" if self._stuck % 2 == 0 else "look_left"
                        log.info(f"[游戏agent] 卡住纠偏：动作改为 {action}")
                else:
                    # 2) 视觉 grounding（看屏兜底）：拼运动片段 → 结构化场景图 → 合并世界态
                    state = await asyncio.to_thread(self._vision_ground, motion)
                    await asyncio.to_thread(self._merge_world, state)
                    world_text = await asyncio.to_thread(self._world_to_text)
                    world_text = f"{world_text}\n[上一步反馈] {self._reflect_text}"
                    action = await asyncio.to_thread(self._decide, world_text, motion)
                    if self._stuck >= 2 and action in self.HOLD_ACTIONS:
                        action = "look_right" if self._stuck % 2 == 0 else "look_left"
                        log.info(f"[游戏agent] 卡住纠偏：动作改为 {action}")
                log.info(f"[游戏agent] step={self._step} 运动={motion:.3f} 状态='{world_text[:60]}' 动作={action}")
                await asyncio.to_thread(self._execute, action)
                # 执行后反思：角色到底动没动/卡没卡/死没死（帧差免费判 + 节流视觉确认）
                await asyncio.to_thread(self._reflect, action)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning(f"[游戏agent] 循环异常: {e}")
        finally:
            self._running = False
            log.info("[游戏agent] 循环结束")
