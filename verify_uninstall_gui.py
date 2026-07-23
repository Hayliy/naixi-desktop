"""端到端验证：真实安装包的安装/卸载 GUI 视觉走查。
依赖：pywin32 + PIL（受管 Python 3.13.12 已自带）。
用法：python verify_uninstall_gui.py
流程：
  1) 静默安装 setup.exe 到临时目录（跳过安装 GUI，仅生成 uninstall.exe）
  2) 启动真实 uninstall.exe（非静默）-> 截图 卸载第1页（确认）
  3) 点击「卸载」按钮 -> 截图 第2页（进度，等进度条跑完）
  4) 进度完成后截图 第3页（完成），点击「完成」收尾
  5) 截图一次安装第1页做回归（确认安装 GUI 未被改动破坏）
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

ROOT = r"D:\naixi_desktop"
BUNDLE_DIR = os.path.join(ROOT, r"src-tauri\target\release\bundle\nsis")
SHOT_DIR = os.path.join(ROOT, "verify_shots")
os.makedirs(SHOT_DIR, exist_ok=True)

INSTALL_DIR = r"C:\tmp\naixi_verify"
SETUP = None
for f in os.listdir(BUNDLE_DIR):
    if f.lower().endswith("setup.exe"):
        SETUP = os.path.join(BUNDLE_DIR, f)
        break
if not SETUP or not os.path.exists(SETUP):
    print("ERROR: 找不到 setup.exe，构建可能未成功")
    sys.exit(2)
print("setup.exe =", SETUP)


def find_window(timeout=120, size_filter=True):
    """查找标题含「奶昔」且尺寸约 540x430 的可见对话框窗口。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "奶昔" in title:
                try:
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                    w, h = right - left, bottom - top
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
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    try:
        hwndc = win32gui.GetWindowDC(hwnd)
        dc = win32ui.CreateDCFromHandle(hwndc)
        memdc = dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(dc, w, h)
        memdc.SelectObject(bmp)
        memdc.BitBlt((0, 0), (w, h), dc, (0, 0), win32con.SRCCOPY)
        bmpinfo = bmp.GetInfo()
        bmpstr = bmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr, "raw", "BGRX", 0, 1)
        img.save(path)
        dc.DeleteDC()
        memdc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndc)
    except Exception as e:
        print("  screenshot failed:", e)
        return False
    print("  shot ->", path)
    return True


def click_client(hwnd, cx, cy):
    left, top, _, _ = win32gui.GetWindowRect(hwnd)
    abs_x = left + cx
    abs_y = top + cy
    win32api.SetCursorPos((abs_x, abs_y))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, abs_x, abs_y, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, abs_x, abs_y, 0, 0)
    print("  点击客户区 (%d,%d) -> 屏幕 (%d,%d)" % (cx, cy, abs_x, abs_y))


def wait_until_done(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
    print("  进度等待完成")


# ── 1) 静默安装 ──
print("[1] 静默安装到", INSTALL_DIR)
if os.path.exists(INSTALL_DIR):
    subprocess.run(["cmd", "/c", "rmdir /s /q " + INSTALL_DIR], shell=True)
os.makedirs(INSTALL_DIR, exist_ok=True)
p = subprocess.Popen([SETUP, "/S", "/D=" + INSTALL_DIR])
p.wait()
print("    安装进程退出码:", p.returncode)
uninstall_exe = os.path.join(INSTALL_DIR, "uninstall.exe")
print("    uninstall.exe 存在:", os.path.exists(uninstall_exe))

# ── 2) 启动真实卸载 GUI ──
print("[2] 启动 uninstall.exe（GUI）")
if not os.path.exists(uninstall_exe):
    print("ERROR: 卸载程序缺失")
    sys.exit(3)
subprocess.Popen([uninstall_exe])
info = find_window(timeout=120, size_filter=True)
if not info:
    print("ERROR: 未找到卸载窗口")
    sys.exit(4)
hwnd, title, w, h = info
print("    卸载窗口:", title, "(%dx%d)" % (w, h))
time.sleep(1.0)
screenshot(hwnd, os.path.join(SHOT_DIR, "u1_confirm.png"))

# ── 3) 点击「卸载」按钮（414,384 尺寸 90x30，中心约 459,399）──
print("[3] 点击「卸载」按钮")
click_client(hwnd, 459, 399)
time.sleep(2.0)
screenshot(hwnd, os.path.join(SHOT_DIR, "u2_progress_early.png"))
wait_until_done(timeout=45)
time.sleep(1.0)
screenshot(hwnd, os.path.join(SHOT_DIR, "u3_done.png"))

# ── 4) 点击「完成」按钮 ──
print("[4] 点击「完成」按钮")
click_client(hwnd, 459, 399)
time.sleep(1.5)
print("    卸载窗口是否仍在:", win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))

# ── 5) 安装 GUI 回归截图（第1页）──
print("[5] 安装 GUI 回归：截图第1页")
INSTALL_DIR2 = r"C:\tmp\naixi_verify2"
if os.path.exists(INSTALL_DIR2):
    subprocess.run(["cmd", "/c", "rmdir /s /q " + INSTALL_DIR2], shell=True)
os.makedirs(INSTALL_DIR2, exist_ok=True)
subprocess.Popen([SETUP, "/D=" + INSTALL_DIR2])
winfo = find_window(timeout=120, size_filter=True)
if winfo:
    h2, t2, _, _ = winfo
    print("    安装窗口:", t2)
    time.sleep(1.0)
    screenshot(h2, os.path.join(SHOT_DIR, "i1_welcome.png"))
    click_client(h2, 520, 21)
    time.sleep(0.5)

print("DONE. 截图目录:", SHOT_DIR)
