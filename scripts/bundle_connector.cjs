/**
 * bundle_connector.cjs —— 把 naixi_connector 打进 resources/connector/（随包下发）
 *
 * 用法：node scripts/bundle_connector.cjs
 *   （可在 package.json 里挂 "bundle:connector"，构建前手动跑一次）
 *
 * 源：D:\数据\naixi_connector（环境变量 NAIXI_CONNECTOR_SRC 可覆盖）
 * 目标：src-tauri/resources/connector/
 *   ├─ naixi_connector/      包本体（排除 __pycache__）
 *   ├─ site-packages/        从连接器 venv 拷的第三方依赖（排除 pip/setuptools 等）
 *   └─ requirements.txt      依赖清单留档
 *
 * ★ 绝不拷：connector_config.json（用户真实凭据！）、wechat_qr.png / 登录态、tests、.venv 本体。
 *   凭据泄漏进安装包 = 发布事故。
 *
 * 为什么拷 site-packages 而不是整个 venv：venv 的 python.exe 依赖 pyvenv.cfg 里
 * 指向创建机的 base 解释器，**venv 不可移植**。连接器 venv 是 cp313，与随包
 * python-embed（3.13.12）同 ABI，纯库 + cp313 .pyd 直接拷来即可用；
 * 运行时由 connector_manager 把包目录与 site-packages 挂进 PYTHONPATH。
 */

const fs = require("fs");
const path = require("path");

const SRC = process.env.NAIXI_CONNECTOR_SRC || "D:\\数据\\naixi_connector";
const ROOT = path.join(__dirname, "..");
const DEST = path.join(ROOT, "src-tauri", "resources", "connector");
const VENV_SP = path.join(SRC, ".venv", "Lib", "site-packages");

// site-packages 里这些是安装器/本地工具，运行时不需要（pip 一项就 12MB）
const SP_EXCLUDE = new Set([
  "pip", "setuptools", "pkg_resources", "_distutils_hack", "distutils-precedence.pth",
  "wheel", "easy_install.py", "pip-*.dist-info",
]);

function rmrf(p) {
  if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true });
}

function copyFilter(src) {
  const base = path.basename(src);
  if (base === "__pycache__") return false;
  if (base === "connector_config.json") return false;   // 用户凭据，绝不打包
  if (base === "wechat_qr.png" || base === "wechat_qr.txt") return false;  // 登录态（保险）
  return true;
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (!copyFilter(path.join(src, entry.name))) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function copySitePackages() {
  if (!fs.existsSync(VENV_SP)) {
    console.warn(`[bundle-connector] warn: 找不到 venv site-packages: ${VENV_SP}（跳过依赖拷贝）`);
    return;
  }
  const destSP = path.join(DEST, "site-packages");
  fs.mkdirSync(destSP, { recursive: true });
  let copied = 0;
  for (const entry of fs.readdirSync(VENV_SP, { withFileTypes: true })) {
    const base = entry.name;
    if (base === "__pycache__") continue;
    if (SP_EXCLUDE.has(base) || base.startsWith("pip-")) continue;
    const s = path.join(VENV_SP, base);
    const d = path.join(destSP, base);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
    copied++;
  }
  console.log(`[bundle-connector] site-packages 条目: ${copied}`);
}

function dirSize(p) {
  let total = 0;
  if (!fs.existsSync(p)) return 0;
  for (const entry of fs.readdirSync(p, { withFileTypes: true })) {
    const full = path.join(p, entry.name);
    total += entry.isDirectory() ? dirSize(full) : fs.statSync(full).size;
  }
  return total;
}

function main() {
  if (!fs.existsSync(path.join(SRC, "naixi_connector"))) {
    console.error(`[bundle-connector] error: 源不存在: ${SRC}`);
    process.exit(1);
  }
  console.log(`[bundle-connector] 源: ${SRC}`);
  console.log(`[bundle-connector] 目标: ${DEST}`);
  rmrf(DEST);
  fs.mkdirSync(DEST, { recursive: true });

  // 1) 包本体（过滤 __pycache__ / 凭据 / 登录态）
  copyDir(path.join(SRC, "naixi_connector"), path.join(DEST, "naixi_connector"));

  // 2) 依赖（venv site-packages，排除安装器）
  copySitePackages();

  // 3) 依赖清单留档
  const req = path.join(SRC, "requirements.txt");
  if (fs.existsSync(req)) fs.copyFileSync(req, path.join(DEST, "requirements.txt"));

  const mb = (dirSize(DEST) / 1024 / 1024).toFixed(1);
  console.log(`[bundle-connector] 完成，总体积 ${mb} MB（7z 压缩后约 1/3）`);

  // 防泄漏自检：目标里绝不允许出现凭据文件
  const leaked = ["connector_config.json", "wechat_qr.png"].filter((f) =>
    fs.existsSync(path.join(DEST, f)));
  if (leaked.length) {
    console.error(`[bundle-connector] FATAL: 凭据文件泄漏进包: ${leaked.join(", ")}`);
    process.exit(1);
  }
}

main();
