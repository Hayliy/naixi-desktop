from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)
SRC = os.path.join(_PROJ, "data", "avatars", "avatar-0.png")
OUT = os.path.join(_HERE, "installer", "banner.bmp")
W, H = 480, 110

base = Image.open(SRC).convert("RGBA")

# cover 铺满：取最大缩放，垂直居中裁切（对准脸部）
scale = max(W / base.width, H / base.height)
new_w = int(base.width * scale)
new_h = int(base.height * scale)
face = base.resize((new_w, new_h), Image.LANCZOS)
x_off = (W - new_w) // 2
y_off = (H - new_h) // 2
banner = Image.new("RGBA", (W, H), (255, 255, 255, 255))
banner.paste(face, (x_off, y_off), face)

# 底部渐变蒙版（保证白字可读）
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
BAND = int(H * 0.5)
for y in range(H):
    a = int(160 * max(0, (y - BAND) / (H - BAND)))
    od.line([(0, y), (W, y)], fill=(35, 12, 28, a))
for x in range(W):
    a = int(70 * max(0, (W * 0.5 - x) / (W * 0.5)))
    od.line([(x, H - 70), (x, H)], fill=(35, 12, 28, a))
banner = Image.alpha_composite(banner, overlay)

# 装饰光斑
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for cx, cy, r, a in [(380, 40, 70, 28), (430, 95, 50, 22)]:
    gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, a))
glow = glow.filter(ImageFilter.GaussianBlur(40))
banner = Image.alpha_composite(banner, glow)

title_font = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 30)
sub_font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 13)
tx, ty = 22, H - 56
draw = ImageDraw.Draw(banner)
draw.text((tx + 1, ty + 1), "奶昔 · 桌面智能体", font=title_font, fill=(0, 0, 0, 90))
draw.text((tx, ty), "奶昔 · 桌面智能体", font=title_font, fill=(255, 255, 255, 255))
sy = ty + 34
draw.text((tx + 1, sy + 1), "AI 对话 · 工作流 · 自动化 · 知识库", font=sub_font, fill=(0, 0, 0, 90))
draw.text((tx, sy), "AI 对话 · 工作流 · 自动化 · 知识库", font=sub_font, fill=(255, 255, 255, 240))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
banner.convert("RGB").save(OUT, "BMP")
print("saved", OUT, banner.size)
