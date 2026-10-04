"""校验并同步 desktop_core → src-tauri/resources/desktop_core 的代码副本。

为什么必须有这个脚本（2026-10-04踩坑）：
`src-tauri/sidecar/naixi_api.py` 的 `_find_core_root()` **优先命中
`src-tauri/resources/desktop_core`**（打包副本），只有找不到才回退到项目根。
也就是说：**你改 `desktop_core/api.py` 后直接重启后端，跑的还是旧副本。**
本次就因此白重启一次（access 端点404，而项目根里明明有）。

项目里没有任何自动同步机制（stage-core.cjs 只做版本号 snapshot，不搬代码），
所以手工 cp 极易漏。本脚本做两件事：
  1. `--sync`：把项目根的文件复制到副本
  2. 默认（无参数）：只比对，有差异则非零退出 —— 可挂 CI / pre-commit

用法：
  python scripts/sync_core_copy.py# 校验，有差异就报错
  python scripts/sync_core_copy.py --sync    # 校验 + 同步
  python scripts/sync_core_copy.py --check   # 同默认
"""
import argparse
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "desktop_core")
DST = os.path.join(ROOT, "src-tauri", "resources", "desktop_core")

# 这些文件只在项目根有意义，不进副本
SKIP_NAMES = {"__pycache__"}
SKIP_SUFFIX = (".pyc", ".pyo")


def md5(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def collect() -> list:
    """返回 [(文件名, 源路径, 副本路径)]，只含 .py。"""
    out = []
    for name in sorted(os.listdir(SRC)):
        if name in SKIP_NAMES or name.endswith(SKIP_SUFFIX):
            continue
        if not name.endswith(".py"):
            continue
        out.append((name, os.path.join(SRC, name), os.path.join(DST, name)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true", help="把差异文件复制到副本")
    args = ap.parse_args()

    if not os.path.isdir(SRC):
        print(f"[FAIL] 源目录不存在: {SRC}")
        return 2
    if not os.path.isdir(DST):
        print(f"[FAIL] 副本目录不存在: {DST}")
        return 2

    files = collect()
    if not files:
        print("[FAIL] 源目录里没有 .py 文件，路径不对？")
        return 2

    diff: list = []
    missing: list = []
    for name, s, d in files:
        if not os.path.isfile(d):
            missing.append(name)
            continue
        if md5(s) != md5(d):
            diff.append(name)

    total = len(files)
    if not diff and not missing:
        print(f"[OK] {total} 个 .py 全部一致（{SRC} == {DST}）")
        return 0

    if missing:
        print(f"[DIFF] 副本缺失 {len(missing)} 个:")
        for n in missing:
            print(f"       - {n}")
    if diff:
        print(f"[DIFF] 内容不一致 {len(diff)} 个:")
        for n in diff:
            print(f"       - {n}")

    if not args.sync:
        print()
        print("后端跑的是**副本**那份（sidecar/_find_core_root 优先命中 resources/desktop_core）。")
        print("改完 desktop_core 不同步，重启后端也白重启。执行：")
        print("    python scripts/sync_core_copy.py --sync")
        return 1

    # 副本缺的直接搬过去；已有的只覆盖内容（保留副本的其他文件）
    synced = []
    for name in missing:
        shutil.copy2(os.path.join(SRC, name), os.path.join(DST, name))
        synced.append(name)
    for name in diff:
        shutil.copy2(os.path.join(SRC, name), os.path.join(DST, name))
        synced.append(name)

    # 校验：同步后必须完全一致
    still = [n for n, s, d in files if not os.path.isfile(d) or md5(s) != md5(d)]
    if still:
        print(f"[FAIL] 同步后仍不一致: {still}")
        return 2
    print(f"[OK] 已同步 {len(synced)} 个文件并复验通过: {', '.join(synced)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())