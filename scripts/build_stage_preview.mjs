// 生成副播面板「视觉走查」独立演示页（离线、不依赖 Tauri/后端）
// 用 esbuild 打包真实组件代码 + react-dom/server 渲染成 HTML，内联手写样式，
// 输出 scripts/stage_preview.html，供在浏览器直接打开查看各状态视觉。
import { build } from "esbuild";
import { pathToFileURL } from "url";
import { writeFileSync, rmSync } from "fs";

const HARNESS = `
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { liveTransportBadge } from "./src/lib/liveBadge";

function Row({ c }) {
  const b = liveTransportBadge(c.transport);
  return React.createElement("div", { className: "row flex items-center gap-2" },
    React.createElement("span", {
      className: "dot " + (c.quarantined ? "bg-red-400" : "bg-green-400"),
    }),
    React.createElement("span", { className: "name font-medium" }, c.name),
    React.createElement("span", { className: "badge text-[8px] px-1 py-0.5 rounded " + b.cls }, b.label),
    c.quarantined ? React.createElement("span", { className: "text-[8px] text-red-400" }, "限流隔离中") : null,
    c.builtin ? React.createElement("span", { className: "text-[8px] text-sakura-300" }, "内置") : null,
  );
}

export function renderPanel() {
  const cons = [
    { agent_id: "naixi", name: "奶昔(主控)", transport: "local", builtin: true, quarantined: false },
    { agent_id: "baike", name: "百科助手", transport: "http", builtin: false, quarantined: false },
    { agent_id: "danmuji", name: "弹幕姬(连出)", transport: "ws", builtin: false, quarantined: false },
    { agent_id: "reverse", name: "示例副播(反向连入)", transport: "ws-in", builtin: false, quarantined: false },
    { agent_id: "spammer", name: "刷屏怪", transport: "http", builtin: false, quarantined: true },
  ];
  return renderToStaticMarkup(
    React.createElement("div", { className: "panel" },
      cons.map((c, i) => React.createElement(Row, { key: i, c }))
    )
  );
}
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
const panelHtml = mod.renderPanel();

const CSS = `
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif; background:#f1f5f9; color:#1e293b; }
.wrap { max-width: 660px; margin: 36px auto; padding: 28px; background:#fff; border-radius:18px; box-shadow:0 6px 30px rgba(15,23,42,.08); }
h1 { font-size:21px; margin:0 0 6px; color:#0f172a; }
.sub { color:#64748b; font-size:13px; margin:0 0 6px; }
.note { color:#94a3b8; font-size:12px; margin:0 0 22px; }
.panel { display:flex; flex-direction:column; gap:10px; }
.row { display:flex; align-items:center; gap:10px; padding:11px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:11px; }
.dot { width:9px; height:9px; border-radius:9999px; flex:0 0 auto; }
.bg-green-400 { background:#4ade80; }
.bg-red-400 { background:#f87171; }
.name { font-weight:500; font-size:14px; }
.badge { font-size:11px; padding:2px 7px; border-radius:7px; font-weight:600; white-space:nowrap; }
.text-\\[8px\\] { font-size:11px; }
.px-1 { padding-left:4px; padding-right:4px; }
.py-0.5 { padding-top:2px; padding-bottom:2px; }
.rounded { border-radius:7px; }
.bg-sakura-100 { background:#ffe4ef; } .text-sakura-500 { color:#d4537e; } .text-sakura-300 { color:#f9a8d4; }
.bg-blue-100 { background:#dbeafe; } .text-blue-500 { color:#3b82f6; }
.bg-indigo-100 { background:#e0e7ff; } .text-indigo-500 { color:#6366f1; }
.bg-purple-100 { background:#f3e8ff; } .text-purple-500 { color:#a855f7; }
.text-red-400 { color:#f87171; }
`;

const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>副播面板视觉走查</title>
<style>${CSS}</style>
</head>
<body>
  <div class="wrap">
    <h1>多角色舞台 · 视觉走查</h1>
    <p class="sub">内置 / HTTP / WS(连出) / WS(反向连入) / 隔离 五态一览</p>
    <p class="note">离线演示页（不依赖 Tauri / 后端），用于核对徽章配色与隔离红点视觉。真实数据由引擎 /api/live/connectors 提供。</p>
    ${panelHtml}
  </div>
</body>
</html>`;

writeFileSync("scripts/stage_preview.html", html);
rmSync(out, { force: true });
console.log("已生成 scripts/stage_preview.html");
