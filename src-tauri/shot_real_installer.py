import time, subprocess, ctypes, sys, os
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
SendMessage = user32.SendMessageW
PostMessage = user32.PostMessageW
GetWindowRect = user32.GetWindowRect
SetForegroundWindow = user32.SetForegroundWindow
BM_CLICK = 0x00F5
BS_CHECKBOX = 0x0002
GWL_STYLE = -16
GetWindowLong = user32.GetWindowLongW

SETUP = r"D:\naixi_desktop\src-tauri\target\release\bundle\nsis\奶昔_0.1.0_x64-setup.exe"
OUTDIR = r"D:\naixi_desktop\src-tauri"

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

def click_control(hwnd):
    r = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    x = (r.right - r.left) // 2
    y = (r.bottom - r.top) // 2
    lparam = (y << 16) | (x & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0201, 0, lparam)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)
    return True

def click_button(hwnd, label):
    matches = []
    for h, t in enum_children(hwnd):
        if t == label:
            r = wintypes.RECT()
            GetWindowRect(h, ctypes.byref(r))
            cx = (r.left + r.right) // 2
            matches.append((cx, h))
    if not matches:
        return False
    matches.sort(key=lambda x: x[0], reverse=True)
    click_control(matches[0][1])
    return True

def find_visible(hwnd, label):
    matches = []
    for h, t in enum_children(hwnd):
        if t == label:
            r = wintypes.RECT()
            GetWindowRect(h, ctypes.byref(r))
            cx = (r.left + r.right) // 2
            matches.append((cx, h))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[0][1]

def wait_button(hwnd, label, timeout=180, interval=0.5):
    start = time.time()
    while time.time() - start < timeout:
        h = find_visible(hwnd, label)
        if h:
            return h
        time.sleep(interval)
    return None

def uncheck_checkbox(hwnd, label):
    h = find_visible(hwnd, label)
    if h:
        style = GetWindowLong(h, GWL_STYLE)
        if style & BS_CHECKBOX:
            user32.SendMessageW(h, BM_CLICK, 0, 0)
            return True
    return False

def screenshot(hwnd, path):
    rect = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    SetForegroundWindow(hwnd)
    time.sleep(0.3)
    img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
    img.save(path)
    print("SAVED", path, img.size)

if __name__ == "__main__":
    if not os.path.exists(SETUP):
        print("SETUP_NOT_FOUND", SETUP)
        sys.exit(1)

    proc = subprocess.Popen([SETUP])
    # 解压阶段「unpacking data」约 8s，主窗口才出现，轮询等待
    hwnd = None
    start = time.time()
    while time.time() - start < 40:
        hwnd = find_main()
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        sys.exit(1)
    print("main window found")

    screenshot(hwnd, os.path.join(OUTDIR, "real_page1.png"))

    # 欢迎页 → 下一步
    if not click_button(hwnd, "下一步"):
        print("FAIL page1 next")
        sys.exit(1)
    time.sleep(2)
    hwnd = find_main()
    screenshot(hwnd, os.path.join(OUTDIR, "real_page2.png"))

    # 目录页 → 安装（开始真实写入）
    if not click_button(hwnd, "安装"):
        print("FAIL page2 install")
        sys.exit(1)
    print("started install, waiting for progress...")

    # 等待进度页出现
    h = wait_button(hwnd, "正在安装", timeout=10)
    if not h:
        print("FAIL progress page not appear")
        sys.exit(1)
    print("progress page appeared")

    # 等待进度页「完成」按钮出现（安装结束）
    finish_btn = wait_button(hwnd, "完成", timeout=360)
    if not finish_btn:
        print("FAIL wait progress")
        sys.exit(1)
    hwnd = find_main()
    screenshot(hwnd, os.path.join(OUTDIR, "real_page3.png"))
    print("progress done")

    # 进度页切到完成页：直接发送 WM_COMMAND 1（默认 Next）
    user32.SendMessageW(hwnd, 0x0111, 1, 0)
    # 等待完成页标题
    h = wait_button(hwnd, "安装完成", timeout=10)
    if not h:
        print("FAIL finish page title not found")
        sys.exit(1)
    time.sleep(0.5)
    hwnd = find_main()

    # 取消「立即运行」避免拉起重型进程；取消桌面快捷方式保持干净
    uncheck_checkbox(hwnd, "立即运行奶昔")
    time.sleep(0.3)
    uncheck_checkbox(hwnd, "创建桌面快捷方式")
    time.sleep(0.3)
    screenshot(hwnd, os.path.join(OUTDIR, "real_page4.png"))

    # 完成页点「完成」收尾（不运行、不建快捷方式）
    if not click_button(hwnd, "完成"):
        print("FAIL page4 done")
        sys.exit(1)
    print("finished install flow")
    time.sleep(3)

    # 验证安装产物：优先读取注册表 InstallLocation
    import subprocess as _sp
    instloc = None
    try:
        out = _sp.run(
            ["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\奶昔", "/v", "InstallLocation"],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines():
            if "InstallLocation" in line:
                instloc = line.split("REG_SZ", 1)[-1].strip().strip('"')
    except Exception as e:
        print("REG_QUERY_FAIL", e)

    local = os.path.expandvars(r"%LOCALAPPDATA%\奶昔")
    prog = r"C:\Program Files\奶昔"
    candidates = [instloc, local, prog]
    candidates = [c for c in candidates if c]
    found = False
    for base in candidates:
        exe = os.path.join(base, "naixi-desktop.exe")
        if os.path.exists(exe):
            print("INSTALLED_AT", base, os.path.getsize(exe))
            found = True
            break
    if not found:
        print("INSTALL_DIR_NOT_FOUND candidates=", candidates)

    print("DONE")
