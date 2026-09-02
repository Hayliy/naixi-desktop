import os, time, subprocess, ctypes, glob
from ctypes import wintypes

user32 = ctypes.windll.user32
GetWindowTextLength = user32.GetWindowTextLengthW
GetWindowText = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

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
            rect = ctypes.wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w == 540 and h == 430:
                res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None

exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target", "release", "bundle", "nsis", "奶昔_0.1.0_x64-setup.exe")
proc = subprocess.Popen([exe])
print("LAUNCH", exe)

hwnd = None
for i in range(120):
    time.sleep(1)
    hwnd = find_main()
    if hwnd:
        break
    print("waiting", i)

if not hwnd:
    print("WINDOW NOT FOUND")
    proc.terminate()
    raise SystemExit(1)

print("WINDOW OK, sleep 10s for file extraction...")
time.sleep(10)

# 用 cmd dir 列出所有 ns*.tmp 目录
os.system(r'cmd /c "for /d %d in (%TEMP%\ns*.tmp) do @echo DIR %d && dir /b /s \"%d\" | findstr \"\.bmp\""')

proc.terminate()
