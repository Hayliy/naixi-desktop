# 奶昔卸载器端到端验证脚本（真实 uninstall.exe，三页：确认/进度/完成）
# 用法: python uninstall_verify.py [--clean]
# 依赖: PIL（受管 Python 已自带）。驱动卸载 GUI 三页截图 + 校验，结束后清理注册表/快捷方式使机器干净。
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
GetWindow = user32.GetWindow

NEXT_C = (459, 399)     # 主按钮（卸载/完成）BitmapBtn 414 384 90 30 中心
PREV_C = (365, 399)


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


def wait_text(hwnd, labels, timeout=12):
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
    do_clean = "--clean" in sys.argv
    instdir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "奶昔")
    exe = os.path.join(instdir, "uninstall.exe")
    outdir = os.path.dirname(os.path.abspath(__file__))
    results = {}
    if not os.path.exists(exe):
        print("UNINSTALL_EXE_NOT_FOUND", exe)
        return
    proc = subprocess.Popen([exe])
    print("LAUNCH", exe)

    hwnd = None
    for i in range(240):
        hwnd = find_main()
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        proc.terminate()
        return
    print("WINDOW_OK")

    # ── 第 1 页：确认 ──
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "u_page1.png"))
    kids1 = enum_children(hwnd)
    results["步骤指示_确认"] = any("卸载" in t for t in kids1)
    print("U1:", [t for t in kids1 if t][:12])

    # 下一步 -> 第 2 页（卸载进度）
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "正在卸载", 15)
    results["翻页_到进度页"] = ok
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "u_page2.png"))
    kids2 = enum_children(hwnd)
    print("U2:", [t for t in kids2 if any(k in t for k in ["准备", "删除", "卸载", "完成"])][:6])

    # 等进度推进后再次截图（验证进度条持续增长而非直接消失）
    time.sleep(3.0)
    screenshot(hwnd, os.path.join(outdir, "u_page2b.png"))

    # 等待完成页
    done = wait_text(hwnd, "卸载完成", 60)
    results["卸载_完成"] = done
    hwnd = find_main()
    time.sleep(0.3)
    screenshot(hwnd, os.path.join(outdir, "u_page3.png"))
    print("U3 done:", done)

    # 完成页点击“完成”关闭卸载器（此时文件已被 un.DoUninstallStage 真实删除）
    click_at(hwnd, *NEXT_C)
    time.sleep(1.5)
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
    print("UNINSTALL_GUI_DONE")

    print("\n==== 卸载验证结果 ====")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    # 清理：删除残留注册表项 + 快捷方式 + 安装目录，使机器回归干净
    if do_clean:
        import subprocess as _sp
        # 注册表卸载项
        try:
            _sp.run(
                ["reg", "delete", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\奶昔", "/f"],
                capture_output=True, text=True, timeout=20,
            )
            print("CLEAN: 注册表项已删")
        except Exception as e:
            print("  reg delete err", e)
        # 快捷方式
        for lnk in (
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "奶昔", "奶昔.lnk"),
            os.path.join(os.path.expanduser("~"), "Desktop", "奶昔.lnk"),
            os.path.join(os.path.expandvars("%PUBLIC%"), "Desktop", "奶昔.lnk"),
        ):
            try:
                if os.path.exists(lnk):
                    os.remove(lnk)
                    print("CLEAN: 删除", lnk)
            except Exception:
                pass
        # 安装目录兜底
        try:
            if os.path.isdir(instdir):
                shutil.rmtree(instdir, ignore_errors=True)
                print("CLEAN: 删除", instdir)
        except Exception:
            pass
        print("CLEAN: done")


if __name__ == "__main__":
    main()
