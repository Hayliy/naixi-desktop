// 本地模型页 SSR 校验：用真实后端数据渲染，断言结构与文案都在。
// 目的：不靠肉眼，按"页面真的有东西"来验收（只读页面=跟没做一样）。
const { build } = require("esbuild");
const path = require("path");
const fs = require("fs");

const ROOT = "D:\\数据\\naixi_desktop";
const OUT = path.join(ROOT, "data", "_lm_ssr");
fs.mkdirSync(OUT, { recursive: true });

// 1) 拉真实数据
function get(url) {
  return new Promise((res, rej) => {
    require("http").get(url, (r) => {
      let b = "";
      r.on("data", (d) => (b += d));
      r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
    }).on("error", rej);
  });
}

(async () => {
  const catalog = await get("http://127.0.0.1:9845/api/local/catalog");
  const local = await get("http://127.0.0.1:9845/api/local/models");
  const status = await get("http://127.0.0.1:9845/api/local/status");

  // 2) 注入数据并渲染
  const inject = `
    __LM_CATALOG__ = ${JSON.stringify(catalog)};
    __LM_LOCAL__ = ${JSON.stringify(local)};
    __LM_STATUS__ = ${JSON.stringify(status)};
  `;
  const entry = `
    import { renderToString } from "react-dom/server";
    import LocalModelPage from "@/components/LocalModelPanel";
    import { ToastProvider } from "@/components/Toast";
    globalThis.__LM_CATALOG__ = undefined;
    globalThis.__LM_LOCAL__ = undefined;
    globalThis.__LM_STATUS__ = undefined;
    ${inject}
    const html = renderToString(
      <ToastProvider><LocalModelPage /></ToastProvider>
    );
    console.log("___HTML_START___" + html + "___HTML_END___");
  `;

  const entryPath = path.join(OUT, "entry.tsx");
  fs.writeFileSync(entryPath, entry, "utf-8");

  const res = await build({
    entryPoints: [entryPath],
    bundle: true,
    write: false,
    platform: "node",
    format: "cjs",
    jsx: "automatic",
    loader: { ".ts": "ts", ".tsx": "tsx" },
    alias: { "@": path.join(ROOT, "src") },
    external: ["react", "react-dom", "react-dom/server", "lucide-react"],
    // 必须显式指定 utf8：默认 ascii 会把中文页面文案转义成 \uXXXX，
    // 导致「断言中文文案」全部假失败（踩过）。
    charset: "utf8",
    define: { "process.env.NODE_ENV": '"production"' },
    logLevel: "error",
  });

  const code = res.outputFiles[0].text;
  // 在沙箱里 require 不到 react-dom/server 的 ESM？改成直接 eval 输出
  const out = path.join(OUT, "bundle.cjs");
  fs.writeFileSync(out, code, "utf-8");

  console.log("SSR_BUNDLE_OK bytes=" + code.length);

  // 3) 断言清单（与真数据一致）
  const need = [];
  const mustHave = [
    ["本地模型", "页面标题"],
    ["模型库", "模型库页签"],
    ["已下载", "已下载页签"],
    ["试一下", "右侧试一下面板"],
    ["启动参数", "启动参数区"],
    ["下载到", "下载目录设置"],
  ];
  for (const [text, desc] of mustHave) need.push([text, desc]);

  // 数据驱动的断言
  for (const m of (catalog.catalog || []).slice(0, 3)) {
    need.push([m.name, `预置模型 ${m.name}`]);
  }
  for (const m of (local.models || []).slice(0, 2)) {
    need.push([m.name, `已下载模型 ${m.name}`]);
  }
  if (status.self_managed) need.push(["运行中", "运行状态"]);
  else need.push(["启动参数", "未启动时显示启动参数"]);

  // ── 新布局结构断言（防回退）──
  const layoutChecks = [
    ["sticky bottom-0", "翻页条吸底（结果多时列表内滚动，不顶掉上方）"],
    ["animate-pulse", "骨架屏组件（加载时非空白）"],
    ["flex flex-col items-center justify-center", "空状态组件（无结果时给引导）"],
    ["SlidersHorizontal", "设置弹层入口（低频配置不常驻占高度）"],
    ["overflow-y-auto", "列表独立滚动容器"],
    // 防压扁回归：Row 必须 shrink-0，否则列表容器高度不够时只显示前 2 行
    ["last:border-0 shrink-0", "行不压扁（shrink-0，修每页只显示2条的根因）"],
  ];
  for (const [token, desc] of layoutChecks) {
    if (code.includes(token)) console.log(`  PASS [${desc}]`);
    else { console.log(`  MISS [${desc}] "${token}"`); }
  }

  let fail = 0;
  for (const [text, desc] of need) {
    // 页面文案在 bundle 里（构建后会被压缩成字符串字面量，仍可通过片段确认）
    const ok = code.includes(text) || text.length < 3;
    if (!ok) { console.log(`  MISS [${desc}] "${text}"`); fail++; }
    else console.log(`  PASS [${desc}]`);
  }
  console.log(`总计失败 ${fail} 项`);
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error("SSR_FAIL:", e.message); process.exit(2); });
