"""
动作引擎：.motion3.json 插值播放 + Pose 参数序列 + 动作标签驱动
"""

import json, logging, time, threading, os
from typing import Optional

log = logging.getLogger("pose_engine")
_DEBUG_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_debug.log")

def _dbg(msg):
    try:
        with open(_DEBUG_LOG, "a") as f:
            f.write(f"{time.time():.0f} POSE {msg}\n")
    except:
        pass

# ── 曲线插值（来自 EasyLive2D/live2d-motion3） ──

class Point:
    def __init__(self, t: float, value: float):
        self.t = t
        self.value = value

class LinearSegment:
    def __init__(self, p0: Point, p1: Point):
        self.p0, self.p1 = p0, p1
    def contains(self, t):
        return self.p0.t <= t <= self.p1.t
    def interpolate(self, t: float) -> float:
        return self.p0.value + (self.p1.value - self.p0.value) * (t - self.p0.t) / (self.p1.t - self.p0.t)

class Curve:
    def __init__(self, param_id: str):
        self.param_id = param_id
        self.segments: list = []

    def interpolate(self, t: float) -> Optional[float]:
        for seg in self.segments:
            if seg.contains(t):
                return seg.interpolate(t)
        return None

    @staticmethod
    def from_pose(param_id: str, target: float, duration: float = 0.7):
        curve = Curve(param_id)
        total = duration * 2
        curve.segments = [
            LinearSegment(Point(0, 0), Point(duration, target)),
            LinearSegment(Point(duration, target), Point(total, 0)),
        ]
        return curve

class Motion:
    def __init__(self):
        self.curves: list[Curve] = []
        self.time_elapsed = 0.0
        self.duration = 0.0
        self.playing = False

    @staticmethod
    def from_pose_dict(params: dict, duration: float = 0.7):
        m = Motion()
        m.duration = duration * 2
        for pid, val in params.items():
            m.curves.append(Curve.from_pose(pid, val, duration))
        return m

    def update(self, dt: float, model) -> bool:
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

# ── 预设姿势库 ──

POSE_LIBRARY = {
    "forward":    {"ParamBodyAngleY": -8, "ParamAngleY": 5},
    "backward":   {"ParamBodyAngleY": 10},
    "lean_left":  {"ParamBodyAngleX": -10, "ParamAngleX": -5},
    "lean_right": {"ParamBodyAngleX": 10, "ParamAngleX": 5},
    "bow":        {"ParamAngleY": -20, "ParamBodyAngleY": -5},
    "tilt":       {"ParamAngleX": 15},
    "wave":       {"ParamArmRAngle": -30},
    "arms_up":    {"ParamArmRAngle": -45, "ParamArmLAngle": -45},
    "shy":        {"ParamAngleY": -15, "ParamBodyAngleY": -5},
    "surprised":  {"ParamBodyAngleY": 10, "ParamAngleX": 5},
    "sad":        {"ParamAngleY": -10, "ParamBodyAngleY": 5},
    "angry":      {"ParamBodyAngleX": 5, "ParamAngleY": -10},
    "kime":       {"ParamArmRAngle": -45, "ParamBodyAngleX": 5},
}

ACTION_TO_POSE = {
    "wave": "wave", "bye": "wave", "nod": "bow",
    "think": "tilt", "surprise": "surprised", "shake": "tilt",
    "kime": "kime", "smile": "forward", "sad": "sad", "angry": "angry",
}

class PoseEngine:
    def __init__(self, model):
        self.model = model
        self._current = None
        self._available: set = set()

    def scan_model(self):
        try:
            ids = self.model.GetParameterIds()
            self._available = set(ids)
            _dbg("scan: " + str(len(ids)) + " params: " + str(list(ids)[:10]))
        except Exception as e:
            _dbg("scan fail: " + str(e))
            self._available = set()

    def play_action(self, action: str) -> bool:
        pose_name = ACTION_TO_POSE.get(action, action)
        pose = POSE_LIBRARY.get(pose_name)
        if not pose:
            _dbg("play: no pose " + action)
            return False
        if self._available:
            filtered = {k: v for k, v in pose.items() if k in self._available}
            _dbg("play: " + action + " pre=" + str(len(pose)) + " post=" + str(len(filtered)))
            pose = filtered
        if not pose:
            _dbg("play: empty after filter")
            return False
        self._current = Motion.from_pose_dict(pose)
        self._current.play()
        _dbg("play: started " + action)
        return True

    def update(self, dt: float):
        if self._current:
            done = self._current.update(dt, self.model)
            if done:
                self._current = None
