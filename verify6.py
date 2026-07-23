"""端到端验证 v6：测试 DEBUG MessageBox + 卸载三页截图。
预期行为：运行 uninstall.exe 后会先弹标题为 "DEBUG: un.Done called" 的消息框；脚本自动点 OK，然后按进程路径找真正的卸载窗口（Temp\\~nsu*.tmp\\un.exe）。
"""
import os
import sys
import time
import subprocess
import win32gui
import win32con
import win32api
import win32ui
import win32process
from PIL import Image

SHOT = r"D:\naixi_desktop\verify_shots"
os.makedirs(SHOT, exist_ok=True)
INST_DIR = r"C:\naixi_test_install"
UE = os.path.join(INST_DIR, "uninstall.exe")


def click_debug_ok():
    """查找 DEBUG 弹窗并点 OK。"""
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if "DEBUG: un.Done called" in t:
                # OK 按钮通常是窗口第一个默认按钮，点中心
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                cx, cy = (l + r) // 2, (b + t) // 2 + 20
                win32api.SetCursorPos((cx, cy))
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, cx, cy, 0, 0)
                time.sleep(0.05)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)
                print("  点击 DEBUG OK")
    win32gui.EnumWindows(cb, None)


def get_proc_path(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = win32api.OpenProcess(0x0410, False, pid)
        path = win32process.GetModuleFileNameEx(h, 0)
        win32api.CloseHandle(h)
        return path.lower()
    except Exception:
        return ""


def find_uninstall_window(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "奶昔" not in title or "卸载" not in title:
                return
            try:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
            except Exception:
                return
            if not (500 <= w <= 560 and 400 <= h <= 450):
                return
            path = get_proc_path(hwnd)
            if "un.exe" not in path and "uninstall" not in path:
                return
            res.append((hwnd, title, w, h, path))

        win32gui.EnumWindows(cb, None)
        if res:
            res.sort(key=lambda r: r[2] * r[3], reverse=True)
            return res[0]
        # 顺便点 DEBUG OK
        click_debug_ok()
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


if not os.path.exists(UE):
    print("ERROR: 找不到 uninstall.exe")
    sys.exit(5)

print("[1] 启动 uninstall.exe")
subprocess.Popen([UE])
print("[2] 等待 DEBUG 弹窗并自动点 OK / 查找卸载窗口")
uinfo = find_uninstall_window(timeout=120)
if not uinfo:
    print("ERROR: 未找到卸载窗口")
    sys.exit(6)
hwnd, title, _, _, upath = uinfo
print("    卸载窗口:", title, upath)
time.sleep(1.0)
screenshot(hwnd, os.path.join(SHOT, "u1_confirm.png"))
print("    点 确认->卸载")
click_client(hwnd, 459, 399)
time.sleep(2.0)
screenshot(hwnd, os.path.join(SHOT, "u2_progress_early.png"))
print("    等待卸载进度（约 45s）")
time.sleep(45)
screenshot(hwnd, os.path.join(SHOT, "u3_done.png"))
print("DONE.")
