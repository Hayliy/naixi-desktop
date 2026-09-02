"""
可观看的扫雷靶机（tkinter）。
- 棋盘直接用 minesweeper_render.render_board 画成 PIL 图显示在画布上，
  因此对其窗口截图与感知模板像素级一致 → 真机"看屏"识别精确。
- 人类也能手动玩（左键翻开 / 右键插旗）；agent 也能程序化点击。
提供 GameWindow 类：.engine 暴露真值，.view()/mines_set() 供 live runner 读取。
"""
import tkinter as tk
from PIL import Image, ImageTk
from minesweeper import Minesweeper
from minesweeper_render import render_board

SKIN = {"cell": 30, "origin": 12, "rows": 9, "cols": 9}  # 默认初级，可改


class GameWindow:
    def __init__(self, rows=9, cols=9, mines=10, master=None):
        self.rows, self.cols, self.mines = rows, cols, mines
        SKIN["rows"], SKIN["origin"]  # 保留
        self.skin = {"cell": 30, "origin": 12, "rows": rows, "cols": cols}
        self.engine = Minesweeper(rows, cols, mines)
        self.master = master or tk.Tk()
        self.master.title("Naixi Minesweeper")
        self.master.overrideredirect(True)  # 去标题栏/边框 → 窗口矩形==画布矩形，bot 可确定性定位
        cs, ox, oy = self.skin["cell"], self.skin["origin"], self.skin["origin"]
        self.W = ox * 2 + cols * cs
        self.H = oy * 2 + rows * cs
        self.master.geometry(f"{self.W}x{self.H}+700+250")
        self.canvas = tk.Canvas(self.master, width=self.W, height=self.H)
        self.canvas.pack()
        self.photo = None
        self.canvas.bind("<Button-1>", self._left)
        self.canvas.bind("<Button-3>", self._right)
        self._redraw()
        # 窗口真正上屏后把真实几何写入文件，供 agent 确定性定位（不再靠标题搜索猜位置）
        self.master.after(300, self._write_geom)

    def _write_geom(self):
        try:
            import json, os
            self.master.update_idletasks()
            geoj = {"x": int(self.master.winfo_rootx()),
                    "y": int(self.master.winfo_rooty()),
                    "w": int(self.W), "h": int(self.H),
                    "cell": self.skin["cell"], "origin": self.skin["origin"]}
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_geom.json"), "w", encoding="utf-8") as f:
                json.dump(geoj, f)
        except Exception:
            pass

    def _cell_from_event(self, ev):
        cs, ox, oy = self.skin["cell"], self.skin["origin"], self.skin["origin"]
        c = (ev.x - ox) // cs
        r = (ev.y - oy) // cs
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return r, c
        return None

    def _left(self, ev):
        p = self._cell_from_event(ev)
        if p:
            self.engine.reveal(*p)
            self._redraw()

    def _right(self, ev):
        p = self._cell_from_event(ev)
        if p:
            self.engine.toggle_flag(*p)
            self._redraw()

    def _redraw(self):
        mine_pos = {(r, c) for r in range(self.rows) for c in range(self.cols)
                    if self.engine.mine[r][c]}
        img = render_board(self.engine.view(), self.skin,
                           show_mines=(self.engine.state == "lost"), mine_pos=mine_pos)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    def view(self):
        return self.engine.view()

    def mines_set(self):
        return {(r, c) for r in range(self.rows) for c in range(self.cols)
                if self.engine.mine[r][c]}

    def geometry(self):
        self.master.update_idletasks()
        return self.master.winfo_rootx(), self.master.winfo_rooty(), self.W, self.H


def main():
    gw = GameWindow()
    gw.master.mainloop()


if __name__ == "__main__":
    main()
