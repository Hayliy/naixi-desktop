"""生成 BMP(DIB) 格式的卸载器图标（uninstall.ico）。

背景：NSIS 的 UninstallIcon 在 WriteUninstaller 时替换卸载器桩的图标资源，
对 PNG 压缩内嵌的 ICO 兼容性差（替换静默失败→回退默认图标）。PIL 默认把
ICO 各尺寸存成 PNG 内嵌，无法满足。此脚本手写标准 BMP(DIB) 条目，
使用 BITMAPINFOHEADER + 32bpp BGRA XOR 位图 + 1bpp AND 掩码，
生成最兼容 NSIS 的经典 ICO。
"""
import struct
from PIL import Image

SRC = "D:/naixi_desktop/src-tauri/icons/512x512.png"
OUT = "D:/naixi_desktop/src-tauri/icons/uninstall.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def dib_entry(img: Image.Image, size: int) -> bytes:
    """把一张图缩放到 size×size，编码为 ICO 内的 BMP(DIB) 条目字节。"""
    im = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    px = im.load()
    w = h = size
    # BITMAPINFOHEADER：高度写 2*h（XOR + AND 掩码合并高度）
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        w,           # biWidth
        h * 2,       # biHeight = 图像高 + 掩码高
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression = BI_RGB
        0,           # biSizeImage
        0, 0,        # biXPelsPerMeter, biYPelsPerMeter
        0, 0,        # biClrUsed, biClrImportant
    )
    # XOR 位图：BGRA，自下而上
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))
    # AND 掩码：1bpp，每行 4 字节对齐；alpha>0 记为不透明(0)
    and_row_bytes = ((w + 31) // 32) * 4
    andmask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(and_row_bytes)
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                bits[x // 8] |= (0x80 >> (x % 8))
        andmask += bits
    return bytes(header) + bytes(xor) + bytes(andmask)


def main():
    src = Image.open(SRC).convert("RGBA")
    entries = [(s, dib_entry(src, s)) for s in SIZES]

    # ICONDIR
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(entries))  # reserved, type=1(icon), count
    offset = 6 + 16 * len(entries)
    dir_bytes = bytearray()
    data_bytes = bytearray()
    for size, data in entries:
        bw = 0 if size >= 256 else size
        bh = 0 if size >= 256 else size
        dir_bytes += struct.pack(
            "<BBBBHHII",
            bw, bh,      # width, height (0 表示 256)
            0,           # color count
            0,           # reserved
            1,           # planes
            32,          # bitcount
            len(data),   # bytes in resource
            offset,      # image offset
        )
        offset += len(data)
        data_bytes += data
    out += dir_bytes + data_bytes
    with open(OUT, "wb") as f:
        f.write(out)
    print(f"已生成 BMP(DIB) 格式卸载图标: {OUT}（{len(entries)} 个尺寸，共 {len(out)} 字节）")


if __name__ == "__main__":
    main()
