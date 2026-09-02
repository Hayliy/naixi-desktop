"""
扫雷引擎（纯逻辑，无 GUI 依赖）
- 首点保证安全：第一次翻开后再布雷，且避开首点及其 8 邻域，确保开局必开一片。
- 给求解器的视图 view[r][c] ∈ {0..8 数字, 'F' 旗, '?' 未翻开}。
- 测试时可暴露真雷位置（不进视图，仅供自测判定）。
"""
import random
from dataclasses import dataclass, field


class Minesweeper:
    def __init__(self, rows=9, cols=9, mines=10, seed=None):
        self.rows = rows
        self.cols = cols
        self.mines = min(mines, rows * cols - 9)  # 留足首点安全区
        self.rng = random.Random(seed)
        self.mine = [[False] * cols for _ in range(rows)]
        self.revealed = [[False] * cols for _ in range(rows)]
        self.flagged = [[False] * cols for _ in range(rows)]
        self.adj = [[0] * cols for _ in range(rows)]   # 邻雷数（翻开后可见）
        self._planted = False
        self.first_click = None
        self.state = "playing"  # playing | won | lost

    # ── 内部 ──
    def _neighbors(self, r, c):
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    yield nr, nc

    def _plant(self, sr, sc):
        """首点后布雷，避开 (sr,sc) 及其邻域。"""
        forbidden = {(sr, sc)} | {(r, c) for r, c in self._neighbors(sr, sc)}
        candidates = [(r, c) for r in range(self.rows) for c in range(self.cols)
                      if (r, c) not in forbidden]
        chosen = self.rng.sample(candidates, self.mines)
        for r, c in chosen:
            self.mine[r][c] = True
        for r in range(self.rows):
            for c in range(self.cols):
                self.adj[r][c] = sum(1 for nr, nc in self._neighbors(r, c) if self.mine[nr][nc])
        self._planted = True

    def _flood(self, sr, sc):
        """翻开 0 区时递归展开（标准扫雷行为）。"""
        stack = [(sr, sc)]
        while stack:
            r, c = stack.pop()
            if self.revealed[r][c] or self.flagged[r][c]:
                continue
            self.revealed[r][c] = True
            if self.adj[r][c] == 0:
                for nr, nc in self._neighbors(r, c):
                    if not self.revealed[nr][nc]:
                        stack.append((nr, nc))

    # ── 对外动作 ──
    def reveal(self, r, c):
        if self.state != "playing":
            return "ended"
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return "oob"
        if self.flagged[r][c] or self.revealed[r][c]:
            return "noop"
        if not self._planted:
            self.first_click = (r, c)
            self._plant(r, c)
        if self.mine[r][c]:
            self.revealed[r][c] = True
            self.state = "lost"
            return "mine"
        self._flood(r, c)
        if self._all_clear():
            self.state = "won"
        return "ok"

    def toggle_flag(self, r, c):
        if self.state != "playing" or self.revealed[r][c]:
            return "noop"
        self.flagged[r][c] = not self.flagged[r][c]
        return "flag" if self.flagged[r][c] else "unflag"

    def _all_clear(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.mine[r][c] and not self.revealed[r][c]:
                    return False
        return True

    # ── 视图（求解器输入）──
    def view(self):
        """返回二维视图：已翻开→数字0..8；插旗→'F'；未翻→'?'。"""
        v = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                if self.revealed[r][c]:
                    row.append(self.adj[r][c])
                elif self.flagged[r][c]:
                    row.append("F")
                else:
                    row.append("?")
            v.append(row)
        return v

    def mines_remaining(self):
        flagged = sum(1 for r in range(self.rows) for c in range(self.cols) if self.flagged[r][c])
        return self.mines - flagged

    def hidden_count(self):
        return sum(1 for r in range(self.rows) for c in range(self.cols)
                   if not self.revealed[r][c] and not self.flagged[r][c])
