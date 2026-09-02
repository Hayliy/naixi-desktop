"""
Live2D 面捕桥（离线）。

在 Live2D 原生桌宠进程内，用 QWebEngineView 加载 face_capture.html（复用 vendored 的
face_tracker.js + face_landmarker.task），把摄像头 ARKit 混合形状回传给原生 Live2D，
映射到 Cubism 参数并 SetParameterValue。

设计要点：
- 全部本地 vendored，运行时零外网（符合「单机/离线」硬约束）。
- 仅在 HTTP 服务下加载页面（file:// 会拦截 WASM/模型 fetch）。
- 「推帧」而非「拉结果」：捕获页是【独立离屏】的 QWebEngineView（非桌宠窗口子控件，否则同窗
  QOpenGLWidget 与 Chromium GPU 表面争抢呈现权 → 桌宠变黑框），页面内 rAF 仍会被浏览器暂停，
  故由 Qt 渲染循环每帧调 poll() 主动推一帧检测（见 poll 注释，2026-09-01 实锤）。
- 参数名不硬编码：不同模型命名差异极大（25 个实测模型中多数非标准命名），
  统一走 idle_engine 的 PARAM_HINTS 模糊匹配，且只写模型实际存在的参数。
- 嘴型参数不在此处写，交给调用方与 TTS 嘴型合并，避免冲突。
- 中性基准（recenter）：真人相对摄像头有固定坐姿角，不减基准会导致头一直歪。
"""

import os
import sys
import json
import math
import time
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
VRM_HTML_DIR = os.path.join(ROOT, "vrm_html")
# 性能日志路径可经环境变量重定向（自测隔离用，避免污染真机实时日志）；默认原路径。
PERF_LOG = os.environ.get("NAIXI_FACECAP_PERFLOG", r"D:\naixi_desktop\facecap_perf.log")

# 面捕驱动的「参数用途」→ 中性值（丢失人脸时回落目标）。
# 用用途而非参数名，是因为参数名因模型而异（见 _build_param_map）。
USE_NEUTRAL = {
    "eye_l_open": 1.0,
    "eye_r_open": 1.0,
    # 眯眼笑（VTS EyeSmile）：笑容时眼睛微眯，是「笑得真 vs 假」的关键。
    # 2026-09-01 补齐：此前完全没有该用途，笑容只有嘴动、眼睛不动 → 观感明显发假。
    "eye_l_smile": 0.0,
    "eye_r_smile": 0.0,
    "angle_x": 0.0,
    "angle_y": 0.0,
    "angle_z": 0.0,
    "eye_ball_x": 0.0,
    "eye_ball_y": 0.0,
    "brow_y": 0.0,
    "mouth_smile": 0.0,   # VTS MouthSmile：笑容（ParamMouthSmile）
    # 嘴形（VTS MouthForm，-1..1）：+1 微笑 / -1 嘟嘴，与「张嘴度」是两回事。
    # 2026-09-01 修正语义：此前 pet_window 把张嘴值直接写进 ParamMouthForm，
    # 导致「一张嘴就同时笑」，表情失真。张嘴走 MouthOpenY，嘴形独立由本用途驱动。
    "mouth_form": 0.0,
    "mouth_x": 0.0,       # VTS MouthX：嘴左右移动（+右, ParamMouthX/MouthA/MouthI）
    "tongue_out": 0.0,    # VTS TongueOut（iOS 专有）：伸舌 → ParamTongueOut
    "cheek_puff": 0.0,    # VTS CheekPuff（iOS 专有）：鼓腮 → ParamCheekPuff
    # FacePosition（脸在画面中的位置/远近）→ 身体微倾（VTS 体感：头/脸位置驱动身体）。
    # 注意：这是"位置"类用途，中性 0，走 body_gain（独立于头/表情增益）。
    "body_x": 0.0,        # 左右（→ ParamBodyAngleX）
    "body_y": 0.0,        # 上下（→ ParamBodyAngleY）
    "body_z": 0.0,        # 远近（→ ParamBodyAngleZ）
}

# 头部用途（需要减中性基准，单位：度）
HEAD_USES = ("angle_x", "angle_y", "angle_z")
# 身体用途（来自 FacePosition，中性 0，走 body_gain）
BODY_USES = ("body_x", "body_y", "body_z")

# idle_engine 的 hints 对部分模型匹配不到（如 ParamBrowLY/ParamBrowRY 分左右），此处补充。
# 合并顺序：补充 hints 在前，先精确后模糊，保证 BrowY 优先于 BrowLY。
_EXTRA_HINTS = {
    "brow_y": ["ParamBrowY", "BROW_Y", "BrowLY", "Brow", "眉"],
    "eye_l_open": ["ParamEyeLOpen", "EyeLOpen", "EYE_L_OPEN", "左眼睁"],
    "eye_r_open": ["ParamEyeROpen", "EyeROpen", "EYE_R_OPEN", "右眼睁"],
    "eye_l_smile": ["ParamEyeLSmile", "EyeLSmile", "EYE_L_SMILE", "左眼笑", "眯眼左"],
    "eye_r_smile": ["ParamEyeRSmile", "EyeRSmile", "EYE_R_SMILE", "右眼笑", "眯眼右"],
    "angle_x": ["ParamAngleX", "AngleX", "角度X"],
    "angle_y": ["ParamAngleY", "AngleY", "角度Y"],
    "angle_z": ["ParamAngleZ", "AngleZ", "角度Z"],
    "eye_ball_x": ["ParamEyeBallX", "EyeBallX", "眼球X"],
    "eye_ball_y": ["ParamEyeBallY", "EyeBallY", "眼球Y"],
    # 注意：MouthForm 已从 mouth_smile 移出（语义是「嘴形」不是「笑容量」），改挂 mouth_form。
    "mouth_smile": ["ParamMouthSmile", "MouthSmile", "ParamMouthUp", "MouthUp", "笑"],
    "mouth_form": ["ParamMouthForm", "MouthForm", "嘴形"],
    "mouth_x": ["ParamMouthX", "MouthX", "ParamMouthA", "MouthA", "MouthI", "嘴左右"],
    "tongue_out": ["ParamTongueOut", "TongueOut", "ParamTongue", "舌", "舌出"],
    "cheek_puff": ["ParamCheekPuff", "CheekPuff", "鼓腮", "腮"],
    "body_x": ["ParamBodyAngleX", "BodyAngleX", "身体X", "身体角度X"],
    "body_y": ["ParamBodyAngleY", "BodyAngleY", "身体Y", "身体角度Y"],
    "body_z": ["ParamBodyAngleZ", "BodyAngleZ", "身体Z", "身体角度Z"],
}

# 丢失人脸后：超过该秒数开始回落，回落持续该秒数后交还（停止写入，让手动眨眼/idle 接管）
LOST_DELAY = 0.5
RELEASE_TIME = 0.45

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".wasm": "application/wasm",
    ".task": "application/octet-stream",
    ".json": "application/json",
    ".png": "image/png",
}


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=VRM_HTML_DIR, **k)

    def _send(self, code, ctype, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        raw = self.path if isinstance(self.path, str) else "/"
        path = raw.split("?", 1)[0].split("#", 1)[0]
        # ── 面捕灵敏度设置页（纯内联 HTML，不依赖外部文件；绕开 Qt 弹窗透明/层级坑）──
        if path in ("/facecap_settings", "/facecap_settings.html"):
            fb = getattr(self.server, "fb", None)
            self._send(200, "text/html; charset=utf-8", _build_settings_html(fb).encode("utf-8"))
            return
        if path == "/facecap_get":
            import json as _json
            fb = getattr(self.server, "fb", None)
            self._send(200, "application/json",
                       _json.dumps(fb.get_gain_dict() if fb else {}, ensure_ascii=False).encode("utf-8"))
            return
        # 只允许白名单路径，禁止目录穿越与隐藏文件
        norm = os.path.normpath(path).lstrip("/\\")
        full = os.path.join(VRM_HTML_DIR, norm)
        if not os.path.isfile(full) or ".." in norm or norm.startswith("."):
            self.send_error(404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = _MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, ctype, data)

    def do_POST(self):
        raw = self.path if isinstance(self.path, str) else "/"
        path = raw.split("?", 1)[0].split("#", 1)[0]
        if path == "/facecap_set":
            import json as _json
            try:
                ln = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(ln) if ln else b"{}"
                d = _json.loads(body.decode("utf-8")) if body else {}
                fb = getattr(self.server, "fb", None)
                if fb is not None:
                    fb.apply_gain_dict(d)
                self._send(200, "application/json", b'{"ok":1}')
            except Exception as e:
                self._send(500, "application/json",
                           _json.dumps({"err": str(e)}, ensure_ascii=False).encode("utf-8"))
            return
        self.send_error(405)

    def log_message(self, *a):
        pass


def _build_settings_html(fb=None):
    """面捕灵敏度设置页（内联 HTML，浏览器打开；滑块 POST /facecap_set 实时改增益）。"""
    return """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>面捕灵敏度</title>
<style>
body{margin:0;background:#1e1e2e;color:#e6e6e6;font-family:'Microsoft YaHei',sans-serif;padding:18px;}
h2{font-size:16px;margin:0 0 12px;color:#c9b6f5;}
.row{margin:10px 0;}
label{display:block;font-size:13px;margin-bottom:4px;}
.v{color:#9b7bd8;font-weight:bold;}
input[type=range]{width:100%;accent-color:#9b7bd8;}
.cb{font-size:13px;margin:8px 0;}
.hint{font-size:11px;color:#888;margin-top:14px;line-height:1.6;}
</style>
</head>
<body>
<h2>面捕灵敏度（实时生效）</h2>
<div id="rows"></div>
<div class="hint">拖动滑块即时调整，无需确定，关闭本页即可。<br>桌宠已开面捕时，改动立刻在桌宠上反映。</div>
<script>
const ITEMS=[
 {k:'masterGain',t:'总灵敏度 masterGain',lo:0.2,hi:3,step:0.05},
 {k:'headGain',t:'头部增益 headGain（动作幅度）',lo:0.3,hi:2.5,step:0.05},
 {k:'bodyYawLink',t:'躯干·左右转 bodyYawLink',lo:0,hi:1.5,step:0.05},
 {k:'bodyPitchLink',t:'躯干·俯仰 bodyPitchLink',lo:0,hi:1.5,step:0.05},
 {k:'bodyRollLink',t:'躯干·歪头 bodyRollLink',lo:0,hi:1.5,step:0.05},
 {k:'expressionGain',t:'表情增益 expressionGain',lo:0.3,hi:2,step:0.05},
 {k:'smooth',t:'平滑 smooth（越小越跟手）',lo:0.01,hi:0.3,step:0.01}
];
const CK=[{k:'mirror',t:'面捕镜像（左右翻转，照镜子）'},{k:'autoCalibrate',t:'面捕自动校准（首次稳定即采中性基准）'}];
function el(id){return document.getElementById(id);}
function setv(k,v){var o={};o[k]=v;fetch('/facecap_set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});}
var rows=el('rows');
ITEMS.forEach(function(it){
 var d=document.createElement('div');d.className='row';
 var lab=document.createElement('label');var span=document.createElement('span');span.className='v';span.id='v_'+it.k;
 lab.appendChild(document.createTextNode(it.t+' '));lab.appendChild(span);
 var s=document.createElement('input');s.type='range';s.id='i_'+it.k;s.min=it.lo;s.max=it.hi;s.step=it.step;
 s.addEventListener('input',function(){span.textContent=s.value;setv(it.k,parseFloat(s.value));});
 d.appendChild(lab);d.appendChild(s);rows.appendChild(d);
});
CK.forEach(function(it){
 var d=document.createElement('div');d.className='cb';var lab=document.createElement('label');
 var c=document.createElement('input');c.type='checkbox';c.id='i_'+it.k;
 c.addEventListener('change',function(){setv(it.k,c.checked);});
 lab.appendChild(c);lab.appendChild(document.createTextNode(' '+it.t));
 d.appendChild(lab);rows.appendChild(d);
});
fetch('/facecap_get').then(function(r){return r.json();}).then(function(c){
 ITEMS.forEach(function(it){var e=el('i_'+it.k);if(e){e.value=(c[it.k]!=null?c[it.k]:it.lo);el('v_'+it.k).textContent=e.value;}});
 CK.forEach(function(it){var e=el('i_'+it.k);if(e)e.checked=!!c[it.k];});
});
</script>
</body>
</html>"""


def start_server(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _match(all_ids, hints):
    """从模型实际参数名里，按包含匹配挑出第一个命中 hint 的参数名。"""
    for hid in hints:
        hl = hid.lower()
        for pid in all_ids:
            if hl in pid.lower():
                return pid
    return None


def _build_param_map(all_ids):
    """用途 -> [实际参数名, ...]。

    复用 idle_engine 的 PARAM_HINTS 并追加 _EXTRA_HINTS（提高非标准模型的命中率）。
    眉毛特殊处理：多数模型左右分离（ParamBrowLY/ParamBrowRY），两者都写。
    """
    hints = {}
    try:
        sys.path.insert(0, ROOT)
        from .idle_engine import PARAM_HINTS
        hints = dict(PARAM_HINTS)
    except Exception:
        pass
    for use, extra in _EXTRA_HINTS.items():
        # 补充 hints 放前面：精确名（ParamBrowY）优先于模糊名（BrowLY）
        merged = list(extra) + [h for h in hints.get(use, []) if h not in extra]
        hints[use] = merged

    out = {}
    for use in USE_NEUTRAL:
        names = []
        p = _match(all_ids, hints.get(use, []))
        if p:
            names.append(p)
        if use == "brow_y":
            # 眉毛：除主匹配外，把左右分离的 BrowLY/BrowRY 一并写入
            for cand in ("ParamBrowLY", "ParamBrowRY"):
                if cand in all_ids and cand not in names:
                    names.append(cand)
        if names:
            out[use] = names
    return out


# ─────────────────────────────────────────────────────────────────────────────
# VTS 兼容层：arkit_to_l2d 严格对齐 VTube Studio Plugin API 的 FaceData 规范。
#
# 权威来源（2026-09-01 核实，非自创）：
#  · VTS 官方 wiki「VTS Model Settings」输入参数约定：
#       FaceAngleX = 左右转(yaw) / FaceAngleY = 上下俯仰(pitch) / FaceAngleZ = 歪头(roll)；
#       EyeOpenLeft/Right 0=闭 1=开；EyeBallX/Y -1..1；Brows 上下合并。
#  · 真实 iFacialMocap→VTS 桥源码（VTube-IFacial-Link/ifacial/utils.py）：
#       EyeOpenLeft = (1 - EYE_BLINK_LEFT)（ARKit blink=1 闭 → VTS 0=闭）。
#  · VTS 坐标系：左手系 +Z 前 +Y 上 +X 右（Unity 兼容）；FaceAngleX = HEAD_ROTATION_Y（yaw）。
#
# 设计：本模块只产出「规范 VTS FaceData」，再由 vts_facedata_to_l2d 映射到 Cubism 用途；
# 符号/轴/单位一律以此为准，不再自行约定（满足「细节不用自己想」）。
# ─────────────────────────────────────────────────────────────────────────────

# 头部三轴符号：VTS 规范 FaceAngleX=左右(yaw) / Y=上下(pitch) / Z=歪头(roll)，默认 +1
# （与 MediaPipe matrixToEulerYXZ 的欧拉自然符号一致）。
# ⚠ 唯一需在真机一次性核对项：MediaPipe facialTransformationMatrixes 的手性未公开文档保证等同
#   ARKit，故轴符号隔离到此常量。真人头向左转→模型应向左转，否则 VTS_HEAD_SIGN.x 取反；
#   低头→模型低头，否则 .y 取反；头向右侧歪→模型右歪，否则 .z 取反。
# 2026-09-01 真机核对（用户原话"歪头没翻转就已经是翻转效果，翻转后又翻转"）：
#   非镜像态 roll 已呈镜像方向 → 说明 base roll 符号与模型相反，故 z 取反为 -1.0。
#   取反后：非镜像=直接(正确)、镜像=再翻一次=镜像(正确)，消除"双翻"错觉。x/y 维持 +1（用户未报方向问题）。
VTS_HEAD_SIGN = {"x": 1.0, "y": 1.0, "z": -1.0}


def arkit_to_vts_facedata(bs: dict, head_euler: dict | None = None) -> dict:
    """ARKit 52 混合形状 + MediaPipe 头部欧拉(弧度, x=pitch y=yaw z=roll)
    → 规范 VTS FaceData（字段名/单位严格对齐 VTS Plugin API）。

    返回字段：
      EyeOpenLeft, EyeOpenRight           0=闭 1=开
      MouthOpen                           0..1（原值，调用方与 TTS 合并）
      MouthSmile, MouthX                  0..1 / -1..1（笑容 / 嘴左右）
      BrowYUp, BrowYDown                  0..1（左右眉合并，上扬/下压）
      EyeBallX, EyeBallY                  -1..1（眼球）
      FaceAngleX, FaceAngleY, FaceAngleZ  度（X=左右转 yaw / Y=上下俯仰 pitch / Z=歪头 roll）
      TongueOut, CheekPuff                0..1（iOS 专有；CheekPuff 在 MediaPipe 52 类下无数据源，恒 0）
    """
    def g(n):
        # 不区分大小写查找（兼容 MediaPipe 不同版本 categoryName 大小写差异；真机实测定位根因用）
        if n in bs:
            return float(bs[n] or 0.0)
        ln = n.lower()
        for k, v in bs.items():
            if k.lower() == ln:
                return float(v or 0.0)
        return 0.0

    fd = {}
    # 眼：ARKit eyeBlink=1 闭 → VTS EyeOpen=1-闭（0=闭 1=开）
    fd["EyeOpenLeft"] = 1.0 - min(1.0, g("eyeBlinkLeft"))
    fd["EyeOpenRight"] = 1.0 - min(1.0, g("eyeBlinkRight"))

    # 眉：InnerUp/OuterUp 上扬(+)，Down 下压(-)，左右合并为上下两路
    brow_up = (g("browInnerUp") + g("browOuterUpLeft") + g("browOuterUpRight")) / 3.0
    brow_down = (g("browDownLeft") + g("browDownRight")) / 2.0
    fd["BrowYUp"] = max(0.0, min(1.0, brow_up))
    fd["BrowYDown"] = max(0.0, min(1.0, brow_down))

    # 眼球：LookIn/Out → X，LookUp/Down → Y（-1..1，前置镜像后方向真机微调）
    fd["EyeBallX"] = max(-1.0, min(1.0,
        (g("eyeLookInLeft") + g("eyeLookInRight")) * 0.5 -
        (g("eyeLookOutLeft") + g("eyeLookOutRight")) * 0.5))
    fd["EyeBallY"] = max(-1.0, min(1.0,
        (g("eyeLookUpLeft") + g("eyeLookUpRight")) * 0.5 -
        (g("eyeLookDownLeft") + g("eyeLookDownRight")) * 0.5))

    # 头部：轴对齐 VTS 规范（FaceAngleX=yaw, FaceAngleY=pitch, FaceAngleZ=roll），弧度→度
    if head_euler:
        DEG = 57.2958
        fd["FaceAngleX"] = float(head_euler.get("y", 0.0)) * DEG * VTS_HEAD_SIGN["x"]   # yaw → 左右转
        fd["FaceAngleY"] = float(head_euler.get("x", 0.0)) * DEG * VTS_HEAD_SIGN["y"]   # pitch → 上下俯仰
        fd["FaceAngleZ"] = float(head_euler.get("z", 0.0)) * DEG * VTS_HEAD_SIGN["z"]   # roll → 歪头

    # 嘴：原值交给调用方与 TTS 合并（VTS MouthOpen 0..1）
    fd["MouthOpen"] = min(1.0, g("jawOpen"))
    # 眯眼笑（VTS EyeSmile 0..1）：ARKit eyeSquintLeft/Right（眯眼/笑眼）。
    # 笑容的真实感一半在眼不在嘴——只动嘴角不动眼，看起来就是「假笑」。
    fd["EyeSmileLeft"] = max(0.0, min(1.0, g("eyeSquintLeft")))
    fd["EyeSmileRight"] = max(0.0, min(1.0, g("eyeSquintRight")))
    # 笑容（VTS MouthSmile 0..1）：ARKit mouthSmile 左右取平均
    _smile = max(0.0, min(1.0, (g("mouthSmileLeft") + g("mouthSmileRight")) * 0.5))
    fd["MouthSmile"] = _smile
    # 嘴形（VTS MouthForm -1..1）：微笑(+) 与 嘟嘴(-) 之合力，0=普通。
    # ARKit 里 mouthPucker（撅嘴）/ mouthFunnel（喇叭嘴）都表现为「噘」，取较大者并略衰减 funnel。
    _pucker = max(float(g("mouthPucker")), float(g("mouthFunnel")) * 0.7)
    fd["MouthForm"] = max(-1.0, min(1.0, _smile - _pucker))
    # 嘴左右（VTS MouthX -1..1，+ = 右）：ARKit mouthRight - mouthLeft
    fd["MouthX"] = max(-1.0, min(1.0, g("mouthRight") - g("mouthLeft")))
    # 伸舌（VTS TongueOut 0..1）：ARKit tongueOut
    fd["TongueOut"] = max(0.0, min(1.0, g("tongueOut")))
    # 鼓腮（VTS CheekPuff 0..1）：ARKit cheekPuff。
    # ⚠ MediaPipe FaceLandmarker 的 52 类 blendshape 不含 cheekPuff → 此处恒 0（无数据源）。
    # 保留映射钩子：若将来换支持该形状的 tracker（如 iPhone ARKit 直采）即自动生效。
    fd["CheekPuff"] = max(0.0, min(1.0, g("cheekPuff")))
    return fd


def vts_facedata_to_l2d(fd: dict) -> dict:
    """规范 VTS FaceData → Cubism 参数用途（VTS 文档化模型映射）。

    VTS 官方模型映射（DenchiSoft wiki「VTS Model Settings」）：
      FaceAngleX → ParamAngleX（左右转, -45..45°）
      FaceAngleY → ParamAngleY（上下俯仰, -35..45°）
      FaceAngleZ → ParamAngleZ（歪头, -30..30°）
      EyeOpenLeft/Right → ParamEyeLOpen/ROpen
      EyeBallX/Y → ParamEyeBallX/Y
      Brows → ParamBrowLY/RY（左右分离，本层合并为 brow_y 用途）
    """
    out = {}
    out["eye_l_open"] = fd.get("EyeOpenLeft", 1.0)
    out["eye_r_open"] = fd.get("EyeOpenRight", 1.0)
    # 眯眼笑（VTS EyeSmile → ParamEyeLSmile/RSmile）
    out["eye_l_smile"] = fd.get("EyeSmileLeft", 0.0)
    out["eye_r_smile"] = fd.get("EyeSmileRight", 0.0)
    out["angle_x"] = fd.get("FaceAngleX", 0.0)   # VTS: ParamAngleX = 左右转(yaw)
    out["angle_y"] = fd.get("FaceAngleY", 0.0)   # VTS: ParamAngleY = 上下俯仰(pitch)
    out["angle_z"] = fd.get("FaceAngleZ", 0.0)   # VTS: ParamAngleZ = 歪头(roll)
    out["eye_ball_x"] = fd.get("EyeBallX", 0.0)
    out["eye_ball_y"] = fd.get("EyeBallY", 0.0)
    # 眉：VTS Brows 合并（上扬为正、下压为负）
    out["brow_y"] = max(-1.0, min(1.0, fd.get("BrowYUp", 0.0) - fd.get("BrowYDown", 0.0) * 0.5))
    # 笑容 / 嘴形 / 嘴左右（VTS MouthSmile / MouthForm / MouthX 文档化模型映射）
    out["mouth_smile"] = fd.get("MouthSmile", 0.0)
    out["mouth_form"] = fd.get("MouthForm", 0.0)
    out["mouth_x"] = fd.get("MouthX", 0.0)
    # 伸舌 / 鼓腮（VTS TongueOut / CheekPuff）
    out["tongue_out"] = fd.get("TongueOut", 0.0)
    out["cheek_puff"] = fd.get("CheekPuff", 0.0)
    return out


# ── 映射：ARKit 52 混合形状 → 参数用途（纯函数，可单测）──
def arkit_to_l2d(bs: dict, head_euler: dict | None = None) -> dict:
    """纯函数：ARKit blendshape + 头部欧拉角(弧度) → {用途: 值}。

    内部先转规范 VTS FaceData（arkit_to_vts_facedata），再映射到 Cubism 用途
    （vts_facedata_to_l2d）；符号/轴/单位以 VTS 规范为唯一权威来源。
    返回键是「用途」而非模型参数名（参数名由 _build_param_map 在运行时解析）。
    head 用途(angle_x/y/z) 为头部角度（度，未减中性基准，由调用方减）。
    """
    fd = arkit_to_vts_facedata(bs, head_euler)
    return vts_facedata_to_l2d(fd)


# 张嘴度用途（调用方与 TTS 嘴型合并，此处只提供原值）
def jaw_open(bs: dict) -> float:
    return min(1.0, float((bs or {}).get("jawOpen", 0.0) or 0.0))


class FaceBridge:
    """管理 QWebEngineView 摄像头捕获 + 推帧检测，把结果映射到 Live2D。

    用法：在 Qt 渲染循环里每帧调用 poll() 推一帧并异步取回结果，
    随后调用 apply_to_l2d(model, dt) 写入眼/眉/眼球/头部参数；
    嘴型通过 last_jaw() 交给调用方与 TTS 合并。
    """

    def __init__(self, port: int = 9877, parent=None):
        from PySide6.QtCore import QUrl, Qt
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.port = port
        self.server = start_server(port)
        # ── 黑屏根因修复（2026-09-01 实锤）──
        # QWebEngineView 与 QOpenGLWidget 绝不能同处一个顶层窗口：Chromium 自有 GPU 合成表面会抢走
        # 同一窗口的呈现权，导致 Live2D 的 QOpenGLWidget 无法 present → 整块桌宠变黑框。
        # 故面捕 view 必须是【独立顶层窗口】（无 parent / 不抢焦点 / 不入任务栏），
        # 绝不挂为桌宠 GL 窗口的子控件（避免 Chromium GPU 合成表面抢 present 导致 Live2D 黑框）。
        # 关键：视频元素必须 CSS「真实可见」(opacity:1, viewport 内) 才能骗过 Chromium 解码/提交视频帧，
        # 否则 Chromium 对 opacity:0 / off-screen 视频直接不解码 → rVFC 被节流到 ~15fps（实测 16）。
        # 视觉隐藏靠【整窗 setWindowOpacity(0)】(Qt 合成层透明，不影响 Chromium 内部 video 元素 CSS 可见性判定)，
        # 用户完全看不到；窗口留在屏幕内右下角以保 page 可见性。
        self._view = QWebEngineView()
        self._view.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self._view.setFixedSize(320, 240)
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # 关键修复 2026-09-01（末轮定论）：video 元素 opacity:1 + 视口内（face_capture.html 已改）是 Chromium 提交帧的前提；
        # 整窗 setWindowOpacity(0.0) 仅做视觉隐藏（Qt 合成 alpha，Chromium 内部 video 仍 opacity:1 → 照常解码）。
        # 窗口留在屏幕内右下角（不 move 出屏），否则 Chromium 判页面不可见 → rVFC 再被节流。
        # 可见性 A/B 开关（2026-09-01 帧率排查）：验证「整窗 opacity=0 被 Chromium GPU 降权」假设。
        # NAIXI_FACECAP_VISIBLE 不设置 -> 维持 opacity0 视觉隐藏（现状，对照基线）；
        # =1 -> opacity1 + 屏幕内右下角可见（肉眼可见小窗，确认是否因透明导致 GPU 降权）；
        # =2 -> opacity1 + 移出屏幕外（不可见，确认 off-screen 窗口是否同样被降权）。
        _vis = os.environ.get("NAIXI_FACECAP_VISIBLE", "")
        try:
            sg = self._view.screen().geometry()
            if _vis == "2":
                self._view.move(sg.width() + 500, 0)
            else:
                self._view.move(max(0, sg.width() - 324), max(0, sg.height() - 244))
        except Exception:
            self._view.move(0, 0)
        self._view.setWindowOpacity(1.0 if _vis in ("1", "2") else 0.0)
        self._view.show()
        try:
            with open(PERF_LOG, "a", encoding="utf-8") as _f:
                print("[FACECAP-WIN] visible_mode=%s opacity=%s" % (_vis or "hidden", "1.0" if _vis in ("1", "2") else "0.0"), file=_f)
        except Exception:
            pass
        self._running = False
        self._want_start = False
        # Qt WebEngine 摄像头权限必须显式授予，否则 getUserMedia 会被默认拒绝（NotAllowedError）。
        try:
            self._view.page().permissionRequested.connect(self._on_perm)
        except Exception:
            pass
        self._view.loadFinished.connect(self._on_load_finished)
        self._view.load(QUrl(f"http://127.0.0.1:{port}/face_capture.html"))
        self._last = {"detected": False, "blendshapes": None, "headEuler": None}

        # ── 运行时状态 ──
        self._pmap = None          # 用途 -> [参数名]，首次 apply 时构建
        self._out = {}             # 用途 -> 平滑后的当前值
        self._calib = None         # 头部中性基准 {angle_x, angle_y, angle_z}（度）
        self._calib_buf = []       # 采集中的样本
        self._calib_want = 0       # 还需采集帧数
        self._torso_calib = None   # 躯干俯仰中性基准（度，PoseLandmarker 肩-髋连线）
        self._torso_calib_buf = []  # 采集中的样本
        self._lost_t = 0.0         # 连续丢失时长
        self._release_t = 0.0      # 回落已进行时长
        self._released = True      # 是否已交还（停止写入）
        self._prev_t = None
        self._poll_pending = False  # 是否有在途的取结果请求（防回调队列堆积）
        self._poll_ts = 0.0
        # 实时帧率探针：每 1s 向 facecap_perf.log 写一行（detect_fps/infer_ms），
        # 用于无 GUI 沙箱外排查"不够丝滑"真因（摄像头帧率 / GPU 推理耗时）。
        self._perf_results = 0
        self._perf_ts = time.monotonic()
        self._perf_fps = 0
        self._perf_infer = 0.0
        self._diag_done = False  # 首次检出后写一次面捕诊断日志（定位"只有头能动"根因）
        self._use_worker = False  # 是否进入 Worker 推理模式（供 perf 日志+启动诊断）
        # 渲染侧速度外推插值状态（2026-09-01 治本"丝滑"）：
        # 检测仅 13~15fps（full 模型单帧 GPU 推理 37ms 硬上限，lite 不存在→无法降 infer_ms），
        # 但 L2D 渲染是 60fps 异步跑（poll 用异步 runJavaScript，不阻塞 Qt 主线程）。
        # 若 target 只用当前检测值、两次检测间(67ms)恒定，平滑只是"追固定值"→ 动作被低通
        # 压缩、快速运动滞后 = 卡顿观感。改：检测帧记录速度，渲染帧按速度外推，让模型动作
        # 在 60fps 下连续无压缩（VTS 等商用面捕同款做法）。
        self._target = {}      # 当前外推目标（每个 use 参数）
        self._vel = {}         # 各参数速度（单位/秒）
        self._detect_t = None  # 上次检测帧时间（用于估速度）
        self._sample_dt = 0.0  # 实测采样间隔 EMA（秒）。自适应平滑下限的输入：tau 必须跨过采样间隔，否则"跳一下停一下"=卡顿
        self._last_ts = 0.0    # _last 最近更新时间（_on_result 写入，判定新检测帧）
        self._applied_ts = 0.0 # 已处理进 _target 的检测时间戳
        self._load_gain()
        # 让 HTTP handler 能回调本实例（网页设置页 /facecap_set 实时改增益）
        try:
            self.server.fb = self
        except Exception:
            pass

    # ── 灵敏度：与 3D(VRM) 共用同一份 facecap_config.json ──
    def _load_gain(self):
        cfg = {}
        try:
            p = os.path.join(ROOT, "facecap_config.json")
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
        except Exception:
            cfg = {}
        master = float(cfg.get("masterGain", 1.0) or 1.0)
        self.expression_gain = float(cfg.get("expressionGain", 1.0) or 1.0) * master
        # 头部增益：总头增益 headGain 可拆 yaw/pitch/roll 三轴分别限制
        # （对齐 VTS/Nod/Head-Tilt Range 同款；VTS 默认三轴一致 = headGain）
        head = float(cfg.get("headGain", 1.2) or 1.2) * master
        self.head_yaw_gain = float(cfg.get("headYawGain", head))      # angle_x = 左右转(yaw)
        self.head_pitch_gain = float(cfg.get("headPitchGain", head))  # angle_y = 上下俯仰(pitch)
        self.head_roll_gain = float(cfg.get("headRollGain", head))    # angle_z = 歪头(roll)
        self.head_gain = head  # 兼容旧字段（apply 不再使用，仅 diagnostics 显示）
        self.smooth_tau = max(0.01, float(cfg.get("smooth", 0.05) or 0.05))
        # 身体跟随：真·躯干跟随头部旋转联动（head→body，VTS 标准），叠加 facePos 微位移。
        # 默认比头幅度小更自然（body 不应等于头，否则像整个头身一体转）。
        self.body_gain = float(cfg.get("bodyGain", 0.5) or 0.5) * master        # 兼容旧字段（facePos 部分）
        self.body_yaw_link = float(cfg.get("bodyYawLink", 0.7) or 0.7) * master     # 头左右转→身体跟转
        self.body_pitch_link = float(cfg.get("bodyPitchLink", 0.7) or 0.7) * master  # 躯干俯仰→身体前倾/后仰
        self.body_roll_link = float(cfg.get("bodyRollLink", 0.6) or 0.6) * master     # 头歪→身体歪
        self.body_pos_gain = float(cfg.get("bodyPosGain", 0.25) or 0.25) * master   # facePos 微附加（脸平移感）
        # 自动校准：VTS 默认首次稳定检出即自动采中性基准（用户仍可随时 recenter 覆盖）
        self.auto_calibrate = bool(cfg.get("autoCalibrate", True))
        # 镜像：webcam 当镜子，左右互换（VTS 默认开，但需真机核对方向，故默认关）
        self.mirror = bool(cfg.get("mirror", False))
        # 联动眨眼：VTS 默认开，两眼睁开度同步为平均（关掉才允许 wink 单眼眨）
        self.link_blink = bool(cfg.get("linkBlink", True))

    def reload_gain(self):
        """灵敏度对话框保存后调用，热更新增益（无需重开摄像头）。"""
        self._load_gain()

    def get_gain_dict(self):
        """网页设置页 GET /facecap_get 取当前增益（原始 json，未乘 masterGain）。"""
        p = os.path.join(ROOT, "facecap_config.json")
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def apply_gain_dict(self, d):
        """网页设置页 POST /facecap_set 调用：合并写 facecap_config.json 后热更新（无需重开摄像头）。"""
        p = os.path.join(ROOT, "facecap_config.json")
        cfg = {}
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
        except Exception:
            cfg = {}
        keys = ("masterGain", "headGain", "headYawGain", "headPitchGain", "headRollGain",
                "bodyGain", "bodyYawLink", "bodyPitchLink", "bodyRollLink", "bodyPosGain",
                "expressionGain", "smooth", "mirror", "autoCalibrate", "linkBlink")
        for k in keys:
            if k in d and d[k] is not None:
                cfg[k] = d[k]
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self.reload_gain()

    def _on_load_finished(self, ok):
        # 页面加载完成后再启动摄像头（首次启动时页面可能还没 ready）
        if self._want_start and ok:
            self._try_start()
        # 捕获页 load 完成后静默预热 MediaPipe 模型（不取摄像头）：把 WASM 编译 + 模型 fetch 的
        # ~16s 从「用户点开面捕」挪到后台。用户点面捕时只差 getUserMedia（几百 ms），等待感大幅缩短。
        # 失败静默忽略（预热只是加速，不影响用户主动开面捕时的即时初始化）。
        if ok:
            try:
                self._view.page().runJavaScript("window.__facePreload && window.__facePreload()")
            except Exception:
                pass

    def _on_perm(self, permission):
        # Qt WebEngine 摄像头权限：显式 grant（兼容新版 permissionRequested API）。
        try:
            from PySide6.QtWebEngineCore import QWebEnginePermission
            if permission.permissionType() == QWebEnginePermission.PermissionType.MediaVideoCapture:
                permission.grant()
        except Exception:
            pass

    def start(self):
        self._want_start = True
        self._running = True
        self._released = False
        self._lost_t = 0.0
        self._release_t = 0.0
        self._prev_t = None
        # 若页面已加载则立即启动；否则交给 _on_load_finished
        self._try_start()

    def _try_start(self):
        # 带回调启动：读取 __faceStart 返回值与错误，避免 Worker 静默失败被 fire-and-forget 吞掉
        #（2026-09-01 摄像头不开回归根因：runJavaScript 无回调 → 错误不可见）。
        try:
            self._view.page().runJavaScript(
                "window.__faceStart ? window.__faceStart() : false", self._on_start_result)
        except Exception as e:
            try:
                with open(r"D:\naixi_desktop\facecap_start_err.log", "a", encoding="utf-8") as f:
                    f.write("[START_ERR] runJavaScript 失败: %s\n" % e)
            except Exception:
                pass

    def _on_start_result(self, ok):
        # ok = window.__faceStart 的返回值（true/false）；undefined 表示页面未 ready（交给 loadFinished 重试）
        try:
            if ok is True:
                self._view.page().runJavaScript(
                    "window.__faceTracker ? window.__faceTracker._useWorker : null", self._on_use_worker)
            else:
                self._view.page().runJavaScript(
                    "JSON.stringify({err: window.__faceErr||'', useWorker: window.__faceTracker ? window.__faceTracker._useWorker : null})",
                    self._on_start_diag)
        except Exception:
            pass

    def _on_use_worker(self, v):
        self._use_worker = bool(v)

    def _on_start_diag(self, raw):
        # __faceStart 失败/未 ready：读真实错误落盘，供无 GUI 排查（不再凭推断）
        try:
            import json as _json
            d = _json.loads(raw) if isinstance(raw, str) else (raw or {})
            self._use_worker = bool(d.get("useWorker"))
            err = d.get("err") or ""
            if err:
                with open(r"D:\naixi_desktop\facecap_start_err.log", "a", encoding="utf-8") as f:
                    f.write("[START_ERR] %s\n" % err)
        except Exception:
            pass

    def stop(self):
        self._view.page().runJavaScript("window.__faceStop && window.__faceStop()")
        self._running = False
        self._released = True
        self._out = {}
        self._calib_buf = []
        self._calib_want = 0
        # 清掉最后一帧，避免停驱后仍被调用时写陈旧人脸值（真机靠菜单 _face_enabled 挡，这里自洽）
        self._last = {"detected": False, "blendshapes": None, "headEuler": None}

    def poll(self):
        """推一帧检测并取回结果（回调写入 self._last）。"""
        if not self._running:
            return
        # 渲染循环每帧(60fps)都会调 poll。检测要跟着摄像头原生 ~60fps 跑——
        # 旧的「派发下限 1/30」会让模型响应卡在 30fps（用户体感顿），故彻底删除该下限，
        # 只保留 pending 门控：runJavaScript 异步，回调约数 ms 后清 pending（320x240 下 <16ms），
        # 故派发自然跟随渲染跑到 ~60fps；GPU 慢时 roundtrip 拉长、pending 在途期变长，自动降频，
        # 无需硬限（硬限反而把响应钉死在 30fps）。≥0.2s 视为回调丢失，强制重派发兜底。
        now = time.monotonic()
        if self._poll_pending and (now - self._poll_ts) < 0.2:
            return
        self._poll_pending = True
        self._poll_ts = now
        # 必须调 __faceTick()「主动推一帧」，不能只读 __faceGet()：
        # 捕获页是独立离屏 QWebEngineView，页面内 rAF 仍被浏览器暂停，
        # 只读不推 = 永远拿到初始的空结果（2026-09-01 实锤）。
        self._view.page().runJavaScript(
            "window.__faceTick ? JSON.stringify(window.__faceTick()) "
            ": (window.__faceGet ? JSON.stringify(window.__faceGet()) : '{}')",
            self._on_result,
        )
        # 诊断拉取：每 3s 读一次 tracker 内部状态写入 perf 日志。
        # 存在理由（2026-09-01 实锤）：面捕「零数据」时 result 从不生成 → PERF 的 detect_fps/
        # infer_ms/cam 字段全 0，无法区分「检测循环没跑」还是「LIVE_STREAM 回调没触发」。
        # DIAG 直读 runningMode/liveMode/liveResults/rvfc/lastError，是零数据时的唯一可观测通道。
        if now - getattr(self, "_diag_ts", 0.0) >= 3.0:
            self._diag_ts = now
            try:
                self._view.page().runJavaScript(
                    "window.__faceDiag ? JSON.stringify(window.__faceDiag()) : '{}'", self._on_diag)
            except Exception:
                pass

    def _on_diag(self, raw):
        """tracker 状态诊断回调：零数据时定位「循环没跑 vs 回调没触发」的唯一依据。"""
        try:
            import json as _json
            d = _json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not isinstance(d, dict) or not d:
                return
            self._diag_cache = d   # 缓存权威诊断（getDiagnostics 才含 feedFps/age/inflight 真值；打包回包不含→PERF 改读此处）
            _werk = "|".join(str(x) for x in (d.get("workerErrs") or [])) or ""
            _wl = "|".join(str(x) for x in (d.get("workerLogs") or [])) or ""
            with open(PERF_LOG, "a", encoding="utf-8") as f:
                f.write("[DIAG] running=%s mode=%s live=%s liveResults=%s worker=%s utr=%s rvfc=%s "
                        "detected=%s fps=%s vtime=%s warmed=%s firstDet=%s gumMs=%s rvfcFps=%s neg=%s tre=%s feed=%s crate=%s ageMax=%s ageAvg=%s inflight=%s wl=%s werk=%s err=%s\n"
                        % (d.get("running"), d.get("runningMode"), d.get("liveMode"),
                           d.get("liveResults"), d.get("useWorker"), d.get("useTrackReader"), d.get("rvfc"),
                           d.get("detected"), d.get("fps"), d.get("lastVideoTime"),
                           d.get("warmed"), d.get("firstDetSec"), d.get("gumMs"), d.get("rvfcFps"),
                           d.get("negotiatedFps"), d.get("trackReaderErr"), d.get("feedFps"), d.get("createMs"),
                           d.get("ageMax") or 0, d.get("ageAvg") or 0, d.get("inflight") or 0,
                           _wl, _werk, (d.get("lastError") or "")))
                # 自愈可观测：区分「消费端慢（背压未解耦/推理占满）」与「摄像头硬件帧率低」。
                # rvfc 路径看 rvfcFps；utr 路径看真实喂帧 feedFps vs 协商 neg。
                # 关键判据：detect_fps 持续高于 feed 即队列不堵、无端到端延迟；此时低 feed 只是动作采样率限制，非 bug。
                try:
                    _rv = d.get("rvfcFps") or 0
                    _neg = d.get("negotiatedFps") or 0
                    _feed = d.get("feedFps") or 0
                    if d.get("running"):
                        if d.get("rvfc"):
                            if _rv > 0 and _rv < 25:
                                with open(PERF_LOG, "a", encoding="utf-8") as fw:
                                    fw.write("[WARN-RVFC] rvfc 路径消费端帧率低 rvfcFps=%s neg=%s（解耦未生效/推理占满）\n" % (_rv, _neg))
                        else:
                            if _neg and _neg >= 25 and _feed > 0 and _feed < 25:
                                with open(PERF_LOG, "a", encoding="utf-8") as fw:
                                    fw.write("[WARN-FEED] utr 路径摄像头实际出帧低于协商 neg=%s feed=%s（硬件/环境帧率限制，非消费端瓶颈；detect_fps 若仍>feed 则无延迟）\n" % (_neg, _feed))
                except Exception:
                    pass
        except Exception:
            pass

    def _on_result(self, raw):
        self._poll_pending = False
        try:
            self._last = json.loads(raw) if isinstance(raw, str) else raw
            self._last_ts = time.monotonic()  # 记录检测完成时间，供渲染侧判定"新检测帧"
        except Exception:
            return
        # 实时帧率探针：统计检测回包速率 + 摄像头实际检测帧率 + 单帧推理耗时
        try:
            self._perf_results += 1
            d = self._last
            _cam_neg = 0; _cam_rvfc = ''; _cam_w = 0; _cam_h = 0
            if isinstance(d, dict):
                if d.get("fps") is not None:
                    self._perf_fps = d["fps"]
                if d.get("inferMs") is not None:
                    self._perf_infer = d["inferMs"]
                cam = d.get("cam") if isinstance(d.get("cam"), dict) else None
                if cam:
                    _cam_neg = cam.get("neg") or 0
                    _cam_rvfc = cam.get("rvfc") or ''
                    _cam_w = cam.get("w") or 0
                    _cam_h = cam.get("h") or 0
            now = time.monotonic()
            if now - self._perf_ts >= 1.0:
                _span = now - self._perf_ts
                _rate = self._perf_results / _span if _span > 0 else 0
                try:
                    with open(PERF_LOG, "a", encoding="utf-8") as f:
                        # detect_fps 用实时消费率 _rate（result 回包速率，最真实反映 worker 吞吐）；
                        # 旧用 d.get("fps") 在队列堆积时恒 0 误导。ageMax/ageAvg=端到端延迟(ms)，inflight=Worker 在途帧数
                        _dc = getattr(self, "_diag_cache", None) or {}
                        f.write("[PERF] result_rate=%.1f detect_fps=%d infer_ms=%.2f ageMax=%.0f ageAvg=%.0f inflight=%d cam_neg=%s rvfc=%s rvfcFps=%d feed=%d crate=%.2f vw=%d vh=%d uw=%s"
                            % (_rate, int(round(_rate)), self._perf_infer, _dc.get("ageMax") or 0, _dc.get("ageAvg") or 0,
                               _dc.get("inflight") or 0, _cam_neg, _cam_rvfc,
                            d.get("rvfcFps") or 0, _dc.get("feedFps") or 0, d.get("createMs") or 0,
                            _cam_w, _cam_h, self._use_worker))
                        f.write(chr(10))
                except Exception:
                    pass
                self._perf_results = 0
                self._perf_ts = now
        except Exception:
            pass

    # ── 中性基准（VTS "Set as Center" 同款，由用户手动触发）──
    def recenter(self, frames: int = 20):
        """下一批帧采为中性基准：用户坐好点击「重置面捕原点」时调用。

        不自动锁、不持久化（坐姿每次都不同；持久化会重蹈 3D 端 xSign 的覆辙）。
        """
        self._calib_buf = []
        self._torso_calib_buf = []
        self._calib_want = int(frames)
        self._vel.clear()  # 重置基准时清空外推速度，避免恢复瞬间按旧速度冲

    def _calib_tick(self, head_deg):
        if self._calib_want <= 0:
            return
        self._calib_buf.append(head_deg)
        # 躯干俯仰基准（与头部基准同步采集）：坐姿前倾角被减掉，弯腰才是相对变化。
        tp = (self._last or {}).get("torsoPitch")
        if tp is not None:
            self._torso_calib_buf.append(float(tp))
        self._calib_want -= 1
        if self._calib_want <= 0:
            if self._calib_buf:
                n = float(len(self._calib_buf))
                self._calib = {
                    k: sum(s.get(k, 0.0) for s in self._calib_buf) / n
                    for k in HEAD_USES
                }
            if self._torso_calib_buf:
                self._torso_calib = sum(self._torso_calib_buf) / float(len(self._torso_calib_buf))
            self._calib_buf = []
            self._torso_calib_buf = []

    def get_calib(self):
        return dict(self._calib) if self._calib else None

    def _ensure_pmap(self, model):
        if self._pmap is not None:
            return
        ids = []
        try:
            if hasattr(model, "GetParamIds"):
                ids = model.GetParamIds()
            elif hasattr(model, "GetParameterIds"):
                ids = model.GetParameterIds()
        except Exception:
            ids = []
        self._pmap = _build_param_map(list(ids or []))
        # ── 模型参数范围诊断（2026-09-01）──
        # 我们写入的是「标准值域」（头部用度、眼/嘴用 0..1、嘴形用 -1..1），但各模型参数 min/max
        # 差异极大。若模型范围与标准值域不符，SetParameterValue 会被 SDK 静默 clamp，
        # 表现为「幅度偏小 / 顶死 / 几乎不动」——这是同硬件下与 VTS 观感差距的可疑主因之一。
        # 先落盘实测范围供比对；暂不据此改变写入行为（拿数据再决定，不臆改）。
        try:
            ranges = {}
            if hasattr(model, "GetParameterCount") and hasattr(model, "GetParameter"):
                for i in range(model.GetParameterCount()):
                    try:
                        p = model.GetParameter(i)
                        ranges[p.id] = (float(p.min), float(p.max), float(p.default))
                    except Exception:
                        continue
            self._prange = ranges
            import os as _os
            with open(r"D:\naixi_desktop\facecap_param_range.log", "w", encoding="utf-8") as f:
                for _use, _names in (self._pmap or {}).items():
                    for _pid in _names:
                        _r = ranges.get(_pid)
                        f.write("%-14s %-22s %s\n" % (
                            _use, _pid,
                            ("min=%.3f max=%.3f def=%.3f" % _r) if _r else "range=UNKNOWN"))
        except Exception:
            pass

    def _write(self, model, use, value, weight=1.0):
        names = (self._pmap or {}).get(use)
        if not names:
            return
        for pid in names:
            try:
                model.SetParameterValue(pid, float(value), float(weight))
            except Exception:
                pass

    def active(self):
        """当前是否正由面捕驱动（检出中、尚未交还）。"""
        return bool(self._running and not self._released)

    def apply_to_l2d(self, model, dt: float | None = None):
        """把最新面捕结果写入模型。dt 用于帧率无关平滑与丢失计时。"""
        if model is None:
            return
        now = time.monotonic()
        if dt is None:
            dt = 0.0 if self._prev_t is None else min(0.1, max(0.0, now - self._prev_t))
        self._prev_t = now

        self._ensure_pmap(model)
        got = bool(self._last and self._last.get("detected"))
        bs = (self._last or {}).get("blendshapes") or {}
        head = (self._last or {}).get("headEuler")

        if got:
            self._lost_t = 0.0
            self._release_t = 0.0
            self._released = False
        else:
            self._lost_t += dt

        # 目标值：检出 → 面捕值；丢失 → 中性值（先等 LOST_DELAY，避免偶发丢帧就回弹）
        if got:
            mapped = arkit_to_l2d(bs, head)
            # ── 一次性真机诊断：定位"只有头能动/镜像无效"根因，写出后不影响运行 ──
            if not getattr(self, "_diag_done", False):
                self._diag_done = True
                try:
                    import os as _os
                    _df = _os.path.join(ROOT, "facecap_blend_diag.log")
                    with open(_df, "w", encoding="utf-8") as _fh:
                        _fh.write("PMAP:\n" + json.dumps(self._pmap, ensure_ascii=False) + "\n\n")
                        _fh.write("BS_SAMPLE(前40):\n" + json.dumps(dict(list((bs or {}).items())[:40]), ensure_ascii=False) + "\n\n")
                        _fh.write("MAPPED(表情类):\n" + json.dumps({k: round(float(mapped.get(k, 0.0)), 3) for k in ("eye_l_open", "eye_r_open", "eye_ball_x", "eye_ball_y", "brow_y", "mouth_smile", "mouth_x")}, ensure_ascii=False) + "\n")
                        _fh.write("FACE_POS(脸在画面位置/远近, 前倾→z↑):\n" + json.dumps((self._last or {}).get("facePos"), ensure_ascii=False) + "\n")
                except Exception:
                    pass
            # 自动校准（VTS 默认首次稳定检出即自动采中性基准）：
            # 仅在尚无手动基准(_calib 为空)且未处于采集中时触发一次；用户随时 recenter 可覆盖。
            if self.auto_calibrate and self._calib is None and self._calib_want == 0 and self._lost_t == 0:
                self.recenter(frames=20)
            # 镜像（webcam 当镜子）：左右眼互换 + 眼球/嘴左右取反
            if self.mirror:
                # 照镜子：头部左右转 + 歪头镜像（真人左转→模型右转，真人右歪→模型左歪）。
                # 原逻辑只镜像眼/嘴、没镜像头部 → 这正是"镜像开关开/关效果一样"的主因。
                # angle_y(上下俯仰)镜像不变，左右转/歪头取反才与真人同侧。
                mapped["angle_x"] = -mapped.get("angle_x", 0.0)
                mapped["angle_z"] = -mapped.get("angle_z", 0.0)
                mapped["eye_l_open"], mapped["eye_r_open"] = mapped["eye_r_open"], mapped["eye_l_open"]
                mapped["eye_ball_x"] = -mapped.get("eye_ball_x", 0.0)
                mapped["mouth_x"] = -mapped.get("mouth_x", 0.0)
            # 联动眨眼（VTS 默认开）：两眼睁开度同步为平均，避免单眼眨时另一只不动
            if self.link_blink:
                e = (mapped.get("eye_l_open", 1.0) + mapped.get("eye_r_open", 1.0)) * 0.5
                mapped["eye_l_open"] = e
                mapped["eye_r_open"] = e
            # FacePosition（脸位置/远近）→ 身体微倾（VTS 体感：头/脸位置驱动身体）。
            # 仅当本帧有 facePos 才写入 body 用途（否则保持中性回落，不强行驱动）。
            facePos = (self._last or {}).get("facePos")
            if facePos:
                mapped["body_x"] = max(-1.0, min(1.0, facePos.get("x", 0.0)))
                mapped["body_y"] = max(-1.0, min(1.0, facePos.get("y", 0.0)))
                mapped["body_z"] = max(-1.0, min(1.0, facePos.get("z", 0.0)))
            # 头部角度（度，未减中性基准）：VTS 规范下 angle_x/y/z 已在顶层
            head_deg = {u: mapped.get(u, 0.0) for u in HEAD_USES}
            if self._calib_want > 0 and head_deg:
                self._calib_tick(head_deg)
            calib = self._calib or {}
            target = {}
            for use in USE_NEUTRAL:
                if use in HEAD_USES:
                    g = (self.head_yaw_gain if use == "angle_x"
                         else self.head_pitch_gain if use == "angle_y"
                         else self.head_roll_gain)
                    v = (head_deg.get(use, 0.0) - calib.get(use, 0.0)) * g
                elif use in BODY_USES:
                    # 真·躯干跟随：用头部真实旋转度数联动驱动（head→body，VTS 标准）。
                    # 关键量级修复：直接写头部角度度数（= head_deg_net * link），与 head 同量级，
                    # 让 live2d 按模型 ParamBodyAngleX/Y/Z 真实 Min/Max 自动 clamp。
                    # 旧写法 body = head_deg/30*link 把度数缩成归一化值，而 Cubism 参数是度数范围
                    # （如 ±10°）→ 写入值被范围吃掉≈不动（"躯干不动"真根因，2026-09-01 实锤）。
                    # mirror 自动含：head_deg 取自已镜像取反的 mapped[angle]，身体随之同侧翻转。
                    # 2026-09-01 补：前倾/坐直"没动作"真根因 = 人是用躯干前倾而非低头，
                    #   头 pitch 几乎不变 → 仅靠 head pitch 联动的 body_y 不动。
                    #   改用 facePos.z（脸离相机远近：前倾→更近→z↑）作主信号，鲁棒且幅度大。
                    link = (self.body_yaw_link if use == "body_x"
                            else self.body_pitch_link if use == "body_y" else self.body_roll_link)
                    if use == "body_y":
                        # 主信号：真实躯干俯仰角（PoseLandmarker 肩-髋连线，VTS BodyAngleY 同款）。
                        # 弯腰到坐直是躯干动作——纯 FaceLandmarker 无身体骨骼、头 pitch 也几乎不变，
                        # 故身体上下起伏只能靠它。减中性基准后直接写度数，让 live2d 按模型范围 clamp；
                        # 增益 body_pitch_link 控幅度（弯腰 30°×0.7≈21°，模型 clamp±10~30 都明显）。
                        torso = (self._last or {}).get("torsoPitch")
                        if torso is not None:
                            t_net = float(torso) - (self._torso_calib if self._torso_calib is not None else 0.0)
                            body = t_net * link
                        else:
                            # 无 pose（降级）：退回头俯仰联动（旧行为，弯腰信号弱）。
                            body = (head_deg.get("angle_y", 0.0) - calib.get("angle_y", 0.0)) * link
                    else:
                        head_use = "angle_x" if use == "body_x" else "angle_z"
                        head_deg_net = head_deg.get(head_use, 0.0) - calib.get(head_use, 0.0)
                        body = head_deg_net * link
                    # facePos 叠加（脸在画面中的位置/远近 → 身体微位移，VTS 体感，2D 不依赖 pose）：
                    # body_y 用 facePos.z（前倾→脸更近→z↑，补偿躯干信号）；
                    # body_x 用 facePos.x（左右）；body_z 用 facePos.z（远近）。
                    fp_src = "body_z" if use == "body_y" else use
                    fp = mapped.get(fp_src)
                    if fp is not None:
                        # facePos ±1；乘系数放大到模型度数范围（±10 量级）。
                        # body_y 用 pitch_link 控幅度（系数 10），避免把脸微动放大成大幅抽搐。
                        gain = self.body_pos_gain * (10.0 if use == "body_y" else 30.0)
                        body += (fp - USE_NEUTRAL.get(fp_src, 0.0)) * gain
                    v = body  # 不预 clamp；live2d SetParameterValue 按模型范围 clamp
                else:
                    raw = mapped.get(use)
                    if raw is None:
                        continue
                    neutral = USE_NEUTRAL[use]
                    v = neutral + (raw - neutral) * self.expression_gain
                target[use] = v
        # ── 渲染侧速度外推插值（2026-09-01 治本"丝滑"，修复误 return 导致完全不跟随）──
        # 检测仅 13~15fps（full 模型单帧 GPU 推理 ~37ms 硬上限），L2D 渲染 60fps 异步跑。
        # 新检测帧记速度，渲染帧按速度外推，动作在 60fps 下连续无压缩（VTS 同款）。
        # 本段在 if got 块外，统一处理检出/丢失；每帧都执行平滑写入（除交还）。
        is_new = (self._last_ts != self._applied_ts)
        if got:
            if is_new:
                if self._detect_t is not None:
                    _dtr = now - self._detect_t
                    if 0 < _dtr < 0.5:  # 异常大间隔（丢帧）不估速度，避免瞬时过冲
                        # 实测采样间隔 EMA（自适应平滑下限的输入；0.8/0.2 平滑，抗单帧抖动）
                        _psd = getattr(self, "_sample_dt", 0.0)
                        self._sample_dt = _dtr if _psd <= 0 else (_psd * 0.8 + _dtr * 0.2)
                        for _u, _tv in target.items():
                            _vnew = (_tv - self._target.get(_u, _tv)) / _dtr
                            _vold = self._vel.get(_u)
                            # 速度 EMA(0.75旧+0.25新)：瞬时差分受检测噪声影响大，直接外推会抖。
                            # 平滑速度后才敢把外推系数从 0.6 提到 0.85（模拟验证：卡顿脉冲比 2.21→1.67）。
                            self._vel[_u] = _vnew if _vold is None else (_vold * 0.75 + _vnew * 0.25)
                self._target = dict(target)
                self._detect_t = now
                self._applied_ts = self._last_ts
            elif self._detect_t is not None:
                # 非新检测帧：按速度外推补偿低采样率（16fps 间隔 62.5ms 内 target 恒定 = 阶梯卡顿的根源）。
                # 0.6 时动作被压缩 ~4%（跟不上真人），模拟扫描 0.85 为甜点：脉冲比 1.77→1.67 且不产生过冲；
                # 1.0 无额外收益反增过冲风险。配合速度 EMA 降噪，0.85 在真实噪声下依然稳定。
                EXTRAP = 0.85
                for _u in list(self._target.keys()):
                    self._target[_u] += self._vel.get(_u, 0.0) * dt * EXTRAP
            else:
                self._target = dict(target)
        else:
            # 丢失：清速度；持续丢失超 LOST_DELAY 才中性回落，否则保持上帧（避免偶发丢帧回弹）
            self._vel.clear()
            self._detect_t = None
            if self._lost_t > LOST_DELAY:
                self._release_t += dt
                k = min(1.0, self._release_t / RELEASE_TIME)
                self._target = {u: self._out.get(u, USE_NEUTRAL.get(u, 0.0)) + (USE_NEUTRAL.get(u, 0.0) - self._out.get(u, USE_NEUTRAL.get(u, 0.0))) * k for u in USE_NEUTRAL}

        # 交还：丢失超 RELEASE_TIME 后停止写面捕值，交还 idle/手动眨眼
        if self._released or (not got and self._release_t >= RELEASE_TIME):
            self._released = True
            return

        # 帧率无关平滑：k = 1 - exp(-dt/tau)
        # 自适应平滑下限（2026-09-02 治本"动作卡顿"）：摄像头实测 16~17fps（采样间隔 ~60ms），
        # 而 smooth 被调到 0.05（< 采样间隔）→ 平滑在一个间隔内就收敛 ~70%，随后停顿等下一采样点
        # = "跳一下、停一下"的卡顿观感。治本：tau 强制 >= 1.6×实测采样间隔，让动作跨过间隔连续过渡；
        # 摄像头越快（间隔越小）下限越低，30fps 时下限仅 ~53ms，不牺牲跟手；上限 0.30 防过度拖尾。
        tau = self.smooth_tau
        _sd = getattr(self, "_sample_dt", 0.0)
        if _sd > 0:
            tau = max(tau, min(0.30, 1.6 * _sd))
        kf = 1.0 - math.exp(-dt / tau) if (dt > 0 and tau > 0) else 1.0
        for use, tv in self._target.items():
            cur = self._out.get(use, USE_NEUTRAL.get(use, 0.0))
            self._out[use] = cur + (tv - cur) * kf
            self._write(model, use, self._out[use], 1.0)
        # 一次性诊断：确认"躯干不动"是否已根治（头部真实角度 + body 实际写入值）
        if got and not getattr(self, "_diag_body_done", False):
            self._diag_body_done = True
            try:
                _df = os.path.join(ROOT, "facecap_blend_diag.log")
                with open(_df, "a", encoding="utf-8") as _fh:
                    _fh.write("HEAD_DEG(度): " + json.dumps({u: round(float(head_deg.get(u, 0.0)), 2) for u in HEAD_USES}, ensure_ascii=False) + "\n")
                    _fh.write("BODY_OUT(写模型值): " + json.dumps({u: round(float(self._out.get(u, 0.0)), 3) for u in BODY_USES}, ensure_ascii=False) + "\n")
                    _fh.write("BODY_LINK: " + json.dumps({"yaw": round(self.body_yaw_link, 2), "pitch": round(self.body_pitch_link, 2), "roll": round(self.body_roll_link, 2)}, ensure_ascii=False) + "\n")
                    _fh.write("TORSO(躯干俯仰度): " + json.dumps({"raw": round(float((self._last or {}).get("torsoPitch", 0.0) or 0.0), 2), "calib": round(self._torso_calib if self._torso_calib is not None else 0.0, 2), "body_y_out": round(float(self._out.get("body_y", 0.0)), 3)}, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def last_jaw(self):
        """返回最新一帧的张口度 0..1（无人脸时为 0），供调用方与 TTS 嘴型合并。"""
        if not self._last or not self._last.get("detected"):
            return 0.0
        return jaw_open(self._last.get("blendshapes") or {})

    def diagnostics(self):
        return {
            "last": self._last,
            "calib": self.get_calib(),
            "params": self._pmap,
            "active": self.active(),
            "gain": {"expression": self.expression_gain, "head": self.head_gain, "tau": self.smooth_tau,
                     "head_yaw": self.head_yaw_gain, "head_pitch": self.head_pitch_gain,
                     "head_roll": self.head_roll_gain, "body": self.body_gain,
                     "body_yaw_link": self.body_yaw_link, "body_pitch_link": self.body_pitch_link,
                     "body_roll_link": self.body_roll_link, "body_pos_gain": self.body_pos_gain,
                     "mirror": self.mirror, "link_blink": self.link_blink, "auto_calibrate": self.auto_calibrate},
        }
