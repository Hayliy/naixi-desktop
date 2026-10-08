// 抓真实页面发出的 /api/local/search 请求参数 + 返回体关键字段
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const WebSocket = require("ws");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9353;

function getJSON(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let b = ""; r.on("data", d => b += d); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on("error", rej);
  });
}
function makeCdp(wsUrl) {
  const ws = new WebSocket(wsUrl, { perMessageDeflate: false, maxPayload: 64 * 1024 * 1024 });
  let id = 0; const pend = new Map();
  const handlers = [];
  ws.on("message", (d) => {
    const m = JSON.parse(d.toString());
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    else if (m.method) { handlers.forEach((h) => h(m)); }
  });
  const ready = new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); });
  return {
    ready,
    onEvent: (fn) => handlers.push(fn),
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
  const rowSel = 'div.last\\\\:border-0.shrink-0';
  const rowsNow = () => Array.from(document.querySelectorAll(rowSel));
  const btnByText = (t) => Array.from(document.querySelectorAll('button')).find(b => (b.innerText||'').trim() === t);
  const countLine = () => (document.body.innerText.match(/本页[^\\n]*/g) || [])[0] || null;
  const pageLine = () => (document.body.innerText.match(/\\d+\\s*\\/\\s*\\d+\\+?/g) || [])[0] || null;
  const noteLine = () => (document.body.innerText.match(/≤[\\d.]+GB (是|的模型)[^\\n]*/g) || [])[0] || null;
  // ★ 必须等"内容真的变了"，不能等"行数稳定"。
  //   切档位后后端要顺序扫十几页上游（5~15 秒），这期间行数一直是旧的稳定值，
  //   等稳定会立刻返回 → 读到切换前的旧数据，误判成"档位没生效"（真踩过）。
  const waitChange = async (oldNames, budget = 60) => {
    for (let i = 0; i < budget; i++) {
      await sleep(500);
      const names = rowsNow().map(r => (r.innerText||'').split('\\n')[0]);
      if (names.length && names.join('|') !== oldNames) return true;
    }
    return false;
  };
  const settle = async () => { let last=-1; for (let i=0;i<70;i++){ await sleep(500); const n=rowsNow().length; if(n>0&&n===last) return; last=n; } };
  window.__names = () => rowsNow().map(r => (r.innerText||'').split('\\n')[0]);
  window.__waitChange = waitChange;
  window.__snap = () => ({ ui: countLine(), page: pageLine(), rows: rowsNow().length, note: noteLine(),
                           names: window.__names().slice(0, 4) });

  for (let i=0;i<20;i++){ const b=btnByText('本地模型'); if(b){b.click();break;} await sleep(400); }
  for (let i=0;i<25;i++){ if(document.body.innerText.indexOf('本地模型')>=0) break; await sleep(400); }
  await settle();
  return { initial: window.__snap() };
})()`;

(async () => {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), "edge-net-"));
  const child = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
    "--window-size=1500,950", `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDir}`, "about:blank",
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
  await c.send("Page.enable", {}); await c.send("Runtime.enable", {}); await c.send("Network.enable", {});

  // ★ 用 CDP Network 域抓真实请求：前端 apiGet 走的是 XHR/axios，
  //   在页面里 monkey-patch window.fetch 抓不到（第一版就因此测了个空，
  //   误以为"档位没生效"）。Network.requestWillBeSent 是 notification，
  //   必须监听 ws 消息，不能靠 send() 的返回值。
  const reqs = [];
  c.onEvent((m) => {
    if (m.method === "Network.requestWillBeSent") {
      const u = (m.params && m.params.request && m.params.request.url) || "";
      if (u.indexOf("/api/local/search") >= 0) {
        reqs.push(u.replace(/^https?:\/\/[^/]+/, ""));
      }
    }
  });
  await c.send("Network.enable", {});

  await c.send("Page.navigate", { url: "http://127.0.0.1:1420/" });
  await new Promise(r => setTimeout(r, 7000));

  const ev = async (expr) => {
    const r = await c.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    return r.result?.value;
  };
  const init = await ev(SCRIPT);

  // 点 ≤8GB：等内容真的变化（后端要扫十几页上游）
  const tierRes = await ev(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText||'').trim() === '≤8GB');
    if (!b) return 'no-tier-button';
    const before = window.__names().join('|');
    b.click();
    await sleep(1000);
    const changed = await window.__waitChange(before, 80);
    await sleep(1200);
    return { changed, snap: window.__snap() };
  })()`);
  const afterTier = tierRes && tierRes.snap ? tierRes : { raw: tierRes };

  // 翻第 2 页
  const pageRes = await ev(`(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const b = Array.from(document.querySelectorAll('button')).find(x => (x.innerText||'').trim() === '下一页');
    if (!b || b.disabled) return 'no-next';
    const before = window.__names().join('|');
    b.click();
    await sleep(1000);
    const changed = await window.__waitChange(before, 60);
    await sleep(1200);
    return { changed, snap: window.__snap() };
  })()`);
  const afterPage = pageRes && pageRes.snap ? pageRes : { raw: pageRes };

  child.kill(); c.close();
  try { fs.rmSync(userDir, { recursive: true, force: true }); } catch (e) {}

  console.log("=== 初始 ==="); console.log(JSON.stringify(init && init.initial || init, null, 2));
  console.log("=== 点 ≤8GB 后 ==="); console.log(JSON.stringify(afterTier, null, 2));
  console.log("=== 翻到第 2 页 ==="); console.log(JSON.stringify(afterPage, null, 2));
  console.log("=== 真实请求（CDP Network 域） ===");
  reqs.forEach(r => console.log(" ", r));
})();