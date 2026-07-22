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
IsIconic = user32.IsIconic
ChildWindowFromPointEx = user32.ChildWindowFromPointEx
ShowWindow = user32.ShowWindow

NEXT_C = (414 + 45, 384 + 15)
PREV_C = (320 + 45, 384 + 15)
MIN_C = (492, 18)
CLOSE_C = (520, 18)


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
        if "奶昔" in get_text(hwnd) and IsWindowVisible(hwnd):
            w, h = get_size(hwnd)
            if 500 <= w <= 600 and 400 <= h <= 470:
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
                out.append(t)
            EnumChildWindows(child, EnumChildProc(cb), 0)
        return True
    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return out


def click_at(hwnd, cx, cy):
    # 真实鼠标事件：STATIC(SS_NOTIFY) 只有在收到真实鼠标按下/抬起时才发 STN_CLICKED
    SetForegroundWindow(hwnd)
    time.sleep(0.1)
    hr = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(hr))
    sx, sy = hr.left + cx, hr.top + cy
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    return True


def wait_text(hwnd, labels, timeout=10):
    labels = labels if isinstance(labels, (list, tuple)) else [labels]
    start = time.time()
    while time.time() - start < timeout:
        for t in enum_children(hwnd):
            if any(l in t for l in labels):
                return True
        time.sleep(0.2)
    return False


def screenshot(hwnd, path):
    # 精确截取客户区（540×430），避免 DWM 阴影/边框裁切
    cr = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    pt = wintypes.POINT(cr.left, cr.top)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    SetForegroundWindow(hwnd)
    time.sleep(0.3)
    img = ImageGrab.grab((pt.x, pt.y, pt.x + cr.right, pt.y + cr.bottom))
    img.save(path)
    print("SAVED", path, img.size)
    return img


def main():
    proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
    time.sleep(2)
    hwnd = find_main()
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        proc.terminate()
        return

    screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page1.png")

    # 下一步 page1 -> page2
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "选择安装位置", 10)
    print("NEXT:", "PASS" if ok else "FAIL")
    hwnd = find_main()
    screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page2.png")

    # 上一步 page2 -> page1
    click_at(hwnd, *PREV_C)
    ok = wait_text(hwnd, "欢迎安装", 10)
    print("PREV:", "PASS" if ok else "FAIL")
    hwnd = find_main()

    # 下一步 page1 -> page2
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "选择安装位置", 10)
    hwnd = find_main()

    # 下一步 page2 -> page3（进度页）
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, ["正在安装", "安装完成"], 10)
    print("NEXT->P3:", "PASS" if ok else "FAIL")
    hwnd = find_main()
    screenshot(hwnd, r"D:\naixi_desktop\src-tauri\shot_page3.png")

    # 最小化
    click_at(hwnd, *MIN_C)
    time.sleep(0.6)
    mini = IsIconic(hwnd)
    print("MIN:", "PASS" if mini else "FAIL")
    ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.4)
    hwnd = find_main()

    # 关闭
    if hwnd:
        click_at(hwnd, *CLOSE_C)
        time.sleep(1.0)
        closed = find_main() is None
        print("CLOSE:", "PASS" if closed else "FAIL")
    else:
        print("CLOSE: SKIP (窗口已不存在)")

    proc.terminate()


if __name__ == "__main__":
    main()
