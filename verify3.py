"""端到端验证 v3：非静默安装（脚本点击 4 页）落地今天版本 + 卸载三页截图。
修正点：currentUser 模式 /S 静默安装空退出，改用非静默交互安装。
按钮坐标统一：footer 主按钮 414,384,90x30 -> 中心 (459,399)
流程：
  A) 启动 setup.exe 非静默：欢迎(下一步)->位置(安装)->进度(等)->完成(完成)
  B) 确认默认位置今天 uninstall.exe 落地
  C) 启动 uninstall.exe：确认(卸载)->进度(等)->完成(完成)，三页截图
  D) 视觉读图交叉验证
依赖：pywin32 + PIL（受管 Python 3.13.12 自带）
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
BUNDLE = os.path.join(ROOT, r"src-tauri\target\release\bundle\nsis")
SHOT = os.path.join(ROOT, "verify_shots")
os.makedirs(SHOT, exist_ok=True)
LOCAL = os.path.expandvars(r"%LOCALAPPDATA%\奶昔")
SETUP = None
for f in os.listdir(BUNDLE):
    if f.lower().endswith("setup.exe"):
        SETUP = os.path.join(BUNDLE, f)
        break
if not SETUP or not os.path.exists(SETUP):
    print("ERROR: 找不到 setup.exe")
    sys.exit(2)
print("setup.exe =", SETUP)


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


NX = 459
NY = 399

# ── A) 非静默安装 ──
print("[A] 启动 setup.exe（非静默安装）")
if os.path.exists(LOCAL):
    import shutil
    shutil.rmtree(LOCAL)
    print("    已清除旧默认位置")
subprocess.Popen([SETUP])
winfo = find_window(timeout=150)
if not winfo:
    print("ERROR: 未找到安装窗口")
    sys.exit(4)
hinst, tinst, _, _ = winfo
print("    安装窗口:", tinst)
time.sleep(1.0)
screenshot(hinst, os.path.join(SHOT, "i1_welcome.png"))
print("    点 欢迎->下一步")
click_client(hinst, NX, NY)
time.sleep(1.5)
screenshot(hinst, os.path.join(SHOT, "i2_location.png"))
print("    点 位置->安装")
click_client(hinst, NX, NY)
print("    等待安装进度（约 150s）...")
time.sleep(150)
screenshot(hinst, os.path.join(SHOT, "i3_progress_or_finish.png"))
print("    点 完成")
click_client(hinst, NX, NY)
time.sleep(2.0)
print("    安装窗口仍在:", win32gui.IsWindow(hinst) and win32gui.IsWindowVisible(hinst))

# ── B) 确认今天 uninstall.exe 落地 ──
print("[B] 确认默认位置今天 uninstall.exe")
ue = os.path.join(LOCAL, "uninstall.exe")
ok = os.path.exists(ue)
print("    uninstall.exe 存在:", ok)
if not ok:
    print("ERROR: 安装后仍未生成 uninstall.exe")
    sys.exit(5)
import time as _t
m = _t.strftime("%m-%d %H:%M", _t.localtime(os.path.getmtime(ue)))
print("    uninstall.exe 时间戳:", m)

# ── C) 卸载三页 ──
print("[C] 启动 uninstall.exe（GUI）")
subprocess.Popen([ue])
uinfo = find_window(timeout=120)
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
