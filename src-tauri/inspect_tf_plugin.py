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
            res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None

proc = subprocess.Popen([os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_flow.exe")])
print("LAUNCH test_flow.exe")
time.sleep(2)
hwnd = find_main()
print("HWND", hwnd)
time.sleep(1)

# 列出所有 ns*.tmp 目录中的 bmp
os.system(r'cmd /c "for /d %d in (%TEMP%\ns*.tmp) do @echo DIR %d && dir /b \"%d\""')

proc.terminate()
