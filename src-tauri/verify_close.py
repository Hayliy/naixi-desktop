import time, subprocess, ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowText = user32.GetWindowTextW
GetWindowTextLength = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
PostMessage = user32.PostMessageW
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

def get_text(hwnd):
    n = GetWindowTextLength(hwnd)
    if n <= 0: return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowText(hwnd, buf, n + 1)
    return buf.value

def find_main():
    res = []
    def cb(hwnd, lp):
        t = get_text(hwnd)
        if "奶昔" in t and "安装" in t:
            res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None

def find_close(hwnd):
    out = []
    def cb(child, lp):
        if IsWindowVisible(child) and get_text(child).strip() == "×":
            out.append(child)
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out[0] if out else None

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
if not hwnd:
    print("[失败] 未找到窗口"); proc.terminate(); raise SystemExit(1)
x = find_close(hwnd)
if not x:
    print("[失败] 未找到关闭按钮 ×"); proc.terminate(); raise SystemExit(1)
print("[OK] 找到关闭按钮 ×，模拟点击...")
# 模拟鼠标按下+抬起，触发 STN_CLICKED
PostMessage(x, WM_LBUTTONDOWN, 0, 0)
time.sleep(0.1)
PostMessage(x, WM_LBUTTONUP, 0, 0)
time.sleep(1.5)
alive = proc.poll() is None
print("[结果] 点击 × 后窗口:", "已关闭" if not alive else "仍在运行（关闭失败）")
print("RESULT:", "PASS" if not alive else "FAIL")
if alive:
    proc.terminate()
