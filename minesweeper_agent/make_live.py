"""
真机自主游玩：在本机真实开 tkinter 窗口 + 真实截图(PIL.ImageGrab) + 真实鼠标点击(ctypes)，
完整走「看屏 → 感知 → 决策 → 落子」闭环，用户能在桌面上直接看到 AI 玩扫雷。
无需 pyautogui（用 Windows API 直接发鼠标事件）。
"""
import time
import ctypes
from ctypes import wintypes
import tkinter as tk
from PIL import ImageGrab
from tkinter_minesweeper import GameWindow
from minesweeper_perceive import perceive

PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

user32 = ctypes.windll.user32
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

def click_abs(x, y, button="left"):
    # 绝对坐标需归一化到 0..65535
    sx, sy = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    nx = int(x * 65535 / sx)
    ny = int(y * 65535 / sy)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx, inp.mi.dy = nx, ny
    inp.mi.dwFlags = flags
    inp.mi.mouseData = 0
    inp.mi.time = 0
    inp.mi.dwExtraInfo = None
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    time.sleep(0.02)
    down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
    up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
    for f in (down, up):
        e = INPUT(); e.type = INPUT_MOUSE; e.mi.dx = nx; e.mi.dy = ny
        e.mi.dwFlags = f | MOUSEEVENTF_ABSOLUTE; e.mi.time = 0; e.mi.dwExtraInfo = None
        user32.SendInput(1, ctypes.byref(e), ctypes.sizeof(e))
        time.sleep(0.02)


def run(rows=9, cols=9, mines=10, delay=0.35, max_moves=500):
    gw = GameWindow(rows, cols, mines)
    skin = gw.skin
    cs, ox, oy = skin["cell"], skin["origin"], skin["origin"]
    gw.master.update_idletasks()
    gw.master.lift()
    hwnd = gw.master.winfo_id()
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    rx, ry, W, H = gw.geometry()
    print(f"[live] 窗口已开 @ ({rx},{ry}) {W}x{H}，难度 {rows}x{cols}/{mines}")
    moves = 0
    last_view = None
    while gw.engine.state == "playing" and moves < max_moves:
        # 1) 真实截图（看屏）
        img = ImageGrab.grab((rx, ry, rx + W, ry + H))
        # 2) 感知：从截图读棋盘
        view = perceive(img, skin)
        # 3) 决策
        from minesweeper_solver import next_move
        move = next_move(view, rows, cols, mines_total=mines)
        if move is None:
            print("[live] 无可行动作，停止")
            break
        act, r, c = move
        # 4) 真实鼠标点击（落子）
        x = rx + ox + c * cs + cs // 2
        y = ry + oy + r * cs + cs // 2
        click_abs(x, y, "left" if act in ("reveal", "guess") else "right")
        gw.master.update()  # 处理点击事件 + 重绘
        moves += 1
        if moves % 5 == 0 or gw.engine.state != "playing":
            print(f"[live] {moves} {act}@({r},{c}) -> {gw.engine.state} 剩雷{gw.engine.mines_remaining()}")
        time.sleep(delay)
    print(f"[live] 结束：{gw.engine.state}，共 {moves} 步")
    gw.master.mainloop()  # 结束后窗口保留，便于查看


if __name__ == "__main__":
    run()
