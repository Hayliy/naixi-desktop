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

    def to_motion3_json(self) -> dict:
        """导出为标准 .motion3.json 格式"""
        curves_data = []
        for c in self.curves:
            if not c.segments:
                continue
            segs = [c.segments[0].p0.t, c.segments[0].p0.value]
            for seg in c.segments:
                segs.append(0)  # linear
                segs.append(seg.p1.t)
                segs.append(seg.p1.value)
            curves_data.append({"Target": "Parameter", "Id": c.param_id, "Segments": segs})
        curve_count = len(curves_data)
        seg_count = sum(len(c["Segments"]) // 3 for c in curves_data) if curve_count else 0
        pt_count = sum(len(c["Segments"]) // 3 * 2 for c in curves_data) if curve_count else 0
        return {
            "Version": 3,
            "Meta": {"Duration": self.duration, "Fps": 30, "Loop": False,
                     "CurveCount": curve_count, "TotalSegmentCount": seg_count,
                     "TotalPointCount": pt_count},
            "Curves": curves_data
        }

# ── 语义参数分类 ──

PARAM_CATEGORIES = {
    "head_tilt":    ["AngleX"],
    "head_nod":     ["AngleY"],
    "head_roll":    ["AngleZ"],
    "brow_l":       ["BrowL"],
    "brow_r":       ["BrowR"],
    "eye_l":        ["EyeLOpen"],
    "eye_r":        ["EyeROpen"],
    "eye_l_smile":  ["EyeLSmile"],
    "eye_r_smile":  ["EyeRSmile"],
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

# ── Live2D 官方标准参数范围（精确值） ──
# 来源：https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/

STANDARD_PARAMS = {
    "ParamAngleX":       (-30, 30, 0),      # 头部左右旋转
    "ParamAngleY":       (-30, 30, 0),      # 头部上下
    "ParamAngleZ":       (-30, 30, 0),      # 头部倾斜
    "ParamEyeLOpen":     (0, 1, 1),         # 左眼开合 (0闭1开)
    "ParamEyeLSmile":    (0, 1, 0),         # 左眼微笑
    "ParamEyeROpen":     (0, 1, 1),         # 右眼开合
    "ParamEyeRSmile":    (0, 1, 0),         # 右眼微笑
    "ParamEyeBallX":     (-1, 1, 0),        # 眼珠左右
    "ParamEyeBallY":     (-1, 1, 0),        # 眼珠上下
    "ParamBrowLY":       (-1, 1, 0),        # 左眉上下 (-1压低, 1抬高)
    "ParamBrowRY":       (-1, 1, 0),        # 右眉上下
    "ParamBrowLX":       (-1, 1, 0),        # 左眉左右
    "ParamBrowRX":       (-1, 1, 0),        # 右眉左右
    "ParamBrowLAngle":   (-1, 1, 0),        # 左眉角度 (-1生气眉)
    "ParamBrowRAngle":   (-1, 1, 0),        # 右眉角度
    "ParamMouthForm":    (-1, 1, 0),        # 嘴形 (-1生气, 1微笑)
    "ParamMouthOpenY":   (0, 1, 0),         # 嘴巴开合
    "ParamCheek":        (0, 1, 0),         # 脸颊泛红
    "ParamBodyAngleX":   (-10, 10, 0),      # 身体左右旋转
    "ParamBodyAngleY":   (-10, 10, 0),      # 身体前后
    "ParamBodyAngleZ":   (-10, 10, 0),      # 身体倾斜
    "ParamBreath":       (0, 1, 0),         # 呼吸
    "ParamArmRA":        (-30, 30, 0),      # 右臂A展开
    "ParamArmLA":        (-30, 30, 0),      # 左臂A展开
    "ParamArmRB":        (-30, 30, 0),      # 右臂B展开
    "ParamArmLB":        (-30, 30, 0),      # 左臂B展开
    "ParamHandL":        (-10, 10, 0),      # 左手变形
    "ParamHandR":        (-10, 10, 0),      # 右手变形
    "ParamShoulderY":    (-10, 10, 0),      # 耸肩
}

# ── 动作模板（语义级，使用实际参数值） ──
# 值来自 Live2D 标准参数参考 + 常见 VTuber 表情习惯

ACTION_TEMPLATES = {
    "nod":      {"head_nod": -15, "head_tilt": 0},
    "bow":      {"head_nod": -20, "body_bow": -8},
    "tilt":     {"head_tilt": 20},
    "shake":    {"head_tilt": 20, "head_nod": -5},
    "wave":     {"head_tilt": 12, "head_nod": 5, "arm_r": -25},
    "arms_up":  {"head_nod": 8, "arm_l": -30, "arm_r": -30},
    "point_r":  {"head_tilt": 5, "arm_r": -20},
    "point_l":  {"head_tilt": -5, "arm_l": -20},
    "forward":  {"head_nod": 10, "body_bow": -6},
    "backward": {"head_nod": -5, "body_bow": 8},
    "shy":      {"head_nod": -18, "head_tilt": -8, "body_bow": -4},
    "surprised":{"head_nod": 10, "head_tilt": 8, "brow_l": 0.6, "brow_r": 0.6, "body_bow": 5, "eye_l": 0.3, "eye_r": 0.3},
    "sad":      {"head_nod": -12, "brow_l": -0.4, "brow_r": -0.4},
    "angry":    {"head_nod": -10, "head_tilt": 8, "brow_l": -0.7, "brow_r": -0.7},
    "smile":    {"head_nod": 5, "brow_l": 0.3, "brow_r": 0.3, "eye_l_smile": 0.6, "eye_r_smile": 0.6},
    "kime":     {"head_tilt": 10, "head_nod": 5, "arm_r": -25},
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

    def _scale_value(self, param_name: str, target: float) -> float:
        """将目标值限制在参数实际范围内，若参数不存在则直接返回"""
        r = self._param_ranges.get(param_name)
        if r:
            pmin, pmax, _ = r
            return max(pmin, min(pmax, target))
        return target

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

    def generate_motion_files(self, cache_dir: str) -> dict:
        """为所有动作模板生成 .motion3.json 文件，返回 {pose_name: filepath}"""
        import os, json
        result = {}
        generated = set()
        for tag, template_name in ACTION_TO_TEMPLATE.items():
            if template_name in generated:
                continue
            generated.add(template_name)
            template = ACTION_TEMPLATES.get(template_name)
            if not template:
                continue
            # 语义→具体参数
            concrete = {}
            for cat_name, target_val in template.items():
                param_names = self._categories.get(cat_name, [])
                if param_names:
                    p0 = param_names[0]
                    concrete[p0] = self._scale_value(p0, target_val)
                    if len(param_names) > 1:
                        concrete[param_names[1]] = self._scale_value(param_names[1], target_val)
            if not concrete:
                continue
            duration = 0.6
            motion = Motion.from_pose_dict(concrete, duration=duration)
            data = motion.to_motion3_json()
            fname = f"pose_{template_name}.motion3.json"
            fpath = os.path.join(cache_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            result[template_name] = fpath
            # 再生成一个循环版的 idle 版本
            idle_data = dict(data)
            idle_data["Meta"]["Loop"] = True
            idle_data["Meta"]["Duration"] = duration * 4
            idle_fname = f"pose_{template_name}_loop.motion3.json"
            idle_fpath = os.path.join(cache_dir, idle_fname)
            with open(idle_fpath, "w", encoding="utf-8") as f:
                json.dump(idle_data, f, ensure_ascii=False)
            result[f"{template_name}_loop"] = idle_fpath
        _dbg(f"gen motions: {len(result)} files in {cache_dir}")
        return result

    def update(self, dt):
        if self._current:
            done = self._current.update(dt, self.model)
            if done:
                self._current = None
