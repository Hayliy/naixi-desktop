"""内部结构不变量分析 —— 判断"肢体到底有没有真的变形/弯曲"。

用户洞察（3D 摆钟类比）：整体旋转不改变内部结构。
数学严格化：**任意两点间的距离是刚体变换的不变量**（平移/旋转都不改变它）。
所以判断一条肢体链（髋→大腿→膝→小腿→踝→脚）有没有真的动，只看两件事：

  1. 关节弯曲角 = 180° - ∠(上段骨, 下段骨)
     - 腿伸直：两骨成一直线，∠=180°，弯曲角=0
     - 腿弯曲：∠<180°，弯曲角>0（弯得越狠数值越大）
     ⇒ 这是"膝盖/髋到底弯没弯"的无歧义物理量。

  2. 端到端距离 |髋 - 脚|
     - 腿伸直时最大；腿一弯就变短。
     ⇒ 也是刚体不变量，不受整体旋转/平移任何影响。

对比"局部四元数关节角"（pose_analyze.py 的 qs）：本法的量全是**几何不变量**，
完全不需要任何对齐/拟合，因此不存在"把腿弯曲误当成整体平移扣掉"的系统偏差。

用法： python joint_geometry.py Spin [Squat ...]
"""
import json, os, sys
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
BASE = os.path.join(_PROJ, "logs", "metrics")
BONES = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
         'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
         'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
         'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
         'rightUpperLeg', 'rightLowerLeg', 'rightFoot']

# (名称, 顶点骨, 上端骨, 下端骨) —— 顶点即关节所在位置
JOINTS = [
    ('左髋', 'leftUpperLeg', 'hips', 'leftLowerLeg'),
    ('右髋', 'rightUpperLeg', 'hips', 'rightLowerLeg'),
    ('左膝', 'leftLowerLeg', 'leftUpperLeg', 'leftFoot'),
    ('右膝', 'rightLowerLeg', 'rightUpperLeg', 'rightFoot'),
    ('左踝', 'leftFoot', 'leftLowerLeg', 'leftHand'),   # 踝的下端用脚到手近似不可靠，仅作参考
    ('左肘', 'leftLowerArm', 'leftUpperArm', 'leftHand'),
    ('右肘', 'rightLowerArm', 'rightUpperArm', 'rightHand'),
]
# 端到端距离（肢体弯曲时变短）
SPANS = [
    ('髋→脚(左腿总长)', 'hips', 'leftFoot'),
    ('髋→脚(右腿总长)', 'hips', 'rightFoot'),
    ('髋→膝(左大腿)', 'hips', 'leftLowerLeg'),
    ('髋→膝(右大腿)', 'hips', 'rightLowerLeg'),
    ('肩→手(左臂总长)', 'leftShoulder', 'leftHand'),
    ('肩→手(右臂总长)', 'rightShoulder', 'rightHand'),
]

# 踝的下端骨骼在 VRM 里是 leftFoot 本身，没有脚趾骨，改用"小腿→脚"与"脚"无关，
# 故去掉踝，只保留可靠关节
JOINTS = [j for j in JOINTS if not j[0].endswith('踝')]


def angle_at(P, a, b, c):
    """∠abc（b 为顶点），返回度。P 为 (骨名->3维坐标) 的映射。"""
    if not (a in P and b in P and c in P):
        return None
    v1 = P[a] - P[b]
    v2 = P[c] - P[b]
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return None
    cos = float(np.dot(v1, v2) / (n1 * n2))
    cos = 1.0 if cos > 1.0 else (-1.0 if cos < -1.0 else cos)
    return float(np.degrees(np.arccos(cos)))


def analyze(name):
    path = os.path.join(BASE, "metrics_%s.jsonl" % name)
    if not os.path.exists(path):
        print("### %s : 无数据 %s" % (name, path))
        return
    raw = [l for l in open(path, encoding='utf-8').read().splitlines() if l.strip()]
    rows = [json.loads(l) for l in raw if '"pts"' in l]
    if not rows:
        print("### %s : 样本无 pts 字段（请用带点云探针的 index.html 重新采样）" % name)
        return
    rows = rows[-120:]
    # 逐帧构造 骨名->坐标
    frames = []
    for r in rows:
        pts = r.get('pts') or []
        if len(pts) != len(BONES):
            continue
        P = {}
        for b, p in zip(BONES, pts):
            if p is not None:
                P[b] = np.array(p, dtype=float)
        frames.append(P)
    if len(frames) < 5:
        print("### %s : 有效帧不足" % name)
        return

    print()
    print("=" * 62)
    print("### 动作 %s   (帧数 %d) —— 内部结构不变量分析" % (name, len(frames)))
    print("=" * 62)

    print("\n【关节弯曲角】= 180° - 骨段夹角；0°=完全伸直，数值越大弯得越狠")
    print("%-8s %10s %10s %10s   %s" % ("关节", "最小", "最大", "变化幅度", "判定"))
    print("-" * 56)
    for jn, vtx, up, dn in JOINTS:
        vals = []
        for P in frames:
            a = angle_at(P, up, vtx, dn)
            if a is not None:
                vals.append(180.0 - a)
        if not vals:
            print("%-8s   (模型缺骨骼，跳过)" % jn)
            continue
        lo, hi = min(vals), max(vals)
        amp = hi - lo
        tag = "明显在弯" if amp > 15 else ("有弯但很轻微" if amp > 4 else "基本是直的(没弯)")
        print("%-8s %10.2f %10.2f %10.2f   %s" % (jn, lo, hi, amp, tag))

    print("\n【端到端距离】肢体弯曲时会变短；刚体旋转/平移不改变它")
    print("%-20s %10s %10s %10s   %s" % ("跨度", "最小", "最大", "变化幅度", "判定"))
    print("-" * 68)
    for sn, a, b in SPANS:
        vals = [np.linalg.norm(P[a] - P[b]) for P in frames if a in P and b in P]
        if not vals:
            print("%-20s   (模型缺骨骼，跳过)" % sn)
            continue
        lo, hi = min(vals), max(vals)
        amp = hi - lo
        rel = amp / hi * 100 if hi > 1e-9 else 0
        tag = "明显伸缩" if rel > 8 else ("轻微伸缩" if rel > 2 else "长度几乎不变(该链是刚体)")
        print("%-20s %10.4f %10.4f %10.4f   %s (%.1f%%)" % (sn, lo, hi, amp, tag, rel))


if __name__ == "__main__":
    names = sys.argv[1:] or ["Spin"]
    for n in names:
        analyze(n)
    print()
    print("说明：以上全部是几何不变量，不含任何对齐/拟合，"
          "因此不受整体旋转与平移影响——整体怎么转都不改变这些数字。")
