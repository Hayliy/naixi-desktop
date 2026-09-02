"""
实时自动游玩窗口（在【用户自己的机器】上运行）。
依赖：numpy + Pillow（Windows 自带 tkinter，无需 pyautogui）。
完整闭环：截图本 tkinter 窗口 → 感知识别棋盘 → 求解下一步 → 直接驱动引擎落子 → 窗口实时重绘。
用户能看到 AI 一步步自动解题。

运行：
    pip install numpy pillow
    python live_window.py
"""
import tkinter as tk
from PIL import ImageGrab
from tkinter_minesweeper import GameWindow
from minesweeper_agent import MinesweeperAgent


def run(rows=9, cols=9, mines=10, delay=0.35, max_moves=500):
    gw = GameWindow(rows, cols, mines)
    agent = MinesweeperAgent(gw.skin, mines_total=mines)
    moves = 0

    def step():
        nonlocal moves
        if gw.engine.state != "playing" or moves >= max_moves:
            print(f"[结束] 状态={gw.engine.state}，共 {moves} 步，剩 {gw.engine.hidden_count()} 格")
            gw.master.after(2500, gw.master.destroy)
            return
        x, y, W, H = gw.geometry()
        # 截图本窗口（屏幕绝对坐标），走真实"看屏"感知链路
        img = ImageGrab.grab((x, y, x + W, y + H))
        view = agent.perceive_from_image(img)
        move = agent.decide(view)
        if move is None:
            print("[停止] 无可行动作")
            gw.master.after(1500, gw.master.destroy)
            return
        act, r, c = move
        if act == "flag":
            gw.engine.toggle_flag(r, c)
        else:
            gw.engine.reveal(r, c)
        gw._redraw()
        moves += 1
        print(f"[{moves}] {act} @ ({r},{c}) -> {gw.engine.state}")
        gw.master.after(int(delay * 1000), step)

    step()
    gw.master.mainloop()


if __name__ == "__main__":
    run()
