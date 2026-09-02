"""
扫雷感知层：截图 → 视图
- 定位网格（由 skin 给出 origin/cell/rows/cols）。
- 分类每格：未翻开('?') / 旗('F') / 数字(1..8) / 空(0)。
- 数字识别：与同例程生成的模板做归一化 SSD 匹配（合成图精确；真机换真实模板同代码）。
"""
import numpy as np
from PIL import Image
from minesweeper_render import render_board, RAISED


def _inner_crop(img, x0, y0, cs, pad=3):
    return img.crop((x0 + pad, y0 + pad, x0 + cs - pad, y0 + cs - pad))


def _norm_gray(crop):
    a = np.asarray(crop.convert("L"), dtype=np.float32)
    mu = a.mean()
    sd = a.std() + 1e-6
    return (a - mu) / sd


def build_templates(cs):
    """生成 0..8 的数字/空模板（与渲染同源）。"""
    tpl = {}
    for d in range(0, 9):
        v = [[0 if d == 0 else d]]
        img = render_board(v, {"cell": cs, "origin": 4})
        crop = _inner_crop(img, 4, 4, cs)
        tpl[d] = _norm_gray(crop)
    return tpl


def _raised(mean_rgb):
    # 未翻开按钮底色偏 (192,192,192)
    return np.linalg.norm(np.array(mean_rgb) - np.array(RAISED)) < 16


def _red_fraction(crop):
    a = np.asarray(crop.convert("RGB"), dtype=np.float32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    red = (r > 150) & (g < 90) & (b < 90)
    return red.mean()


def perceive(image, skin):
    rows, cols = skin["rows"], skin["cols"]
    cs = skin["cell"]
    ox = oy = skin["origin"]
    tpl = build_templates(cs)
    view = []
    for r in range(rows):
        row = []
        for c in range(cols):
            x0, y0 = ox + c * cs, oy + r * cs
            crop = _inner_crop(image, x0, y0, cs)
            mean = np.asarray(crop.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(0)
            if _raised(mean):
                row.append("?")
                continue
            if _red_fraction(crop) > 0.06:
                row.append("F")
                continue
            ng = _norm_gray(crop)
            best, best_d = 1e9, 0
            for d, t in tpl.items():
                ssd = float(np.mean((ng - t) ** 2))
                if ssd < best:
                    best, best_d = ssd, d
            row.append(best_d)  # 0 表示空
        view.append(row)
    return view


def cell_to_screen(r, c, skin, win_x=0, win_y=0):
    """格子中心 → 屏幕绝对坐标（真机点击用；win_x/y 为游戏窗口左上角屏幕坐标）。"""
    cs = skin["cell"]
    ox = oy = skin["origin"]
    cx = win_x + ox + c * cs + cs / 2
    cy = win_y + oy + r * cs + cs / 2
    return int(cx), int(cy)
