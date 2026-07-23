"""非静默安装自动化：跑真实 GUI 安装，产出带 DEBUG 弹窗的 uninstall.exe。
安装段 Section 为空，文件写入只在进度页 timer 里触发，所以 /S 静默是空操作，
必须走 GUI。脚本按进程路径 setup.exe 过滤窗口，先点 5 次主按钮 (414,384)
翻过欢迎+位置页，再纯等进度页 timer 写出 uninstall.exe；检测到新写入的
uninstall.exe 后关窗（不启动 app，避免占端口）。

关键：旧目录 C:\naixi_test_install 残留 14:12 的旧 uninstall.exe，必须用
"mtime >= 脚本启动时刻" 过滤，只认本次新写入的文件，否则会误判已装好。
"""
import os
import sys
import time
import subprocess
import win32gui
import win32con
import win32api
import win32process
import win32ui
from PIL import Image

SETUP = r"D:\naixi_desktop\src-tauri\target\release\bundle\nsis\奶昔_0.1.0_x64-setup.exe"
LOCAL = os.path.expandvars(r"%LOCALAPPDATA%\奶昔")
CAND = [LOCAL, r"C:\naixi_test_install"]
SHOT = r"D:\naixi_desktop\verify_shots"
os.makedirs(SHOT, exist_ok=True)
START = time.time()


def get_proc_path(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = win32api.OpenProcess(0x0410, False, pid)
        p = win32process.GetModuleFileNameEx(h, 0)
        win32api.CloseHandle(h)
        return p.lower()
    except Exception:
        return ""


def find_setup(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "奶昔" not in title or "安装" not in title:
                return
            try:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
            except Exception:
                return
            if not (500 <= w <= 560 and 400 <= h <= 450):
                return
            p = get_proc_path(hwnd)
            if "setup.exe" not in p:
                return
            res.append((hwnd, title, w, h, p))

        win32gui.EnumWindows(cb, None)
        if res:
            res.sort(key=lambda r: r[2] * r[3], reverse=True)
            return res[0]
        time.sleep(0.5)
    return None


def screenshot(hwnd, path):
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        w, h = r - l, b - t
        hd = win32gui.GetWindowDC(hwnd)
        dc = win32ui.CreateDCFromHandle(hd)
        mem = dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(dc, w, h)
        mem.SelectObject(bmp)
        mem.BitBlt((0, 0), (w, h), dc, (0, 0), win32con.SRCCOPY)
        info = bmp.GetInfo()
        s = bmp.GetBitmapBits(True)
        img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), s, "raw", "BGRX", 0, 1)
        img.save(path)
        dc.DeleteDC(); mem.DeleteDC(); win32gui.ReleaseDC(hwnd, hd)
        print("  shot ->", path, flush=True)
    except Exception as e:
        print("  screenshot failed:", e, flush=True)


def click_client(hwnd, cx, cy):
    l, t, _, _ = win32gui.GetWindowRect(hwnd)
    ax, ay = l + cx, t + cy
    win32api.SetCursorPos((ax, ay))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, ax, ay, 0, 0)
    time.sleep(0.08)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, ax, ay, 0, 0)
    print("  点主按钮 (%d,%d)" % (cx, cy), flush=True)


def uninstall_exists():
    best = None
    for c in CAND:
        ue = os.path.join(c, "uninstall.exe")
        if os.path.exists(ue):
            mt = os.path.getmtime(ue)
            if mt >= START and (best is None or mt > best[1]):
                best = (c, mt)
    return best[0] if best else None


print("[1] 启动 setup.exe (非静默)", flush=True)
subprocess.Popen([SETUP])

print("[2] 等待安装窗口", flush=True)
info = find_setup(timeout=180)
if not info:
    print("ERROR: 未找到安装窗口", flush=True)
    sys.exit(2)
hwnd, title, _, _, _ = info
print("    安装窗口:", title, flush=True)

print("[3] 先点 5 次主按钮翻过 欢迎+位置 页", flush=True)
for i in range(5):
    if uninstall_exists():
        print("    (意外：此时已出现 uninstall.exe)", flush=True)
        break
    click_client(hwnd, 414, 384)
    time.sleep(3)
    if i % 2 == 0:
        screenshot(hwnd, os.path.join(SHOT, "install_step_%02d.png" % i))

print("[4] 纯等进度页 timer 写出 uninstall.exe (最多 150s)", flush=True)
landed = None
deadline = time.time() + 150
while time.time() < deadline:
    d = uninstall_exists()
    if d:
        landed = d
        print("    uninstall.exe 出现于:", d, flush=True)
        break
    time.sleep(3)

if not landed:
    screenshot(hwnd, os.path.join(SHOT, "install_stuck.png"))
    print("ERROR: 进度页 150s 内未写出 uninstall.exe", flush=True)
    sys.exit(3)

print("[5] 关闭安装窗口（不启动 app）", flush=True)
win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
time.sleep(2)

ue = os.path.join(landed, "uninstall.exe")
print("INSTALL_DONE path=%s size=%d mtime=%s" % (
    ue, os.path.getsize(ue),
    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(ue)))))
print("INSTALL_DIR=%s" % landed)
