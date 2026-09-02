"""三维多点骨骼模型 + Procrustes 形状分析。

目的：区分「角色整体位移/旋转」与「部位自身真在动」。
方法：每帧把 20 个骨骼的世界坐标当作一个点云（"姿态形状"），
      用 Kabsch/Procrustes 求最优刚体变换（平移+旋转）对齐到参考帧，
      对齐后剩下的残差 = 扣除整体运动后该骨骼的净位移。
"""
import json, sys
import numpy as np

import os
NAME = sys.argv[1] if len(sys.argv) > 1 else "Spin"
PATH = os.path.join(r"D:\naixi_desktop\logs\metrics", "metrics_%s.jsonl" % NAME)
print("=== 动作: %s ===" % NAME)
N_TAKE = 120
THRESH = 0.015          # 净运动残差 RMS 阈值（模型身高约 1.36，此值约 1.5cm）

BONES = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
         'leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand',
         'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand',
         'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
         'rightUpperLeg', 'rightLowerLeg', 'rightFoot']

GROUPS = {
    '下半身(hips+双腿脚)': ['hips', 'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
                            'rightUpperLeg', 'rightLowerLeg', 'rightFoot'],
    '躯干+头颈':           ['spine', 'chest', 'upperChest', 'neck', 'head'],
    '左上肢':              ['leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand'],
    '右上肢':              ['rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand'],
}


def align(B, A):
    """把点云 B 刚体对齐到 A（Kabsch），返回对齐后的 B。"""
    mA, mB = A.mean(0), B.mean(0)
    A0, B0 = A - mA, B - mB
    H = B0.T @ A0
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:            # 防反射
        Vt2 = Vt.copy()
        Vt2[-1, :] *= -1
        R = Vt2.T @ U.T
    t = mA - R @ mB
    return (B @ R.T) + t


raw = [l for l in open(PATH, encoding='utf-8').read().splitlines() if l.strip()]
with_pts = [json.loads(l) for l in raw if '"pts"' in l]
print("含三维点云的样本: %d  (文件总行数 %d)" % (len(with_pts), len(raw)))
if not with_pts:
    print("NO_PTS_DATA — 探针未输出点云，先用新版 index.html 重新采样")
    sys.exit(2)
with_pts = with_pts[-N_TAKE:]

# 只用「所有帧都非 null」的骨骼（本模型缺 upperChest，自动排除，不牵连其他骨）
valid_idx, missing = [], set()
for j in range(len(BONES)):
    ok = all(len(r.get('pts') or []) == len(BONES) and (r['pts'][j] is not None)
             for r in with_pts)
    if ok:
        valid_idx.append(j)
    else:
        missing.add(BONES[j])
USE = [BONES[j] for j in valid_idx]
frames = [np.array([r['pts'][j] for j in valid_idx], dtype=float) for r in with_pts]
print("有效帧数: %d   参与分析的骨骼点: %d" % (len(frames), len(USE)))
if missing:
    print("模型缺失骨骼(已从点云中排除):", sorted(missing))
if len(frames) < 5 or len(USE) < 4:
    print("TOO_FEW_FRAMES_OR_BONES")
    sys.exit(3)

F = np.stack(frames)                     # (T, N, 3)
ref = F[0]

raw_disp = np.linalg.norm(F - ref, axis=2)          # 原始世界位移（含整体运动）
res = np.zeros_like(raw_disp)
for k in range(len(F)):
    res[k] = np.linalg.norm(align(F[k], ref) - ref, axis=1)   # 净运动残差(N,)

print()
print("%-20s %13s %14s   %s" % ("骨骼", "原始位移RMS", "净运动残差RMS", "判定"))
print("-" * 66)
per = {}
for j, b in enumerate(USE):
    rd = float(np.sqrt((raw_disp[:, j] ** 2).mean()))
    rs = float(np.sqrt((res[:, j] ** 2).mean()))
    per[b] = (rd, rs)
    v = "真在动" if rs > THRESH else ("仅随整体移动" if rd > THRESH else "几乎不动")
    print("%-20s %13.4f %14.4f   %s" % (b, rd, rs, v))

print()
print("=== 分区聚合（净运动残差 RMS，已扣除整体平移+旋转）===")
for g, bs in GROUPS.items():
    vs = [per[b][1] for b in bs if b in per]
    rs = [per[b][0] for b in bs if b in per]
    if not vs:
        continue
    m, mr = sum(vs) / len(vs), sum(rs) / len(rs)
    print("%-22s 净运动=%.4f   原始位移=%.4f   -> %s"
          % (g, m, mr, "真在动" if m > THRESH else "基本没动（只是随整体移动）"))

print()
print("=== 被 Procrustes 扣除掉的整体运动 ===")
cent = F.mean(axis=1)
rng = cent.max(0) - cent.min(0)
print("质心平移范围: x=%.4f  y=%.4f  z=%.4f  (这是整体位移，不是局部动作)" % tuple(rng))
print()
print("阈值: 净运动残差 RMS > %.3f 判为『真在动』" % THRESH)

# ── 关节旋转角：判断"关节自身转没转"的金标准，不受整体平移/旋转干扰 ──
if all('qs' in r for r in with_pts):
    def qang(q0, q1):
        d = abs(sum(a * b for a, b in zip(q0, q1)))
        d = 1.0 if d > 1.0 else d
        return float(np.degrees(2.0 * np.arccos(d)))

    Q = [[(r.get('qs') or [])[j] for j in valid_idx] for r in with_pts]
    refq = {b: Q[0][k] for k, b in enumerate(USE)}
    angs = {b: [] for b in USE}
    for row in Q:
        for k, b in enumerate(USE):
            if refq[b] is None or row[k] is None:
                continue
            angs[b].append(qang(refq[b], row[k]))

    print()
    print("=== 关节旋转角（相对首帧夹角，度；不受整体平移影响，位置法的补充）===")
    print("%-20s %10s %10s" % ("骨骼", "RMS°", "峰值°"))
    print("-" * 44)
    for b in USE:
        v = angs[b]
        if not v:
            continue
        print("%-20s %10.2f %10.2f" % (b, float(np.sqrt(np.mean(np.square(v)))), max(v)))

    print()
    print("=== 分区关节活动度（RMS°，这是『到底动没动』的最终判据）===")
    for g, bs in GROUPS.items():
        vals = [float(np.sqrt(np.mean(np.square(angs[b]))))
                for b in bs if b in angs and angs[b]]
        if vals:
            m = sum(vals) / len(vals)
            tag = "明显在动" if m > 8 else ("有动作但幅度小" if m > 2 else "基本不动")
            print("%-22s 关节活动=%.2f°   -> %s" % (g, m, tag))
else:
    print()
    print("(本批样本无 qs 字段，跳过关节角分析)")
