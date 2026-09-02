#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真机扫雷 · 看屏(眼睛) → LLM(脑) → 真实鼠标(手) 最小端到端验证
================================================================
路线：用户在【自己电脑】上打开真实扫雷 → 本脚本截图当"眼睛" → 调 qwen-vl-plus
      识别棋盘并决策 → 用 pyautogui 真实点击"手"去翻格/插旗 → 循环。
目的：验证「截图 → LLM 理解 → 真实输入注入」这条通用路线到底好不好用
      （与奶昔桌宠 game_agent 的 A 路视觉 grounding 同源）。

运行（请在【你自己的 Windows 机器】上执行；沙箱开不了你桌面窗口）：
    1) 装依赖： pip install pyautogui requests pillow
    2) 百炼 key（二选一）：
         - 环境变量： set DASHSCOPE_API_KEY=你的key
         - 或保证 <项目根>/data/live_config.json 里有 "dashscope_api_key"
    3) 运行： python real_minesweeper_agent.py
    4) 按提示手动打开扫雷并置于前台，回车，AI 开始自动玩。
"""
import os
import sys
import time
import json
import base64
import io
import argparse
import requests
import pyautogui
from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_HERE)


# ───────────────────────── API key ─────────────────────────
def get_api_key():
    k = os.environ.get("DASHSCOPE_API_KEY")
    if k:
        return k
    for p in (os.path.join(_PROJ, "data", "live_config.json"),
              os.path.join(_PROJ, "data", "config.json")):
        if os.path.isfile(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if isinstance(d, dict):
                    if d.get("dashscope_api_key"):
                        return d["dashscope_api_key"]
                    lc = d.get("live_config")
                    if isinstance(lc, dict) and lc.get("dashscope_api_key"):
                        return lc["dashscope_api_key"]
            except Exception:
                pass
    return None


API_KEY = get_api_key()
if not API_KEY:
    print("[错误] 未找到百炼 API key。请设置环境变量 DASHSCOPE_API_KEY，")
    print("       或确保", os.path.join(_PROJ, "data", "live_config.json"), "含 dashscope_api_key。")
    sys.exit(1)


# ───────────────────────── 视觉 LLM ─────────────────────────
VL_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
VL_MODEL = "qwen-vl-plus"


def vl_look(img, rows, cols, mines):
    """截屏 → qwen-vl-plus → 结构化棋盘 + 决策 + 棋盘像素边界。"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    prompt = f"""这是 Windows 扫雷游戏的一张截图。该局棋盘为 {rows} 行 {cols} 列，共 {mines} 颗雷。
请完成两件事：
1) 识别棋盘：输出二维数组 grid[r][c]（r 从 0 到 {rows-1} 自上而下，c 从 0 到 {cols-1} 自左而右）。
   取值：未翻开="#"；已翻开的数字格填数字(1-8)；翻开后是空白(无数字)填 0；已插旗填"F"。
2) 逻辑推理下一步最优动作，并给出棋盘在截图中的像素边界，便于程序点击：
   只输出如下 JSON（不要任何多余文字或代码块标记）：
   {{
     "grid": [[...],[...]],
     "state": "playing" 或 "won" 或 "lost",
     "action": "reveal" 或 "flag",
     "r": 整数行号,
     "c": 整数列号,
     "board": {{"x": 棋盘左上角在截图中的像素X, "y": 像素Y, "cell": 单格像素边长}},
     "reason": "一句话中文理由"
   }}"""
    payload = {
        "model": VL_MODEL,
        "input": {"messages": [{"role": "user", "content": [
            {"image": f"data:image/png;base64,{b64}"},
            {"text": prompt}]}]}
    }
    headers = {"Authorization": f"Bearer {API_KEY}",
               "Content-Type": "application/json"}
    try:
        r = requests.post(VL_URL, headers=headers, json=payload, timeout=40)
        r.raise_for_status()
        out = r.json()["output"]["choices"][0]["message"]["content"]
        txt = out[0]["text"] if isinstance(out, list) else out
        txt = txt.strip().strip("`").replace("```json", "").replace("```", "").strip()
        return json.loads(txt)
    except Exception as e:
        print("[VL错误]", repr(e)[:300])
        return None


# ───────────────────────── 主循环 ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=16)
    ap.add_argument("--cols", type=int, default=16)
    ap.add_argument("--mines", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--delay", type=float, default=1.2)
    a = ap.parse_args()

    input("请在你电脑上打开『扫雷』并把它置于前台（不要遮挡），准备好后按回车开始…")
    win = None
    for title in ("扫雷", "Minesweeper", "Microsoft Minesweeper"):
        ws = pyautogui.getWindowsWithTitle(title)
        if ws:
            win = ws[0]
            break
    if not win:
        print("[错误] 没找到扫雷窗口。请确认它已打开且标题含『扫雷/Minesweeper』。")
        sys.exit(1)
    win.activate()
    time.sleep(0.5)

    steps = 0
    while steps < a.max_steps:
        region = (win.left, win.top, win.width, win.height)
        shot = pyautogui.screenshot(region=region)
        res = vl_look(shot, a.rows, a.cols, a.mines)
        if not res:
            print("[跳过] VL 本次无结果，1秒后重试")
            time.sleep(1)
            continue
        state = res.get("state", "playing")
        if state in ("won", "lost"):
            print(f"[结束] 游戏状态={state}，共 {steps} 步")
            break
        action = res.get("action")
        r = res.get("r")
        c = res.get("c")
        board = res.get("board") or {}
        bx, by, cell = board.get("x", 0), board.get("y", 0), board.get("cell", 0)
        if action not in ("reveal", "flag") or r is None or c is None or not cell:
            print("[跳过] VL 输出缺字段，重试")
            time.sleep(0.5)
            continue
        sx = win.left + bx + c * cell + cell // 2
        sy = win.top + by + r * cell + cell // 2
        if action == "flag":
            pyautogui.click(sx, sy, button="right")
        else:
            pyautogui.click(sx, sy, button="left")
        steps += 1
        print(f"[{steps}] {action} ({r},{c}) reason={res.get('reason','')[:40]}")
        time.sleep(a.delay)
    print("完成。如需重开，关闭扫雷再运行本脚本。")


if __name__ == "__main__":
    main()
