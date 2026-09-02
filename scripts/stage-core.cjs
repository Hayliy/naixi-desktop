/*
 * stage-core.cjs — 端口化 stage_core 启动器
 * ------------------------------------------------------------
 * 作用：在构建期（tauri beforeBuildCommand）定位一个可用的 Python 来运行
 *       src-tauri/stage_core.py，避免在 tauri.conf.json 里硬编码任何
 *       用户专属的 Python 路径（如 C:/Users/<user>/.workbuddy/...）。
 *
 * Python 解析顺序：
 *   1. 环境变量 NAIXI_BUILD_PYTHON（显式指定，优先级最高）
 *   2. 受管 Python：~/.workbuddy/binaries/python/versions/<最新版本>/python.exe
 *   3. 系统 PATH 上的 python / python3 / py
 *
 * 这样「别人 clone 后自己构建」也能跑通——只要他装了任意 Python 并设置好
 * NAIXI_BUILD_PYTHON 或加入 PATH，无需复刻开发者的目录结构。
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

function findManagedPython() {
  const base = path.join(os.homedir(), ".workbuddy", "binaries", "python", "versions");
  try {
    const entries = fs.readdirSync(base)
      .filter((e) => {
        try {
          return fs.statSync(path.join(base, e)).isDirectory();
        } catch (_) {
          return false;
        }
      })
      .sort()
      .reverse(); // 版本目录名按字典序排，倒序取最新
    for (const ver of entries) {
      const p = path.join(base, ver, "python.exe");
      if (fs.existsSync(p)) return p;
    }
  } catch (_) {
    /* 受管 Python 不存在则跳过 */
  }
  return null;
}

function resolvePython() {
  if (process.env.NAIXI_BUILD_PYTHON) {
    return process.env.NAIXI_BUILD_PYTHON.trim();
  }
  const managed = findManagedPython();
  if (managed) return managed;
  for (const cmd of ["python", "python3", "py"]) {
    const r = spawnSync(cmd, ["--version"], { windowsHide: true, stdio: "ignore" });
    if (r.status === 0) return cmd;
  }
  throw new Error(
    "找不到可用的 Python。请设置环境变量 NAIXI_BUILD_PYTHON 指向 python 可执行文件，\n" +
    "或把 python / python3 / py 加入系统 PATH 后重试。"
  );
}

function main() {
  let py;
  try {
    py = resolvePython();
  } catch (e) {
    console.error("[stage-core] " + e.message);
    process.exit(1);
  }
  const script = path.join(__dirname, "..", "src-tauri", "stage_core.py");
  if (!fs.existsSync(script)) {
    console.error("[stage-core] 找不到 stage_core.py: " + script);
    process.exit(1);
  }
  console.log("[stage-core] 使用 Python: " + py);
  const r = spawnSync(py, [script], {
    stdio: "inherit",
    windowsHide: true,
    shell: process.platform === "win32",
  });
  process.exit(r.status === null ? 1 : r.status);
}

main();
