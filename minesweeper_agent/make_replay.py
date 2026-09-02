"""
回放生成器：用「图像」跑完整自主链路（渲染棋盘=屏幕显示内容 → 感知 → 决策 → 落子），
每步存一帧并把落子格高亮，最终打包成单文件 HTML 动画（帧以 base64 内嵌），
用户无需运行任何东西即可在浏览器观看 AI 自主扫雷全过程。
"""
import base64
import io
from PIL import Image, ImageDraw
from minesweeper import Minesweeper
from minesweeper_render import render_board
from minesweeper_perceive import perceive
from minesweeper_solver import next_move


def _frame_png(img, hl=None):
    if hl:
        r, c = hl
        d = ImageDraw.Draw(img)
        cs = img.width  # 占位，实际用 skin
    return img


def make_replay(rows=9, cols=9, mines=10, seed=7, out_html=None, interval_ms=420):
    skin = {"cell": 30, "origin": 12, "rows": rows, "cols": cols}
    cs, ox, oy = skin["cell"], skin["origin"], skin["origin"]
    eng = Minesweeper(rows, cols, mines, seed=seed)
    frames = []
    steps = 0
    max_steps = rows * cols * 4
    last_action = None
    while eng.state == "playing" and steps < max_steps:
        img = render_board(eng.view(), skin)  # 屏幕上 tkinter 显示的就是这张图
        perceived = perceive(img, skin)       # 感知：从图里读棋盘
        move = next_move(perceived, rows, cols, mines_total=mines)
        if move is None:
            break
        act, r, c = move
        # 高亮 AI 即将落的格子
        disp = img.copy()
        d = ImageDraw.Draw(disp)
        x0, y0 = ox + c * cs, oy + r * cs
        color = (255, 0, 255) if act in ("reveal", "guess") else (0, 200, 255)
        d.rectangle([x0 + 2, y0 + 2, x0 + cs - 3, y0 + cs - 3], outline=color, width=3)
        buf = io.BytesIO()
        disp.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        cap = f"第 {steps+1} 步：{act} @ ({r},{c}) ｜ 剩雷 {eng.mines_remaining()} ｜ 状态 {eng.state}"
        frames.append((b64, cap))
        # 落子
        if act in ("reveal", "guess"):
            eng.reveal(r, c)
        else:
            eng.toggle_flag(r, c)
        steps += 1
        last_action = (act, r, c)
    # 终局帧
    final_img = render_board(eng.view(), skin,
                             show_mines=(eng.state == "lost"),
                             mine_pos={(r, c) for r in range(rows) for c in range(cols) if eng.mine[r][c]})
    buf = io.BytesIO()
    final_img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    result_txt = "胜利 🎉" if eng.state == "won" else ("踩雷 💥" if eng.state == "lost" else "未结束")
    frames.append((b64, f"终局：{result_txt} ｜ 共 {steps} 步"))

    if out_html is None:
        out_html = f"D:/naixi_desktop/minesweeper_agent/replay_{rows}x{cols}_{seed}.html"
    html = _build_html(frames, interval_ms, rows, cols, mines, seed, result_txt)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    return out_html, eng.state, steps


def _build_html(frames, interval_ms, rows, cols, mines, seed, result_txt):
    data = ",\n".join(f'{{"img":"{b}", "cap":"{c}"}}' for b, c in frames)
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>奶昔自主扫雷回放 {rows}x{cols}/{mines} seed{seed}</title>
<style>body{{font-family:system-ui,'Microsoft YaHei',sans-serif;background:#1e1e1e;color:#eee;margin:0;padding:16px}}
h2{{margin:0 0 8px}} .wrap{{display:flex;gap:16px;flex-wrap:wrap}}
#frame{{border:2px solid #444;border-radius:8px;background:#222;padding:4px}}
#frame img{{display:block;image-rendering:pixelated}}
#cap{{font-size:15px;margin:8px 0;color:#9fe}}
#log{{width:280px;height:520px;overflow:auto;background:#111;border:1px solid #333;border-radius:8px;padding:8px;font-size:12px;line-height:1.5}}
#log div{{border-bottom:1px solid #222;padding:2px 0}}
.btns button{{background:#333;color:#eee;border:1px solid #555;border-radius:6px;padding:6px 12px;cursor:pointer;margin-right:6px}}
.result{{font-size:20px;font-weight:700;margin-bottom:6px}}</style></head>
<body>
<h2>奶昔自主扫雷回放</h2>
<div class="result">{rows}x{cols} / {mines} 雷 ｜ seed {seed} ｜ 结果：{result_txt}</div>
<div class="btns"><button onclick="go(-1)">上一步</button><button onclick="go(1)">下一步</button>
<button onclick="toggle()">暂停/播放</button><span id="spd"></span></div>
<div class="wrap">
  <div><div id="frame"><img id="img" width="360"></div><div id="cap"></div></div>
  <div id="log"></div>
</div>
<script>
var F=[{data}];
var i=0, timer=null, playing=true;
var img=document.getElementById('img'), cap=document.getElementById('cap'), log=document.getElementById('log');
function render(){{ img.src='data:image/png;base64,'+F[i].img; cap.textContent=F[i].cap;
  var d=document.createElement('div'); d.textContent=F[i].cap; log.appendChild(d); log.scrollTop=log.scrollHeight; }}
function go(d){{ i=Math.max(0,Math.min(F.length-1,i+d)); render(); }}
function tick(){{ if(i>=F.length-1){{stop();return;}} go(1); }}
function start(){{ if(playing) timer=setInterval(tick,{interval_ms}); }}
function stop(){{ clearInterval(timer); timer=null; }}
function toggle(){{ if(timer){{stop();playing=false;}} else {{playing=true;start();}} }}
render(); start();
</script></body></html>"""


if __name__ == "__main__":
    import sys
    path, state, steps = make_replay(seed=7)
    print(f"回放已生成: {path} | 终局 {state} | {steps} 步")
