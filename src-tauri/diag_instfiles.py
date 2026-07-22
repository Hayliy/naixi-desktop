import time, subprocess, ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowText = user32.GetWindowTextW
GetWindowTextLength = user32.GetWindowTextLengthW
GetWindowLongW = user32.GetWindowLongW
IsWindowVisible = user32.IsWindowVisible
SendMessage = user32.SendMessageW
BM_CLICK = 0x00F5
GWL_ID = -12
GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
GetWindowLongW.restype = wintypes.LONG

def get_text(hwnd):
    n = GetWindowTextLength(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowText(hwnd, buf, n + 1)
    return buf.value

def get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
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

def click_text(hwnd, label):
    out = []
    def cb(child, lp):
        if IsWindowVisible(child) and get_text(child).strip() == label:
            SendMessage(child, BM_CLICK, 0, 0)
            out.append(child)
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return bool(out)

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
click_text(hwnd, "安装 >>")   # 欢迎 -> 位置
time.sleep(1.5)
hwnd = find_main()
click_text(hwnd, "安装 >>")   # 位置 -> 进度
time.sleep(2.0)
hwnd = find_main()

print("=== 安装进度页所有子控件（含隐藏）===")
def dump(child, lp):
    t = get_text(child).strip()
    cid = GetWindowLongW(child, GWL_ID)
    cls = get_class(child)
    vis = IsWindowVisible(child)
    if t or cls in ("Button", "Static", "Edit", "SysListView32", "msctls_progress32"):
        print(f"  id={cid:>5} vis={vis} class={cls:<16} text={t!r}")
    return True
EnumChildWindows(hwnd, EnumChildProc(dump), 0)

nxt = user32.GetDlgItem(hwnd, 1)
print("GetDlgItem(hwnd,1) =", nxt, "可见=", IsWindowVisible(nxt) if nxt else "N/A", "文本=", repr(get_text(nxt)) if nxt else "")

proc.terminate()
