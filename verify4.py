"""端到端验证 v4：直接从实际安装路径 C:\naixi_test_install 启动 uninstall.exe，验证卸载三页 GUI。
用途：前序非静默安装因注册表脏 InstallLocation 落到了 C:\naixi_test_install；用该路径验证今天 uninstall.exe 的三页 GUI。
"""
import os
import sys
import time
import subprocess
import win32gui
import win32con
import win32api
import win32ui
from PIL import Image

SHOT = r"D:\naixi_desktop\verify_shots"
os.makedirs(SHOT, exist_ok=True)
INST_DIR = r"C:\naixi_test_install"
UE = os.path.join(INST_DIR, "uninstall.exe")

if not os.path.exists(UE):
    print("ERROR: 找不到 uninstall.exe:", UE)
    sys.exit(5)
print("uninstall.exe =", UE)


def find_window(timeout=150, size_filter=True):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "奶昔" in title:
                try:
                    l, t, r, b = win32gui.GetWindowRect(hwnd)
                    w, h = r - l, b - t
                except Exception:
                    return
                if (not size_filter) or (520 <= w <= 560 and 410 <= h <= 450):
                    res.append((hwnd, title, w, h))

        win32gui.EnumWindows(cb, None)
        if res:
            res.sort(key=lambda r: r[2] * r[3], reverse=True)
            return res[0]
        time.sleep(0.5)
    return None


def screenshot(hwnd, path):
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    try:
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
        print("  shot ->", path)
        return True
    except Exception as e:
        print("  screenshot failed:", e)
        return False


def click_client(hwnd, cx, cy):
    l, t, _, _ = win32gui.GetWindowRect(hwnd)
    ax, ay = l + cx, t + cy
    win32api.SetCursorPos((ax, ay))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, ax, ay, 0, 0)
    time.sleep(0.08)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, ax, ay, 0, 0)
    print("  点击 (%d,%d)" % (cx, cy))


NX, NY = 459, 399

print("[1] 启动 uninstall.exe（GUI）")
subprocess.Popen([UE])
uinfo = find_window(timeout=150)
if not uinfo:
    print("ERROR: 未找到卸载窗口")
    sys.exit(6)
hwnd, title, _, _ = uinfo
print("    卸载窗口:", title)
time.sleep(1.0)
screenshot(hwnd, os.path.join(SHOT, "u1_confirm.png"))
print("    点 确认->卸载")
click_client(hwnd, NX, NY)
time.sleep(2.0)
screenshot(hwnd, os.path.join(SHOT, "u2_progress_early.png"))
print("    等待卸载进度（约 45s）")
time.sleep(45)
screenshot(hwnd, os.path.join(SHOT, "u3_done.png"))
print("    点 完成")
click_client(hwnd, NX, NY)
time.sleep(1.5)
print("    卸载窗口仍在:", win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))
print("DONE. 截图目录:", SHOT)
