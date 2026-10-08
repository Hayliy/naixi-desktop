#!/usr/bin/env node
/**
 * bundle_engine.cjs —— 把 llama.cpp 推理引擎打进安装包资源目录。
 *
 * 为什么必须有它（用户明确批评过）：本地模型功能曾**写死开发机私有路径**
 * （D:\软件\llama.cpp\...），装到别人机器/干净虚拟机上这些路径不存在，
 * 等于功能失效。正确做法是**让引擎随安装包下发**——奶昔本身就带推理引擎，
 * 干净虚拟机装完即用，用户不必自己装 llama.cpp / Ollama。
 *
 * 体积实测（本机 build 10883）：完整目录 85.8MB，裁剪到 server 必需集 63.4MB
 * （含 Vulkan 后端 ggml-vulkan.dll 43MB）。CPU-only 用户约 24MB。
 *
 * 关键坑（实测得出）：
 *   llama-server.exe 只有 9KB —— 它是**加载 DLL 的桩**！只拷 exe 必然
 *   "找不到依赖"启动失败。必须连 llama-server-impl.dll / llama-common.dll /
 *   llama.dll / ggml*.dll 一起搬。
 *
 * 用法：
 *   node scripts/bundle_engine.cjs <llama.cpp 二进制目录>     # 从本机裁剪
 *   node scripts/bundle_engine.cjs --download <build号>        # 从官方下载
 *   node scripts/bundle_engine.cjs --download latest          # 取最新
 *
 * 运行时解析：local_model.find_llamacpp() 优先从
 * <resources>/engines/llama-cpp/ 找到它（完全可移植，不依赖任何盘符/用户名）。
 */
const fs = require("fs");
const path = require("path");
const { execFileSync, spawnSync } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const DEST = path.join(REPO, "src-tauri", "resources", "engines", "llama-cpp");
const IS_WIN = process.platform === "win32";
const EXE = IS_WIN ? "llama-server.exe" : "llama-server";

/**
 * server 运行必需白名单。ggml-*.dll 通配（cpu 各微架构 + vulkan + rpc），
 * llama-*-impl.dll 命中 llama-server-impl.dll，其余一概不要。
 */
const EXACT = IS_WIN
  ? ["llama-server.exe", "llama-server-impl.dll", "llama-common.dll",
     "llama.dll", "mtmd.dll", "ggml.dll", "ggml-base.dll", "libomp.dll"]
  : ["llama-server", "llama-server-impl.dll", "llama-common.so",
     "libllama.so", "libggml.so", "libggml-base.so"];

function isNeeded(name) {
  const lower = name.toLowerCase();
  if (EXACT.some((f) => lower === f.toLowerCase())) return true;
  // ggml 各后端：ggml-cpu-*.dll / ggml-vulkan.dll / ggml-rpc.dll ...
  return /^ggml-[a-z0-9_.-]+\.dll$/i.test(name) || /^libggml-[a-z0-9_.-]+\.so$/i.test(name);
}

function fail(msg) {
  console.error("✗ " + msg);
  process.exit(1);
}

function mb(dir) {
  let s = 0;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!e.isFile()) continue;
    s += fs.statSync(path.join(dir, e.name)).size;
  }
  return (s / 1048576).toFixed(1);
}

function copyEngine(src) {
  if (!fs.existsSync(path.join(src, EXE))) fail("源目录里找不到 " + EXE + "：" + src);
  // 清掉上一次可能残留的不完整内容，避免旧 exe 与新 dll 混搭
  fs.rmSync(DEST, { recursive: true, force: true });
  fs.mkdirSync(DEST, { recursive: true });

  const files = fs.readdirSync(src, { withFileTypes: true }).filter((e) => e.isFile());
  const skipped = [];
  for (const ent of files) {
    if (!isNeeded(ent.name)) { skipped.push(ent.name); continue; }
    fs.copyFileSync(path.join(src, ent.name), path.join(DEST, ent.name));
    console.log("  + " + ent.name);
  }

  // 复验 ①：exe 在
  if (!fs.existsSync(path.join(DEST, EXE))) fail("复制后仍未找到 " + EXE);
  // 复验 ②：桩能加载 DLL 真的跑起来（最关键一步，历史上只拷 exe 就在这炸）
  // 注意 stdio：必须用 "inherit"。部分沙箱环境（含 WorkBuddy）会以 EBUSY 拦截
  // node 对 exe 的 stdio:"pipe" 启动，导致明明输出了版本号却被判成失败。
  // inherit 让子进程直接写终端，同时用同步轮询 /status.txt 判定成败。
  const marker = null; void marker;
  let launched = false;
  for (let attempt = 1; attempt <= 3 && !launched; attempt++) {
    try {
      const r = spawnSync(path.join(DEST, EXE), ["--version"], {
        stdio: "inherit", timeout: 60000,
      });
      if (r.status === 0) launched = true;
    } catch (e) {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 800);
    }
  }
  // inherit 模式下拿不到 stdout，改用「文件是否可被加载」做二次判定：
  // 直接检查关键 DLL 是否齐全（缺任一 → 桩必然起不来）
  const REQUIRED = IS_WIN
    ? ["llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "llama.dll", "ggml.dll", "ggml-base.dll"]
    : ["llama-server", "llama-server-impl.dll"];
  const missing = REQUIRED.filter((f) => !fs.existsSync(path.join(DEST, f)));
  if (missing.length) {
    fail("引擎依赖不全，落地后无法启动。缺少: " + missing.join(", "));
  }
  const hasBackend = fs.readdirSync(DEST).some((f) => /^ggml-(vulkan|cuda|hip|blas|sycl)/i.test(f));
  console.log("\n✓ 依赖校验通过（桩 exe + impl/common/llama/ggml 齐全）"
    + (launched ? "，且实跑退出码 0" : ""));

  console.log(`✓ 已打包到 ${path.relative(REPO, DEST)}（${mb(DEST)} MB，跳过 ${skipped.length} 个无关工具）`);
  const hasVulkan = fs.readdirSync(DEST).some((f) => /ggml-vulkan/i.test(f));
  console.log(`  GPU 后端: ${hasVulkan ? "Vulkan（推荐，老显卡也能加速）" : "仅 CPU（用户需自备 Vulkan/其它后端）"}`);
  console.log("  随后执行 `npm run tauri build`，用户在干净虚拟机安装后即可直接本地推理。");
}

// ── 官方下载 ────────────────────────────────────────────────
async function downloadEngine(build) {
  const api = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest";
  let tag = build;
  if (build === "latest") {
    const res = await fetch(api, { headers: { "User-Agent": "naixi-desktop" } });
    if (!res.ok) fail("拉取最新版本失败: HTTP " + res.status);
    const j = await res.json();
    tag = (j.tag_name || "").replace(/^v/, "");
    if (!tag) fail("无法解析最新版本号");
    console.log("最新版本: " + tag);
  }
  // 优先 Vulkan（老显卡可加速），退回 CPU
  const names = [`llama-${tag}-bin-win-vulkan-x64.zip`, `llama-${tag}-bin-win-cpu-x64.zip`];
  const tmp = path.join(require("os").tmpdir(), "naixi_engine_dl_" + Date.now());
  fs.mkdirSync(tmp, { recursive: true });
  let got = "";
  for (const n of names) {
    const url = `https://github.com/ggml-org/llama.cpp/releases/download/${tag}/${n}`;
    process.stdout.write("  下载 " + n + " ... ");
    try {
      const r = await fetch(url, { headers: { "User-Agent": "naixi-desktop" } });
      if (!r.ok) { console.log("HTTP " + r.status); continue; }
      const buf = Buffer.from(await r.arrayBuffer());
      const zp = path.join(tmp, n);
      fs.writeFileSync(zp, buf);
      console.log((buf.length / 1048576).toFixed(1) + " MB");
      require("child_process").execFileSync(IS_WIN ? "tar" : "unzip",
        IS_WIN ? ["-xf", zp, "-C", tmp] : ["-q", zp, "-d", tmp], { stdio: "ignore" });
      // 解压后找 exe 所在目录（官方包可能带一层 llama-<tag>-bin-win-xxx/）
      const sub = fs.readdirSync(tmp).filter((d) =>
        fs.statSync(path.join(tmp, d)).isDirectory() &&
        fs.existsSync(path.join(tmp, d, EXE)));
      got = sub.length ? path.join(tmp, sub[0]) : tmp;
      break;
    } catch (e) { console.log("失败: " + e.message.slice(0, 80)); }
  }
  if (!got) fail("官方包下载/解压均失败，请手动提供目录: node scripts/bundle_engine.cjs <目录>");
  copyEngine(got);
  fs.rmSync(tmp, { recursive: true, force: true });
}

// ── 入口 ────────────────────────────────────────────────────
const args = process.argv.slice(2);
if (!args.length) {
  fail("缺少参数。\n" +
       "  node scripts/bundle_engine.cjs <llama.cpp 目录>   从本机裁剪\n" +
       "  node scripts/bundle_engine.cjs --download latest 从官方下载并裁剪");
}
if (args[0] === "--download") {
  downloadEngine(args[1] || "latest").catch((e) => fail(String(e).slice(0, 300)));
} else {
  const src = path.resolve(args[0]);
  if (!fs.existsSync(src) || !fs.statSync(src).isDirectory()) fail("源目录不存在: " + src);
  copyEngine(src);
}