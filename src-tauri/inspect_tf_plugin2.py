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

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
print("HWND", hwnd)
time.sleep(2)

tmpdirs = [p for p in glob.glob(os.path.expandvars(r"%TEMP%\ns*.tmp")) if os.path.isdir(p)]
if tmpdirs:
    latest = max(tmpdirs, key=os.path.getmtime)
    print("LATEST TEMP DIR", latest)
    for f in sorted(os.listdir(latest)):
        p = os.path.join(latest, f)
        try:
            sz = os.path.getsize(p) if os.path.isfile(p) else "DIR"
            print(f"  {f} {sz}")
        except Exception as e:
            print(f"  {f} ERR {e}")
else:
    print("NO TEMP DIR")

proc.terminate()
