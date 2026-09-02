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

    # 3. 复制内置「资源库」内容（专家 / Skill / 专家团队 JSON）
    #    这些是应用自带内容，必须打进安装包；
    #    用户私有数据（对话、日志、模型、知识库）仍严格排除。
    prompt_src = ROOT / "data" / "prompts"
    prompt_dst = DST.parent / "data" / "prompts"
    if prompt_src.is_dir():
        prompt_dst.mkdir(parents=True, exist_ok=True)
        for name in ("prompts.json", "experts.json", "skills.json"):
            sp = prompt_src / name
            if sp.exists():
                shutil.copy2(sp, prompt_dst / name)
        print(f"已暂存内置资源库（专家/Skill/专家团队）到 {prompt_dst}")

    # 4. 安全收尾：剥离打包目录里的「个人/运行时」数据，确保安装包零私有信息。
    #    resources/data 只保留内置 prompts；其余（个人数据库、日志、模型/语音缓存、
    #    截图、知识库）一律删除，避免把用户的对话/记忆/密钥库随安装包发出去。
    _scrub_bundled_personal_data(DST.parent)
    print(f"已暂存 {count} 个 .py 文件到 {DST}（仅代码，不含用户私有数据/模型/日志）")


def _scrub_bundled_personal_data(resources_dir: pathlib.Path):
    """删除 resources/data 与 resources/logs 中的个人/运行时产物，仅保留内置 prompts。"""
    data_dir = resources_dir / "data"
    if data_dir.is_dir():
        for item in list(data_dir.iterdir()):
            if item.name == "prompts":
                continue  # 内置资源库，保留
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
    logs_dir = resources_dir / "logs"
    if logs_dir.is_dir():
        for item in list(logs_dir.iterdir()):
            if item.is_file():
                item.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
