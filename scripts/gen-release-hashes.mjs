#!/usr/bin/env node
// 发布完整性哈希清单生成器
// 扫描 src-tauri/target/release/bundle 下的安装包产物，算 SHA-256 写 sha256sums.txt
// 用途：随 GitHub Releases 上传，用户下载后可 `sha256sum -c sha256sums.txt` 校验，
//       防银狐类伪造/投毒安装包（只认官方清单里的哈希）。
import { readdirSync, statSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const bundleDir = join(__dirname, "..", "src-tauri", "target", "release", "bundle");
if (!existsSync(bundleDir)) {
  console.error(`[err] 未找到构建产物目录：${bundleDir}\n请先运行 \`npm run tauri build\` 再生成哈希清单。`);
  process.exit(1);
}
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
const lines = [];
for (const f of files.sort()) {
  const h = createHash("sha256").update(readFileSync(f)).digest("hex");
  const rel = f.replace(bundleDir + "\\", "").replace(bundleDir + "/", "");
  lines.push(`${h}  ${rel}`);
  console.log(`[ok] ${rel}  ${h.slice(0, 16)}...`);
}
const out = join(bundleDir, "sha256sums.txt");
writeFileSync(out, lines.join("\n") + "\n", "utf8");
console.log(`[done] wrote ${out}`);
console.log("上传到 GitHub Releases 与安装包一同发布；用户用 \`sha256sum -c sha256sums.txt\` 校验。");
