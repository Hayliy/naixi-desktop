import subprocess, time, ctypes, os, sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# DPI aware
user32.SetProcessDPIAware()

WND_TITLE = "奶昔 · 桌面智能体"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(SCRIPT_DIR, "test_flow.exe")
OUT_DIR = os.path.join(SCRIPT_DIR, "validate_shots")
os.makedirs(OUT_DIR, exist_ok=True)

def find_window():
    target_pid = proc.pid
    result = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid and user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return result[0] if result else None

def get_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom

def screenshot(name):
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        path = os.path.join(OUT_DIR, name)
        img.save(path)
        print("SHOT", path)
    except Exception as e:
        print("SHOT_ERR", e)

# --- 鼠标输入 ---
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

def send_mouse(flags, dx=0, dy=0):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.dwFlags = flags
    inp.mi.mouseData = 0
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def move_abs(x, y):
    sx = user32.GetSystemMetrics(0)
    sy = user32.GetSystemMetrics(1)
    send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
               int(x * 65535 / sx), int(y * 65535 / sy))

def click_at(x, y):
    move_abs(x, y)
    time.sleep(0.05)
    send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.05)
    send_mouse(MOUSEEVENTF_LEFTUP)
    time.sleep(0.2)

def drag(start_x, start_y, dx, dy):
    move_abs(start_x, start_y)
    time.sleep(0.1)
    send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.1)
    # move in steps
    steps = 10
    for i in range(1, steps + 1):
        move_abs(start_x + dx * i // steps, start_y + dy * i // steps)
        time.sleep(0.02)
    time.sleep(0.1)
    send_mouse(MOUSEEVENTF_LEFTUP)
    time.sleep(0.2)

# 启动
proc = subprocess.Popen([EXE])
print("LAUNCHED pid=", proc.pid)
time.sleep(2.5)

hwnd = find_window()
if not hwnd:
    print("NO_WINDOW")
    sys.exit(1)
print("WINDOW", hwnd)
user32.SetForegroundWindow(hwnd)
user32.ShowWindow(hwnd, 9)
time.sleep(0.3)
x0, y0, x1, y1 = get_rect(hwnd)
print("RECT0", x0, y0, x1, y1)
screenshot("01_welcome.png")

# 在 banner 区域（顶部条带）拖拽窗口：banner 高 150，取 (left+270, top+75)
bx = x0 + 270
by = y0 + 75
drag(bx, by, 120, 60)
time.sleep(0.5)
x2, y2, x3, y3 = get_rect(hwnd)
print("RECT1", x2, y2, x3, y3)
moved = (abs(x2 - x0) > 20 or abs(y2 - y0) > 20)
print("DRAG_OK" if moved else "DRAG_FAIL")
screenshot("02_after_drag.png")

# 点击“下一步”(Next) 按钮：footer 右侧按钮 client (414..504, 384..414) 中心约 (459, 399)
def click_next():
    r = get_rect(hwnd)
    click_at(r[0] + 459, r[1] + 399)

# welcome -> dir
click_next()
time.sleep(1.0)
screenshot("03_dirpage.png")
# dir -> progress (点“安装”按钮，同一位置)
click_next()
time.sleep(1.0)
# 进度页约 5s
time.sleep(6.5)
screenshot("04_progress.png")
# progress -> finish (此时 Next 已启用)
click_next()
time.sleep(1.0)
screenshot("05_finish.png")

# 在 finish 页点击“完成”按钮（同一 Next 位置），验证关闭且无重入
r = get_rect(hwnd)
click_at(r[0] + 459, r[1] + 399)
# 等待进程退出
gone = False
for _ in range(40):
    if proc.poll() is not None:
        gone = True
        break
    time.sleep(0.25)
print("FINISH_CLOSED" if gone else "FINISH_STUCK")
# 再检查窗口是否还存在（重入则会出现第二个）
time.sleep(0.5)
hwnd2 = find_window()
print("REPOP" if hwnd2 else "NO_REPOP")
print("DONE")
