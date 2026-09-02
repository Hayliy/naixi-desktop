"""
扫雷渲染器：把视图画成一张 PNG（供①合成自测图 ②生成数字模板）。
感知层用同一套 draw 例程生成模板，因此模板匹配在合成图上精确成立；
真机上只需把模板换成真实截图（同匹配代码即可）。
"""
from PIL import Image, ImageDraw, ImageFont

# 标准扫雷数字配色
DIGIT_COLORS = {
    1: (0, 0, 255), 2: (0, 128, 0), 3: (255, 0, 0), 4: (0, 0, 128),
    5: (128, 0, 0), 6: (0, 128, 128), 7: (0, 0, 0), 8: (128, 128, 128),
}
RAISED = (192, 192, 192)      # 未翻开按钮底色
REVEALED = (215, 215, 215)    # 翻开后底色
GRID_LINE = (120, 120, 120)
BEVEL_HI = (255, 255, 255)
BEVEL_LO = (128, 128, 128)
FLAG_RED = (220, 0, 0)
MINE_BLACK = (0, 0, 0)


def _font(cell):
    try:
        return ImageFont.truetype("arial.ttf", max(10, cell // 2))
    except Exception:
        return ImageFont.load_default()


def draw_digit(draw, x0, y0, cs, d):
    """在格子内画数字 d（1..8），与模板生成完全一致。"""
    color = DIGIT_COLORS.get(d, (0, 0, 0))
    f = _font(cs)
    txt = str(d)
    bbox = draw.textbbox((0, 0), txt, font=f)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x0 + (cs - w) / 2 - bbox[0], y0 + (cs - h) / 2 - bbox[1]),
              txt, fill=color, font=f)


def draw_flag(draw, x0, y0, cs):
    cx = x0 + cs / 2
    top = y0 + cs * 0.22
    bot = y0 + cs * 0.78
    # 旗杆
    draw.line([(cx, top), (cx, bot)], fill=(0, 0, 0), width=max(1, cs // 16))
    # 旗面（红三角）
    draw.polygon([(cx, top), (cx, top + cs * 0.32), (cx - cs * 0.26, top + cs * 0.16)],
                 fill=FLAG_RED)
    # 底座
    draw.line([(cx - cs * 0.18, bot), (cx + cs * 0.18, bot)], fill=(0, 0, 0), width=max(1, cs // 16))


def draw_mine(draw, x0, y0, cs):
    cx, cy = x0 + cs / 2, y0 + cs / 2
    r = cs * 0.22
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=MINE_BLACK)
    # 尖刺
    for ang in range(0, 360, 45):
        import math
        a = math.radians(ang)
        draw.line([(cx, cy), (cx + r * 1.5 * math.cos(a), cy + r * 1.5 * math.sin(a))],
                  fill=MINE_BLACK, width=max(1, cs // 20))


def render_board(view, skin, show_mines=False, mine_pos=None):
    """view: 二维（0..8 / 'F' / '?'）。返回 PIL Image。skin 决定布局。"""
    rows, cols = len(view), len(view[0])
    cs = skin["cell"]
    ox = oy = skin["origin"]
    W = ox * 2 + cols * cs
    H = oy * 2 + rows * cs
    img = Image.new("RGB", (W, H), (160, 160, 160))
    d = ImageDraw.Draw(img)
    for r in range(rows):
        for c in range(cols):
            x0, y0 = ox + c * cs, oy + r * cs
            v = view[r][c]
            if v == "?":
                # 凸起按钮
                d.rectangle([x0, y0, x0 + cs - 1, y0 + cs - 1], fill=RAISED)
                d.line([(x0, y0), (x0 + cs - 1, y0)], fill=BEVEL_HI, width=2)
                d.line([(x0, y0), (x0, y0 + cs - 1)], fill=BEVEL_HI, width=2)
                d.line([(x0 + cs - 1, y0), (x0 + cs - 1, y0 + cs - 1)], fill=BEVEL_LO, width=2)
                d.line([(x0, y0 + cs - 1), (x0 + cs - 1, y0 + cs - 1)], fill=BEVEL_LO, width=2)
            else:
                # 翻开底
                d.rectangle([x0, y0, x0 + cs - 1, y0 + cs - 1], fill=REVEALED)
                if v == "F":
                    draw_flag(d, x0, y0, cs)
                elif isinstance(v, int) and v > 0:
                    draw_digit(d, x0, y0, cs, v)
                elif show_mines and mine_pos and (r, c) in mine_pos:
                    draw_mine(d, x0, y0, cs)
            d.rectangle([x0, y0, x0 + cs - 1, y0 + cs - 1], outline=GRID_LINE)
    return img
