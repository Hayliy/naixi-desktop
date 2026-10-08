#!/usr/bin/env node
/**
 * bundle_converter.cjs —— 把 HuggingFace→GGUF 转换层随包进安装包。
 *
 * 为什么（用户要求「非 gguf 也能启动 + 不依赖外部软件」）：
 *   llama.cpp 的 llama-server 只吃 GGUF。别人（Ollama/LM Studio）支持 safetensors
 *   的办法是内置一个转换层——Ollama 用 Go 重写转换；llama.cpp 官方给 Python 脚本
 *   convert_hf_to_gguf.py（依赖 torch + conversion/ 模块 + gguf 包）。
 *   奶昔复用官方脚本随包，让本地模型页所有 safetensors 模型也能一键转 GGUF 启动。
 *
 * 用户已拍板：**torch 随包（全架构）**。即转换层自带 torch(CPU)，支持所有架构，
 * 最稳；代价是安装包 +约 800MB（torch 体积）。用户在操作上无需安装任何外部软件。
 *
 * 路线确认（2026-10-06）：在 llama.cpp 生态下「支持所有架构」与「零外部库体积」
 * 二者不可兼得——官方脚本顶部直接 import torch，剥离 torch 需自研转换（仅覆盖主流
 * 架构）。故选 torch 随包以达成「所有类型全部支持」。
 *
 * 用法：
 *   node scripts/bundle_converter.cjs              # 优先用本机 llama.cpp 源码树
 *   node scripts/bundle_converter.cjs --download   # 强制从 GitHub 下载
 *   node scripts/bundle_converter.cjs --src <dir>  # 指定本机 llama.cpp 源码目录
 *   node scripts/bundle_converter.cjs --tag b11435 # 下载时固定版本（与引擎一致）
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const os = require("os");

const REPO = path.resolve(__dirname, "..");
const DEST = path.join(REPO, "src-tauri", "resources", "engines", "convert");
const PY = path.join(REPO, "src-tauri", "resources", "python-embed", "python.exe");
const IS_WIN = process.platform === "win32";

function fail(msg) {
  console.error("✗ " + msg);
  process.exit(1);
}
function run(cmd, args, opts) {
  const r = spawnSync(cmd, args, Object.assign({ stdio: "inherit" }, opts || {}));
  if (r.error) fail("命令失败: " + cmd + " " + (args || []).join(" ") + " -> " + r.error.message);
  if (r.status !== 0) fail("命令退出码 " + r.status + ": " + cmd + " " + (args || []).join(" "));
  return r;
}
async function fetchBuffer(url) {
  const res = await fetch(url, { headers: { "User-Agent": "naixi-desktop" } });
  if (!res.ok) fail("下载失败 HTTP " + res.status + ": " + url);
  return Buffer.from(await res.arrayBuffer());
}
function copyDir(s, d) {
  fs.mkdirSync(d, { recursive: true });
  for (const e of fs.readdirSync(s, { withFileTypes: true })) {
    const sp = path.join(s, e.name), dp = path.join(d, e.name);
    if (e.isDirectory()) copyDir(sp, dp);
    else fs.copyFileSync(sp, dp);
  }
}

/** 本机是否已有 llama.cpp 源码树（含 convert_hf_to_gguf.py）。
 *  开发机/构建机上常常已经 clone 过（用户本机实测在 D:\数据\llama_src\llama.cpp-*），
 *  优先复用可省一次大体积下载，也避开构建时 GitHub 不通的问题。
 *  按约定不写死私人盘符：从环境变量 + 常见相对位置推导，找不到就回退下载。 */
function findLocalLlamaSrc() {
  const envDir = process.env.NAIXI_LLAMACPP_SRC;
  const cands = [];
  if (envDir) cands.push(envDir);
  // 项目内或相邻数据目录下的 llama.cpp 源码树
  cands.push(path.join(REPO, "src-tauri", "resources", "engines", "llama-cpp-src"));
  cands.push(path.join(REPO, "..", "llama_src"));
  for (const d of cands) {
    try {
      const abs = path.resolve(d);
      if (fs.existsSync(path.join(abs, "convert_hf_to_gguf.py"))) return abs;
    } catch {}
  }
  return null;
}

/** 从本机源码树拷贝（不联网）。与官方 tarball 同构的目录布局：
 *  convert_hf_to_gguf.py + conversion/（早期版本叫 convert/，两种都认）。 */
function copyFromLocalSrc(src) {
  console.log("使用本机 llama.cpp 源码树: " + src);
  fs.rmSync(DEST, { recursive: true, force: true });
  fs.mkdirSync(DEST, { recursive: true });
  fs.copyFileSync(path.join(src, "convert_hf_to_gguf.py"), path.join(DEST, "convert_hf_to_gguf.py"));
  console.log("  + convert_hf_to_gguf.py");
  // ★ 官方 import 的是 `from conversion import ...`，所以真实包名是 conversion/
  //   （老版本才是 convert/）。两种都认，避免版本差异导致转换残缺。
  for (const name of ["conversion", "convert"]) {
    const d = path.join(src, name);
    if (fs.existsSync(d)) {
      copyDir(d, path.join(DEST, name));
      // 剔掉 __pycache__（含 .pyc，且可能是别的 Python 版本编译产物）
      const pc = path.join(DEST, name, "__pycache__");
      if (fs.existsSync(pc)) fs.rmSync(pc, { recursive: true, force: true });
      console.log("  + " + name + "/ (官方转换逻辑模块)");
      copyGgufPy(src);
      return;
    }
  }
  fail("本机源码树里没有 conversion/ 或 convert/ 模块目录，转换会不完整");
}

/** 随包 gguf-py —— 转换层的 gguf 读写实现。
 *  ★ 必须与 conversion/ **同源同版本**：官方脚本默认会优先插「脚本同目录的 gguf-py」。
 *    若缺它或改用 PyPI 的 gguf(0.19.0)，会因枚举落后而报
 *    "MODEL_ARCH has no attribute 'DFLASH'"。所以这是必需件，不是可选件。 */
function copyGgufPy(src) {
  const gp = path.join(src, "gguf-py");
  if (!fs.existsSync(gp)) {
    console.log("  ! 源码树缺少 gguf-py/，转换可能因 gguf 版本不匹配而失败");
    return;
  }
  copyDir(gp, path.join(DEST, "gguf-py"));
  for (const sub of ["gguf", path.join("gguf", "scripts")]) {
    const pc = path.join(DEST, "gguf-py", sub, "__pycache__");
    if (fs.existsSync(pc)) fs.rmSync(pc, { recursive: true, force: true });
  }
  console.log("  + gguf-py/ (与 conversion 同源的 gguf 实现，必须随包)");
}

async function downloadConvert(tag) {
  const ref = tag || "master";
  const url = `https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/heads/${ref}`;
  console.log("下载 llama.cpp 源码 tarball (" + ref + ") …");
  const buf = await fetchBuffer(url);
  const tmp = path.join(os.tmpdir(), "naixi_convert_dl_" + Date.now());
  fs.mkdirSync(tmp, { recursive: true });
  const tarball = path.join(tmp, "llama.tar.gz");
  fs.writeFileSync(tarball, buf);
  run(IS_WIN ? "tar" : "tar", ["-xzf", tarball, "-C", tmp], { stdio: "ignore" });

  // 找顶层含 convert_hf_to_gguf.py 的目录（codeload 顶层目录名含 commit/ref）
  const top = fs.readdirSync(tmp).find((d) => {
    const p = path.join(tmp, d);
    return fs.statSync(p).isDirectory() && fs.existsSync(path.join(p, "convert_hf_to_gguf.py"));
  });
  if (!top) fail("tarball 里找不到 convert_hf_to_gguf.py");
  const src = path.join(tmp, top);

  fs.rmSync(DEST, { recursive: true, force: true });
  fs.mkdirSync(DEST, { recursive: true });
  fs.copyFileSync(path.join(src, "convert_hf_to_gguf.py"), path.join(DEST, "convert_hf_to_gguf.py"));
  console.log("  + convert_hf_to_gguf.py");

  // 官方 import 的是 `conversion`（老版本为 convert），两种都认
  for (const name of ["conversion", "convert"]) {
    const d = path.join(src, name);
    if (fs.existsSync(d)) {
      copyDir(d, path.join(DEST, name));
      const pc = path.join(DEST, name, "__pycache__");
      if (fs.existsSync(pc)) fs.rmSync(pc, { recursive: true, force: true });
      console.log("  + " + name + "/ (官方转换逻辑模块)");
      copyGgufPy(src);
      fs.rmSync(tmp, { recursive: true, force: true });
      return;
    }
  }
  fail("tarball 里没有 conversion/ 或 convert/ 模块目录，转换会不完整");
}

function installDeps() {
  if (!fs.existsSync(PY)) fail("找不到 python-embed: " + PY + "\n请先执行 npm run bundle:engine 打包推理引擎。");
  console.log("安装转换依赖（torch CPU + transformers / gguf / safetensors / numpy）…");
  // torch 走 CPU 专用索引，避免拉 CUDA 版（体积/下载量都大得多）
  run(PY, ["-m", "pip", "install", "--quiet", "--index-url", "https://download.pytorch.org/whl/cpu", "torch"],
    { stdio: "inherit" });
  // ★ 依赖清单是**实测踩出来**的，不是照抄文档 —— 官方脚本的 import 链很深，
  //   少任何一个都会在跑一半时才炸（浪费用户十几分钟下载后才看到报错）：
  //     torch        —— 脚本顶部直接 import
  //     transformers —— conversion/base.py 顶部 from transformers import AutoConfig
  //     sentencepiece—— Qwen2 等模型的词表是 SentencePiece，转词表时才 import（最晚暴露）
  //     gguf/safetensors/numpy —— 权重读写
  //   刻意不装 PyPI 的 gguf：随包 gguf-py 与 conversion/ 同源，版本必须自洽。
  run(PY, ["-m", "pip", "install", "--quiet",
    "gguf", "safetensors", "numpy", "transformers", "sentencepiece"], { stdio: "inherit" });
}

function verify() {
  console.log("复验：转换脚本可列出支持模型…");
  // ★ 必须用 -c 注入 sys.path（不能直接跑脚本）：
  //   python-embed 自带 python313._pth 锁死 sys.path（不含脚本所在目录），
  //   官方脚本的 `from conversion import ...` 会 ModuleNotFoundError。
  const convDir = path.join(DEST);
  const script = path.join(DEST, "convert_hf_to_gguf.py");
  const runner = "import sys, runpy\n"
    + "sys.path.insert(0, " + JSON.stringify(convDir) + ")\n"
    + "sys.argv = [" + JSON.stringify(script) + ", '--print-supported-models']\n"
    + "runpy.run_path(" + JSON.stringify(script) + ", run_name='__main__')\n";
  const r = spawnSync(PY, ["-c", runner], {
    stdio: "inherit",
    // ★ 不设 NO_LOCAL_GGUF：官方脚本会改用 PyPI 的 gguf（0.19.0，枚举偏旧），
    //   与随包 conversion/ 不匹配，实测报 "MODEL_ARCH has no attribute 'DFLASH'"。
    //   不设它 = 用同目录随包 gguf-py，与 conversion/ 严格同源。
    env: Object.assign({}, process.env, { PYTHONUTF8: "1" }),
  });
  if (r.status !== 0) fail("转换脚本复验失败（依赖可能未装齐）");
  console.log("\n✓ 转换层就绪：" + path.relative(REPO, DEST));
  console.log("  随后执行 `npm run tauri build`，用户在干净虚拟机安装后即可直接加载 safetensors 模型（首次自动转 GGUF 缓存）。");
  const sizeMB = (() => {
    let s = 0;
    const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p); else s += fs.statSync(p).size; } };
    try { walk(DEST); } catch {}
    return (s / 1048576).toFixed(0);
  })();
  console.log("  转换层体积约 " + sizeMB + " MB（含 torch CPU）。");
}

(async () => {
  const args = process.argv.slice(2);
  let tag = "master";
  let forceDownload = false;
  let srcDir = null;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--tag" && args[i + 1]) tag = args[i + 1];
    else if (args[i] === "--download") forceDownload = true;
    else if (args[i] === "--src" && args[i + 1]) srcDir = args[i + 1];
  }
  // 优先本机源码树（省下载 + 构建机可能不通 GitHub），下载仅作 fallback
  const local = srcDir ? (fs.existsSync(path.join(srcDir, "convert_hf_to_gguf.py")) ? srcDir : null) : findLocalLlamaSrc();
  if (local && !forceDownload) {
    copyFromLocalSrc(local);
  } else {
    if (local && forceDownload) console.log("--download 已指定，忽略本机源码树: " + local);
    await downloadConvert(tag);
  }
  installDeps();
  verify();
})().catch((e) => fail(String(e).slice(0, 300)));
