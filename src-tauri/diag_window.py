import time, subprocess, ctypes
from ctypes import wintypes
user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowText = user32.GetWindowTextW
GetWindowTextLength = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
GetClassName = user32.GetClassNameW

def get_text(h):
    n = GetWindowTextLength(h)
    if n <= 0: return ""
    b = ctypes.create_unicode_buffer(n + 1)
    GetWindowText(h, b, n + 1)
    return b.value

def get_class(h):
    b = ctypes.create_unicode_buffer(256)
    GetClassName(h, b, 256)
    return b.value

def get_size(h):
    r = wintypes.RECT()
    GetWindowRect(h, ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top)

exe = r"D:\naixi_desktop\src-tauri\target\release/bundle/nsis/奶昔_0.1.0_x64-setup.exe"
proc = subprocess.Popen([exe])
found = None
for i in range(45):  # 最多 90 秒
    time.sleep(2)
    wins = []
    def cb(h, lp):
        if IsWindowVisible(h):
            t = get_text(h); c = get_class(h); w, hh = get_size(h)
            wins.append((t, c, (w, hh)))
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    # 检测自定义安装窗口：宽 500-600 且高 400-470
    for t, c, (w, hh) in wins:
        if 500 <= w <= 600 and 400 <= hh <= 470:
            found = (t, c, (w, hh))
            print(f"[{i*2}s] 找到自定义窗口 title={t!r} class={c!r} size=({w},{hh})")
            break
    if found:
        break
    # 否则报告当前解压进度
    prog = [ (t,(w,hh)) for t,c,(w,hh) in wins if "unpacking" in t.lower() or "奶昔" in t ]
    print(f"[{i*2}s] 尚未出现自定义窗口; 相关窗口: {prog}")
proc.terminate()
print("RESULT:", found)
