/**
 * GatewayPanel 真实 SSR 渲染验证（2026-10-04）
 *
 * 目的：类型检查 + 文案存在性检查都抓不到「DOM 结构错乱/ 渲染崩溃 /
 * 空数据分支没走到」这类问题。这里用 react-dom/server 把组件真渲染成 HTML 字符串，
 * 数据直接来自后端真实响应。
 *
 * 跑法（需先起后端 9845 + dist 静态服务，或只用 node 直接跑）：
 *   cd D:/naixi_desktop
 *   node scripts/verify/gw_ssr_check.cjs
 *
 * 注：组件是 TSX，这里用 esbuild（项目已有 vite 自带）先转译再require。
 */
const path = require("path");
const fs = require("fs");

const ROOT = path.join(__dirname, "..", "..");
const OUT = path.join(ROOT, "node_modules", ".gw_ssr_tmp");
fs.mkdirSync(OUT, { recursive: true });

// ── 1. 用项目自带的 esbuild 把 TSX 转成 CJS ──────────────────────────
const esbuild = require(path.join(ROOT, "node_modules", "esbuild"));
const entry = path.join(ROOT, "src", "components", "GatewayPanel.tsx");

// stub 必须写成 **ESM**（用 export const）——若写成 CommonJS（exports.x =），
// esbuild 对跨文件具名导入的解析会失败并把调用编译成 `(void 0)()`。
const stubToast = `
export const useToast = () => ({ notify: () => {} });
export const ToastProvider = ({ children }) => children;
`;
const apiShim = `
const real = global.fetch;
export const API_BASE = "http://127.0.0.1:9845";
export async function apiGet(p) {
  const r = await real("http://127.0.0.1:9845" + p, { signal: (new AbortController()).signal });
  return JSON.parse(await r.text());
}
export async function apiPost(p, b) {
  const r = await real("http://127.0.0.1:9845" + p, {
    method: "POST", body: JSON.stringify(b || {}),
    headers: { "Content-Type": "application/json" },
    signal: (new AbortController()).signal,
  });
  return JSON.parse(await r.text());
}
`;

// stub 必须**在 build 之前**落盘
fs.writeFileSync(path.join(OUT, "toast_stub.js"), stubToast);
fs.writeFileSync(path.join(OUT, "api_shim.js"), apiShim);

// 组件里是 "@/lib/api" / "@/components/Toast"。用 esbuild 的 alias 选项
// （支持绝对路径 key），比手改源码可靠 —— 改源码写"D:/xxx" 在 platform:node 下
// 会被当 unresolved external，编译出 `(void 0)()`。
function build() {
  return esbuild.buildSync({
    entryPoints: [entry],
    bundle: true,
    write: false,
    format: "cjs",
    platform: "node",
    jsx: "automatic",
    // React 必须 external —— 内联一份会导致 bundle 与 renderer 各持一份副本，
    // hooks 直接报 "Invalid hook call"
    external: ["react", "react-dom", "react-dom/server", "react/jsx-runtime", "lucide-react"],
    alias: {
      "@/lib/api": path.join(OUT, "api_shim.js"),
      "@/components/Toast": path.join(OUT, "toast_stub.js"),
    },
    loader: { ".ts": "ts", ".tsx": "tsx" },
    // 必须关掉 tree shaking：跨模块时 esbuild 会把 `useToast()` 当可能的
    // 纯函数调用而删掉导入，编译出 `(void 0)()`。
    treeShaking: false,
    minify: false,
    logLevel: "silent",
  }).outputFiles[0].text;
}

(async () => {
  const fails = [];
  const need = (cond, msg) => {
    console.log((cond ? "  OK   " : "  MISS ") + msg);
    if (!cond) fails.push(msg);
  };

  // ── 2. mock 掉 api，让 fetch 打真实后端 ─────────────────────────────
  const realFetch = global.fetch;
  const ApiCalls = [];
  global.fetch = async (url, init) => {
    const full = String(url).startsWith("http") ? String(url) : "http://127.0.0.1:9845" + url;
    ApiCalls.push({ url: full, method: (init && init.method) || "GET" });
    return realFetch(full, init);
  };

  const React = require("react");
  const ReactDOMServer = require("react-dom/server");

  // ── 3. 渲染：真实后端数据（peer 为空的场景）─────────────────────
  fs.writeFileSync(path.join(OUT, "gw_ssr_bundle.js"), build());
  const mod = require(path.join(OUT, "gw_ssr_bundle.js"));
  const GatewayPage = mod.default || mod.GatewayPage;

  // SSR 不跑 useEffect，组件永远停在 loading。要验证「数据进来后渲染成什么样」，
  // 就再构建一个**注入真实数据**的变体：把 useState 初值替换成字面量数据、
  // loading 初值改 false。数据来自真实后端响应，不是 mock。
  // 注意 esbuild 输出的是 `(0, import_react.useState)(null)` 这种形态，
  // 替换串必须与之一字不差，否则静默不命中（踩过一次）。
  async function renderWithRealData(st, caps) {
    const base = build();
    const subs = [
      ['(0, import_react.useState)(null)', `(0, import_react.useState)(${JSON.stringify(st)})`],
      ['(0, import_react.useState)([])', `(0, import_react.useState)(${JSON.stringify(caps)})`],
      ['(0, import_react.useState)(true)', '(0, import_react.useState)(false)'],
    ];
    let variant = base;
    for (const [from, to] of subs) {
      if (!variant.includes(from)) {
        console.log(`  WARN 未命中替换串: ${from}`);
        continue;
      }
      variant = variant.replace(from, to);
    }
    const p = path.join(OUT, `gw_ssr_variant_${Date.now()}.js`);
    fs.writeFileSync(p, variant);
    const vmod = require(p);
    const C = vmod.default || vmod.GatewayPage;
    return ReactDOMServer.renderToStaticMarkup(
      React.createElement(React.Fragment, null, React.createElement(C))
    );
  }

  console.log("=== SSR 渲染 GatewayPage（真实后端数据）===");
  const html = ReactDOMServer.renderToStaticMarkup(
    React.createElement(React.Fragment, null, React.createElement(GatewayPage))
  );

  need(html.length > 100, `渲染出 HTML（${html.length} 字符）`);
  need(!/Error|错误|Cannot read/i.test(html), "无错误信息混入 DOM");
  // SSR 不跑 useEffect，所以首屏必然是 loading 态 —— 这本身是正确的
  need(html.includes("animate-spin"), "SSR 首屏为 loading 态（useEffect 未执行，符合预期）");
  console.log("  注：SSR 不执行 useEffect，数据加载要靠浏览器。已另用数据层脚本验证真实取数。");

  // ── 关键：手动跑一次真实取数+ 状态推导，证明数据进来后内容正确 ──
  console.log();
  console.log("=== 组件加载完成后的内容（用真实后端数据复算渲染树）===");
  const st = await (await fetch("http://127.0.0.1:9845/api/gateway/status")).json();
  const cp = await (await fetch("http://127.0.0.1:9845/api/gateway/capabilities")).json();
  const caps = cp.capabilities || [];
  const peerCount = st.peer_count ?? 0;
  const readCount = caps.filter((c) => c.trust === "read").length;
  const writeCount = caps.filter((c) => c.trust === "write").length;
  const confirmCount = caps.filter((c) => c.requires_confirm).length;
  console.log(`  真实数据: ws_started=${st.ws_started} ws_port=${st.ws_port} peers=${peerCount} caps=${caps.length}`);

  // 把真实数据注入组件的初始状态再渲染一次（绕过 useEffect）
  const html2 = await renderWithRealData(st, caps);

  const cards = [
    ["控制平面", `WS ${st.ws_port}`],
    ["已连接对端", `${peerCount} 个`],
    ["暴露能力", `${caps.length} 条`],
    ["需人工确认", `${confirmCount} 条`],
  ];
  for (const [k, v] of cards) {
    need(html2.includes(k), `状态卡「${k}」渲染（真实值 ${v}）`);
  }
  need(html2.includes(`WS ${st.ws_port}`), `显示真实 WS 端口 ${st.ws_port}`);
  need(html2.includes(`${caps.length} 条`), `显示真实能力数 ${caps.length}`);
  need(html2.includes(`${confirmCount} 条`), `显示真实需确认数 ${confirmCount}`);
  need(html2.includes(`只读 ${readCount}`), `显示只读数 ${readCount}`);
  need(html2.includes(`可写 ${writeCount}`), `显示可写数 ${writeCount}`);
  need(html2.includes(st.ws_started ? "运行中" : "未启动"),
       `控制平面状态文案正确（${st.ws_started ? "运行中" : "未启动"}）`);

  if (peerCount === 0) {
    need(html2.includes("暂无对端接入"), "无对端时走空态分支");
    need(html2.includes("独立运行中"), "显示「独立运行中」");
  } else {
    need(html2.includes(st.peers[0].provider), "渲染出首个对端名");
  }

  // ── 有 peer 的场景：当前后端无对端，这个分支还没被真实验证过。
  //    用**真实数据形状**（字段名/类型照抄上面真响应，只把 peers 填上）走一遍渲染，
  //    验证不会因为空态而漏写有对端的渲染分支。
  if (peerCount === 0) {
    console.log();
    console.log("=== 补验「有对端」分支（沿用真实响应的字段形状）===");
    const fakePeerStatus = Object.assign({}, st, {
      peer_count: 1,
      peers: [{
        provider: "qq-naixi",
        remote: "",
        subs: ["capability", "task", "event"],
        idle_s: 3.2,
      }],
    });
    const html3 = await renderWithRealData(fakePeerStatus, caps);
    need(!html3.includes("暂无对端接入"), "有对端时不再显示空态");
    need(html3.includes("qq-naixi"), "渲染出对端名 qq-naixi");
    need(html3.includes("订阅 capability/task/event"), "渲染出订阅主题");
    need(html3.includes("3 秒前"), "渲染出空闲时长（3.2s → 3 秒前）");
    need(html3.includes("1 个"), "对端计数显示 1");
    need(html3.includes("互联已建立"), "有对端时显示「互联已建立」而非独立运行中");
    console.log("  注：peer 数据为构造（当前后端确实无对端接入），字段形状照抄真实响应。");
  }

  need(html2.includes("本端能力"), "有「本端能力」区块标题");
  for (const c of caps) {
    need(html2.includes(c.id), `能力行 ${c.id} 已渲染`);
  }
  const tags = new Set();
  for (const c of caps) {
    tags.add(c.trust);
    if (c.requires_confirm) tags.add("confirm");
    if (c.kind === "channel") tags.add("channel");
  }
  for (const t of tags) {
    need(html2.includes(t === "confirm" ? "需确认" : t === "channel" ? "通道" : (t === "read" ? "只读" : "可写")),
         `标签「${t}」已渲染`);
  }
  need(html2.includes("不提供直接测试"), "write 能力按钮提示正确");

  console.log(`\n  实际发起的后端请求 (${ApiCalls.length} 条):`);
  for (const c of ApiCalls) console.log(`    ${c.method} ${c.url}`);

  console.log(`\n总计失败 ${fails.length} 项`);
  fails.forEach((f) => console.log("  FAIL:", f));

  // 留一份 HTML 供人工核对
  const htmlPath = path.join(OUT, "gateway_page.html");
  fs.writeFileSync(htmlPath, html2);
  console.log(`\n渲染结果已保存（含真实数据）: ${htmlPath}`);
  process.exit(fails.length ? 1 : 0);
})().catch((e) => {
  console.error("SSR 渲染失败:", e);
  process.exit(1);
});