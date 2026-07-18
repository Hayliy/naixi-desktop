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

# ── 动作模板（语义级） ──
# 每个动作定义哪些部位参与、幅度和方向

ACTION_TEMPLATES = {
    "nod":      {"head_nod": -20, "head_tilt": 0},
    "bow":      {"head_nod": -20, "body_bow": -8},
    "tilt":     {"head_tilt": 15},
    "shake":    {"head_tilt": 15, "head_nod": -5},
    "wave":     {"head_tilt": 10, "head_nod": 5, "arm_r": -20},
    "arms_up":  {"head_nod": 8, "arm_l": -30, "arm_r": -30},
    "point_r":  {"head_tilt": 5, "arm_r": -20},
    "point_l":  {"head_tilt": -5, "arm_l": -20},
    "forward":  {"head_nod": 8, "body_bow": -8},
    "backward": {"head_nod": -5, "body_bow": 10},
    "shy":      {"head_nod": -15, "head_tilt": -5, "body_bow": -5},
    "surprised":{"head_nod": 8, "head_tilt": 5, "brow_l": 0.5, "brow_r": 0.5, "body_bow": 10},
    "sad":      {"head_nod": -10, "brow_l": -0.3, "brow_r": -0.3},
    "angry":    {"head_nod": -8, "head_tilt": 5, "brow_l": -0.5, "brow_r": -0.5},
    "smile":    {"head_nod": 5, "brow_l": 0.3, "brow_r": 0.3},
    "kime":     {"head_tilt": 8, "head_nod": 5, "arm_r": -30},
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
        self._categories = {}  # semantic category → [param names]

    def scan_model(self):
        try:
            ids = self.model.GetParamIds()
            self._categories = _categorize_params(ids)
            _dbg(f"scan: {len(ids)} params, cats: {len(self._categories)}")
            for cat, names in sorted(self._categories.items()):
                _dbg(f"  {cat}: {names}")
        except Exception as e:
            _dbg(f"scan fail: {e}")

    def play_action(self, action: str) -> bool:
        template_name = ACTION_TO_TEMPLATE.get(action, action)
        template = ACTION_TEMPLATES.get(template_name)
        if not template:
            _dbg(f"play: no template {action}")
            return False
        # 模板中的语义→实际参数名匹配
        concrete = {}
        for cat_name, target_val in template.items():
            param_names = self._categories.get(cat_name, [])
            if param_names:
                # 同类多个参数时取第一个，值按比例缩放
                concrete[param_names[0]] = target_val
                # 对称部位（双手/双腿）同步
                if len(param_names) > 1:
                    concrete[param_names[1]] = target_val
        _dbg(f"play: {action} tmpl={template_name} "
             f"cats={list(template.keys())} concrete={len(concrete)}")
        if not concrete:
            _dbg("play: no params matched")
            return False
        self._current = Motion.from_pose_dict(concrete)
        self._current.play()
        _dbg(f"play: started {action}")
        return True

    def update(self, dt):
        if self._current:
            done = self._current.update(dt, self.model)
            if done:
                self._current = None
