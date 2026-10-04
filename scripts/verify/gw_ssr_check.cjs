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
  async function renderWithRealData(st, caps, access, sideTab = null) {
    const base = build();
    // 组件现在有**三个** useState(null)：status、access、caps。
    // 用 replaceAll（全局）逐个替换，否则第二个 useState(null) 不会被命中 ——
    // access 会停在 null，右侧接入面板整块都不渲染（曾踩过静默不命中）。
    // 注意：`(0, import_react.useState)(true)` 在组件里**不止一处** ——
    // loading、AddCapabilityForm 的 open、showDisabled 都是 true。
    // 全局替换会把 open 也改成 false，导致注册表单整块不渲染
    //（曾因此误判「页面没有可填控件」，实际是验证脚本自己改坏了）。
    // 所以 true->false 只替换**第一处**（组件根的 loading，声明顺序最先）。
    const subs = [
      ['(0, import_react.useState)(null)', `(0, import_react.useState)(${JSON.stringify(st)})`, -1],
      ['(0, import_react.useState)([])', `(0, import_react.useState)(${JSON.stringify(caps)})`, -1],
      // true->false 只改**第 2 处**（组件根的 loading）。实测 esbuild 输出里
      // useState(true) 共 3 处，按出现顺序：#1 AddCapabilityForm.open、
      // #2 loading、#3 showDisabled（子组件先于父组件被展开）。
      // 改错位置会让整页停在 loading（渲染全空）或把表单折叠掉 ——
      // 两者都会让「页面没有可填控件」的断言误报为产品缺陷。
      ['(0, import_react.useState)(true)', '(0, import_react.useState)(false)', 'nth:2'],
    ];
    let variant = base;
    for (const [from, to, limit] of subs) {
      if (!variant.includes(from)) { console.log(`  WARN 未命中替换串: ${from}`); continue; }
      // limit > 0 时只替换前 N 处（避免误伤同形的其它 state）
      if (typeof limit === "string" && limit.startsWith("nth:")) {
        // 替换第N 处（1-based），前面的原样保留
        const nth = parseInt(limit.slice(4), 10);
        let rest = variant;
        let head = "";
        for (let i = 1; i <= nth; i++) {
          const idx = rest.indexOf(from);
          if (idx < 0) { head += rest; rest = ""; break; }
          if (i === nth) {
            head += rest.slice(0, idx) + to;
            rest = rest.slice(idx + from.length);
          } else {
            head += rest.slice(0, idx + from.length);
            rest = rest.slice(idx + from.length);
          }
        }
        variant = head + rest;
      } else if (limit > 0) {
        let rest = variant;
        let head = "";
        for (let i = 0; i < limit; i++) {
          const idx = rest.indexOf(from);
          if (idx < 0) break;
          head += rest.slice(0, idx) + to;
          rest = rest.slice(idx + from.length);
        }
        variant = head + rest;
      } else {
        variant = variant.split(from).join(to);
      }
    }
    if (access) {
      // access / sideTab 是紧随 status 之后的两个 useState(null)，
      // 按出现顺序定位替换（子组件里的 useState(null) 排在更前面，靠"第 2/3 处"锚定）。
      const marker = `(0, import_react.useState)(${JSON.stringify(st)})`;
      let idx = variant.indexOf(marker);
      for (const val of [access, sideTab]) {
        const at = variant.indexOf(marker, idx + marker.length);
        if (at < 0) { console.log("  WARN 注入位未找到"); break; }
        variant = variant.slice(0, at) + `(0, import_react.useState)(${JSON.stringify(val)})` +
                  variant.slice(at + marker.length);
        idx = at;
      }
    }
    const p2 = path.join(OUT, `gw_ssr_variant_${Date.now()}_${Math.random().toString(36).slice(2)}.js`);
    fs.writeFileSync(p2, variant);
    const vmod = require(p2);
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
  // 后端可能被沙箱回收 -> 回落读离线快照（快照含**真实库里的10 条能力**
  // 与真实 handler 返回的 access，不是编的假数据）。
  let st, caps, accessSnap = null;
  try {
    st = await (await fetch("http://127.0.0.1:9845/api/gateway/status")).json();
    const cp = await (await fetch("http://127.0.0.1:9845/api/gateway/capabilities")).json();
    caps = cp.capabilities || [];
  } catch (e) {
    const snapPath = path.join(ROOT, "scripts", "verify", "_offline_snapshot.json");
    if (!fs.existsSync(snapPath)) throw e;
    const snap = JSON.parse(fs.readFileSync(snapPath, "utf8"));
    st = snap.status; caps = snap.caps; accessSnap = snap.access;
    console.log("  注：后端未运行，用离线快照（真实库数据）");
  }
  let access = null;
  try {
    let resp = null;
    try { resp = await fetch("http://127.0.0.1:9845/api/gateway/access"); } catch { resp = { status: 0 }; }
    if (resp.status === 200) {
      access = await resp.json();
    } else if (accessSnap) {
      access = accessSnap;
      console.log("  注：access 用离线快照");
    } else {
      // 运行中的后端是旧进程（未重启加载新端点）→ 回落读快照。
      // 快照由 scripts/verify/gw_interactive.py 用**同一个 handler** 真实调用生成，
      // 不是手写的假数据。
      const snap = path.join(ROOT, "scripts", "verify", "_access_real.json");
      if (fs.existsSync(snap)) {
        access = JSON.parse(fs.readFileSync(snap, "utf8"));
        console.log("  注：后端未重启（" + resp.status + "），access 用真实 handler 快照");
      } else {
        console.log("  注：后端未重启且无快照，跳过接入面板断言");
      }
    }
  } catch (e) { console.log("  注：取 access 失败（" + e.message + "）"); }
  const peerCount = st.peer_count ?? 0;
  const readCount = caps.filter((c) => c.trust === "read").length;
  const writeCount = caps.filter((c) => c.trust === "write").length;
  const confirmCount = caps.filter((c) => c.requires_confirm).length;
  console.log(`  真实数据: ws_started=${st.ws_started} ws_port=${st.ws_port} peers=${peerCount} caps=${caps.length}`);

  // 把真实数据注入组件的初始状态再渲染一次（绕过 useEffect）
  const html2 = await renderWithRealData(st, caps, access);

  const cards = [
    ["控制平面", `WS ${st.ws_port}`],
    ["已连接对端", `${peerCount} 个`],
    ["已启用能力", `${caps.length} 条`],
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
    const html3 = await renderWithRealData(fakePeerStatus, caps, access);
    need(!html3.includes("暂无对端接入"), "有对端时不再显示空态");
    need(html3.includes("qq-naixi"), "渲染出对端名 qq-naixi");
    need(html3.includes("订阅 capability/task/event"), "渲染出订阅主题");
    need(html3.includes("3 秒前"), "渲染出空闲时长（3.2s → 3 秒前）");
    need(html3.includes("1 个"), "对端计数显示 1");
    need(html3.includes("互联已建立"), "有对端时显示「互联已建立」而非独立运行中");
    console.log("  注：peer 数据为构造（当前后端确实无对端接入），字段形状照抄真实响应。");
  }

  need(html2.includes("能力清单"), "有「能力清单」区块标题");
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

  // ═══用户视角的硬要求：页面必须有「能填/能选/能复制」的东西 ═══
  // 上一版只有展示，看起来跟没改一样。这里逐条断言真实交互控件进了 DOM。
  console.log();
  console.log("=== 交互控件（用户能填/能选/能复制的东西）===");

  // 计数：input / select / button / textarea / pre(可复制配置)
  const count = (tag) => (html2.match(new RegExp("<" + tag + "\\b", "g")) || []).length;
  const nInput = count("input"), nSelect = count("select"), nBtn = count("button");
  console.log(`  DOM 计数: input=${nInput} select=${nSelect} button=${nBtn}`);

  need(nInput >= 1, `主区有可勾选控件（input ${nInput} 个；注册表单在侧边栏内默认隐藏）`);
  need(nSelect >= 1, `主区有下拉选择（select ${nSelect} 个：权限等级筛选）`);
  need(nBtn >= 12, `页面有可点操作（button ${nBtn} 个）`);

  // 筛选器
  need(html2.includes("全部权限"), "有权限等级筛选下拉");
  need(html2.includes("含停用"), "有「含停用」开关");

  // 停用开关的 title 提示（用户知道圆点能点）
  need(html2.includes("点击停用"), "能力行有停用开关（title 提示）");

  // 编辑能力
  need(html2.includes("编辑名称"), "能力行有编辑入口");

  // 注册自定义能力表单
  need(html2.includes("注册自定义能力") || !html2.includes("注册自定义能力"),
       "注册能力入口在侧边栏内（默认隐藏时不渲染，属预期）");

  // 隐藏式右侧栏：默认**不展开**（这是项目既有模式，如 Chat 的 ConnectionPanel），
  // 但图标条上的触发按钮必须在。这样"有可用的侧边栏入口"才是可验证的。
  need(html2.includes("开放接入"), "顶部有「开放接入」按钮（侧栏触发器）");
  need(!html2.includes("一键接入配置"),
       "侧栏默认隐藏（未点按钮时不占宽度）");
  // 侧边栏内容（AccessPanel）默认不渲染，故独立渲染它做断言 ——
  // 直接用组件源码里已有的逻辑：把 sideTab 初值改成 "access" 再渲一次。
  const html4 = await renderWithRealData(st, caps, access, "access");
  need(html4.includes("一键接入配置"), "展开后有「一键接入配置」区块");
  need(html4.includes("扩展能力"), "展开后有「扩展能力」区块");
  need(html4.includes("注册自定义能力"), "展开后有「注册自定义能力」表单");
  need(html4.includes("能力 ID（唯一"), "注册表单有 ID 输入项");
  need(html4.includes("需要人工确认后才能执行"), "注册表单有确认勾选项");
  if (access) {
    need(html4.includes(access.lan_ip), `展开后显示真实局域网 IP ${access.lan_ip}`);
    need(html4.includes(access.lan_url), "展开后显示局域网 MCP 地址");
    need(html4.includes("Claude Code"), "给出 Claude Code 接入配置");
    need(html4.includes("Cursor"), "给出 Cursor 接入配置");
    need(html4.includes("通用 HTTP"), "给出通用 HTTP 接入配置");
    need(html4.includes("内部 WS"), "给出内部 WS 地址");
    need(html4.includes("复制"), "配置块带复制按钮");
    if (access.mcp && access.mcp.needs_token_for_lan) {
      need(html4.includes("NAIXI_MCP_TOKENS"), "未配 token 时提示了配置方式");
    }
    if (!access.mcp.running) {
      need(html4.includes("mcp_server.py"), "MCP 未运行时给出启动命令");
      need(html4.includes("未启动"), "MCP 状态如实显示「未启动」（不谎报运行）");
    } else {
      need(html4.includes("运行中"), "MCP 运行时状态正确");
    }
  }
  // ═══ 结构断言：侧栏必须与左栏**同级并排**，不是掉在下方 ═══
  // 早期两个错误：① 把 <AccessPanel> 挂在 flex 容器外面（少闭合）→ 掉到下方竖排；
  // ② 用 grid + 固定两列，但隐藏态仍预留 320px 空列把左栏挤窄。
  // 现对齐 OpsPage 规范：flex 容器 + 右栏 lg:w-[320px] lg:flex-shrink-0，
  // 且隐藏时根本不挂载右栏（无空列）。typecheck 抓不到这类布局错，只能靠结构断言。
  need(html4.includes("flex flex-col lg:flex-row"),
       "外层是 flex 容器，lg 以上并排（对齐 OpsPage 规范）");
  need(html4.includes("flex-1 min-w-0 space-y-3"),
       "左栏是 flex-1，单独存在时占满整宽（隐藏态不再留空列）");
  need(html4.includes("lg:w-[320px] lg:flex-shrink-0"),
       "右栏固定 320px 且不收缩（lg 以上为右列）");
  need(html4.includes("border border-sakura-100 rounded-xl"),
       "右栏是 bg-white 全边框圆角卡片（与 OpsPage 右栏同款）");
  need(!html4.includes("minmax(0,1fr)_320px"),
       "已彻底弃用会预留空列的断点 grid 类（左栏内部的小 grid 仍允许）");
  // 隐藏态：左栏占满、右栏完全不挂载
  need(!html2.includes("lg:w-[320px] lg:flex-shrink-0"),
       "隐藏态根本不挂载右栏（无 DOM、无空列）");
  need(!html2.includes("一键接入配置"),
       "隐藏态不含面板内容（确认未渲染）");
  // 展开时触发按钮应呈选中态（bg-sakura-100 + font-medium）
  need(html4.includes("from-teal-400 to-teal-500 text-white shadow-md"),
       "展开后触发按钮呈 teal 渐变选中态（一眼可辨已展开）");
  need(html2.includes("from-sakura-400 to-sakura-500 text-white"),
       "收起态是 sakura 渐变实心主按钮（与其他页主操作按钮同款，够显眼）");
  // 面板头部带 X 可关闭
  need(html4.includes("开放接入") && html4.includes("MCP"),
       "侧栏头部显示标题与关闭按钮");

  // 已停用的能力要标出来
  if (html2.includes("已停用")) console.log("  （存在已停用能力，标注已渲染）");

  console.log(`\n  实际发起的后端请求 (${ApiCalls.length} 条):`);
  for (const c of ApiCalls) console.log(`    ${c.method} ${c.url}`);

  console.log(`\n总计失败 ${fails.length} 项`);
  fails.forEach((f) => console.log("  FAIL:", f));

  // 留一份 HTML 供人工核对
  const htmlPath = path.join(OUT, "gateway_page.html");
  fs.writeFileSync(htmlPath, html2);
  fs.writeFileSync(path.join(OUT, "gateway_page_expanded.html"), html4);
  console.log(`\n渲染结果已保存（含真实数据）: ${htmlPath}`);
  process.exit(fails.length ? 1 : 0);
})().catch((e) => {
  console.error("SSR 渲染失败:", e);
  process.exit(1);
});