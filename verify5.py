"""端到端验证 v5：非静默安装 + 卸载三页，按进程路径过滤窗口，避免误抓残留安装窗口。
关键修正：
  - 安装完成页若"完成"按钮没关闭窗口，点右上角 × (520,18) 兜底。
  - find_window 增加 process_substr 过滤，安装窗口/卸载窗口用各自 exe 路径区分。
  - 安装路径仍受注册表脏值影响落 C:\naixi_test_install；卸载真实删除后再清理注册表。
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

ROOT = r"D:\naixi_desktop"
BUNDLE = os.path.join(ROOT, r"src-tauri\target\release\bundle\nsis")
SHOT = os.path.join(ROOT, "verify_shots")
os.makedirs(SHOT, exist_ok=True)
INST_DIR = r"C:\naixi_test_install"

SETUP = None
for f in os.listdir(BUNDLE):
    if f.lower().endswith("setup.exe"):
        SETUP = os.path.join(BUNDLE, f)
        break
if not SETUP or not os.path.exists(SETUP):
    print("ERROR: 找不到 setup.exe")
    sys.exit(2)
print("setup.exe =", SETUP)


def get_proc_path(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = win32api.OpenProcess(0x0410, False, pid)  # QUERY_INFO | VM_READ
        path = win32process.GetModuleFileNameEx(h, 0)
        win32api.CloseHandle(h)
        return path.lower()
    except Exception:
        return ""


def find_window(timeout=150, process_substr=None, size_filter=True):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if "奶昔" not in title:
                return
            try:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
            except Exception:
                return
            if size_filter and not (520 <= w <= 560 and 410 <= h <= 450):
                return
            path = get_proc_path(hwnd)
            if process_substr and process_substr not in path:
                return
            res.append((hwnd, title, w, h, path))

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


def close_window(hwnd):
    if not (win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)):
        return
    print("    兜底关闭窗口")
    click_client(hwnd, 520, 18)  # 右上角 ×
    time.sleep(0.5)
    if win32gui.IsWindow(hwnd):
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.5)


NX, NY = 459, 399

# ── A) 非静默安装 ──
print("[A] 启动 setup.exe（非静默安装）")
if os.path.exists(INST_DIR):
    import shutil
    shutil.rmtree(INST_DIR)
    print("    已清除旧安装目录")
subprocess.Popen([SETUP])
hinst = find_window(process_substr='setup', timeout=180)
if not hinst:
    print("ERROR: 未找到安装窗口")
    sys.exit(4)
hwin, tinst, _, _, path = hinst
print("    安装窗口:", tinst, path)
time.sleep(1.0)
screenshot(hwin, os.path.join(SHOT, "i1_welcome.png"))
print("    点 欢迎->下一步")
click_client(hwin, NX, NY)
time.sleep(1.5)
screenshot(hwin, os.path.join(SHOT, "i2_location.png"))
print("    点 位置->安装")
click_client(hwin, NX, NY)
print("    等待安装进度（约 150s）...")
time.sleep(150)
screenshot(hwin, os.path.join(SHOT, "i3_progress_or_finish.png"))
print("    点 完成")
click_client(hwin, NX, NY)
time.sleep(1.5)
close_window(hwin)

# ── B) 确认 uninstall.exe ──
print("[B] 确认 uninstall.exe")
ue = os.path.join(INST_DIR, "uninstall.exe")
ok = os.path.exists(ue)
print("    uninstall.exe 存在:", ok)
if not ok:
    print("ERROR: 安装后未生成 uninstall.exe")
    sys.exit(5)
import time as _t
print("    时间戳:", _t.strftime("%m-%d %H:%M", _t.localtime(os.path.getmtime(ue))))

# ── C) 卸载三页 ──
print("[C] 启动 uninstall.exe（GUI）")
subprocess.Popen([ue])
uinfo = find_window(process_substr='uninstall', timeout=180)
if not uinfo:
    print("ERROR: 未找到卸载窗口")
    sys.exit(6)
hwnd, title, _, _, upath = uinfo
print("    卸载窗口:", title, upath)
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
close_window(hwnd)

print("DONE. 截图目录:", SHOT)
