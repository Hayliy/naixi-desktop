import subprocess, time, ctypes, sys, base64
from ctypes import wintypes
from PIL import Image, ImageGrab

EXE = r"D:\naixi_desktop\src-tauri\test_flow.exe"
OUT = r"D:\naixi_desktop\src-tauri"

user32 = ctypes.windll.user32

WND = None
@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def enum_cb(hwnd, lp):
    global WND
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    t = buf.value
    if t == "奶昔 · 桌面智能体 安装" and user32.IsWindowVisible(hwnd):
        r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        area = (r.right-r.left)*(r.bottom-r.top)
        if WND is None or area > WND[1]:
            WND = (hwnd, area, r, t)
    return True

def find():
    global WND; WND = None; t0 = time.time()
    while time.time()-t0 < 20:
        user32.EnumWindows(enum_cb, 0)
        if WND: return WND
        time.sleep(0.5)
    return None

def shot(hwnd, name, delay=0):
    if delay: time.sleep(delay)
    r = wintypes.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    try:
        img = ImageGrab.grab(bbox=(r.left,r.top,r.right,r.bottom))
    except: return None
    if img and img.size[0] > 2:
        p = f"{OUT}\\{name}.png"; img.save(p); print(f"saved {name}")
        return img, p

p = subprocess.Popen([EXE])
w = find()
if not w: print("WINDOW NOT FOUND"); sys.exit(1)
hwnd, area, r, title = w
print("Window:", title, f"({r.left},{r.top})-({r.right},{r.bottom})")

# P1
shot(hwnd, "vc_p1", 0.5)
# click P1→P2
ctypes.windll.user32.SetCursorPos(r.left+459, r.top+399)
ctypes.windll.user32.mouse_event(0x0002,0,0,0,0); ctypes.windll.user32.mouse_event(0x0004,0,0,0,0)
shot(hwnd, "vc_p2", 0.6)
# click P2→P3
ctypes.windll.user32.SetCursorPos(r.left+459, r.top+399)
ctypes.windll.user32.mouse_event(0x0002,0,0,0,0); ctypes.windll.user32.mouse_event(0x0004,0,0,0,0)
# capture P3 at 1s intervals to see what user actually sees
for i in range(6):
    shot(hwnd, f"vc_p3_t{i}", 0.7)
# close
user32.PostMessageW(hwnd, 0x0010, 0, 0)
time.sleep(0.3)
p.terminate()
print("DONE")
