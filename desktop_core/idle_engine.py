"""Qt 桌宠程序化 idle 动作引擎（下意识动作）。

不依赖模型作者制作的 motion 文件，直接驱动 Live2D Cubism 标准参数
（ParamAngleX/Y/Z、ParamEyeBallX/Y、ParamEyeLOpen/ROpen、ParamBreath、
ParamBodyAngleX/Y 等），在每帧渲染前叠加设置，模拟真人下意识小动作：
呼吸、身体浮动、眨眼、视线跟随鼠标、随机摇头/歪头、被风吹、突脸等。

设计要点：
- 标准参数名 -> 模型实际参数名用「模糊包含匹配」，找不到该参数的动作自动跳过（容错，避免不同模型命名差异崩）。
- 每个动作可独立开关，右键「动作」子菜单勾选；默认开启基础几项。
- 每帧调用 IdleEngine.update(model, ctx)，由各动作累加到模型参数。
- 与 Live2D 的 motion/expression 共存：idle 参数应在 model.Update() 之后、Draw() 之前设置（weight 控制叠加强度）。
- 动作冲突/覆盖：多个动作可能写同一 Cubism 参数（见文件下方 _ACTION_PARAM_SPEC 冲突地图）。
  同一参数被多个 set 动作写时，按 UPDATE_ORDER 的"末位写入者"按权重混合占优（即覆盖前者）。
  冲突与覆盖关系在运行时由 _log_conflicts() 自检并打印到 [idle] 日志；每个 _update_* 内也有行内注释。
"""

import math
import time
import random
import logging

_log = logging.getLogger("idle_engine")

# 突脸（poke）一次放大的总时长（秒）：快速攻顶 + 缓回弹
POKE_DURATION = 0.55
# 突脸峰值缩放：模型在 scale=1.0 时已贴合窗口，超过 ~1.12 就会从四边溢出被裁，
# 故峰值压到 1.10；配合轻微前倾(angle_x)增强"脸凑近"观感，避免靠大幅缩放撑场面。
POKE_PEAK_SCALE = 1.10
POKE_LEAN_DEG = 5.0

# 呼吸式缩放（scale_breath 动作）：像呼吸一样轻微缩放脉动，安全不溢出窗口。
# 它走模型 transform 的 SetScale（与 poke 同源），不写 Cubism 参数，
# 故与参数冲突地图(_ACTION_PARAM_SPEC)无关，缩放在 update() 末尾统一合成。
SCALE_BREATH_AMP = 0.03       # 缩放幅度（±3%，模型在窗口内轻微胀缩）
SCALE_BREATH_FREQ = 1.2       # 脉动频率（rad/s），约 5.2s 一个呼吸周期
SCALE_MAX = 2.2               # 合成缩放上限：须 == pet_window.ZOOM_PAD（2.2）。模型 Resize 用 BASE/ZOOM_PAD，
                               # SetScale 最大 2.2 时模型恰好铺满窗口；配合滚轮 zoom[0.5,2.0]×呼吸(1.03)×突脸(1.10)×蹦跳(1.05)峰值≈2.39>2.2 会被夹断
                               # （仅满档微抑，无裁边）。改这里务必同步 pet_window.ZOOM_PAD。
# 开心蹦跳（bounce 动作）：像小跳一样周期性轻微放大脉冲（走 SetScale，非 Cubism 参数）。
# 幅度须小：峰值 POKE_PEAK_SCALE=1.10 已接近窗口边；bounce 峰值 1.05 叠加呼吸 1.03 ≈ 1.08，与 poke 同帧极端情况才触顶。
BOUNCE_AMP = 0.05             # 蹦跳缩放幅度（±5%）
BOUNCE_FREQ = 6.0             # 蹦跳频率（rad/s），约 1.05s 一跳，俏皮不急促

# 歪头杀（tilt）：angle_z 单向定格偏移（卖萌歪头）。正值=向右歪（不同模型朝向可能相反，容错即可）。
TILT_ANGLE_Z = 12.0           # 歪头定格角度（度），约 ±12° 明显但不夸张
# 头发飘动（hair_sway）：发丝自然微摆幅度（度/无量纲，按模型 hair 参数尺度）。
HAIR_SWAY_AMP = 6.0           # 前发摆幅
HAIR_SWAY_AMP_BACK = 4.0      # 后发/鬓发摆幅（更慢更柔）
HAIR_SWAY_FREQ = 1.3          # 飘动基频（rad/s）
# 眉毛挑动（brow_raise）：周期性"嗯?"挑眉；幅度按 BrowY 参数尺度（多数模型 0..1，挑眉正向）。
BROW_RAISE_AMP = 0.8
BROW_RAISE_HOLD = 0.5         # 挑眉保持时长（s）
BROW_RAISE_GAP = (4.0, 9.0)   # 两次挑眉间隔随机区间（s）
# 开心扭动（wiggle）：body_angle_x 快速叠加微抖（跳舞感），add 模式不与 look_cursor/wind 打架。
WIGGLE_AMP = 4.0              # 扭动角幅（度）
WIGGLE_FREQ = 7.0             # 扭动频率（rad/s），较快显俏皮
# 张嘴哼歌（mouth_hum）：周期性"哼"短语，嘴一张一合。
MOUTH_HUM_OPEN = 0.7          # 张嘴峰值（MouthOpenY 0..1）
MOUTH_HUM_GAP = (3.0, 8.0)    # 两次哼歌间隔随机区间（s）
MOUTH_HUM_PHRASE = (0.6, 1.4) # 单次哼歌短语时长随机区间（s）

# ── 动作参数占用表（冲突标注）──
# 每个程序化动作驱动的标准 Cubism 参数、写入权重、写入模式。
#   模式 "set" = SetParameterValue(value, weight)：在前者基础上按权重混合，权重高者占优。
#   模式 "add" = AddParameterValue(value)：在前者结果上增量叠加（不抢占）。
# 同一参数被多个动作写入 = 冲突：update() 按固定顺序叠加，后写者用权重在前值上混合，
# 故"谁后写 + 权重高"谁占优。下表即冲突地图，与下方各 _update_* 的注释一一对应。
_ACTION_PARAM_SPEC = {
    "breath":      [("breath", 0.6, "set")],
    "body_float":  [("body_angle_x", 0.7, "set"), ("body_angle_y", 0.7, "set")],
    "look_cursor": [("angle_x", 0.85, "set"), ("angle_y", 0.85, "set"),
                    ("eye_ball_x", 0.95, "set"), ("eye_ball_y", 0.95, "set")],
    "head_sway":   [("angle_z", 0.6, "set"), ("angle_x", 0.5, "add")],
    "wind":        [("angle_z", 0.8, "set"), ("body_angle_x", 0.75, "set"), ("angle_x", 0.6, "set")],
    "poke":        [("angle_x", 0.9, "set")],  # 仅"突脸窗口"内写 angle_x(前倾)；窗口外不碰，交还 look_cursor。另用 SetScale 做整体放大(transform，非 Cubism 参数)
    # —— 以下为 2026-07-31 新增的"鲜活动作"（默认关闭，菜单勾选启用）——
    "mouth_hum":   [("mouth_open", 1.0, "set")],          # 张嘴哼歌：嘴部一张一合；仅本动作写 mouth_open，无冲突
    "bounce":      [],                                     # 开心蹦跳：走 transform SetScale 微脉冲（非 Cubism 参数），与 breath/poke 同在 update() 末尾合成
    "tilt":        [("angle_z", 0.55, "set")],             # 歪头杀：angle_z 单向定格（卖萌歪头）；与 head_sway(angle_z 0.6 振荡)抢，本动作权重略低→head_sway 启用时覆盖本动作
    "hair_sway":   [("hair_front", 0.6, "set"), ("hair_back", 0.5, "set"), ("hair_body", 0.5, "set")],  # 头发飘动：发丝自然微摆；仅本动作写 hair_*，无冲突
    "brow_raise":  [("brow_y", 1.0, "set")],               # 眉毛挑动：周期性"嗯?"挑眉；仅本动作写 brow_y，无冲突
    "wiggle":      [("body_angle_x", 0.6, "add")],         # 开心扭动：body_angle_x 快速叠加微抖（跳舞感）；add 模式不与 look_cursor/wind/body_float 的 set 打架，叠加共存
}


def _conflict_map():
    """返回 {被争夺的参数用途: [(动作名, 模式), ...]}，只列被>=2个动作共用的参数。"""
    rev = {}
    for _act, _spec in _ACTION_PARAM_SPEC.items():
        for _use, _, _mode in _spec:
            rev.setdefault(_use, []).append((_act, _mode))
    return {_use: _acts for _use, _acts in rev.items() if len(_acts) > 1}


# update() 内各动作的应用顺序（后者在同一参数上按权重混合，故"末位写入者占优/覆盖前者"）。
# 须与 IdleEngine.update() 中的 if 顺序保持一致；新增动作须同步追加到此处，否则覆盖判定失准。
UPDATE_ORDER = ["breath", "body_float", "blink", "look_cursor", "head_sway", "wind", "poke",
                "mouth_hum", "bounce", "tilt", "hair_sway", "brow_raise", "wiggle"]


def _weight_of(act, use):
    """取某动作对某参数的写入权重（找不到返回 None）。"""
    for u, w, _ in _ACTION_PARAM_SPEC.get(act, []):
        if u == use:
            return w
    return None


# 标准 Cubism 参数用途 -> 模糊匹配 hint 列表（按包含匹配模型实际参数名）
PARAM_HINTS = {
    "angle_x": ["AngleX", "角度X", "ANGLEX"],
    "angle_y": ["AngleY", "角度Y"],
    "angle_z": ["AngleZ", "角度Z"],
    "eye_ball_x": ["EyeBallX", "眼球X", "EYEBALLX"],
    "eye_ball_y": ["EyeBallY", "眼球Y"],
    "eye_l_open": ["EyeLOpen", "EYE_L_OPEN", "左眼睁"],
    "eye_r_open": ["EyeROpen", "EYE_R_OPEN", "右眼睁"],
    "breath": ["Breath", "BREATH", "呼吸"],
    "body_angle_x": ["BodyAngleX", "BODYANGLEX", "身体X"],
    "body_angle_y": ["BodyAngleY", "BODYANGLEY"],
    "body_angle_z": ["BodyAngleZ", "BODYANGLEZ"],
    "mouth_open":   ["MouthOpenY", "MOUTH_OPEN", "嘴型", "口"],
    "mouth_form":   ["MouthForm", "MOUTH_FORM", "嘴形"],
    "brow_y":       ["BrowY", "BROW_Y", "眉毛Y", "眉"],
    "hair_front":   ["HairFront", "HAIRFRONT", "前发", "刘海"],
    "hair_back":    ["HairBack", "HAIRBACK", "后发"],
    "hair_body":    ["HairBody", "HAIRBODY", "鬓发", "侧发"],
    "arm_l":        ["ArmL", "ARML", "手臂L", "左臂"],
    "arm_r":        ["ArmR", "ARMR", "手臂R", "右臂"],
}


def _match_param(all_ids, hints):
    """从模型实际参数名里，按包含匹配挑出第一个命中 hint 的参数名。"""
    for hid in hints:
        hl = hid.lower()
        for pid in all_ids:
            if hl in pid.lower():
                return pid
    return None


class IdleEngine:
    def __init__(self):
        # 呼吸/眨眼用模型自带 SetAutoBreathEnable/SetAutoBlinkEnable（initializeGL 已开启），
        # 故 IdleEngine 默认不开 breath/blink，避免双重驱动；以下为程序化独有的下意识动作。
        self.enabled = {
            "breath": False,
            "blink": False,
            "body_float": True,
            "look_cursor": True,
            "head_sway": True,
            "wind": False,
            "poke": False,
            "scale_breath": False,
            # —— 2026-07-31 新增鲜活动作（默认关闭，菜单勾选启用）——
            "mouth_hum": False,
            "bounce": False,
            "tilt": False,
            "hair_sway": False,
            "brow_raise": False,
            "wiggle": False,
        }
        self._t0 = time.monotonic()
        self._next_blink = 0.0
        self._blink_state = "open"
        self._blink_t = 0.0
        self._poke_until = 0.0
        self._poke_scale = 1.0  # 每帧由 _update_poke 计算，update() 末尾与呼吸缩放合成
        self._wind_phase = random.uniform(0, math.tau)
        self._head_next = 0.0
        self._head_target = 0.0
        self._head_current = 0.0
        # —— 新增动作临时状态 ——
        self._mouth_next = 0.0      # 下次哼歌起始时刻
        self._mouth_t = 0.0         # 当前哼歌短语已进行时间
        self._mouth_active = False  # 是否正在哼
        self._mouth_phrase = 0.0    # 当前哼歌短语总时长
        self._bounce_scale = 1.0    # 每帧由 _update_bounce 计算，update() 末尾合成
        self._bounce_phase = random.uniform(0, math.tau)
        self._brow_next = 0.0       # 下次挑眉时刻
        self._brow_state = "down"
        self._brow_t = 0.0
        self._param_cache = {}  # 用途 -> 实际参数名

    # ---- 配置 ----
    def set_enabled(self, name, val):
        if name in self.enabled:
            self.enabled[name] = bool(val)
            self._log_conflicts()

    def toggle(self, name):
        self.enabled[name] = not self.enabled.get(name, False)
        self._log_conflicts()
        return self.enabled[name]

    def reset(self, model=None):
        """模型加载/切换时调用：重置时间基准、临时状态、参数缓存。"""
        self._t0 = time.monotonic()
        self._next_blink = time.monotonic() + random.uniform(2.0, 5.0)
        self._blink_state = "open"
        self._blink_t = 0.0
        self._poke_until = 0.0
        self._poke_scale = 1.0
        self._head_next = time.monotonic() + random.uniform(4.0, 9.0)
        self._head_target = 0.0
        self._head_current = 0.0
        self._mouth_next = time.monotonic() + random.uniform(3.0, 8.0)
        self._mouth_t = 0.0
        self._mouth_active = False
        self._mouth_phrase = 0.0
        self._bounce_scale = 1.0
        self._bounce_phase = random.uniform(0, math.tau)
        self._brow_next = time.monotonic() + random.uniform(4.0, 9.0)
        self._brow_state = "down"
        self._brow_t = 0.0
        self._param_cache = {}
        if model is not None:
            self._build_param_cache(model)
        self._log_conflicts()

    def _log_conflicts(self):
        """自检：对当前已启用的动作，列出互相争夺同一参数的冲突项，并标注覆盖关系。
        打印到 [idle] 日志，便于排查"某动作看不出"是不是被同参数其它动作覆盖。
        注意：仅当两个动作都用 set 模式写同一参数才算"打架"（后写+高权重占优）；
        add 模式只是叠加微抖，不报冲突。覆盖判定按 UPDATE_ORDER 末位写入者占优。"""
        cmap = _conflict_map()
        if not cmap:
            return
        lines = []
        for use, acts in cmap.items():
            # 真正会"打架"的是两个都用 set 的动作；add 仅叠加，不构成冲突。
            setters = [(a, mode) for (a, mode) in acts if mode == "set" and self.enabled.get(a)]
            if len(setters) <= 1:
                continue
            # 按 update() 应用顺序排成链，末位写入者按权重混合占优（即"覆盖"前者）
            ordered = sorted(setters, key=lambda am: UPDATE_ORDER.index(am[0]))
            chain = " → ".join(f"{a}(w={_weight_of(a, use)})" for a, _ in ordered)
            last = ordered[-1][0]
            # poke 仅在"突脸窗口"内写 angle_x，窗口外交还 look_cursor，故覆盖是瞬时的而非常驻
            note = " (仅突脸窗口内瞬时覆盖)" if last == "poke" else ""
            lines.append(f"{use}: {chain} → 末位[{last}]覆盖占优{note}")
        if lines:
            _log.warning("[idle] 已启用动作存在参数冲突(覆盖关系): " + "; ".join(lines))
        else:
            _log.info("[idle] 当前启用动作无参数冲突")

    def _build_param_cache(self, model):
        ids = []
        try:
            # pet_window 传入的是 live2d.LAppModel 包装层，它暴露的是 GetParamIds()
            # （底层 cpp 对象才是 GetParameterIds）；两个都试，避免 AttributeError 被吞导致缓存恒空。
            if hasattr(model, "GetParamIds"):
                ids = model.GetParamIds()
            elif hasattr(model, "GetParameterIds"):
                ids = model.GetParameterIds()
        except Exception as e:
            _log.warning(f"[idle] GetParamIds 调用失败: {e}")
            ids = []
        if not ids:
            _log.warning("[idle] 模型参数列表为空，程序化动作将无法驱动任何参数（模型可能未就绪）")
            return
        for use, hints in PARAM_HINTS.items():
            pid = _match_param(ids, hints)
            if pid:
                self._param_cache[use] = pid
        if not self._param_cache:
            _log.warning("[idle] 参数缓存为空：未匹配到任何标准 Cubism 参数（模型参数命名可能非标准）")

    def _set(self, model, use, value, weight=1.0):
        pid = self._param_cache.get(use)
        if not pid:
            return
        try:
            model.SetParameterValue(pid, float(value), float(weight))
        except Exception:
            pass

    def _add(self, model, use, value):
        pid = self._param_cache.get(use)
        if not pid:
            return
        try:
            model.AddParameterValue(pid, float(value))
        except Exception:
            pass

    # ---- 主循环 ----
    def update(self, model, ctx):
        """每帧调用。ctx 提供：now/dt/cursor=(gx,gy)/pet_center=(cx,cy)/pet_size=(w,h)。"""
        if model is None:
            return
        if not self._param_cache:
            self._build_param_cache(model)
        now = ctx.get("now", time.monotonic())
        dt = ctx.get("dt", 0.016)
        t = now - self._t0

        if self.enabled.get("breath"):
            v = 0.5 + 0.5 * math.sin(t * 1.8)
            self._set(model, "breath", v, 0.6)

        if self.enabled.get("body_float"):
            bx = math.sin(t * 1.1) * 2.0
            by = math.cos(t * 0.9) * 1.5
            # 冲突: body_angle_x 同时被 wind 写(权重 0.75 > 本 0.7)。启用 wind 时本动作被部分覆盖。
            self._set(model, "body_angle_x", bx, 0.7)
            self._set(model, "body_angle_y", by, 0.7)

        if self.enabled.get("blink"):
            self._update_blink(model, now, dt)

        if self.enabled.get("look_cursor"):
            self._update_look(model, ctx)

        if self.enabled.get("head_sway"):
            self._update_head_sway(model, now, dt)

        if self.enabled.get("wind"):
            self._update_wind(model, t, dt)

        # —— 2026-07-31 新增鲜活动作（默认关，菜单勾选）——
        if self.enabled.get("mouth_hum"):
            self._update_mouth_hum(model, now, dt)
        if self.enabled.get("bounce"):
            self._update_bounce(model, t)
        if self.enabled.get("tilt"):
            self._update_tilt(model, t)
        if self.enabled.get("hair_sway"):
            self._update_hair_sway(model, t)
        if self.enabled.get("brow_raise"):
            self._update_brow_raise(model, now, dt)
        if self.enabled.get("wiggle"):
            self._update_wiggle(model, t)

        # 缩放合成（每帧仅一次 SetScale）：呼吸缩放(±3%) × 突脸缩放(瞬时回弹) × 蹦跳缩放(周期微脉冲) × 滚轮缩放(zoom)。
        # 三者都走模型 transform 的 SetScale（非 Cubism 参数）。窗口几何固定，zoom 仅放大模型本身，零 resize 零闪烁。
        self._poke_scale = 1.0
        if self.enabled.get("poke") or now < self._poke_until:
            self._update_poke(model, now)
        breath_s = 1.0 + SCALE_BREATH_AMP * math.sin(t * SCALE_BREATH_FREQ) if self.enabled.get("scale_breath") else 1.0
        zoom_s = ctx.get("zoom", 1.0)
        final_s = breath_s * self._poke_scale * self._bounce_scale * zoom_s
        if final_s > SCALE_MAX:
            final_s = SCALE_MAX
        elif final_s < 0.3:
            final_s = 0.3
        try:
            model.SetScale(final_s)
        except Exception:
            pass

    # ---- 各动作实现 ----
    def _update_blink(self, model, now, dt):
        if self._blink_state == "open":
            if now >= self._next_blink:
                self._blink_state = "closing"
                self._blink_t = 0.0
        elif self._blink_state == "closing":
            self._blink_t += dt
            k = min(1.0, self._blink_t / 0.08)
            self._set(model, "eye_l_open", 1.0 - k, 1.0)
            self._set(model, "eye_r_open", 1.0 - k, 1.0)
            if k >= 1.0:
                self._blink_state = "closed"
                self._blink_t = 0.0
        elif self._blink_state == "closed":
            self._blink_t += dt
            if self._blink_t >= 0.06:
                self._blink_state = "opening"
                self._blink_t = 0.0
        elif self._blink_state == "opening":
            self._blink_t += dt
            k = min(1.0, self._blink_t / 0.12)
            self._set(model, "eye_l_open", k, 1.0)
            self._set(model, "eye_r_open", k, 1.0)
            if k >= 1.0:
                self._blink_state = "open"
                self._next_blink = now + random.uniform(2.5, 6.0)

    def _update_look(self, model, ctx):
        cursor = ctx.get("cursor")
        center = ctx.get("pet_center")
        if not cursor or not center:
            return
        pw, ph = ctx.get("pet_size", (200, 200))
        dx = (cursor[0] - center[0]) / max(1, pw)
        dy = (cursor[1] - center[1]) / max(1, ph)
        dx = max(-1.0, min(1.0, dx * 2.0))
        dy = max(-1.0, min(1.0, dy * 2.0))
        # angle_x/angle_y 与 head_sway(add angle_x)/wind(angle_x) 冲突；本动作权重最高(0.85/0.95)通常占优。
        self._set(model, "angle_x", dx * 18.0, 0.85)
        self._set(model, "angle_y", -dy * 14.0, 0.85)
        self._set(model, "eye_ball_x", dx * 1.0, 0.95)
        self._set(model, "eye_ball_y", -dy * 1.0, 0.95)

    def _update_head_sway(self, model, now, dt):
        if now >= self._head_next:
            self._head_target = random.choice([-1, 1]) * random.uniform(6.0, 16.0)
            self._head_next = now + random.uniform(5.0, 11.0)
        self._head_current += (self._head_target - self._head_current) * min(1.0, dt * 3.0)
        # 冲突: angle_z 同时被 wind 写(权重 0.8 > 本 0.6)。启用 wind 时本摇头被覆盖；权重低故常态下本动作占优。
        self._set(model, "angle_z", self._head_current, 0.6)
        # angle_x 增量(非抢占)，与 look_cursor/wind 共存时不打架（仅叠加微抖）
        self._add(model, "angle_x", math.sin(now * 2.0) * 0.5)

    def _update_wind(self, model, t, dt):
        # 基础持续轻摇 + 慢起伏的"阵风(gust)"包络：让"被风吹"有明显强弱起伏，
        # 而非恒定微动（旧版权重仅 0.4、幅度小，被 head_sway/body_float 同参数覆盖，几乎看不出）。
        base = math.sin(t * 0.9 + self._wind_phase) * 0.5
        gust_env = 0.5 + 0.5 * math.sin(t * 0.11 + self._wind_phase * 2.0)  # 0..1 慢起伏
        gust = (math.sin(t * 2.1 + self._wind_phase) * 0.6
                + math.sin(t * 3.3 + self._wind_phase * 1.7) * 0.4)
        w = base + gust_env * gust * 1.7
        # 吹动表现：头部左右摆 + 身体随阵风倾斜 + 整体朝风向微倾（读得出"被风吹"）
        # 冲突标注: angle_z 与 head_sway(0.6) 抢、body_angle_x 与 body_float(0.7) 抢、angle_x 与 look_cursor(0.85)/head_sway 抢；
        # 本动作权重(0.8/0.75/0.6)均 >= 竞争者，故启用 wind 时本动作占优、其它被部分覆盖。
        # 幅度取舍（2026-07-28 调大）：angle_z 拉到 w*20（峰≈±36°，超标准 ±30 夹断，强阵风时头部被"钉"在最大倾角，自然）；
        #   body_angle_x 维持 w*8（峰≈±14°已超身体 ±10 夹断，再大只会让身体更久"卡"在极限而非摆动，故不放大）；
        #   angle_x 拉到 w*10（峰≈±18°，强阵风时盖过看鼠标的轻微跟随，符合"被风吹得仰/低头"）。
        self._set(model, "angle_z", w * 20.0, 0.8)
        self._set(model, "body_angle_x", w * 8.0, 0.75)
        self._set(model, "angle_x", w * 10.0, 0.6)

    def _update_poke(self, model, now):
        # 只计算本帧突脸缩放因子(self._poke_scale)，真正的 SetScale 在 update() 末尾统一合成，
        # 与呼吸缩放(scale_breath)合并为一次调用，避免两者各 SetScale 互相覆盖。
        self._poke_scale = 1.0
        if now >= self._poke_until and self.enabled.get("poke"):
            if random.random() < 0.002:  # 常开启时的偶发突脸
                self._poke_until = now + POKE_DURATION
        if now < self._poke_until:
            elapsed = POKE_DURATION - (self._poke_until - now)  # 0..DURATION
            attack = 0.09  # 快速攻顶
            if elapsed < attack:
                f = elapsed / attack
                self._poke_scale = 1.0 + (POKE_PEAK_SCALE - 1.0) * f
            else:
                # 缓回弹（ease-out），落回 1.0
                f = (elapsed - attack) / max(1e-3, POKE_DURATION - attack)
                self._poke_scale = 1.0 + (POKE_PEAK_SCALE - 1.0) * (1.0 - f) * (1.0 - f)
            # 轻微前倾强化"脸凑近"观感（poke 是一次性意图动作，短暂覆盖 look_cursor/wind 的 angle_x 无妨）
            self._set(model, "angle_x", POKE_LEAN_DEG * (self._poke_scale - 1.0) / (POKE_PEAK_SCALE - 1.0), 0.9)
        # 非突脸时段：_poke_scale 保持 1.0，且绝不碰 angle_x，把头部交还给 look_cursor/wind。

    # ---- 2026-07-31 新增鲜活动作 ----
    def _update_mouth_hum(self, model, now, dt):
        """张嘴哼歌：周期性"哼"短语，嘴一张一合（ParamMouthOpenY）。无嘴部模型自动跳过。"""
        if not self._mouth_active:
            if now >= self._mouth_next:
                self._mouth_active = True
                self._mouth_t = 0.0
                self._mouth_phrase = random.uniform(*MOUTH_HUM_PHRASE)
        else:
            self._mouth_t += dt
            # 短语内：2~3 个快速张合循环（哼哼~）
            cyc = self._mouth_t / max(1e-3, self._mouth_phrase) * 2.5 * math.pi
            v = max(0.0, math.sin(cyc)) * MOUTH_HUM_OPEN
            self._set(model, "mouth_open", v, 1.0)
            if self._mouth_t >= self._mouth_phrase:
                self._mouth_active = False
                self._set(model, "mouth_open", 0.0, 1.0)
                self._mouth_next = now + random.uniform(*MOUTH_HUM_GAP)

    def _update_bounce(self, model, t):
        """开心蹦跳：周期性轻微放大脉冲（走 SetScale，非 Cubism 参数），与呼吸/突脸在 update() 末尾合成。"""
        self._bounce_scale = 1.0 + BOUNCE_AMP * (0.5 + 0.5 * math.sin(t * BOUNCE_FREQ + self._bounce_phase))

    def _update_tilt(self, model, t):
        """歪头杀：angle_z 单向定格偏移（卖萌歪头）。与 head_sway(angle_z 振荡)抢同参数，本动作权重略低→head_sway 启用时覆盖本动作。"""
        self._set(model, "angle_z", TILT_ANGLE_Z, 0.55)

    def _update_hair_sway(self, model, t):
        """头发飘动：前发/后发/鬓发自然微摆（ParamHairFront/Back/Body）。模型无 hair 参数自动跳过。"""
        self._set(model, "hair_front", math.sin(t * HAIR_SWAY_FREQ) * HAIR_SWAY_AMP, 0.6)
        self._set(model, "hair_back", math.sin(t * HAIR_SWAY_FREQ * 0.7 + 1.0) * HAIR_SWAY_AMP_BACK, 0.5)
        self._set(model, "hair_body", math.sin(t * HAIR_SWAY_FREQ * 0.8 + 2.0) * HAIR_SWAY_AMP_BACK, 0.5)

    def _update_brow_raise(self, model, now, dt):
        """眉毛挑动：周期性"嗯?"挑眉（ParamBrowY）。模型无 brow 参数自动跳过。"""
        if self._brow_state == "down":
            if now >= self._brow_next:
                self._brow_state = "up"
                self._brow_t = 0.0
        elif self._brow_state == "up":
            self._brow_t += dt
            if self._brow_t < 0.12:
                k = self._brow_t / 0.12
            elif self._brow_t < BROW_RAISE_HOLD:
                k = 1.0
            else:
                k = max(0.0, 1.0 - (self._brow_t - BROW_RAISE_HOLD) / 0.25)
            self._set(model, "brow_y", k * BROW_RAISE_AMP, 1.0)
            if self._brow_t >= BROW_RAISE_HOLD + 0.25:
                self._brow_state = "down"
                self._set(model, "brow_y", 0.0, 1.0)
                self._brow_next = now + random.uniform(*BROW_RAISE_GAP)

    def _update_wiggle(self, model, t):
        """开心扭动：body_angle_x 快速叠加微抖（跳舞感）。add 模式不与 look_cursor/wind/body_float 的 set 打架，叠加共存。"""
        self._add(model, "body_angle_x", math.sin(t * WIGGLE_FREQ) * WIGGLE_AMP)

    def trigger_poke(self):
        """外部（如右键「突脸一下」）触发一次突脸放大回弹。"""
        self._poke_until = time.monotonic() + POKE_DURATION
