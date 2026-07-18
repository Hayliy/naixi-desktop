"""
动作引擎：参数语义匹配 + Pose 插值播放
自动扫描模型参数，按语义分组，动态匹配到动作模板
"""

import json, logging, time, threading, os, re
from typing import Optional

log = logging.getLogger("pose_engine")
_DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_debug.log")

def _dbg(msg):
    try:
        with open(_DEBUG_LOG, "a") as f:
            f.write(f"{time.time():.0f} POSE {msg}\n")
    except:
        pass

# ── 曲线插值 ──

class LinearSegment:
    def __init__(self, p0, p1):
        self.p0, self.p1 = p0, p1
    def contains(self, t):
        return self.p0.t <= t <= self.p1.t
    def interpolate(self, t):
        return self.p0.value + (self.p1.value - self.p0.value) * (t - self.p0.t) / (self.p1.t - self.p0.t)

class Point:
    def __init__(self, t, value):
        self.t, self.value = t, value

class Curve:
    def __init__(self, param_id):
        self.param_id = param_id
        self.segments = []
    def interpolate(self, t):
        for seg in self.segments:
            if seg.contains(t):
                return seg.interpolate(t)
        return None
    @staticmethod
    def from_pose(param_id, target, duration=0.7):
        c = Curve(param_id)
        total = duration * 2
        c.segments = [LinearSegment(Point(0,0), Point(duration,target)),
                      LinearSegment(Point(duration,target), Point(total,0))]
        return c

class Motion:
    def __init__(self):
        self.curves = []
        self.time_elapsed = 0.0
        self.duration = 0.0
        self.playing = False
    @staticmethod
    def from_pose_dict(params, duration=0.7):
        m = Motion()
        m.duration = duration * 2
        for pid, val in params.items():
            m.curves.append(Curve.from_pose(pid, val, duration))
        return m
    def update(self, dt, model):
        if not self.playing:
            return True
        self.time_elapsed += dt
        for c in self.curves:
            v = c.interpolate(self.time_elapsed)
            if v is not None:
                model.SetParameterValue(c.param_id, v)
        if self.time_elapsed >= self.duration:
            self.playing = False
            return True
        return False
    def play(self):
        self.playing = True
        self.time_elapsed = 0.0

# ── 语义参数分类 ──

PARAM_CATEGORIES = {
    "head_tilt":    ["AngleX"],
    "head_nod":     ["AngleY"],
    "head_roll":    ["AngleZ"],
    "brow_l":       ["BrowL"],
    "brow_r":       ["BrowR"],
    "eye_l":        ["EyeL"],
    "eye_r":        ["EyeR"],
    "mouth":        ["Mouth"],
    "arm_l":        ["ArmL", "ShoulderL", "ElbowL"],
    "arm_r":        ["ArmR", "ShoulderR", "ElbowR"],
    "hand_l":       ["HandL", "WristL"],
    "hand_r":       ["HandR", "WristR"],
    "body_lean":    ["BodyAngleX", "BodyX"],
    "body_bow":     ["BodyAngleY", "BodyY"],
    "leg_l":        ["LegL", "KneeL"],
    "leg_r":        ["LegR", "KneeR"],
}

def _categorize_params(all_params):
    """扫描全部参数名，按语义分成组"""
    cats = {}
    for cat_name, keywords in PARAM_CATEGORIES.items():
        matches = []
        for p in all_params:
            for kw in keywords:
                if kw in p:
                    matches.append(p)
                    break
        if matches:
            cats[cat_name] = matches
    return cats

# ── 动作模板（语义级，归一化值） ──
# 值范围：头部/身体/手臂 = -1.0~1.0（按实际参数范围缩放）
# 眉毛/眼睛/嘴巴 = 0.0~1.0（按实际参数范围缩放）

ACTION_TEMPLATES = {
    "nod":      {"head_nod": -0.7, "head_tilt": 0},
    "bow":      {"head_nod": -0.7, "body_bow": -0.4},
    "tilt":     {"head_tilt": 0.5},
    "shake":    {"head_tilt": 0.5, "head_nod": -0.2},
    "wave":     {"head_tilt": 0.4, "head_nod": 0.2, "arm_r": -0.6},
    "arms_up":  {"head_nod": 0.3, "arm_l": -0.8, "arm_r": -0.8},
    "point_r":  {"head_tilt": 0.2, "arm_r": -0.6},
    "point_l":  {"head_tilt": -0.2, "arm_l": -0.6},
    "forward":  {"head_nod": 0.3, "body_bow": -0.4},
    "backward": {"head_nod": -0.2, "body_bow": 0.4},
    "shy":      {"head_nod": -0.5, "head_tilt": -0.2, "body_bow": -0.3},
    "surprised":{"head_nod": 0.3, "head_tilt": 0.2, "brow_l": 0.6, "brow_r": 0.6, "body_bow": 0.4},
    "sad":      {"head_nod": -0.4, "brow_l": -0.4, "brow_r": -0.4},
    "angry":    {"head_nod": -0.3, "head_tilt": 0.2, "brow_l": -0.6, "brow_r": -0.6},
    "smile":    {"head_nod": 0.2, "brow_l": 0.4, "brow_r": 0.4},
    "kime":     {"head_tilt": 0.3, "head_nod": 0.2, "arm_r": -0.7},
}

ACTION_TO_TEMPLATE = {
    "wave": "wave", "bye": "wave", "nod": "nod", "think": "tilt",
    "surprise": "surprised", "shake": "shake", "kime": "kime",
    "smile": "smile", "forward": "forward", "backward": "backward",
    "sad": "sad", "angry": "angry", "shy": "shy",
}

class PoseEngine:
    def __init__(self, model):
        self.model = model
        self._current = None
        self._categories = {}
        self._param_ranges = {}  # param_name → (min, max, default)

    def scan_model(self):
        try:
            ids = self.model.GetParamIds()
            self._categories = _categorize_params(ids)
            # 扫描每个参数的范围
            for i in range(self.model.GetParameterCount()):
                p = self.model.GetParameter(i)
                self._param_ranges[p.id] = (p.min, p.max, p.default)
            _dbg(f"scan: {len(ids)} params, cats: {len(self._categories)}, ranges: {len(self._param_ranges)}")
            for cat, names in sorted(self._categories.items()):
                _dbg(f"  {cat}: {names}")
        except Exception as e:
            _dbg(f"scan fail: {e}")

    def _scale_value(self, param_name: str, normalized: float) -> float:
        """归一化值(-1~1) → 实际参数范围内的值"""
        r = self._param_ranges.get(param_name)
        if not r:
            return normalized
        pmin, pmax, pdefault = r
        if pmin >= pmax:
            return normalized
        mid = (pmax + pmin) / 2 if pmin < 0 else pmin
        half = (pmax - pmin) / 2
        return mid + normalized * half

    def play_action(self, action: str) -> bool:
        template_name = ACTION_TO_TEMPLATE.get(action, action)
        template = ACTION_TEMPLATES.get(template_name)
        if not template:
            _dbg(f"play: no template {action}")
            return False
        concrete = {}
        for cat_name, norm_val in template.items():
            param_names = self._categories.get(cat_name, [])
            if param_names:
                # 按范围缩放归一化值
                p0 = param_names[0]
                concrete[p0] = self._scale_value(p0, norm_val)
                if len(param_names) > 1:
                    p1 = param_names[1]
                    concrete[p1] = self._scale_value(p1, norm_val)
        _dbg(f"play: {action} tmpl={template_name} concrete={len(concrete)}")
        if not concrete:
            _dbg("play: no params matched")
            return False
        self._current = Motion.from_pose_dict(concrete, duration=0.6)
        self._current.play()
        _dbg(f"play: started {action}")
        return True

    def update(self, dt):
        if self._current:
            done = self._current.update(dt, self.model)
            if done:
                self._current = None
