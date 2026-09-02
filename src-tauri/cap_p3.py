import subprocess, time, ctypes, sys, os
from ctypes import wintypes, Structure, byref, sizeof, create_string_buffer, c_int, c_long, c_uint, c_ulong, c_void_p, c_short, c_ushort
from PIL import Image, ImageGrab

EXE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_flow.exe")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p3frames")
os.makedirs(OUT, exist_ok=True)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# BITMAPINFOHEADER
class BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", c_ulong),
        ("biWidth", c_long),
        ("biHeight", c_long),
        ("biPlanes", c_ushort),
        ("biBitCount", c_ushort),
        ("biCompression", c_ulong),
        ("biSizeImage", c_ulong),
        ("biXPelsPerMeter", c_long),
        ("biYPelsPerMeter", c_long),
        ("biClrUsed", c_ulong),
        ("biClrImportant", c_ulong),
    ]

class RGBQUAD(Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte),
                ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]

class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

WND = None
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = ctypes.c_bool

@EnumWindowsProc
def enum_cb(hwnd, lparam):
    global WND
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    if buf.value == "奶昔 · 桌面智能体 安装" and user32.IsWindowVisible(hwnd):
        r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        area = (r.right-r.left)*(r.bottom-r.top)
        if WND is None or area > WND[1]:
            WND = (hwnd, area)
    return True

def find_window(timeout=40):
    global WND
    WND = None
    t0 = time.time()
    while time.time()-t0 < timeout:
        user32.EnumWindows(enum_cb, 0)
        if WND: return WND[0]
        time.sleep(0.5)
    return None

def print_window(hwnd, path):
    r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    w = r.right-r.left; h = r.bottom-r.top
    if w <= 0 or h <= 0: return False
    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    user32.PrintWindow(hwnd, mem_dc, 2)  # PW_RENDERFULLCONTENT
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = create_string_buffer(w*h*4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, byref(bmi), 0)
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    img.save(path)
    gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem_dc); user32.ReleaseDC(hwnd, hwnd_dc)
    return True

def img_grab(hwnd, path):
    r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    try:
        img = ImageGrab.grab((r.left, r.top, r.right, r.bottom))
        img.save(path); return True
    except Exception as e:
        print("  img_grab err", e); return False

def click_client(hwnd, cx, cy):
    box = wintypes.RECT(); user32.GetWindowRect(hwnd, byref(box))
    sx, sy = box.left+cx, box.top+cy
    user32.SetForegroundWindow(hwnd); time.sleep(0.2)
    user32.SetCursorPos(sx, sy)
    user32.mouse_event(0x0002,0,0,0,0); user32.mouse_event(0x0004,0,0,0,0)
    time.sleep(0.4)

def count_nonwhite(img,x0,y0,x1,y1,tol=18):
    px=img.load(); cnt=0
    for y in range(y0,min(img.size[1],y1)):
        for x in range(x0,min(img.size[0],x1)):
            r,g,b=px[x,y][:3]
            if not(abs(r-255)<tol and abs(g-255)<tol and abs(b-255)<tol): cnt+=1
    return cnt

def count_pink(img,x0,y0,x1,y1,tol=60):
    px=img.load(); cnt=0
    for y in range(y0,min(img.size[1],y1)):
        for x in range(x0,min(img.size[0],x1)):
            r,g,b=px[x,y][:3]
            if abs(r-212)<tol and abs(g-83)<tol and abs(b-126)<tol: cnt+=1
    return cnt

def count_darkpink(img,x0,y0,x1,y1,tol=60):
    px=img.load(); cnt=0
    for y in range(y0,min(img.size[1],y1)):
        for x in range(x0,min(img.size[0],x1)):
            r,g,b=px[x,y][:3]
            if abs(r-114)<tol and abs(g-36)<tol and abs(b-62)<tol: cnt+=1
    return cnt

def footer_text_px(img):
    # step label rects: x=54,124,194,264 width44 y=390 h18 ; bg near-white (250,248,250)
    px=img.load(); bg=(250,248,250); tot=0
    for x0 in (54,124,194,264):
        for y in range(390,408):
            for x in range(x0,x0+44):
                r,g,b=px[x,y][:3]
                if abs(r-bg[0])+abs(g-bg[1])+abs(b-bg[2])>40: tot+=1
    return tot

# launch installer
p = subprocess.Popen([EXE])
print("launched")
hwnd = find_window(40)
if not hwnd:
    print("WINDOW NOT FOUND"); p.terminate(); sys.exit(1)
print("WINDOW hwnd", hwnd)

time.sleep(1.0)
print_window(hwnd, f"{OUT}/p1.png")
# advance to P2
click_client(hwnd, 459, 399); time.sleep(0.8)
print_window(hwnd, f"{OUT}/p2.png")
# advance to P3 -> animation runs, pauses 6s at 50%
click_client(hwnd, 459, 399)
print("[P3] capturing frames during pause window...")
best = None; best_score = -1
for i in range(70):
    f = f"{OUT}/p3_{i:03d}.png"
    ok = print_window(hwnd, f)
    if ok:
        if i < 12:
            img_grab(hwnd, f"{OUT}/real_{i:03d}.png")
        img = Image.open(f)
        # title region non-white (should show "正在安装" + subtitle + status)
        title_nw = count_nonwhite(img,30,150,510,280)
        bar_pink = count_pink(img,30,246,510,254)
        # title color check: dark-pink (114,36,62) vs black (0,0,0)
        title_dp = count_darkpink(img,30,168,510,196)
        ft = footer_text_px(img)
        print(f"  frame {i}: title_nonwhite={title_nw} title_darkpink={title_dp} bar_pink={bar_pink} footer_text={ft}")
        # want a frame where title visible and bar ~half
        score = title_nw + (1 if 1500 < bar_pink < 2500 else 0)*100
        if score > best_score:
            best_score = score; best = f
    time.sleep(0.12)
print("[P3] best frame:", best, "score", best_score)
if best:
    import shutil
    shutil.copy(best, f"{OUT}/p3_mid_best.png")
    print("copied best to p3_mid_best.png")

# close
click_client(hwnd, 520, 18); time.sleep(0.5)
if not user32.IsWindowVisible(hwnd):
    print("[CLOSE] PASS")
else:
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
p.terminate()
print("=== REAL-SCREEN (ImageGrab) footer_text for first 12 frames ===")
for i in range(12):
    fn = f"{OUT}/real_{i:03d}.png"
    try:
        im = Image.open(fn).convert("RGB")
        ft = footer_text_px(im)
        print(f"  real frame {i}: footer_text={ft}  size={im.size}")
    except Exception as e:
        print(f"  real frame {i}: MISSING ({e})")
print("DONE")
