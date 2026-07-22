import time, subprocess, ctypes
from ctypes import wintypes
from PIL import ImageGrab

user32 = ctypes.windll.user32
GetWindowTextLength = user32.GetWindowTextLengthW
GetWindowText = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowRect = user32.GetWindowRect

def find_main():
    res = []
    def cb(hwnd, lp):
        if not IsWindowVisible(hwnd):
            return True
        n = GetWindowTextLength(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowText(hwnd, buf, n + 1)
        t = buf.value
        if "奶昔" in t and "安装" in t:
            res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None

def shot(hwnd, path):
    rect = ctypes.wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    img.save(path)
    print("SAVED", path)

def click(hwnd, x, y):
    rect = ctypes.wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    sx = rect.left + x
    sy = rect.top + y
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    time.sleep(0.05)

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
if not hwnd:
    print("NOT FOUND")
    proc.terminate()
    raise SystemExit(1)
user32.SetForegroundWindow(hwnd)
time.sleep(0.3)
shot(hwnd, r"D:\naixi_desktop\src-tauri\tf_page1.png")

click(hwnd, 459, 399)  # 下一步
time.sleep(1.0)
hwnd = find_main()
if hwnd:
    shot(hwnd, r"D:\naixi_desktop\src-tauri\tf_page2.png")
    click(hwnd, 459, 399)  # 安装
    time.sleep(1.0)
    hwnd = find_main()
    if hwnd:
        shot(hwnd, r"D:\naixi_desktop\src-tauri\tf_page3_start.png")
        time.sleep(2.0)
        hwnd = find_main()
        if hwnd:
            shot(hwnd, r"D:\naixi_desktop\src-tauri\tf_page3_mid.png")

proc.terminate()
