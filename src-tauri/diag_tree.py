import ctypes, ctypes.wintypes, time, subprocess

user32 = ctypes.windll.user32

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWL_ID = -12
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_DISABLED = 0x08000000
WS_CAPTION = 0x00C00000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000

def get_text(h):
    n = user32.GetWindowTextLengthW(h)
    if n <= 0: return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value

def get_class(h):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(h, buf, 64)
    return buf.value

def get_rect(h):
    r = ctypes.wintypes.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)

def get_style(h):
    return user32.GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF

def get_ex(h):
    return user32.GetWindowLongW(h, GWL_EXSTYLE) & 0xFFFFFFFF

def get_id(h):
    return user32.GetWindowLongW(h, GWL_ID) & 0xFFFF

def style_str(s):
    parts = []
    if s & WS_POPUP: parts.append("POPUP")
    if s & WS_CHILD: parts.append("CHILD")
    if s & WS_VISIBLE: parts.append("VISIBLE")
    if s & WS_DISABLED: parts.append("DISABLED")
    if s & WS_CAPTION: parts.append("CAPTION")
    if s & WS_BORDER: parts.append("BORDER")
    if s & WS_DLGFRAME: parts.append("DLGFRAME")
    if s & WS_THICKFRAME: parts.append("THICKFRAME")
    if s & WS_SYSMENU: parts.append("SYSMENU")
    if s & 0x80: parts.append("DS_MODALFRAME")
    return " ".join(parts) if parts else "(none)"

WINFUNCTYPE_BOOL = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

def find_main():
    cands = []
    def cb(h, lp):
        if get_class(h) == "#32770":
            t = get_text(h)
            if ("奶昔" in t) or ("NSIS" in t.upper()):
                cands.append((h, t))
        return True
    user32.EnumWindows(WINFUNCTYPE_BOOL(cb), 0)
    return cands[0][0] if cands else None

results = []
def enum_child(h, depth):
    def cb(child, lp):
        results.append((depth, child))
        enum_child(child, depth + 1)
        return True
    user32.EnumChildWindows(h, WINFUNCTYPE_BOOL(cb), 0)

proc = subprocess.Popen([r"D:\naixi_desktop\src-tauri\test_flow.exe"])
time.sleep(2.5)
main = find_main()
print("=== 主窗口 ===")
print("hwnd=%s text=%r rect=%s size=%dx%d" % (main, get_text(main), get_rect(main),
      get_rect(main)[2]-get_rect(main)[0], get_rect(main)[3]-get_rect(main)[1]))
print("STYLE: %s (0x%08X)" % (style_str(get_style(main)), get_style(main)))
print("EXSTYLE: 0x%08X" % get_ex(main))
print()
print("=== 子控件树 ===")
results.clear()
enum_child(main, 0)
def keyf(t):
    depth, h = t
    r = get_rect(h)
    return (depth, r[1], r[0])
for depth, h in sorted(results, key=keyf):
    r = get_rect(h)
    w = r[2] - r[0]; ht = r[3] - r[1]
    s = get_style(h)
    vis = "V" if (s & WS_VISIBLE) else "."
    print("%s[%s] id=%-5d cls=%-10s txt=%-12r rect=(%d,%d,%dx%d) %s" % (
        "  " * depth, vis, get_id(h), get_class(h), get_text(h)[:12], r[0], r[1], w, ht, style_str(s)))
proc.terminate()
