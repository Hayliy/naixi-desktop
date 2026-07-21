"""
打包前暂存桌面核心代码到 resources/desktop_core/。
只复制 .py 源文件，显式排除一切非代码资产（日志、调试产物、备份、
缓存、模型、数据），确保私有资产绝不被打进安装包。

运行时机：tauri.conf.json 的 beforeBuildCommand（仅 tauri build 触发）。
"""
import os
import shutil
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent  # naixi_desktop/
SRC = ROOT / "desktop_core"
DST = ROOT / "src-tauri" / "resources" / "desktop_core"


def main():
    DST.mkdir(parents=True, exist_ok=True)

    # 1. 复制 / 覆盖 .py 文件
    count = 0
    for path in SRC.rglob("*.py"):
        # 跳过 Python 缓存目录
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC)
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1

    # 2. 清理 DST 中已删除的 .py（增量更新，避免 rmtree 触发沙箱拦截）
    staged = {p.relative_to(DST) for p in DST.rglob("*.py")}
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        staged.discard(path.relative_to(SRC))
    for stale in staged:
        (DST / stale).unlink()

    print(f"已暂存 {count} 个 .py 文件到 {DST}（仅代码，不含任何数据/模型/日志）")


if __name__ == "__main__":
    main()
