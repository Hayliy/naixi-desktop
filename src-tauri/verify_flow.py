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
SendMessage = user32.SendMessageW
PostMessage = user32.PostMessageW
GetDlgItem = user32.GetDlgItem
BM_CLICK = 0x00F5
GetDlgItem.argtypes = (wintypes.HWND, ctypes.c_int)
GetDlgItem.restype = wintypes.HWND

def get_text(hwnd):
    n = GetWindowTextLength(hwnd)
    if n <= 0:
        return ""
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

def enum_children(hwnd):
    out = []
    def cb(child, lp):
        if IsWindowVisible(child):
            t = get_text(child).strip()
            if t:
                out.append((child, t))
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out

def short_texts(hwnd):
    return sorted(set(t for h, t in enum_children(hwnd) if len(t) < 40))

def click_button(hwnd, label):
    for h, t in enum_children(hwnd):
        if t == label:
            SendMessage(h, BM_CLICK, 0, 0)
            return True
    return False

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
hwnd = find_main()
if not hwnd:
    print("[失败] 未找到 NSIS 安装窗口")
    proc.terminate()
    raise SystemExit(1)
print("[页1 欢迎] 文本:", short_texts(hwnd))

ok = True
if click_button(hwnd, "安装 >>"):
    time.sleep(1.5)
    hwnd = find_main()
    print("[页2 位置] 文本:", short_texts(hwnd))
else:
    print("[失败] 未找到欢迎页「安装 >>」")
    ok = False

if ok and click_button(hwnd, "安装 >>"):
    time.sleep(1.5)
    hwnd = find_main()
    print("[页3 进度] 文本:", short_texts(hwnd))
else:
    print("[失败] 未找到位置页「安装 >>」或翻页失败")
    ok = False

if ok:
    # 安装进度页：等待“下一步”按钮出现并可见，点击它进入完成页
    # 用 PostMessage（异步）避免脚本阻塞在模态对话框里
    advanced = False
    for _ in range(20):
        hwnd = find_main()
        nxt = GetDlgItem(hwnd, 1)
        if nxt and IsWindowVisible(nxt):
            PostMessage(nxt, BM_CLICK, 0, 0)
            advanced = True
            break
        time.sleep(0.5)
    time.sleep(1.5)
    hwnd = find_main()
    print("[页4 完成] 文本:", short_texts(hwnd) if hwnd else "(窗口已关闭)")

if ok and hwnd:
    if click_button(hwnd, "完成"):
        time.sleep(3.0)
        print("[退出] 进程状态:", "已退出" if proc.poll() is not None else "仍在运行")
    else:
        print("[失败] 未找到完成页「完成」")

print("RESULT:", "PASS" if ok and proc.poll() is not None else "CHECK")
if proc.poll() is None:
    proc.terminate()
