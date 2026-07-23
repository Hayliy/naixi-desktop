import subprocess, time, ctypes, sys, os
import ctypes.wintypes as wt
from PIL import Image, ImageGrab

user32 = ctypes.windll.user32
EXE = r"D:\naixi_desktop\src-tauri\test_flow.exe"
OUT = r"D:\naixi_desktop\src-tauri"
TITLE = "奶昔 · 桌面智能体 安装"
WND = None
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
user32.EnumWindows.restype = ctypes.c_bool

@EnumWindowsProc
def enum_cb(hwnd, lparam):
    global WND
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    if buf.value == TITLE and user32.IsWindowVisible(hwnd):
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
    time.sleep(0.6)

def grab(hwnd, path):
    r = wt.RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
    img = ImageGrab.grab((r.left, r.top, r.right, r.bottom))
    img.save(path); return True

# 启动安装器
p = subprocess.Popen([EXE])
hwnd = find_window(40)
if not hwnd:
    print("WINDOW NOT FOUND")
    try: p.terminate()
    except Exception: pass
    sys.exit(1)
print("WINDOW", hwnd)

# P1 -> P2
time.sleep(1.0)
grab(hwnd, f"{OUT}/p4_p1.png")
click_client(hwnd, 459, 399); time.sleep(1.5)
grab(hwnd, f"{OUT}/p4_p2.png")

# P2 -> P3 (开始动画)
click_client(hwnd, 459, 399); time.sleep(5.0)  # 等动画走完并稳定到 P3 完成态
grab(hwnd, f"{OUT}/p4_p3.png")

# P3 完成 -> P4
click_client(hwnd, 459, 399); time.sleep(1.5)
grab(hwnd, f"{OUT}/p4_p4_before.png")

# P4 完成 -> 应关闭安装器
click_client(hwnd, 459, 399)
# 修复成功后窗口会立即关闭，再截图会得到空句柄，直接检测进程退出

# 等待进程退出（修复前 Quit 卡死=进程不退出；修复后 nsDialogs::Close=进程退出）
t0 = time.time()
exited = False
while time.time()-t0 < 12:
    rc = p.poll()
    if rc is not None:
        exited = True
        print("PROCESS_EXITED rc=", rc, "after", round(time.time()-t0, 1), "s")
        break
    time.sleep(0.5)
if not exited:
    print("FAIL: 进程在点击完成后 12s 内仍未退出（完成按钮未关闭安装器）")
    try: p.terminate()
    except Exception: pass
    sys.exit(2)
print("PASS: 完成按钮已关闭安装器")
sys.exit(0)
