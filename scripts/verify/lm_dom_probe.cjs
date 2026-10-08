// 本地模型页 DOM 实测：等数据渲染完，数真实结果行 + 量列表可视高度。
// 教训：不要用 setTimeout + document.title 回传（回调可能不执行），
// 用 Runtime.evaluate + awaitPromise 直接拿返回值。
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const WebSocket = require("ws");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9334;
const W = 1500, H = 950;

function getJSON(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let b = ""; r.on("data", d => b += d); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on("error", rej);
  });
}

function makeCdp(wsUrl) {
  const ws = new WebSocket(wsUrl, { perMessageDeflate: false, maxPayload: 64 * 1024 * 1024 });
  let id = 0;
  const pend = new Map();
  ws.on("message", (d) => {
    const m = JSON.parse(d.toString());
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  });
  const ready = new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); });
  return {
    ready,
    send(method, params) {
      const i = ++id;
      return new Promise((res, rej) => {
        pend.set(i, (m) => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result));
        ws.send(JSON.stringify({ id: i, method, params }));
        setTimeout(() => { if (pend.has(i)) { pend.delete(i); rej(new Error("timeout " + method)); } }, 90000);
      });
    },
    close: () => ws.close(),
  };
}

const SCRIPT = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const findTitle = () => Array.from(document.querySelectorAll('p'))
    .find(x => (x.innerText||'').trim() === '本地模型');
  for (let i = 0; i < 20; i++) {
    const b = Array.from(document.querySelectorAll('button'))
      .find(x => (x.innerText||'').trim() === '本地模型');
    if (b) { b.click(); break; }
    await sleep(400);
  }
  for (let i = 0; i < 25; i++) { if (findTitle()) break; await sleep(400); }
  const rowSel = 'div.last\\\\:border-0.shrink-0';
  let rows = [];
  for (let i = 0; i < 40; i++) {
    rows = Array.from(document.querySelectorAll(rowSel));
    if (rows.length >= 3) break;
    await sleep(500);
  }
  const title = findTitle();
  const rootBox = title ? title.closest('.h-full') : null;
  const mainRow = rootBox && rootBox.children[2] ? rootBox.children[2] : null;
  const cols = mainRow ? Array.from(mainRow.children).map(c => {
    const sc = c.querySelector('div.overflow-y-auto');
    return {
      cls: (c.className||'').toString().slice(0, 40),
      h: c.clientHeight,
      scH: sc ? sc.clientHeight : null,
      scScrollH: sc ? sc.scrollHeight : null,
      scKids: sc ? sc.children.length : null,
      headH: c.firstElementChild ? c.firstElementChild.clientHeight : null,
    };
  }) : [];
  const inView = rows.filter(r => {
    const p = r.closest('div.overflow-y-auto');
    if (!p) return false;
    const b = r.getBoundingClientRect(), pb = p.getBoundingClientRect();
    return b.top >= pb.top - 2 && b.bottom <= pb.bottom + 2;
  }).length;
  return {
    viewport: { w: innerWidth, h: innerHeight },
    rowCount: rows.length,
    rowH: rows[0] ? rows[0].clientHeight : null,
    rowsInView: inView,
    cols,
    totalText: (document.body.innerText.match(/共\\s*[\\d,]+\\s*条/) || [null])[0],
  };
})()`;

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), "edge-p-"));
  const child = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
    `--window-size=${W},${H}`,
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDir}`,
    "about:blank",
  ], { stdio: "ignore" });

  let targets = null;
  for (let i = 0; i < 25; i++) {
    await new Promise(r => setTimeout(r, 700));
    try { targets = await getJSON(`http://127.0.0.1:${PORT}/json/list`); if (targets && targets.length) break; } catch (e) {}
  }
  if (!targets || !targets.length) { console.log("EDGE_FAIL"); child.kill(); process.exit(2); }

  const page = targets.find(t => t.type === "page") || targets[0];
  const c = makeCdp(page.webSocketDebuggerUrl);
  await c.ready;
  await c.send("Page.enable", {});
  await c.send("Runtime.enable", {});
  await c.send("Page.navigate", { url: "http://127.0.0.1:1420/" });
  await new Promise(r => setTimeout(r, 6000));

  let out = null;
  try {
    const r = await c.send("Runtime.evaluate", { expression: SCRIPT, awaitPromise: true, returnByValue: true });
    out = r.result?.value;
  } catch (e) { out = { error: String(e).slice(0, 150) }; }

  child.kill();
  c.close();
  try { fs.rmSync(userDir, { recursive: true, force: true }); } catch (e) {}

  if (!out) { console.log("NO_RESULT"); process.exit(3); }
  if (out.error) { console.log("ERR:", out.error); process.exit(4); }
  console.log("视口:", out.viewport && `${out.viewport.w}x${out.viewport.h}`);
  console.log("结果行总数:", out.rowCount, "| 单行高:", out.rowH, "px");
  console.log("实际可见行数:", out.rowsInView, out.rowsInView >= 3 ? "✓ 正常" : "✗ 偏少");
  console.log("页面统计:", out.totalText);
  (out.cols || []).forEach((c2, i) => {
    console.log(`  col${i} h=${c2.h} | 头部=${c2.headH} | 列表可见=${c2.scH} 内容=${c2.scScrollH} 子项=${c2.scKids}`);
    console.log(`       ${c2.cls}`);
  });
})();
