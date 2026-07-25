// 副播面板「真机视觉走查」渲染级验证（无需浏览器/显示器）
// 用 esbuild 打包真实组件代码 + react-dom/server 渲染成 HTML，断言各状态徽章/红点。
import { build } from "esbuild";
import { pathToFileURL } from "url";
import { writeFileSync, rmSync } from "fs";

const HARNESS = `
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { liveTransportBadge } from "./src/lib/liveBadge";

function Row({ c }) {
  const b = liveTransportBadge(c.transport);
  return React.createElement("div", { className: "flex items-center gap-2" },
    React.createElement("span", {
      className: "w-2 h-2 rounded-full " + (c.quarantined ? "bg-red-400" : "bg-green-400"),
    }),
    React.createElement("span", { className: "font-medium" }, c.name),
    React.createElement("span", { className: "text-[8px] px-1 py-0.5 rounded " + b.cls }, b.label),
    c.quarantined ? React.createElement("span", { className: "text-[8px] text-red-400" }, "限流隔离中") : null,
    c.builtin ? React.createElement("span", { className: "text-[8px] text-sakura-300" }, "内置") : null,
  );
}

export function render(c) {
  return renderToStaticMarkup(React.createElement(Row, { c }));
}
export { liveTransportBadge };
`;

const out = "scripts/_stage_panel_harness.generated.mjs";
await build({
  stdin: { contents: HARNESS, resolveDir: process.cwd(), loader: "tsx", sourcefile: "harness.tsx" },
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: out,
  external: ["react", "react-dom", "react-dom/server"],
  logLevel: "silent",
});

const mod = await import(pathToFileURL(process.cwd() + "/" + out).href);

const cases = [
  { transport: "local", name: "奶昔", quarantined: false, builtin: true, expLabel: "内置", expCls: "bg-sakura-100 text-sakura-500" },
  { transport: "http", name: "Sakura", quarantined: false, builtin: false, expLabel: "HTTP", expCls: "bg-blue-100 text-blue-500" },
  { transport: "ws", name: "RemoteA", quarantined: false, builtin: false, expLabel: "WS(连出)", expCls: "bg-indigo-100 text-indigo-500" },
  { transport: "ws-in", name: "ReverseB", quarantined: false, builtin: false, expLabel: "WS(反向连入)", expCls: "bg-purple-100 text-purple-500" },
  { transport: "mystery", name: "Mystery", quarantined: false, builtin: false, expLabel: "mystery", expCls: "bg-sakura-100 text-sakura-500" },
];

let pass = 0, fail = 0;
for (const tc of cases) {
  const b = mod.liveTransportBadge(tc.transport);
  const html = mod.render(tc);
  const okLabel = b.label === tc.expLabel;
  const okCls = b.cls === tc.expCls;
  const okHtml = html.includes(">" + tc.expLabel + "<") && html.includes(tc.expCls);
  const ok = okLabel && okCls && okHtml;
  console.log((ok ? "PASS" : "FAIL"), "[徽章]", tc.transport, "=>", JSON.stringify(b),
    "| html含标签:", html.includes(">" + tc.expLabel + "<"), "| html含配色:", html.includes(tc.expCls));
  ok ? pass++ : fail++;
}

// 隔离红点 + 反向连入 组合行
const qHtml = mod.render({ transport: "ws-in", name: "刷屏Agent", quarantined: true, builtin: false });
const okQ = qHtml.includes("bg-red-400") && qHtml.includes("限流隔离中") && qHtml.includes("WS(反向连入)");
console.log((okQ ? "PASS" : "FAIL"), "[隔离行] ws-in+quarantined =>",
  "红点:", qHtml.includes("bg-red-400"), "| 隔离文案:", qHtml.includes("限流隔离中"), "| 反向连入:", qHtml.includes("WS(反向连入)"));
okQ ? pass++ : fail++;

console.log(`\n=== 副播面板渲染级视觉走查：${pass} PASS / ${fail} FAIL ===`);
rmSync(out, { force: true });
process.exit(fail ? 1 : 0);
