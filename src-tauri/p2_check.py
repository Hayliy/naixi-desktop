import subprocess, time, ctypes, sys, os
import ctypes.wintypes as wt
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
EXE = r"D:\naixi_desktop\src-tauri\test_flow.exe"
OUT = r"D:\naixi_desktop\src-tauri"
WND = None
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.EnumWindows.restype = ctypes.c_bool

@EnumWindowsProc
def enum_cb(hwnd, lparam):
    global WND
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    if buf.value == "奶昔 · 桌面智能体 安装" and user32.IsWindowVisible(hwnd):
        r = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
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

def click_client(hwnd, cx, cy):
    box = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(box))
    sx, sy = box.left+cx, box.top+cy
    user32.SetForegroundWindow(hwnd); time.sleep(0.3)
    user32.SetCursorPos(sx, sy)
    user32.mouse_event(0x0002,0,0,0,0); user32.mouse_event(0x0004,0,0,0,0)
    time.sleep(0.5)

def grab(hwnd, path):
    r = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    img = ImageGrab.grab((r.left, r.top, r.right, r.bottom))
    img.save(path); return True

def is_p2(path):
    img = Image.open(path).convert("RGB"); px = img.load()
    border = (211,193,208)
    cnt = sum(1 for y in range(205,245) for x in range(29,411) if abs(px[x,y][0]-border[0])+abs(px[x,y][1]-border[1])+abs(px[x,y][2]-border[2]) < 30)
    return cnt > 100

p = subprocess.Popen([EXE])
hwnd = find_window(40)
if not hwnd:
    print("WINDOW NOT FOUND"); p.terminate(); sys.exit(1)
print("WINDOW", hwnd)
time.sleep(1.0)
grab(hwnd, f"{OUT}/p1_check.png")
click_client(hwnd, 459, 399); time.sleep(1.0)
grab(hwnd, f"{OUT}/p2_check.png")
if not is_p2(f"{OUT}/p2_check.png"):
    print("retry clicking next to reach P2...")
    click_client(hwnd, 459, 399); time.sleep(1.0)
    grab(hwnd, f"{OUT}/p2_check.png")
img = Image.open(f"{OUT}/p2_check.png").convert("RGB"); px = img.load()
bg = (253, 248, 250)
cnt = sum(1 for y in range(212,238) for x in range(40,400) if abs(px[x,y][0]-bg[0])+abs(px[x,y][1]-bg[1])+abs(px[x,y][2]-bg[2]) > 40)
print("is_p2:", is_p2(f"{OUT}/p2_check.png"), "P2 addr-box text pixels:", cnt)
for fn in ["p2_dbg1.log", "p2_dbg2.log"]:
    fp = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")), fn)
    if os.path.exists(fp):
        print(fn, "=>", open(fp, encoding="utf-8", errors="ignore").read().strip())
p.terminate()
print("DONE")
