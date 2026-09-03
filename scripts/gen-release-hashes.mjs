#!/usr/bin/env node
// 发布完整性哈希清单生成器
// 扫描 src-tauri/target/release 下的安装包产物 + 主程序 exe，算 SHA-256 写 sha256sums.txt
// 用途：随 GitHub Releases 上传，用户下载后可 `sha256sum -c sha256sums.txt` 校验，
//       防银狐类伪造/投毒安装包（只认官方清单里的哈希）。
//
// ★ 清单分两组，缺一不可（2026-09-03 补齐）：
//   ── 安装包 ──：下载后校验「下载到的那个文件」（防下载到伪造安装包）
//   ── 主程序 ──：安装后校验，对应应用内「设置 → 安全 → 安装包完整性 · 本程序哈希」
//                 显示的那串 SHA-256（防安装目录里的 exe 被替换）
//   只算安装包是不够的：卡片显示的是安装后 naixi-desktop.exe 的哈希，
//   与安装包哈希不是同一个文件，早期版本缺[主程序]组导致用户永远比不上。
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { basename, dirname, join, relative } from "node:path";
import { createHash } from "node:crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const releaseDir = join(__dirname, "..", "src-tauri", "target", "release");
const bundleDir = join(releaseDir, "bundle");
const MAIN_EXE = "naixi-desktop.exe";

function sha256(file) {
  return createHash("sha256").update(readFileSync(file)).digest("hex");
}
// 统一成正斜杠：Windows 的 sha256sum/PowerShell 都认，Linux coreutils 也不会把 \ 当转义
function posix(p) {
  return p.split("\\").join("/");
}

if (!existsSync(bundleDir)) {
  console.error(`[err] 未找到构建产物目录：${bundleDir}\n请先运行 \`npm run tauri build\` 再生成哈希清单。`);
  process.exit(1);
}

// ── 安装包 ──
const exts = new Set([".exe", ".msi", ".app", ".dmg", ".deb", ".rpm", ".AppImage", ".apk", ".appx", ".appxbundle"]);
const files = [];
function walk(d) {
  for (const e of readdirSync(d)) {
    const p = join(d, e);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else if (exts.has(p.slice(p.lastIndexOf(".")).toLowerCase())) files.push(p);
  }
}
walk(bundleDir);
if (!files.length) { console.error("[err] 未找到安装包产物"); process.exit(1); }

// 清单用【纯文件名】：用户把 sha256sums.txt 与下载到的安装包放在同一目录校验，
// 带 msi/ nsis/ 目录前缀在用户侧是无效路径（历史版本就踩过这个坑）。
// ★ GitHub Releases 资产名会被服务端强制清洗成 ASCII（非 ASCII 字符被直接删除）：
//   实测上传 ?name=奶昔_0.2.0_x64_zh-CN.msi → 存下来是 _0.2.0_x64_zh-CN.msi（中文前缀被删）；
//   ?name=奶昔测试.txt → 存下来是 default.txt。
//   所以清单里的文件名必须用「清洗后」的 ASCII 名，否则用户下载到的文件名与清单对不上，
//   `sha256sum -c` 会全部 FAILED。这里主动按同一规则归一化，保证两边一致。
function asciiName(name) {
  return name.replace(/奶昔/g, "naixi-desktop").replace(/[^\x20-\x7E]/g, "");
}

const pkgLines = [];
for (const f of files.sort()) {
  const rel = posix(relative(bundleDir, f));
  const h = sha256(f);
  const out = asciiName(basename(f));
  pkgLines.push(`${h}  ${out}`);
  console.log(`[pkg] ${rel}  -> ${out}  ${h.slice(0, 16)}...`);
}

// ── 主程序 ──（安装后的 naixi-desktop.exe，应用内卡片显示的就是它）
const mainExe = join(releaseDir, MAIN_EXE);
const mainLines = [];
if (existsSync(mainExe)) {
  const h = sha256(mainExe);
  mainLines.push(`${h}  ${MAIN_EXE}`);
  console.log(`[exe] ${MAIN_EXE}  ${h.slice(0, 16)}...`);
} else {
  console.warn(`[warn] 未找到主程序 ${mainExe}，清单将缺少[主程序]组；请先完成 release 构建。`);
}

const stamp = new Date().toISOString();
const header = [
  "# 奶昔 发布完整性哈希清单（SHA-256）",
  `# 生成时间：${stamp}`,
  "#",
  "# 【怎么校验】清单一律用纯文件名，把它和下载到的安装包放在同一个目录里用。",
  "# 【文件名说明】GitHub Releases 会把资产名里的非 ASCII 字符删掉，",
  "#   所以安装包在 GitHub 上的名字是 naixi-desktop_0.2.0_*.msi / .exe（不是「奶昔_」开头）。",
  "#   本清单就用这个实际下载名，下载后文件名可直接对上、无需改名。",
  "#   1) 安装包 —— 下载后立刻验，确认你下载到的就是官方文件：",
  "#        sha256sum -c --ignore-missing sha256sums.txt",
  "#      （--ignore-missing 用于跳过下面[主程序]那一行——它不在下载目录里）",
  "#      Windows PowerShell：",
  "#        Get-FileHash naixi-desktop_0.2.0_x64-setup.exe -Algorithm SHA256",
  "#   2) 主程序 —— 装完后验，确认安装目录里的程序没被替换：",
  "#      方式 A（推荐）：应用内打开「设置 → 安全 → 安装包完整性 · 本程序哈希」，",
  "#                     一键复制页面显示的 SHA-256，与下方[主程序]段的值比对。",
  "#      方式 B：在安装目录执行  sha256sum naixi-desktop.exe",
  "#              （安装目录可从开始菜单「奶昔」右键 → 打开文件位置 定位）",
  "#      不一致 = 本机程序已被篡改/替换，请卸载重装并全盘查杀。",
  "#",
  "# ⚠ 只认 GitHub Releases 上的这份清单。随安装包一起下发的「清单」不可信——",
  "#   攻击者会连清单一起换，所以本程序内只暴露哈希、不内置清单做自动比对。",
  "#",
];
const body = [
  "# ── 安装包（下载后校验）──",
  ...pkgLines,
  "# ── 主程序（安装后校验）──",
  ...mainLines,
];
const out = join(bundleDir, "sha256sums.txt");
writeFileSync(out, [...header, ...body].join("\n") + "\n", "utf8");
console.log(`[done] wrote ${out}`);
console.log("随 GitHub Releases 与安装包一同发布。");
console.log("注意：src-tauri/target/ 已被 .gitignore 排除，若要提交/发布这份清单，请复制到仓库根：");
console.log("  cp src-tauri/target/release/bundle/sha256sums.txt ./sha256sums.txt");
