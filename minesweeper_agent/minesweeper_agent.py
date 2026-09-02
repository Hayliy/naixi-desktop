"""
扫雷自主 agent：感知 → 求解 → 执行闭环
- 模拟模式（sim）：直接用引擎真值驱动，验证求解智能（可在沙箱跑）。
- 真机模式（screen）：对游戏窗口截图 → 感知 → 求解 → pyautogui 点击（用户机器上跑，演示看屏操控）。
"""
import time
import numpy as np
from minesweeper import Minesweeper
from minesweeper_solver import next_move
from minesweeper_perceive import perceive, cell_to_screen

try:
    import pyautogui
    HAVE_GUI = True
except Exception:
    HAVE_GUI = False


class MinesweeperAgent:
    def __init__(self, skin, mines_total=None):
        self.skin = skin
        self.rows, self.cols = skin["rows"], skin["cols"]
        self.mines_total = mines_total

    # ── 感知 ──
    def perceive_from_image(self, image):
        return perceive(image, self.skin)

    # ── 决策 ──
    def decide(self, view):
        return next_move(view, self.rows, self.cols, self.mines_total)

    # ── 执行 ──
    def screen_coord(self, r, c, win_x=0, win_y=0):
        return cell_to_screen(r, c, self.skin, win_x, win_y)

    def click(self, r, c, action, win_x=0, win_y=0):
        """action: 'reveal'/'guess'→左键；'flag'→右键。真机点击。"""
        if not HAVE_GUI:
            x, y = self.screen_coord(r, c, win_x, win_y)
            return ("DRY", x, y, action)
        x, y = self.screen_coord(r, c, win_x, win_y)
        if action in ("reveal", "guess"):
            pyautogui.click(x, y, button="left")
        else:
            pyautogui.click(x, y, button="right")
        return ("CLICK", x, y, action)

    # ── 模拟整局（沙箱可跑，验证逻辑）──
    def play_sim(self, engine, max_steps=None):
        if max_steps is None:
            max_steps = self.rows * self.cols * 4
        guesses = 0
        steps = 0
        while engine.state == "playing" and steps < max_steps:
            move = self.decide(engine.view())
            if move is None:
                break
            act, r, c = move
            if act in ("reveal", "guess"):
                if act == "guess":
                    guesses += 1
                res = engine.reveal(r, c)
                if res == "mine":
                    break
            else:
                engine.toggle_flag(r, c)
            steps += 1
        return {"result": engine.state, "guesses": guesses, "steps": steps}


def screenshot_window(win_title, region):
    """真机：截取游戏窗口区域（region=(x,y,w,h) 屏幕绝对）。需 pyautogui。"""
    if not HAVE_GUI:
        raise RuntimeError("pyautogui 不可用（沙箱）。真机模式需在用户机器安装 pyautogui。")
    return pyautogui.screenshot(region=region)
