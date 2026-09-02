"""生成卸载 UI 专属位图，复用安装器 gen_top.py 的字体/配色规范。

输出：
  - banner_uninstall.bmp  (540x150) 猫娘 banner，副标题「桌面智能体 · 卸载」
  - txt_step_u{1,2,3}_on.bmp  (44x18) 步骤文字（激活粉 #D4537E）
  - txt_step_u{1,2,3}_off.bmp (44x18) 步骤文字（未激活灰 #AAAAAA）
  - dot_uninstall.bmp (6x6) 组件清单粉色圆点
  - warn_uninstall.bmp (480x30) 警告框（浅粉底 + 左粉边 + 圆角）
"""
from PIL import Image, ImageDraw, ImageFont
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(os.path.dirname(_HERE))
BASE = _HERE
FONT = r"C:\Windows\Fonts\msyh.ttc"

CLR_FOOTER_BG = (253, 248, 250)   # #FDF8FA
CLR_PINK = (212, 83, 126)         # #D4537E
CLR_GRAY = (170, 170, 170)        # #AAAAAA
CLR_LIGHT_PINK = (244, 192, 209)  # #F4C0D1
CLR_WARN_BG = (253, 238, 242)     # #FDEEF2
CLR_WARN_BORDER = (212, 83, 126)  # #D4537E
CLR_WARN_TEXT = (155, 50, 82)     # #9b3252
CLR_DISABLE_BG = (224, 224, 224)  # #E0E0E0
CLR_DISABLE_TEXT = (153, 153, 153)  # #999999


def get_font(size, bold=False):
    idx = 1 if bold else 0
    return ImageFont.truetype(FONT, size, index=idx)


def gen_banner():
    src = Image.open(os.path.join(_PROJ, "data", "avatars", "avatar-0.png")).convert("RGBA")
    sw, sh = src.size
    tw, th = 540, 150
    scale = max(tw / sw, th / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    resized = src.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = (nh - th) // 2
    out = Image.new("RGBA", (tw, th), (255, 255, 255, 255))
    out.paste(resized, (-x, -y), resized)
    overlay = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    BAND = int(th * 0.5)
    for yy in range(th):
        a = int(160 * max(0, (yy - BAND) / (th - BAND)))
        od.line([(0, yy), (tw, yy)], fill=(35, 12, 28, a))
    for xx in range(tw):
        a = int(70 * max(0, (tw * 0.5 - xx) / (tw * 0.5)))
        od.line([(xx, th - 70), (xx, th)], fill=(35, 12, 28, a))
    out = Image.alpha_composite(out, overlay)
    title_font = get_font(30, bold=True)
    sub_font = get_font(13)
    tx, ty = 22, th - 56
    d = ImageDraw.Draw(out)
    d.text((tx + 1, ty + 1), "奶昔", font=title_font, fill=(0, 0, 0, 90))
    d.text((tx, ty), "奶昔", font=title_font, fill=(255, 255, 255, 255))
    sy = ty + 34
    d.text((tx + 1, sy + 1), "桌面智能体 · 卸载", font=sub_font, fill=(0, 0, 0, 90))
    d.text((tx, sy), "桌面智能体 · 卸载", font=sub_font, fill=(255, 255, 255, 240))
    os.makedirs(BASE, exist_ok=True)
    out.convert("RGB").save(os.path.join(BASE, "banner_uninstall.bmp"), "BMP")
    print("saved banner_uninstall.bmp", (tw, th))


def gen_step_text(name, text, color):
    im = Image.new("RGB", (44, 18), CLR_FOOTER_BG)
    d = ImageDraw.Draw(im)
    f = get_font(12)
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = 0
    ty = (18 - th) // 2 - bbox[1]
    d.text((tx, ty), text, font=f, fill=color)
    im.save(os.path.join(BASE, name), "BMP")
    print("saved", name)


def gen_dot():
    im = Image.new("RGB", (6, 6), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([(0, 0), (5, 5)], fill=CLR_PINK)
    im.save(os.path.join(BASE, "dot_uninstall.bmp"), "BMP")
    print("saved dot_uninstall.bmp")


def gen_warn():
    w, h = 480, 30
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=4, fill=CLR_WARN_BG)
    d.rectangle([(0, 0), (2, h - 1)], fill=CLR_WARN_BORDER)
    f = get_font(12)
    d.text((12, (h - 16) // 2), "此操作不可撤销。确定要继续卸载吗？", font=f, fill=CLR_WARN_TEXT)
    im.save(os.path.join(BASE, "warn_uninstall.bmp"), "BMP")
    print("saved warn_uninstall.bmp", (w, h))


def draw_button(name, text, bg, fg, corner, w=90, h=30, radius=5):
    im = Image.new("RGB", (w, h), corner)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([(0, 0), (w - 1, h - 1)], radius=radius, fill=bg)
    f = get_font(13)
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((w - tw) // 2 - bbox[0], (h - th) // 2 - bbox[1]), text, font=f, fill=fg)
    im.save(os.path.join(BASE, name), "BMP")
    print("saved", name, (w, h), text)


def main():
    gen_banner()
    for text, idx in [("确认", 1), ("卸载", 2), ("完成", 3)]:
        gen_step_text(f"txt_step_u{idx}_on.bmp", text, CLR_PINK)
        gen_step_text(f"txt_step_u{idx}_off.bmp", text, CLR_GRAY)
    gen_dot()
    gen_warn()
    draw_button("btn_uninstalling.bmp", "卸载中", CLR_DISABLE_BG, CLR_DISABLE_TEXT, CLR_FOOTER_BG)


if __name__ == "__main__":
    main()
