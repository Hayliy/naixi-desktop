from PIL import Image, ImageDraw, ImageFont
import os

BASE = r"D:\naixi_desktop\src-tauri\installer"
OUT_DIR = BASE

# 控件坐标（与 test_flow.nsi / installer.nsi 保持一致）
WIN_W, BANNER_H = 540, 150
BTN_W, BTN_H = 90, 30
BROWSE_W, BROWSE_H = 90, 28
RADIUS = 5
NUM_SIZE = 20  # 步骤圆点尺寸（匹配 mockup .step .num 18x18）

CLR_PINK = "#D4537E"
CLR_LIGHT_PINK = "#F4C0D1"
CLR_DARK_PINK = "#72243E"
CLR_FOOTER_BG = "#FDF8FA"
CLR_BG = "#FFFFFF"
CLR_DISABLE_BG = "#E0E0E0"
CLR_DISABLE_TEXT = "#999999"
CLR_WHITE = "#FFFFFF"


def ensure_dir():
    os.makedirs(OUT_DIR, exist_ok=True)


def hex_rgb(hex_val: str):
    hex_val = hex_val.lstrip("#")
    return tuple(int(hex_val[i:i + 2], 16) for i in (0, 2, 4))


def get_font(size: int):
    try:
        return ImageFont.truetype("Microsoft YaHei", size)
    except Exception:
        return ImageFont.load_default()


def fit_crop(src_path: str, out_path: str, size: tuple):
    """把源图按 cover 规则裁剪到指定尺寸，输出 BMP。"""
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


def draw_text_centered(d: ImageDraw.Draw, text: str, font, cx: int, cy: int, fill):
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = cx - tw // 2 - bbox[0]
    ty = cy - th // 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=fill)


def draw_banner(src_path: str, out_path: str, size: tuple):
    """生成 banner 位图（干净，不绘制最小化/关闭按钮，改由 NSIS 透明蒙版控件绘制）。"""
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


def draw_button(out_path: str, text: str, bg_hex: str, fg_hex: str,
                w: int = BTN_W, h: int = BTN_H, font_size: int = 13):
    """生成圆角按钮位图（固定宽度，文字居中）。"""
    bg = hex_rgb(bg_hex)
    fg = hex_rgb(fg_hex)
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    # 圆角按钮：整块圆角填充背景色，文字居中
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=RADIUS, fill=bg)
    font = get_font(font_size)
    draw_text_centered(d, text, font, w // 2, h // 2, fg)
    im.save(out_path, "BMP")
    print("saved", out_path, (w, h), text)


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

    # 底部导航主按钮（粉底白字，统一 90x30，圆角 5px）
    draw_button(os.path.join(OUT_DIR, "btn_next.bmp"), "下一步",
                CLR_PINK, CLR_WHITE, BTN_W, BTN_H, 13)
    draw_button(os.path.join(OUT_DIR, "btn_install.bmp"), "安装",
                CLR_PINK, CLR_WHITE, BTN_W, BTN_H, 13)
    draw_button(os.path.join(OUT_DIR, "btn_finish.bmp"), "完成",
                CLR_PINK, CLR_WHITE, BTN_W, BTN_H, 13)
    # 安装中（禁用态：灰底灰字）
    draw_button(os.path.join(OUT_DIR, "btn_installing.bmp"), "安装中",
                CLR_DISABLE_BG, CLR_DISABLE_TEXT, BTN_W, BTN_H, 13)
    # 上一步（次级：浅粉底深粉字）
    draw_button(os.path.join(OUT_DIR, "btn_prev.bmp"), "上一步",
                CLR_LIGHT_PINK, CLR_DARK_PINK, BTN_W, BTN_H, 13)

    # 浏览按钮（次级：浅粉底深粉字，90x28 与地址框等高）
    draw_button(os.path.join(OUT_DIR, "btn_browse.bmp"), "浏览...",
                CLR_LIGHT_PINK, CLR_DARK_PINK, BROWSE_W, BROWSE_H, 12)

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
