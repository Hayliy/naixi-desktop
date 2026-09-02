"""把 --diag 截出的 PNG 序列合成动画 GIF，供人眼直接核对动作。

输出两张：
  - <名字>_full.gif  全身（缩到 300 宽）
  - <名字>_legs.gif  下半身特写（模型高度的下 45%，放大到 300 宽）—— 专看腿动不动

用法： python make_motion_gif.py Squat [输出目录]
"""
import glob, os, sys
import numpy as np
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CAPDIR = os.path.join(_PROJ, "logs", "capture")
name = sys.argv[1] if len(sys.argv) > 1 else "Squat"
outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
NMAX = int(sys.argv[3]) if len(sys.argv) > 3 else 24

files = sorted(glob.glob(os.path.join(CAPDIR, "frame_*.png")))
files = [f for f in files if os.path.basename(f) <= "frame_%03d.png" % NMAX]
if len(files) < 4:
    print("截图不足")
    sys.exit(2)

imgs = [Image.open(f).convert("RGBA") for f in files]
arr = [np.array(im) for im in imgs]
H, W = arr[0].shape[:2]

# 模型垂直范围（用全部帧的 alpha 并集，保证裁切稳定）
allm = np.zeros((H, W), dtype=bool)
for a in arr:
    allm |= (a[..., 3] > 16)
rows = np.where(allm.any(axis=1))[0]
cols = np.where(allm.any(axis=0))[0]
top, bot = int(rows.min()), int(rows.max())
left, right = int(cols.min()), int(cols.max())
mh = bot - top + 1


def to_gif(frames, path, width=300, duration=110):
    """frames: PIL.Image 列表（RGBA，透明背景）→ 合成 GIF（白底便于观看）"""
    out = []
    for im in frames:
        w, h = im.size
        nh = max(1, int(h * width / w))
        im2 = im.resize((width, nh), Image.LANCZOS)
        bg = Image.new("RGB", (width, nh), (255, 255, 255))
        bg.paste(im2, (0, 0), im2)
        out.append(bg)
    out[0].save(path, save_all=True, append_images=out[1:],
                duration=duration, loop=0, optimize=True)
    print("已生成:", path, "(%d 帧)" % len(out))


# 1) 全身
full = [im.crop((left, top, right + 1, bot + 1)) for im in imgs]
to_gif(full, os.path.join(outdir, "%s_full.gif" % name))

# 2) 下半身特写：模型高度的下 45%
leg_top = top + int(mh * 0.55)
legs = [im.crop((left, leg_top, right + 1, bot + 1)) for im in imgs]
to_gif(legs, os.path.join(outdir, "%s_legs.gif" % name), duration=110)

print()
print("模型垂直范围 y=%d..%d (高 %d)，下半身特写取 y=%d 以下" % (top, bot, mh, leg_top))
print("用途：legs 动图专供核对『大腿→膝→小腿→脚 这条链到底动没动』。")
