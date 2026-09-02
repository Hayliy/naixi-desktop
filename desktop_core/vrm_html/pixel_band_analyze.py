"""像素分带形状分析 —— 判断"画面上某部位到底有没有真的变形"。

背景：骨骼数据（刚体不变量）显示腿部关节在弯，但用户肉眼坚称腿没动。
二者只能靠**渲染出来的像素**裁决：骨骼动了 ≠ 网格跟着动（可能是蒙皮问题）。

方法：
  1. 读 --diag 截出的 PNG 序列（透明背景桌宠，alpha 即模型轮廓）。
  2. 求模型垂直范围，按高度切成 5 个水平带（头颈/胸腰/髋大腿/膝小腿/脚）。
  3. 每带内把相邻两帧的 alpha 掩膜**按质心对齐**（消除整体平移），
     再算 1 - IoU（交并比）= 该带的**形状变化率**。
     - 若某带只是随身体整体平移，对齐后 IoU≈1，变化率≈0；
     - 若该带真的在变形（如膝盖弯曲），对齐后轮廓对不上，变化率明显 >0。
  ⇒ 这直接回答"这个部位在画面上到底有没有变形"，与骨骼数据互为交叉验证。

用法： python pixel_band_analyze.py [最多帧数，默认20]
"""
import glob, os, sys
import numpy as np
from PIL import Image

CAPDIR = r"D:\naixi_desktop\logs\capture"
NMAX = int(sys.argv[1]) if len(sys.argv) > 1 else 20

files = sorted(glob.glob(os.path.join(CAPDIR, "frame_*.png")))
files = [f for f in files if os.path.basename(f) <= "frame_%03d.png" % NMAX]
if len(files) < 4:
    print("截图不足（%d 张）。请先用 --diag 20 采样。" % len(files))
    sys.exit(2)

masks = []
for f in files:
    im = np.array(Image.open(f).convert("RGBA"))
    masks.append(im[..., 3] > 16)          # 透明背景：alpha 即模型轮廓
H, W = masks[0].shape
print("帧数 %d   画面 %dx%d" % (len(masks), W, H))

allm = np.zeros_like(masks[0])
for m in masks:
    allm |= m
rows = np.where(allm.any(axis=1))[0]
if rows.size == 0:
    print("画面全透明，未渲染出模型")
    sys.exit(3)
top, bot = int(rows.min()), int(rows.max())
mh = bot - top + 1
print("模型垂直范围 y=%d..%d (高 %d px, 占画面 %.0f%%)" % (top, bot, mh, mh / H * 100))

NAMES = ["头颈", "胸腰", "髋/大腿", "膝/小腿", "脚/踝"]
nb = len(NAMES)
print()
print("%-10s %14s %10s   %s" % ("水平带", "形状变化率%", "面积px", "判定"))
print("-" * 56)

results = {}
for k, nm in enumerate(NAMES):
    a = top + int(mh * k / nb)
    b = top + int(mh * (k + 1) / nb)
    band = [m[a:b] for m in masks]
    area = int(np.mean([x.sum() for x in band]))
    if area < 30:
        print("%-10s %14s %10d   (该带几乎没有模型像素)" % (nm, "-", area))
        results[nm] = None
        continue
    diffs = []
    for i in range(len(band) - 1):
        m1, m2 = band[i], band[i + 1]
        if m1.sum() < 30 or m2.sum() < 30:
            continue
        c1 = np.argwhere(m1).mean(0)
        c2 = np.argwhere(m2).mean(0)
        sh = np.round(c1 - c2).astype(int)
        m2s = np.roll(np.roll(m2, int(sh[0]), axis=0), int(sh[1]), axis=1)
        inter = int((m1 & m2s).sum())
        union = int((m1 | m2s).sum())
        if union:
            diffs.append(1.0 - inter / union)
    if not diffs:
        print("%-10s %14s %10d   (无可比帧)" % (nm, "-", area))
        results[nm] = None
        continue
    r = float(np.mean(diffs)) * 100
    results[nm] = r
    tag = "明显在变形" if r > 8 else ("轻微变形" if r > 2 else "形状几乎不变(刚体)")
    print("%-10s %14.2f %10d   %s" % (nm, r, area, tag))

print()
print("说明：变化率 = 1 - IoU，已按质心对齐消除整体平移。")
print("      数值越大 = 该部位轮廓形状变化越大 = 画面上真的在动/变形。")
print("      若骨骼数据显示腿部在弯、但这里『膝/小腿』带接近 0，")
print("      则是骨骼动了而网格没动（蒙皮/权重问题），需要查 VRM 模型。")
