import time, subprocess, ctypes, sys
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
ScreenToClient = user32.ScreenToClient
ChildWindowFromPointEx = user32.ChildWindowFromPointEx

# 按钮在客户区中的大致中心（与 NSIS 宏定义一致）
NEXT_BTN_CENTER = (414 + 45, 384 + 15)   # 下一步/安装/完成
PREV_BTN_CENTER = (320 + 45, 384 + 15)   # 上一步


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
    def cb(hwnd, lp):
        t = get_text(hwnd)
        if "奶昔" in t and IsWindowVisible(hwnd):
            w, h = get_size(hwnd)
            if 500 <= w <= 600 and 400 <= h <= 470:
                res.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(cb), 0)
    return res[0] if res else None


def enum_children(hwnd):
    """递归枚举所有可见子控件及其文本。"""
    out = []
    def cb(child, lp):
        if IsWindowVisible(child):
            t = get_text(child).strip()
            if t:
                out.append((child, t))
            EnumChildWindows(child, EnumChildProc(cb), 0)
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def click_at(hwnd, cx, cy):
    """在主窗口客户区 (cx,cy) 位置找到子控件并发送鼠标点击。"""
    pt = wintypes.POINT(cx, cy)
    # 不跳过透明窗口，因为透明 Label 点击区正好在按钮位图之上
    target = ChildWindowFromPointEx(hwnd, pt, 0x0001)
    if not target or target == hwnd:
        target = hwnd

    hr = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(hr))
    screen_x = hr.left + cx
    screen_y = hr.top + cy

    pt = wintypes.POINT(screen_x, screen_y)
    ScreenToClient(target, ctypes.byref(pt))

    lparam = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
    user32.SendMessageW(target, 0x0201, 0, lparam)
    time.sleep(0.05)
    user32.SendMessageW(target, 0x0202, 0, lparam)
    return True


def wait_text(hwnd, labels, timeout=15):
    """等待任一指定文本出现在可见子控件中。"""
    start = time.time()
    labels = labels if isinstance(labels, (list, tuple)) else [labels]
    while time.time() - start < timeout:
        for _, t in enum_children(hwnd):
            if any(l in t for l in labels):
                return t
        time.sleep(0.2)
    return None


def screenshot(hwnd, path):
    rect = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    SetForegroundWindow(hwnd)
    time.sleep(0.3)
    img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
    img.save(path)
    print("SAVED", path, img.size)
    return img


def sample_color(img, x, y):
    return img.getpixel((x, y))


def run():
    proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
    time.sleep(2)
    hwnd = find_main()
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        proc.terminate()
        sys.exit(1)

    img1 = screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page1.png")

    click_at(hwnd, *NEXT_BTN_CENTER)
    time.sleep(1.5)
    if not wait_text(hwnd, "选择安装位置", timeout=10):
        print("FAIL page2 not appear")
        proc.terminate()
        return
    hwnd = find_main()
    img2 = screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page2.png")

    click_at(hwnd, *NEXT_BTN_CENTER)
    if not wait_text(hwnd, ["正在安装", "安装完成"], timeout=10):
        print("FAIL progress page not appear")
        proc.terminate()
        return
    hwnd = find_main()
    time.sleep(0.3)
    img3 = screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page3.png")

    if not wait_text(hwnd, "安装完成", timeout=20):
        print("FAIL finish page not appear")
        proc.terminate()
        return

    # 进度页切到完成页
    user32.SendMessageW(hwnd, 0x0111, 1, 0)
    time.sleep(0.5)
    hwnd = find_main()
    img4 = screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_finish.png")

    print("\n像素采样验证（RGB）：")
    print("内容区白底 (50,180):", sample_color(img1, 50, 180))
    print("footer 浅粉底 (50,390):", sample_color(img1, 50, 390))
    print("banner 非白像素 (270,75):", sample_color(img1, 270, 75))
    print("下一步按钮 (460,400):", sample_color(img1, 460, 400))
    print("进度条 (200,250):", sample_color(img3, 200, 250))

    proc.terminate()


if __name__ == "__main__":
    run()
