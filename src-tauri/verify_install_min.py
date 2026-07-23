# 奶昔安装器最简端到端验证脚本（不点浏览，避免对话框干扰）
# 用法: python verify_install_min.py [setup.exe 路径]
# 流程：欢迎 -> 位置 -> 安装（自动开始）-> 完成，每页截图，不运行应用。
import time, subprocess, ctypes, os, sys
from ctypes import wintypes
from PIL import ImageGrab

user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetWindowText = user32.GetWindowTextW
GetWindowTextLength = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
SetForegroundWindow = user32.SetForegroundWindow

NEXT_C = (459, 399)   # 主按钮（下一步/安装/完成）中心
RUNCHK_C = (45, 259)  # 立即运行复选框中心


def get_text(hwnd):
    n = GetWindowTextLength(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowText(hwnd, buf, n + 1)
    return buf.value


def get_size(hwnd):
    r = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    return (r.right - r.left, r.bottom - r.top)


def find_main():
    res = []
    def cb(h, lp):
        if "奶昔" in get_text(h) and IsWindowVisible(h):
            w, h = get_size(h)
            if 500 <= w <= 600 and 400 <= h <= 470:
                res.append(h)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None


def enum_children(hwnd):
    out = []
    def cb(c, lp):
        if IsWindowVisible(c):
            t = get_text(c).strip()
            if t:
                out.append(t)
            EnumChildWindows(c, EnumChildProc(cb), 0)
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def click_at(hwnd, cx, cy):
    SetForegroundWindow(hwnd)
    time.sleep(0.15)
    hr = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(hr))
    user32.SetCursorPos(hr.left + cx, hr.top + cy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    return True


def wait_text(hwnd, labels, timeout=20):
    labels = labels if isinstance(labels, (list, tuple)) else [labels]
    start = time.time()
    while time.time() - start < timeout:
        for t in enum_children(hwnd):
            if any(l in t for l in labels):
                return True
        time.sleep(0.2)
    return False


def screenshot(hwnd, path):
    cr = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    pt = wintypes.POINT(cr.left, cr.top)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    SetForegroundWindow(hwnd)
    time.sleep(0.3)
    img = ImageGrab.grab((pt.x, pt.y, pt.x + cr.right, pt.y + cr.bottom))
    img.save(path)
    print("  SAVED", path, img.size)
    return img


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else r"D:\naixi_desktop\src-tauri\target\release\bundle\nsis\奶昔_0.1.0_x64-setup.exe"
    outdir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(exe):
        print("SETUP_NOT_FOUND", exe)
        return

    proc = subprocess.Popen([exe])
    print("LAUNCH", exe)

    # 等主窗口（最长 120 秒）
    hwnd = None
    for i in range(240):
        hwnd = find_main()
        if hwnd:
            break
        if i % 10 == 0:
            print(f"  等待主窗口... {i*0.5:.0f}s")
        time.sleep(0.5)
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        proc.terminate()
        return
    print("WINDOW_OK")

    # P1 欢迎
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "m_page1.png"))
    print("P1:", [t for t in enum_children(hwnd) if t][:8])
    click_at(hwnd, *NEXT_C)

    # P2 位置
    if not wait_text(hwnd, "选择安装位置", 15):
        print("FAIL: 未到位置页")
        return
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "m_page2.png"))
    print("P2:", [t for t in enum_children(hwnd) if t][:8])
    # 直接点安装按钮
    click_at(hwnd, *NEXT_C)

    # P3 进度：等「正在安装」出现
    if not wait_text(hwnd, "正在安装", 15):
        print("FAIL: 未到安装进度页")
        return
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "m_page3_a.png"))
    print("P3a:", [t for t in enum_children(hwnd) if any(k in t for k in ["准备", "写入", "创建", "注册", "安装"])][:6])

    # 等进度推进
    time.sleep(3.0)
    screenshot(hwnd, os.path.join(outdir, "m_page3_b.png"))

    # 等安装完成（「安装完成。」或「完成」页）
    if not wait_text(hwnd, "安装完成。", 120):
        print("FAIL: 安装未完成")
        return
    hwnd = find_main()
    time.sleep(0.3)
    screenshot(hwnd, os.path.join(outdir, "m_page3_c.png"))
    print("P3c done")
    click_at(hwnd, *NEXT_C)

    # P4 完成
    if not wait_text(hwnd, "立即运行奶昔", 15):
        print("FAIL: 未到完成页")
        return
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "m_page4.png"))
    print("P4:", [t for t in enum_children(hwnd) if t][:8])

    # 取消「立即运行」，点完成
    click_at(hwnd, *RUNCHK_C)
    time.sleep(0.2)
    click_at(hwnd, *NEXT_C)
    time.sleep(1.5)
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
    print("INSTALL_GUI_DONE")


if __name__ == "__main__":
    main()
