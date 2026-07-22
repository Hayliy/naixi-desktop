# 奶昔安装器端到端验证脚本（真实 setup.exe）
# 用法: python verify_installer.py <setup.exe 路径> [--clean]
# 依赖: PIL（受管 Python 已自带）。仅做 UI 走查 + 快捷方式校验，结束后静默卸载清理。
import time, subprocess, ctypes, sys, os, shutil
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
GetWindow = user32.GetWindow

# 窗口内坐标偏移（无边框窗口，client 原点即窗口原点）
NEXT_C = (459, 399)     # BitmapBtn 414 384 90 30 中心
PREV_C = (365, 399)     # BitmapBtn 320 384 90 30 中心
BROWSE_C = (465, 224)   # BitmapBtn 420 210 90 28 中心
MIN_C = (492, 18)       # 最小化 Label 478 6 28 24 中心
CLOSE_C = (520, 18)     # 关闭 Label 506 6 28 24 中心
RUNCHK_C = (45, 259)    # 复选框“立即运行奶昔”中心
DESKCHK_C = (45, 291)   # 复选框“创建桌面快捷方式”中心

PINK_LO, PINK_HI = (180, 40, 90), (240, 120, 160)  # 进度填充粉色范围


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
    SetForegroundWindow(hwnd)
    time.sleep(0.15)
    hr = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(hr))
    sx, sy = hr.left + cx, hr.top + cy
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # DOWN
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # UP
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


def count_pink(img, x0, y0, x1, y1):
    crop = img.crop((x0, y0, x1, y1))
    px = crop.load()
    n = 0
    for y in range(crop.size[1]):
        for x in range(crop.size[0]):
            r, g, b = px[x, y][:3]
            if PINK_LO[0] <= r <= PINK_HI[0] and PINK_LO[1] <= g <= PINK_HI[1] and PINK_LO[2] <= b <= PINK_HI[2]:
                n += 1
    return n


# 通过 ctypes + COM（IShellLinkW）解析 .lnk 目标路径，无需 pywin32
def resolve_lnk(path):
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(0, 0x2)  # COINIT_APARTMENTTHREADED
        def guid_from_hex(hx):
            return ctypes.create_string_buffer(bytes.fromhex(hx), 16)
        clsid = guid_from_hex("0002140100000000C000000000000046")  # CLSID_ShellLink
        iid_sl = guid_from_hex("000214F900000000C000000000000046")  # IID_IShellLinkW
        iid_pf = guid_from_hex("0000010B00000000C000000000000046")  # IID_IPersistFile
        ppv = ctypes.c_void_p()
        if ole32.CoCreateInstance(ctypes.byref(clsid), 0, 0x1, ctypes.byref(iid_sl), ctypes.byref(ppv)) != 0:
            return None
        psl = ppv.value
        # IShellLink::QueryInterface(IID_IPersistFile) via vtable[0]
        vq = ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p * 3))[0][0]
        QueryInterface = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(vq)
        ppf = ctypes.c_void_p()
        if QueryInterface(psl, ctypes.byref(iid_pf), ctypes.byref(ppf)) != 0:
            return None
        pf = ppf.value
        # IPersistFile::Load(path, 0) -> vtable[3]
        vload = ctypes.cast(pf, ctypes.POINTER(ctypes.c_void_p * 7))[0][3]
        Load = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32)(vload)
        if Load(pf, path, 0) != 0:
            return None
        # IShellLink::GetPath(buf, cb, WIN32_FIND_DATA*, flags) -> vtable[3]
        vgetpath = ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p * 20))[0][3]
        buf = ctypes.create_unicode_buffer(260)
        fd = ctypes.create_string_buffer(592)  # WIN32_FIND_DATAW
        GetPath = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)(vgetpath)
        if GetPath(psl, buf, 260, fd, 0) != 0:
            return None
        return buf.value
    except Exception:
        return None


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else r"D:\naixi_desktop\src-tauri\target\release\bundle\nsis\奶昔_0.1.0_x64-setup.exe"
    do_clean = "--clean" in sys.argv
    outdir = os.path.dirname(os.path.abspath(__file__))
    results = {}

    # 不指定 /D：按产品默认安装到 %LOCALAPPDATA%\奶昔；验证后通过注册表卸载命令清理，保持机器干净
    proc = subprocess.Popen([exe])
    print("LAUNCH", exe)

    # 等待主窗口（210MB 安装包 NSIS 解压较慢，可能需数十秒；解压对话框标题为“unpacking data”且尺寸很小，会被尺寸过滤）
    hwnd = None
    for i in range(240):  # 最多 120 秒
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

    # ── 第 1 页：欢迎 ──
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "v_page1.png"))
    kids1 = enum_children(hwnd)
    results["右上角_最小化可见"] = "—" in kids1
    results["右上角_关闭可见"] = "×" in kids1
    results["步骤指示_欢迎"] = any("欢迎" in t for t in kids1)
    print("P1 min/close/chk:", results["右上角_最小化可见"], results["右上角_关闭可见"], results["步骤指示_欢迎"])

    # 下一步 -> 第 2 页
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "选择安装位置", 12)
    results["翻页_下一步"] = ok
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "v_page2.png"))
    kids2 = enum_children(hwnd)
    results["步骤指示_位置"] = any("位置" in t for t in kids2)
    # 地址框文本（Edit 控件内容）
    addr = next((t for t in kids2 if t.startswith(r"C:\naixi_verify") or "naixi" in t.lower() or "奶昔" in t), "")
    results["地址框_显示路径"] = bool(addr)
    print("P2 next/addr:", ok, repr(addr))

    # 浏览按钮点击性：点击后弹出文件夹对话框，再取消
    click_at(hwnd, *BROWSE_C)
    time.sleep(0.8)
    dlg = None
    def cb2(h, lp):
        nonlocal dlg
        t = get_text(h)
        if "选择安装文件夹" in t or (IsWindowVisible(h) and get_text(GetWindow(h, 5)) and "浏览" in get_text(GetWindow(h, 5))):
            if "选择安装文件夹" in t or get_size(h)[0] > 300:
                dlg = h
        return True
    EnumWindows(EnumWindowsProc(cb2), 0)
    results["浏览按钮_可点击弹窗"] = dlg is not None
    print("P2 browse dialog:", dlg is not None)
    # 取消对话框（Escape）
    if dlg:
        SetForegroundWindow(dlg)
        time.sleep(0.2)
        user32.keybd_event(0x1B, 0, 0, 0)  # VK_ESCAPE
        time.sleep(0.5)

    # 下一步 -> 第 3 页（安装进度）
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "正在安装", 12)
    results["翻页_到进度页"] = ok
    hwnd = find_main()
    time.sleep(0.4)
    img_a = screenshot(hwnd, os.path.join(outdir, "v_page3_a.png"))
    kids_a = enum_children(hwnd)
    status_a = next((t for t in kids_a if any(k in t for k in ["准备", "写入", "创建", "注册", "安装"])), "")
    pink_a = count_pink(img_a, 30, 246, 510, 254)

    # 等待进度推进
    time.sleep(2.0)
    img_b = screenshot(hwnd, os.path.join(outdir, "v_page3_b.png"))
    kids_b = enum_children(hwnd)
    status_b = next((t for t in kids_b if any(k in t for k in ["准备", "写入", "创建", "注册", "安装"])), "")
    pink_b = count_pink(img_b, 30, 246, 510, 254)

    results["进度条_未消失_填充可见"] = pink_a > 0 or pink_b > 0
    results["进度条_持续推进"] = (status_a != status_b) or (pink_b > pink_a) or ("安装完成" in status_b)
    print("P3 status:", repr(status_a), "->", repr(status_b), "pink", pink_a, pink_b)

    # 等待安装完成（状态“安装完成。”）
    done = wait_text(hwnd, "安装完成。", 60)
    results["安装_完成"] = done
    hwnd = find_main()
    time.sleep(0.3)
    screenshot(hwnd, os.path.join(outdir, "v_page3_c.png"))

    # 下一步 -> 第 4 页（完成）
    click_at(hwnd, *NEXT_C)
    ok = wait_text(hwnd, "立即运行奶昔", 12)
    results["翻页_到完成页"] = ok
    hwnd = find_main()
    time.sleep(0.4)
    screenshot(hwnd, os.path.join(outdir, "v_page4.png"))

    # 校验快捷方式（此时 start menu 已建，desktop 将在 fn_Done 建）
    sm = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "奶昔", "奶昔.lnk")
    results["快捷方式_开始菜单_奶昔.lnk"] = os.path.exists(sm)
    sm_tgt = resolve_lnk(sm) if os.path.exists(sm) else None
    results["快捷方式_开始菜单_指向exe"] = bool(sm_tgt) and sm_tgt.lower().endswith(".exe")

    # 取消“立即运行”，保留“创建桌面快捷方式”，点击完成
    click_at(hwnd, *RUNCHK_C)
    time.sleep(0.2)
    click_at(hwnd, *NEXT_C)
    time.sleep(1.2)

    # 桌面快捷方式校验（currentUser 模式写到用户桌面，兼容公共桌面）
    dl = None
    for cand in (
        os.path.join(os.path.expanduser("~"), "Desktop", "奶昔.lnk"),
        os.path.join(os.path.expandvars("%PUBLIC%"), "Desktop", "奶昔.lnk"),
    ):
        if os.path.exists(cand):
            dl = cand
            break
    if dl is None:
        dl = os.path.join(os.path.expanduser("~"), "Desktop", "奶昔.lnk")
    results["快捷方式_桌面_奶昔.lnk"] = os.path.exists(dl)
    dl_tgt = resolve_lnk(dl) if os.path.exists(dl) else None
    results["快捷方式_桌面_指向exe"] = bool(dl_tgt) and dl_tgt.lower().endswith(".exe")

    # 等待安装器退出
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()

    # 输出汇总
    print("\n==== 验证结果 ====")
    for k, v in results.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    # 清理：从注册表读取卸载命令，静默卸载，使机器回归干净
    if do_clean:
        import subprocess as _sp
        uninst_cmd = ""
        try:
            out = _sp.run(
                ["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\奶昔", "/v", "UninstallString"],
                capture_output=True, text=True, timeout=20,
            )
            for line in out.stdout.splitlines():
                if "UninstallString" in line:
                    uninst_cmd = line.split("REG_SZ", 1)[-1].strip().strip('"')
        except Exception as e:
            print("  query uninst err", e)
        if uninst_cmd:
            print("CLEAN: 静默卸载", uninst_cmd)
            try:
                _sp.run(uninst_cmd + " /S", shell=True, timeout=180)
            except Exception as e:
                print("  uninstall err", e)
        # 兜底删除残留快捷方式
        for lnk in (sm, dl):
            try:
                if lnk and os.path.exists(lnk):
                    os.remove(lnk)
            except Exception:
                pass
        print("CLEAN: done")


if __name__ == "__main__":
    main()
