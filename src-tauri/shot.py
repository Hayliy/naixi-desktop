# 用 Pillow + ctypes 截图 NSIS 窗口（不依赖 Add-Type / 大环境块）
import ctypes, ctypes.wintypes, subprocess, time, sys
from PIL import ImageGrab

EXE = sys.argv[1] if len(sys.argv) > 1 else r"D:\naixi_desktop\src-tauri\test_flow.exe"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"D:\naixi_desktop\src-tauri\shot_test_welcome.png"

# 启动
subprocess.Popen([EXE])
time.sleep(4)

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
target = [0]
def cb(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    t = buf.value
    if "奶昔" in t:
        target[0] = hwnd
        return False
    return True
user32.EnumWindows(EnumWindowsProc(cb), 0)

if not target[0]:
    # 回退：取第一个可见且标题非空的 #32770
    def cb2(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if len(buf.value) > 0:
            target[0] = hwnd
            return False
        return True
    user32.EnumWindows(EnumWindowsProc(cb2), 0)

if not target[0]:
    print("WINDOW_NOT_FOUND")
    sys.exit(1)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(target[0], ctypes.byref(rect))
user32.SetForegroundWindow(target[0])
time.sleep(0.4)
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
img.save(OUT)
print("SAVED", OUT, img.size, "RECT", rect.left, rect.top, rect.right, rect.bottom)
