from PIL import Image, ImageDraw, ImageFont
import os

BASE = r"D:\naixi_desktop\src-tauri\installer"
OUT_DIR = BASE

# 微软雅黑绝对路径（Pillow 无法按名字解析，必须用绝对路径，否则回退点阵字体导致中文/×/— 变豆腐块）
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"

# 控件坐标（与 test_flow.nsi / installer.nsi 保持一致）
WIN_W, BANNER_H = 540, 150
BTN_W, BTN_H = 90, 30
BROWSE_W, BROWSE_H = 90, 28
ADDR_W, ADDR_H = 382, 32
TRACK_W, TRACK_H = 480, 8
RADIUS = 5
NUM_SIZE = 18  # 步骤圆点尺寸（匹配 mockup .step .num 18x18）

CLR_PINK = "#D4537E"
CLR_LIGHT_PINK = "#F4C0D1"
CLR_DARK_PINK = "#72243E"
CLR_FOOTER_BG = "#FDF8FA"
CLR_BG = "#FFFFFF"
CLR_DISABLE_BG = "#E0E0E0"
CLR_DISABLE_TEXT = "#999999"
CLR_WHITE = "#FFFFFF"
CLR_BORDER = "#D3C1D0"


def ensure_dir():
    os.makedirs(OUT_DIR, exist_ok=True)


def hex_rgb(hex_val: str):
    hex_val = hex_val.lstrip("#")
    return tuple(int(hex_val[i:i + 2], 16) for i in (0, 2, 4))


def get_font(size: int, bold: bool = False):
    """微软雅黑：常规 index=0，粗体 index=1（msyhbd 在 ttc 中）。"""
    idx = 1 if bold else 0
    try:
        return ImageFont.truetype(FONT_PATH, size, index=idx)
    except Exception as e:
        print("FONT LOAD FAIL", e)
        return ImageFont.load_default()


def draw_text_centered(d: ImageDraw.Draw, text: str, font, cx: int, cy: int, fill):
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw // 2 - bbox[0]
    ty = cy - th // 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=fill)


def draw_banner(src_path: str, out_path: str, size: tuple):
    """生成 banner 位图（不含右上角按钮字形，按钮由独立位图按钮叠加）。"""
    src = Image.open(src_path).convert("RGBA")
    sw, sh = src.size
    tw, th = size
    scale = max(tw / sw, th / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    resized = src.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = (nh - th) // 2
    out = Image.new("RGBA", size, (255, 255, 255, 255))
    out.paste(resized, (-x, -y), resized)
    out.convert("RGB").save(out_path, "BMP")
    print("saved", out_path, size)


def draw_corner_btn(out_path: str, symbol: str, region: tuple, bar: bool = False):
    """右上角按钮：80% 半透明蒙版（叠加 banner 角像素 + 20% 暗化），白色字形。

    region = (x0, y0, w, h) 为该按钮在 banner 上的实际覆盖区域，
    从已生成的 banner.bmp 取对应像素做混合，使位图覆盖后呈现「半透明」观感。
    bar=True 时绘制 12x2 圆角白条（用于最小化，避免字体短横过细）。
    """
    bx0, by0, bw, bh = region
    banner = Image.open(os.path.join(OUT_DIR, "banner.bmp")).convert("RGB")
    bpx = banner.load()
    im = Image.new("RGB", (bw, bh))
    px = im.load()
    for y in range(bh):
        for x in range(bw):
            r, g, b = bpx[bx0 + x, by0 + y]
            r = int(r * 0.8 + 50 * 0.2)
            g = int(g * 0.8 + 35 * 0.2)
            b = int(b * 0.8 + 45 * 0.2)
            px[x, y] = (r, g, b)
    d = ImageDraw.Draw(im)
    if bar:
        # 居中 12x2 圆角白条，与 × 视觉粗细接近
        d.rounded_rectangle([(bw // 2 - 6, bh // 2 - 1), (bw // 2 + 5, bh // 2 + 1)],
                            radius=1, fill=(255, 255, 255))
    else:
        font = get_font(16)
        draw_text_centered(d, symbol, font, bw // 2, bh // 2 + 1, (255, 255, 255))
    im.save(out_path, "BMP")
    print("saved", out_path, (bw, bh), symbol)


def draw_button(out_path: str, text: str, btn_bg_hex: str, fg_hex: str,
                corner_hex: str, w: int, h: int, font_size: int, bold: bool = False):
    """圆角按钮位图：整块圆角填充按钮底色，圆角外区域填「底色」使其与所在背景融合呈现圆角。

    corner_hex 必须是按钮实际所在背景色：
      - 底部导航按钮在 footer（#FDF8FA）
      - 浏览按钮在白色内容区（#FFFFFF）
    """
    bg = hex_rgb(btn_bg_hex)
    fg = hex_rgb(fg_hex)
    corner = hex_rgb(corner_hex)
    im = Image.new("RGB", (w, h), corner)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=RADIUS, fill=bg)
    font = get_font(font_size, bold)
    draw_text_centered(d, text, font, w // 2, h // 2, fg)
    im.save(out_path, "BMP")
    print("saved", out_path, (w, h), text)


def draw_addr_border(out_path: str, w: int, h: int):
    """地址输入框圆角边框位图：1px #D3C1D0 边框 + 圆角 5px + 内部 #FDF8FA + 圆角外白色（与页面融合）。"""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=5,
                        outline=hex_rgb(CLR_BORDER), width=1,
                        fill=hex_rgb(CLR_FOOTER_BG))
    im.save(out_path, "BMP")
    print("saved", out_path, (w, h))


def draw_progress_track(out_path: str, w: int, h: int):
    """进度条轨道：圆角 4px 浅粉 #F4C0D1，圆角外白色（与页面融合）。"""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=4, fill=hex_rgb(CLR_LIGHT_PINK))
    im.save(out_path, "BMP")
    print("saved", out_path, (w, h))


def draw_num(out_path: str, num: int, on: bool):
    """生成带数字的圆形步骤指示点（匹配 mockup .step .num）。

    on=True  深粉底 #D4537E + 白字
    on=False 浅粉底 #F4C0D1 + 白字
    """
    bg = hex_rgb(CLR_PINK) if on else hex_rgb(CLR_LIGHT_PINK)
    fg = hex_rgb(CLR_WHITE)
    im = Image.new("RGB", (NUM_SIZE, NUM_SIZE), (255, 255, 255))
    d = ImageDraw.Draw(im)
    cx = cy = NUM_SIZE // 2
    r = NUM_SIZE // 2 - 1
    d.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=bg)
    font = get_font(11)
    draw_text_centered(d, str(num), font, cx, cy + 1, fg)
    im.save(out_path, "BMP")
    print("saved", out_path, (NUM_SIZE, NUM_SIZE), num, "on" if on else "off")


def main():
    ensure_dir()

    draw_banner(
        os.path.join(BASE, "banner_preview.png"),
        os.path.join(OUT_DIR, "banner.bmp"),
        (WIN_W, BANNER_H))

    # 底部导航主按钮（粉底白字，统一 90x30，圆角 5px，圆角底色=footer #FDF8FA 融合）
    draw_button(os.path.join(OUT_DIR, "btn_next.bmp"), "下一步",
                CLR_PINK, CLR_WHITE, CLR_FOOTER_BG, BTN_W, BTN_H, 13, bold=True)
    draw_button(os.path.join(OUT_DIR, "btn_install.bmp"), "安装",
                CLR_PINK, CLR_WHITE, CLR_FOOTER_BG, BTN_W, BTN_H, 13, bold=True)
    draw_button(os.path.join(OUT_DIR, "btn_finish.bmp"), "完成",
                CLR_PINK, CLR_WHITE, CLR_FOOTER_BG, BTN_W, BTN_H, 13, bold=True)
    # 卸载页「卸载」主按钮（粉底白字，与 安装 同款）
    draw_button(os.path.join(OUT_DIR, "btn_uninstall.bmp"), "卸载",
                CLR_PINK, CLR_WHITE, CLR_FOOTER_BG, BTN_W, BTN_H, 13, bold=True)
    # 安装中（禁用态：灰底灰字）
    draw_button(os.path.join(OUT_DIR, "btn_installing.bmp"), "安装中",
                CLR_DISABLE_BG, CLR_DISABLE_TEXT, CLR_FOOTER_BG, BTN_W, BTN_H, 13)
    # 上一步（次级：浅粉底深粉字）
    draw_button(os.path.join(OUT_DIR, "btn_prev.bmp"), "上一步",
                CLR_LIGHT_PINK, CLR_DARK_PINK, CLR_FOOTER_BG, BTN_W, BTN_H, 13)

    # 浏览按钮（次级：浅粉底深粉字，90x28 与地址框等高，圆角底色=白色内容区）
    draw_button(os.path.join(OUT_DIR, "btn_browse.bmp"), "浏览...",
                CLR_LIGHT_PINK, CLR_DARK_PINK, CLR_BG, BROWSE_W, BROWSE_H, 12)

    # 右上角 最小化 / 关闭 按钮（80% 半透明蒙版，白色 - / ×）
    # 最小化用自定义粗横线（12x2 圆角白条），避免字体渲染出过细短横
    draw_corner_btn(os.path.join(OUT_DIR, "btn_min.bmp"), "-", (478, 6, 28, 24), bar=True)
    draw_corner_btn(os.path.join(OUT_DIR, "btn_close.bmp"), "×", (506, 6, 28, 24))

    # 地址输入框圆角边框
    draw_addr_border(os.path.join(OUT_DIR, "addr_border.bmp"), ADDR_W, ADDR_H)
    # 进度条轨道（圆角 4px 浅粉）
    draw_progress_track(os.path.join(OUT_DIR, "progress_track.bmp"), TRACK_W, TRACK_H)

    # 步骤圆点（数字 1-4，激活/未激活）
    for i in range(1, 5):
        draw_num(os.path.join(OUT_DIR, f"num{i}_on.bmp"), i, True)
        draw_num(os.path.join(OUT_DIR, f"num{i}_off.bmp"), i, False)

    # 清理旧的步骤位图（不再使用）
    for i in range(1, 5):
        for state in ("on", "off"):
            p = os.path.join(OUT_DIR, f"step{i}_{state}.bmp")
            if os.path.exists(p):
                os.remove(p)
                print("removed obsolete", p)


if __name__ == "__main__":
    main()
