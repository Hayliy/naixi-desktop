#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真机扫雷自动游玩（在用户真机运行：打开真实窗口 + 看屏 + 真实点击）
路线：启动 tkinter 扫雷窗口（弹出在用户桌面）→ ImageGrab 全屏截图(眼睛)
      → qwen-vl-plus 识别棋盘+决策(脑) → ctypes 真实鼠标点击(手) → 循环。
目的：验证「截图 → LLM 理解 → 真实输入注入」这条通用路线到底好不好用。
"""
import os
import sys
import time
import json
import base64
import io
import subprocess
import argparse
import requests
import ctypes
import minesweeper_solver as solver
from PIL import Image, ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))

CELL = 30    # 必须与 tkinter_minesweeper.py 皮肤一致
ORIGIN = 12


def _extract_balanced_json(s):
    """从首个 '{' 扫描到匹配 '}'（尊重字符串内的括号/转义）。零正则，比贪婪 .* 稳。"""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def get_api_key():
    # 优先：从桌面端 storage 读取 bailian_vision provider（DPAPI 加密，同机器同用户可解）
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(HERE), "desktop_core"))
        import storage
        storage.DB_PATH = os.path.join(os.path.dirname(HERE), "data", "naixi_desktop.db")
        cfg = json.loads(storage.meta_get("desktop_config"))
        storage.decrypt_config(cfg)
        for name in ("bailian_vision", "bailian"):
            pv = cfg.get("api_providers", {}).get(name, {})
            k = pv.get("api_key", "")
            if k and not k.startswith("enc:"):
                return k
    except Exception as e:
        print("[key] storage 读取失败:", repr(e)[:200])
    # 兜底：环境变量
    return os.environ.get("DASHSCOPE_API_KEY")


API_KEY = get_api_key()
if not API_KEY:
    print("[错误] 未找到百炼 key。请设置 DASHSCOPE_API_KEY 或确保 live_config.json 含 dashscope_api_key。")
    sys.exit(1)

VL_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
VL_MODEL = "qwen-vl-plus"


def vl_look(img, rows, cols, mines):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    prompt = f"""这是扫雷游戏棋盘的截图（已裁剪到棋盘区域）。棋盘为 {rows} 行 {cols} 列，共 {mines} 颗雷。
请只识别棋盘，输出如下 JSON（不要任何多余文字或代码块标记）：
{{"grid":[[...]], "state":"playing"/"won"/"lost", "action":"reveal"/"flag", "r":int, "c":int, "reason":"一句话中文理由"}}
grid 取值：未翻开="#"；已翻开的数字格填数字(1-8)；翻开后空白填0；已插旗填"F"。
只选择未翻开(#)的格子作为动作目标；若 state 为 won/lost 则 action/r/c 随意。"""
    payload = {"model": VL_MODEL,
               "input": {"messages": [{"role": "user", "content": [
                   {"image": f"data:image/png;base64,{b64}"}, {"text": prompt}]}]}}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(VL_URL, headers=headers, json=payload, timeout=40)
        r.raise_for_status()
        resp = r.json()
        content = resp["output"]["choices"][0]["message"]["content"]
        if isinstance(content, list):
            txt = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        else:
            txt = str(content)
        txt = txt.strip()
        body = _extract_balanced_json(txt)
        if not body:
            print("[VL原始返回]", txt[:400])
            return None
        try:
            return json.loads(body)
        except Exception as je:
            print("[VL JSON解析失败]", repr(je)[:120], "原始:", txt[:400])
            return None
    except Exception as e:
        print("[VL错误]", repr(e)[:200])
        return None


def click(x, y, right=False):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    if right:
        ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)
    else:
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def find_window(title):
    """按标题找窗口真实屏幕矩形（物理像素），返回 (left,top,right,bottom)。"""
    user32 = ctypes.windll.user32
    matches = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        if title in buff.value:
            rc = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rc))
            matches.append((rc.left, rc.top, rc.right, rc.bottom))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return matches[0] if matches else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=9)
    ap.add_argument("--cols", type=int, default=9)
    ap.add_argument("--mines", type=int, default=10)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    print("[启动] 打开扫雷窗口（会弹在你桌面上）…")
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "tkinter_minesweeper.py")])
    time.sleep(2.5)

    steps = 0
    shot_dir = os.path.join(HERE, "_live_shots")
    os.makedirs(shot_dir, exist_ok=True)
    # 定位真实窗口（确定性坐标，不依赖 VL 给像素）
    rect = find_window("Naixi Minesweeper")
    if not rect:
        print("[错误] 找不到扫雷窗口 'Naixi Minesweeper'")
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(1)
    wl, wt, wr, wb = rect
    logical_w = 2 * ORIGIN + a.cols * CELL
    scale = (wr - wl) / logical_w
    origin_px = ORIGIN * scale
    cell_px = CELL * scale
    print(f"[窗口] 位置=({wl},{wt}) 缩放={scale:.3f} 单格={cell_px:.1f}px")
    ImageGrab.grab().save(os.path.join(shot_dir, "step_000_start.png"))
    fail = 0
    model = [["?"] * a.cols for _ in range(a.rows)]  # 持久棋盘模型（VL读到的数字/旗锁定，防误读带偏）
    pending_since = {}  # (r,c) -> 点击步号；久未确认则回退为"?"允许重试
    while steps < a.max_steps:
        img = ImageGrab.grab()
        # 裁剪棋盘区域（基于窗口真实位置，像素精确）→ 只让 VL 读数字
        bx = int(wl + origin_px); by = int(wt + origin_px)
        bw = int(a.cols * cell_px); bh = int(a.rows * cell_px)
        board_img = img.crop((bx, by, bx + bw, by + bh))
        res = vl_look(board_img, a.rows, a.cols, a.mines)
        if not res:
            fail += 1
            if fail >= 12:
                print(f"[终止] 连续 VL 失败 {fail} 次，停止")
                break
            print(f"[跳过] VL 无结果({fail}/12)，1秒后重试")
            time.sleep(1)
            continue
        fail = 0
        state = res.get("state", "playing")
        if state in ("won", "lost"):
            board_img.save(os.path.join(shot_dir, f"step_{steps:03d}_{state}.png"))
            print(f"[结束] 游戏状态={state}，共 {steps} 步")
            break
        # 大脑用确定性求解器（LLM 只当"眼睛"读棋盘，不当逻辑大脑——纯LLM做题已证弱）
        grid = res.get("grid")
        if not grid or len(grid) != a.rows:
            print("[跳过] VL 未返回合法 grid，重试")
            time.sleep(0.5)
            continue
        # 持久模型：VL 读到的数字(int)/旗(F) 锁定；VL 读 "#" 时保留模型旧值（防误读带偏）
        for r in range(a.rows):
            for c in range(a.cols):
                v = grid[r][c]
                if isinstance(v, int):
                    model[r][c] = v
                    pending_since.pop((r, c), None)
                elif isinstance(v, str) and v == "F":
                    model[r][c] = "F"
                    pending_since.pop((r, c), None)
        # 久未确认（>4步）的"R"格回退为"?"，允许重新尝试（应对 VL 偶发误读）
        for (r, c), st in list(pending_since.items()):
            if steps - st > 4:
                model[r][c] = "?"
                pending_since.pop((r, c), None)
        mv = solver.next_move(model, a.rows, a.cols, a.mines)
        if not mv:
            print("[结束] 求解器无可用动作（可能已胜/棋盘异常）")
            break
        act, rr, cc = mv[0], mv[1], mv[2]
        if model[rr][cc] != "?":
            print(f"[跳过] 求解器选({rr},{cc})模型视其已非?，读盘/状态误差")
            time.sleep(0.3)
            continue
        action = "flag" if act == "flag" else "reveal"
        sx = wl + origin_px + cc * cell_px + cell_px / 2
        sy = wt + origin_px + rr * cell_px + cell_px / 2
        click(sx, sy, right=(action == "flag"))
        model[rr][cc] = "R"  # 已点，待 VL 下轮确认数字
        pending_since[(rr, cc)] = steps
        steps += 1
        if steps % 5 == 0:
            board_img.save(os.path.join(shot_dir, f"step_{steps:03d}.png"))
        print(f"[{steps}] {action} ({rr},{cc}) reason={res.get('reason','')[:30]}")
        time.sleep(a.delay)
    final = ImageGrab.grab()
    final.save(os.path.join(shot_dir, "final.png"))
    try:
        proc.terminate()
    except Exception:
        pass
    print(f"完成。共 {steps} 步，过程截图在 {shot_dir}")


if __name__ == "__main__":
    main()
