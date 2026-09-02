"""
真机演示：agent 看屏玩 tkinter 扫雷（用户机器上跑，沙箱无显示无法执行）。
流程：截图游戏窗口区域 → 感知识别棋盘 → 求解下一步 → pyautogui 真实点击。
同一进程内 GameWindow 的画布绑定会响应点击并更新引擎；循环读 engine.state 判定胜负。
"""
import time
import tkinter as tk
from tkinter_minesweeper import GameWindow, SKIN
from minesweeper_agent import MinesweeperAgent, HAVE_GUI, screenshot_window


def run(rows=9, cols=9, mines=10, delay=0.3, max_moves=500):
    if not HAVE_GUI:
        raise RuntimeError("沙箱无 pyautogui/显示，无法运行真机演示。请在用户机器安装 pyautogui 后运行。")
    gw = GameWindow(rows, cols, mines)
    agent = MinesweeperAgent(gw.skin, mines_total=mines)
    win_x, win_y, W, H = gw.geometry()
    moves = 0
    while gw.engine.state == "playing" and moves < max_moves:
        region = (win_x, win_y, W, H)
        img = screenshot_window(None, region)
        view = agent.perceive_from_image(img)
        move = agent.decide(view)
        if move is None:
            print("无可行动作，停止")
            break
        act, r, c = move
        agent.click(r, c, act, win_x, win_y)
        gw.master.update()   # 处理点击事件 + 重绘
        moves += 1
        time.sleep(delay)
        print(f"[{moves}] {act} @ ({r},{c}) -> {gw.engine.state} | 剩雷 {gw.engine.mines_remaining()}")
    print(f"结束：{gw.engine.state}，共 {moves} 步，剩 {gw.engine.hidden_count()} 格未翻")
    gw.master.mainloop()


if __name__ == "__main__":
    run()
