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

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
if not hwnd:
    print("NOT FOUND")
    proc.terminate()
    raise SystemExit(1)

user32.SetForegroundWindow(hwnd)
user32.BringWindowToTop(hwnd)
user32.ShowWindow(hwnd, 1)
time.sleep(0.5)

rect = ctypes.wintypes.RECT()
GetWindowRect(hwnd, ctypes.byref(rect))
print("RECT", rect.left, rect.top, rect.right, rect.bottom)
img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
path = r"D:\naixi_desktop\src-tauri\tf_grab_page1.png"
img.save(path)
print("SAVED", path, img.size)
proc.terminate()
