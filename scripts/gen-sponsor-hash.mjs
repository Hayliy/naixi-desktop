#!/usr/bin/env node
// 赞助收款码完整性生成器
// 读取 public/sponsor/{wechat,alipay}.png -> base64 内联 + SHA-256，写回 src/lib/sponsorIntegrity.ts
// 目的：把收款码固化进已编译前端 bundle，配合 SettingsPage 运行时哈希自检，
//       拦截「只换图不重编译」的 fork/投毒攻击（银狐类替换收款码截胡赞助款）。
//
// 用法：把真实微信/支付宝收款码命名为 wechat.png / alipay.png 放进 public/sponsor/，
//       然后 `npm run gen:sponsor-hash`。脚本保留你手填的 SPONSOR_REAL_NAME，只重写 SPONSOR_QR。
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const srcFile = join(root, "src/lib/sponsorIntegrity.ts");
const keys = ["wechat", "alipay"];

function b64sha(pngPath) {
  const buf = readFileSync(pngPath);
  const b64 = buf.toString("base64");
  const sha = createHash("sha256").update(buf).digest("hex");
  return { b64, sha };
}

let block = "";
for (const k of keys) {
  const p = join(root, "public/sponsor", `${k}.png`);
  if (!existsSync(p)) {
    console.warn(`[skip] ${p} 不存在，跳过（该渠道将显示空码）`);
    block += `  ${k}: { b64: "", sha256: "0" },\n`;
    continue;
  }
  const { b64, sha } = b64sha(p);
  console.log(`[ok] ${k}.png  base64=${b64.length}B  sha256=${sha.slice(0, 16)}...`);
  block += `  ${k}: { b64: "${b64}", sha256: "${sha}" },\n`;
}

// 保留用户手填的收款实名，仅重写 SPONSOR_QR 与工具函数
let ts = existsSync(srcFile) ? readFileSync(srcFile, "utf8") : "";
const m = ts.match(/export const SPONSOR_REAL_NAME = ("(?:[^"\\]|\\.)*");/);
const realName = m ? m[1] : "【替换为你的微信/支付宝收款实名】";

const out = `// 赞助收款码完整性校验 —— 防 fork/投毒替换收款码截胡赞助款（银狐类攻击）
// 本文件的 SPONSOR_QR 由 \`npm run gen:sponsor-hash\` 在放入真实收款码后重新生成。
// 收款码以 base64 内联 + SHA-256 固化进已编译 bundle：仅换图不重编译会被 SettingsPage 运行时自检拦截。
// SPONSOR_REAL_NAME 为双核对关键，请手填你的真实收款实名（不要把占位名发布出去）。
// 威胁边界：此机制挡「换图不重编译」的懒攻击；若攻击者重编译整个应用替换哈希，
//           则靠 Tauri 代码签名 + 仅从官方 GitHub Releases 下载兜底（见 docs/RELEASE_SECURITY.md）。

export const SPONSOR_REAL_NAME = ${JSON.stringify(realName)};

export const SPONSOR_QR: Record<string, { b64: string; sha256: string }> = {
${block}};

export async function sha256Hex(buf: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
`;
writeFileSync(srcFile, out, "utf8");
console.log(`[done] wrote ${srcFile}`);
