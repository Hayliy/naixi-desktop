"""端到端验证 v2：用今天 build 的真实安装包验证卸载/安装 GUI。
修正点：currentUser 模式下 /D 被忽略，安装固定落到 %LOCALAPPDATA%\奶昔。
流程：
  0) 备份并删除旧安装目录（确保今天的 uninstall.exe 落地）
  1) setup.exe /S 重装到默认位置
  2) 启动真实 uninstall.exe -> 截 卸载第1页(确认)
  3) 点「卸载」-> 截 第2页(进度，等跑完) -> 截 第3页(完成)，点「完成」
  4) 启动 setup.exe 非静默 -> 截 安装第1页，点关闭收尾
依赖：pywin32 + PIL（受管 Python 3.13.12 自带）
"""
import os
import sys
import time
import shutil
import subprocess
import win32gui
import win32con
import win32api
import win32ui
from PIL import Image

ROOT = r"D:\naixi_desktop"
BUNDLE = os.path.join(ROOT, r"src-tauri\target\release\bundle\nsis")
SHOT = os.path.join(ROOT, "verify_shots")
os.makedirs(SHOT, exist_ok=True)
LOCAL = os.path.expandvars(r"%LOCALAPPDATA%\奶昔")
ARCHIVE = r"D:\数据\Naixi-旧版留档\Naixi-旧版留档_20260723\奶昔_old_install_20260722"

SETUP = None
for f in os.listdir(BUNDLE):
    if f.lower().endswith("setup.exe"):
        SETUP = os.path.join(BUNDLE, f)
        break
if not SETUP or not os.path.exists(SETUP):
    print("ERROR: 找不到 setup.exe")
    sys.exit(2)
print("setup.exe =", SETUP)


def find_window(timeout=120, size_filter=True):
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
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, ax, ay, 0, 0)
    print("  点击 (%d,%d)" % (cx, cy))


# ── 0) 备份并清除旧安装 ──
print("[0] 备份旧安装")
if os.path.exists(LOCAL):
    if not os.path.exists(ARCHIVE):
        shutil.copytree(LOCAL, ARCHIVE)
        print("    已备份 ->", ARCHIVE)
    else:
        print("    备份已存在，跳过")
    shutil.rmtree(LOCAL)
    print("    已删除旧安装目录")
else:
    print("    无旧安装")

# ── 1) 静默重装今天版本（currentUser 落默认位置）──
print("[1] 静默重装今天版本 ->", LOCAL)
p = subprocess.Popen([SETUP, "/S"])
p.wait()
print("    安装退出码:", p.returncode)
uninstall_exe = os.path.join(LOCAL, "uninstall.exe")
ok = False
for _ in range(60):
    if os.path.exists(uninstall_exe):
        ok = True
        break
    time.sleep(1)
print("    uninstall.exe 存在:", ok)
if not ok:
    print("ERROR: 重装后未生成 uninstall.exe")
    sys.exit(3)

# ── 2) 启动真实卸载 GUI ──
print("[2] 启动 uninstall.exe（GUI）")
subprocess.Popen([uninstall_exe])
info = find_window(timeout=120)
if not info:
    print("ERROR: 未找到卸载窗口")
    sys.exit(4)
hwnd, title, w, h = info
print("    卸载窗口:", title, "(%dx%d)" % (w, h))
time.sleep(1.0)
screenshot(hwnd, os.path.join(SHOT, "u1_confirm.png"))

# ── 3) 点「卸载」(414,384,90x30 中心 459,399) ──
print("[3] 点击「卸载」")
click_client(hwnd, 459, 399)
time.sleep(2.0)
screenshot(hwnd, os.path.join(SHOT, "u2_progress_early.png"))
time.sleep(45)
screenshot(hwnd, os.path.join(SHOT, "u3_done.png"))
print("[4] 点击「完成」")
click_client(hwnd, 459, 399)
time.sleep(1.5)
print("    卸载窗口仍在:", win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))

# ── 5) 安装 GUI 回归（第1页）──
print("[5] 安装 GUI 回归：截图第1页")
subprocess.Popen([SETUP])
winfo = find_window(timeout=120)
if winfo:
    h2, t2, _, _ = winfo
    print("    安装窗口:", t2)
    time.sleep(1.0)
    screenshot(h2, os.path.join(SHOT, "i1_welcome.png"))
    click_client(h2, 520, 18)  # 关闭按钮
    time.sleep(0.5)

print("DONE. 截图目录:", SHOT)
