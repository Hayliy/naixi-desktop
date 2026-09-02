"""
扫雷自主能力自测（沙箱可跑，端到端验证）：
1) 求解器智能：初级/中级/高级各跑 N 局（引擎真值驱动），报告胜率/平均猜测数。
2) 感知管线：渲染棋盘图 → 感知识别 → 与引擎视图逐格比对，报告识别准确率。
3) 坐标映射：断言 cell_to_screen 计算正确。
全部结果打印并可由调用方落盘。
"""
import sys
from minesweeper import Minesweeper
from minesweeper_agent import MinesweeperAgent
from minesweeper_render import render_board
from minesweeper_perceive import perceive, cell_to_screen

SKIN = {"cell": 30, "origin": 12, "rows": 9, "cols": 9}


def test_solver(rows, cols, mines, n=200, seed0=1000):
    wins = 0
    total_guesses = 0
    total_steps = 0
    for i in range(n):
        eng = Minesweeper(rows, cols, mines, seed=seed0 + i)
        agent = MinesweeperAgent({"cell": 30, "origin": 12, "rows": rows, "cols": cols},
                                 mines_total=mines)
        out = agent.play_sim(eng)
        if out["result"] == "won":
            wins += 1
        total_guesses += out["guesses"]
        total_steps += out["steps"]
    return {
        "difficulty": f"{rows}x{cols}/{mines}",
        "games": n,
        "win_rate": wins / n,
        "avg_guesses": total_guesses / n,
        "avg_steps": total_steps / n,
    }


def _accuracy(perceived, truth):
    ok = 0
    tot = 0
    for r in range(len(truth)):
        for c in range(len(truth[0])):
            tot += 1
            if perceived[r][c] == truth[r][c]:
                ok += 1
    return ok / tot


def test_perception(rows=9, cols=9, mines=10, seed=42):
    results = {}

    # A) 初始全未翻开
    eng = Minesweeper(rows, cols, mines, seed=seed)
    view0 = eng.view()
    img0 = render_board(view0, SKIN)
    p0 = perceive(img0, SKIN)
    results["all_unrevealed_acc"] = _accuracy(p0, view0)

    # B) 翻完所有非雷格（数字 0-8 识别）+ 雷格仍为 '?'
    eng2 = Minesweeper(rows, cols, mines, seed=seed)
    eng2.reveal(0, 0)  # 布雷
    for r in range(rows):
        for c in range(cols):
            if not eng2.mine[r][c] and not eng2.revealed[r][c]:
                eng2.reveal(r, c)
    view_nums = eng2.view()
    img_nums = render_board(view_nums, SKIN)
    p_nums = perceive(img_nums, SKIN)
    results["numbers_acc"] = _accuracy(p_nums, view_nums)

    # C) 插一面旗
    eng3 = Minesweeper(rows, cols, mines, seed=seed)
    mr, mc = next((r, c) for r in range(rows) for c in range(cols) if eng3.mine[r][c])
    eng3.toggle_flag(mr, mc)
    view_flag = eng3.view()
    img_flag = render_board(view_flag, SKIN)
    p_flag = perceive(img_flag, SKIN)
    results["flag_cell_acc"] = (p_flag[mr][mc] == "F")
    results["flag_board_acc"] = _accuracy(p_flag, view_flag)

    return results


def test_coords():
    r, c = 3, 4
    cs, ox, oy = SKIN["cell"], SKIN["origin"], SKIN["origin"]
    x, y = cell_to_screen(r, c, SKIN, win_x=100, win_y=50)
    expect_x = 100 + ox + c * cs + cs // 2
    expect_y = 50 + oy + r * cs + cs // 2
    return x == expect_x and y == expect_y


def main():
    print("===== 1) 求解器智能（胜率）=====")
    for cfg in [(9, 9, 10), (16, 16, 40), (16, 30, 99)]:
        r = test_solver(*cfg, n=200)
        print(f"  {r['difficulty']:>12} | 胜率 {r['win_rate']*100:5.1f}% | "
              f"平均猜测 {r['avg_guesses']:4.2f} | 平均步数 {r['avg_steps']:5.1f}")

    print("\n===== 2) 感知管线（识别准确率）=====")
    per = test_perception()
    for k, v in per.items():
        if isinstance(v, float):
            print(f"  {k:>18}: {v*100:6.2f}%")
        else:
            print(f"  {k:>18}: {v}")

    print("\n===== 3) 坐标映射 =====")
    ok = test_coords()
    print(f"  cell_to_screen 断言: {'PASS' if ok else 'FAIL'}")

    overall = (per["all_unrevealed_acc"] == 1.0 and per["numbers_acc"] == 1.0
               and per["flag_cell_acc"] and ok)
    print(f"\n总体自测: {'ALL PASS' if overall else 'CHECK ABOVE'}")
    return overall


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
