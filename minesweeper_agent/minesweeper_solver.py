"""
扫雷求解器：约束传播 + 概率猜测
算法：
1. 基本规则：某数字格的未知邻格数 == 其剩余雷数 → 全雷；剩余雷数==0 → 全安全。
2. 子集推导：约束A的未知集合 ⊆ 约束B → 差分格的雷数 = needed_B - needed_A，可推出安全/雷。
3. 固定点迭代直到无新推论。
4. 优先翻安全格；无安全格则插旗（帮助下一轮推导）；都无则最低概率猜测。
概率：对每个连通约束分量；未知格数 ≤16 时精确枚举所有合法布雷，否则用全局密度兜底
（绝不用拒绝采样，避免大棋盘接受率≈0 导致死循环）。
返回 ('reveal'|'flag'|'guess', r, c) 或 None。
"""
from itertools import product


def _neighbors(r, c, rows, cols):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                yield nr, nc


def next_move(view, rows, cols, mines_total=None):
    hidden = [(r, c) for r in range(rows) for c in range(cols) if view[r][c] == "?"]
    flagged_count = sum(1 for r in range(rows) for c in range(cols) if view[r][c] == "F")
    hidden_count = len(hidden)
    if hidden_count == 0:
        return None

    def constraints():
        cons = []
        for r in range(rows):
            for c in range(cols):
                v = view[r][c]
                if isinstance(v, int) and v > 0:
                    unk = []
                    flagged_n = 0
                    for nr, nc in _neighbors(r, c, rows, cols):
                        if view[nr][nc] == "?":
                            unk.append((nr, nc))
                        elif view[nr][nc] == "F":
                            flagged_n += 1
                    needed = v - flagged_n
                    if unk:
                        cons.append((set(unk), needed))
        return cons

    # ── 确定性推导 ──
    safe = set()
    mine = set()
    changed = True
    while changed:
        changed = False
        cons = constraints()
        for unk, needed in cons:
            if needed <= 0:
                for cell in unk:
                    if cell not in mine and cell not in safe:
                        safe.add(cell)
                        changed = True
            elif needed >= len(unk):
                for cell in unk:
                    if cell not in safe and cell not in mine:
                        mine.add(cell)
                        changed = True
        for i in range(len(cons)):
            ui, ni = cons[i]
            for j in range(len(cons)):
                if i == j:
                    continue
                uj, nj = cons[j]
                if ui < uj:  # 真子集
                    diff = uj - ui
                    if not diff:
                        continue
                    nd = nj - ni
                    if nd <= 0:
                        for cell in diff:
                            if cell not in mine and cell not in safe:
                                safe.add(cell)
                                changed = True
                    elif nd >= len(diff):
                        for cell in diff:
                            if cell not in safe and cell not in mine:
                                mine.add(cell)
                                changed = True

    if safe:
        return ("reveal",) + next(iter(safe))
    if mine:
        return ("flag",) + next(iter(mine))

    # ── 概率猜测 ──
    probs = _probabilities(view, rows, cols, hidden, constraints(),
                           mines_total, flagged_count, hidden_count)
    best = min(hidden, key=lambda c: probs.get(c, 1.0))
    return ("guess",) + best


def _probabilities(view, rows, cols, hidden, cons, mines_total, flagged_count, hidden_count):
    mines_remaining = (mines_total - flagged_count) if mines_total is not None else None
    density = (mines_remaining / hidden_count) if (mines_remaining is not None and hidden_count) else 0.5

    # 连通分量（约束未知集合相交即连通）
    m = len(cons)
    adj = [[] for _ in range(m)]
    for i in range(m):
        for j in range(i + 1, m):
            if cons[i][0] & cons[j][0]:
                adj[i].append(j)
                adj[j].append(i)
    visited = [False] * m
    prob = {}
    for i in range(m):
        if visited[i]:
            continue
        stack = [i]
        comp = []
        while stack:
            u = stack.pop()
            if visited[u]:
                continue
            visited[u] = True
            comp.append(u)
            for v in adj[u]:
                if not visited[v]:
                    stack.append(v)
        cells = set()
        for u in comp:
            cells |= cons[u][0]
        cells = sorted(cells)
        idx = {c: k for k, c in enumerate(cells)}
        n = len(cells)
        masks = []
        for u in comp:
            unk, need = cons[u]
            mask = 0
            for c in unk:
                if c in idx:
                    mask |= 1 << idx[c]
            masks.append((mask, need))
        if n <= 16:
            cell_mine = [0] * n
            total = 0
            for mask in range(1 << n):
                ok = True
                for cm, need in masks:
                    if bin(mask & cm).count("1") != need:
                        ok = False
                        break
                if ok:
                    total += 1
                    mm = mask
                    while mm:
                        lsb = mm & -mm
                        cell_mine[lsb.bit_length() - 1] += 1
                        mm ^= lsb
            if total:
                for c in cells:
                    prob[c] = cell_mine[idx[c]] / total
                continue
        # 大分量 / 无合法解 → 全局密度
        for c in cells:
            prob[c] = density

    # 无邻数字的孤格：全局密度
    for c in hidden:
        if c not in prob:
            prob[c] = density
    return prob
