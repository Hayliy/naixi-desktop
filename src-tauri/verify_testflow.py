import subprocess, time, ctypes, sys
from ctypes import wintypes
from PIL import ImageGrab

EXE = r"D:\naixi_desktop\src-tauri\test_flow.exe"
OUT_DIR = r"D:\naixi_desktop\src-tauri"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WND = None
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = ctypes.c_bool

@EnumWindowsProc
def enum_cb(hwnd, lparam):
    global WND
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    t = buf.value
    # 精确匹配安装器窗口标题，避开标题含「奶昔」的浏览器等无关窗口
    if t == "奶昔 · 桌面智能体 安装" and user32.IsWindowVisible(hwnd):
        r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        area = (r.right-r.left)*(r.bottom-r.top)
        if WND is None or area > WND[1]:
            WND = (hwnd, area, (r.left,r.top,r.right,r.bottom), t)
    return True

def find_window(timeout=40):
    global WND
    WND = None
    t0 = time.time()
    while time.time()-t0 < timeout:
        user32.EnumWindows(enum_cb, 0)
        if WND: return WND
        time.sleep(1)
    return None

def rect_of(hwnd):
    r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left,r.top,r.right,r.bottom)

def shot(hwnd, name):
    box = rect_of(hwnd)
    try:
        img = ImageGrab.grab(bbox=box)
    except Exception as e:
        print(f"  [shot {name}] grab err: {e}")
        return None, box, None
    if img is None or img.size[0] < 2 or img.size[1] < 2:
        print(f"  [shot {name}] empty image size={None if img is None else img.size}")
        return None, box, None
    p = f"{OUT_DIR}\\{name}.png"
    try:
        img.save(p)
    except Exception as e:
        print(f"  [shot {name}] save err: {e}")
    return img, box, p

def click_client(hwnd, cx, cy):
    box = rect_of(hwnd); sx, sy = box[0]+cx, box[1]+cy
    user32.SetForegroundWindow(hwnd); time.sleep(0.2)
    ctypes.windll.user32.SetCursorPos(sx, sy)
    ctypes.windll.user32.mouse_event(0x0002,0,0,0,0); ctypes.windll.user32.mouse_event(0x0004,0,0,0,0)
    time.sleep(0.4)

def count_color(img,x0,y0,x1,y1,target,tol=50):
    px=img.load(); cnt=0
    for y in range(max(0,y0),min(img.size[1],y1)):
        for x in range(max(0,x0),min(img.size[0],x1)):
            r,g,b=px[x,y][:3]
            if abs(r-target[0])<tol and abs(g-target[1])<tol and abs(b-target[2])<tol: cnt+=1
    return cnt

def count_nonwhite(img,x0,y0,x1,y1,tol=18):
    px=img.load(); cnt=0
    for y in range(y0,min(img.size[1],y1)):
        for x in range(x0,min(img.size[0],x1)):
            r,g,b=px[x,y][:3]
            if not(abs(r-255)<tol and abs(g-255)<tol and abs(b-255)<tol): cnt+=1
    return cnt

p = subprocess.Popen([EXE])
print("launched, waiting...")
w = find_window(40)
if not w:
    print("WINDOW NOT FOUND"); p.terminate(); sys.exit(1)
hwnd, area, box, title = w
print("WINDOW:", title, box)

# ---------- PAGE 1 ----------
time.sleep(1.0)
img1, box1, p1 = shot(hwnd, "tf_p1")
print("[P1] banner non-white:", count_nonwhite(img1,10,10,530,145))
for idx,cx in enumerate([39,109,179,249]):
    pc = count_color(img1,cx-6,392,cx+6,404,(212,83,126),60)
    lc = count_color(img1,cx-6,392,cx+6,404,(244,192,209),60)
    print(f"[P1] step{idx+1} pink={pc} lightpink={lc}")
print(f"[P1] footer next-btn pink: {count_color(img1,414,384,504,414,(212,83,126),60)}")

# ---------- TEST MIN BUTTON (banner region 478-506,6-30) ----------
click_client(hwnd, 492, 18)   # min hotspot
time.sleep(0.6)
if user32.IsIconic(hwnd):
    print("[MIN] PASS - window minimized")
else:
    print("[MIN] FAIL - window not minimized")
user32.ShowWindow(hwnd, 9)    # SW_RESTORE
time.sleep(0.4)

# ---------- PAGE 2 ----------
click_client(hwnd, 459, 399)
time.sleep(1.0)
img2, box2, p2 = shot(hwnd, "tf_p2")
print(f"[P2] address bg #FDF8FA: {count_color(img2,30,210,410,240,(253,248,250),14)}")
print(f"[P2] browse light-pink: {count_color(img2,420,210,510,238,(244,192,209),60)}")

# ---------- PAGE 3 (time-series to see gradual fill) ----------
click_client(hwnd, 459, 399)
print("[P3] time-series fill width (px):")
series = []
for i in range(20):
    time.sleep(0.4)
    imgt, boxt, pt = shot(hwnd, f"tf_p3_t{i}")
    if imgt is None:
        print(f"  t={i*0.4+0.4:.1f}s shot failed")
        series.append(-1)
        continue
    pink = count_color(imgt, 30,246,510,254, (212,83,126), 60)
    width_px = pink // 8   # 8 行高
    series.append(width_px)
    print(f"  t={i*0.4+0.4:.1f}s width≈{width_px}px")
img3b, box3b, p3b = shot(hwnd, "tf_p3_done")
if img3b is not None:
    print(f"[P3 done] progress fill pink: {count_color(img3b,30,246,510,254,(212,83,126),60)}/3840")
    print(f"[P3 done] progress fill non-white: {count_nonwhite(img3b,30,246,510,254)}/3840")
    print(f"[P3 done] finish btn pink: {count_color(img3b,414,384,504,414,(212,83,126),60)}")
else:
    print("[P3 done] shot failed")

# ---------- PAGE 4 ----------
click_client(hwnd, 459, 399)
time.sleep(1.0)
img4, box4, p4 = shot(hwnd, "tf_p4")
if img4 is not None:
    print(f"[P4] finish btn pink: {count_color(img4,414,384,504,414,(212,83,126),60)}")
else:
    print("[P4] shot failed")

# close via banner close hotspot (506-534,6-30)
click_client(hwnd, 520, 18)
time.sleep(0.5)
if not user32.IsWindowVisible(hwnd):
    print("[CLOSE] PASS - window closed")
else:
    print("[CLOSE] (still open, force terminate)")
user32.PostMessageW(hwnd, 0x0010, 0, 0)
time.sleep(0.3)
p.terminate()
# dump diagnostic log
logp = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")), "naixi_installer_ev.log")
try:
    with open(logp, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    print("=== ev.log (last 40) ===")
    print("\n".join(lines[-40:]))
except Exception as e:
    print("ev.log read err:", e)
print("DONE")
