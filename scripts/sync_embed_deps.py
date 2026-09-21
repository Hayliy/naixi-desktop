#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把第三方依赖同步进嵌入版 Python（src-tauri/resources/python-embed）。

为什么需要它：`src-tauri/resources/` 在 .gitignore 里（体积原因），所以
python-embed 的依赖**不在版本控制内**，换机器/CI 构建就会缺失。历史上正是
这样漏掉了 23 个依赖（全局热键、系统监控、游戏视觉、本地 TTS、文档导入、
MCP、网页解析、token 计数、离线 ASR 全部静默失效），而安装包照样能装出来。
清单（requirements-embed.txt）+ 本同步脚本 + 构建期守卫，三者合起来才算
可复现构建。

两种模式：
  1) --from-env <site-packages>   从一台依赖齐全的同版本 Python 环境复制
                                   （最快，无需网络；会按依赖闭包递归收集）
  2) --from-pip                   用 pip 按 requirements-embed.txt 安装
                                   （干净、可复现，但需要网络与时间）

同步完成后自动调用 scripts/verify_embed_deps.py 校验，失败即非零退出。

用法：
    python scripts/sync_embed_deps.py --from-env "C:/path/to/site-packages"
    python scripts/sync_embed_deps.py --from-pip --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    python scripts/sync_embed_deps.py --from-env ... --dry-run
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EMBED = ROOT / "src-tauri" / "resources" / "python-embed"
SITE = EMBED / "Lib" / "site-packages"
REQ = ROOT / "scripts" / "requirements-embed.txt"
PY = EMBED / "python.exe" if os.name == "nt" else EMBED / "bin" / "python3"

# 显式映射：导入名 → 安装条目前缀（发行名≠目录名，最容易漏）
ALIASES = {
    "cv2": ["cv2", "opencv"],
    "phonemizer": ["phonemizer"],
    "rpds": ["rpds"],
    "dateutil": ["dateutil", "python_dateutil"],
    "yaml": ["yaml", "_yaml", "pyyaml"],
    "docx": ["docx", "python_docx"],
    "bs4": ["bs4", "beautifulsoup4", "soupsieve"],
    "win32api": ["win32", "pywin32", "pythonwin", "win32comext"],
    "OpenGL": ["OpenGL", "pyopengl"],
    "sklearn": ["sklearn", "scikit_learn"],
    "PIL": ["PIL", "pillow"],
}


def dist_dirs(root: pathlib.Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for e in os.listdir(root):
        low = e.lower()
        for cut in ("-dist-info", ".dist-info"):
            if low.endswith(cut):
                name = e[: -len(cut)].rpartition("-")[0].replace("_", "-").lower()
                out.setdefault(name, []).append(e)
                break
    return out


def entries_for(root: pathlib.Path, import_name: str) -> list[str]:
    """按导入名找出 site-packages 里相关的目录/文件条目"""
    names = set(ALIASES.get(import_name, [import_name]))
    names.add(import_name)
    hits = []
    for e in os.listdir(root):
        stem = e.lower()
        for cut in ("-dist-info", ".dist-info", ".egg-info"):
            if stem.endswith(cut):
                stem = stem[: -len(cut)]
        for cut2 in ("/", "\\"):
            stem = stem.split(cut2)[0]
        stem_flat = stem.replace("_", "").replace("-", "").replace(".", "")
        for n in names:
            n_flat = n.lower().replace("_", "").replace("-", "").replace(".", "")
            if stem_flat == n_flat or stem_flat.startswith(n_flat):
                hits.append(e)
                break
    return hits


def sync_from_env(src: pathlib.Path, dry: bool = False) -> int:
    """把源环境里"依赖闭包"涉及的所有条目复制到 python-embed。

    闭包算法：从 requirements-embed.txt 的发行名出发，读每个 dist 的
    Requires-Dist 递归展开——比逐个手装靠谱，也不会漏掉间接依赖。
    """
    if not src.is_dir():
        print(f"✗ 源 site-packages 不存在: {src}")
        return 2
    try:
        from importlib.metadata import distributions
    except ImportError:
        print("✗ 需要 Python 3.8+ 的 importlib.metadata")
        return 2

    meta = {}
    for d in distributions(path=[str(src)]):
        n = (d.metadata["Name"] or "").lower().replace("_", "-")
        if n:
            meta[n] = d

    want = set()
    if REQ.exists():
        for ln in REQ.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            want.add(ln.split("==")[0].split(">=")[0].split("[")[0].strip().lower().replace("_", "-"))
    else:
        want = set(meta)

    need: set[str] = set()

    # 清单发行名 → 源环境里实际存在的 dist 名（清单与源环境版本载体不一致时的桥接）。
    # 例：清单用 webrtcvad-wheels（可复现、有 wheel），本地源环境装的是手工编译的 webrtcvad。
    ENV_ALIASES = {"webrtcvad-wheels": "webrtcvad"}

    def add(name: str) -> None:
        name = name.lower().replace("_", "-")
        if name in need:
            return
        if name not in meta:
            bridged = ENV_ALIASES.get(name)
            if bridged and bridged in meta:
                name = bridged
            else:
                return
        need.add(name)
        for r in (meta[name].requires or []):
            if "extra ==" in r:
                continue
            dep = r.split(";")[0].split("[")[0]
            for sep in ("<", ">", "=", "!", "~"):
                dep = dep.split(sep)[0]
            dep = dep.strip().lower().replace("_", "-")
            if dep and dep != "python":
                add(dep)

    for w in sorted(want):
        add(w)

    print(f"源环境 dist {len(meta)} 个 → 闭包 {len(need)} 个包")
    copied, files, total = 0, 0, 0
    for name in sorted(need):
        for e in entries_for(src, name):
            s, d = src / e, SITE / e
            if dry:
                print(f"  [dry] {e}")
                continue
            if s.is_dir():
                shutil.copytree(s, d, dirs_exist_ok=True)
                for _r, _dd, fs in os.walk(s):
                    files += len(fs)
                    total += sum(os.path.getsize(os.path.join(_r, f)) for f in fs)
            elif s.is_file():
                shutil.copy2(s, d)
                files += 1
                total += os.path.getsize(s)
            copied += 1
    if dry:
        return 0
    print(f"✓ 同步 {copied} 个条目 / {files} 个文件 / {total / 1024 / 1024:.1f} MB")
    return 0


def sync_from_pip(index_url: str | None) -> int:
    if not REQ.exists():
        print(f"✗ 缺少清单 {REQ}")
        return 2
    if not PY.exists():
        print(f"✗ 缺少嵌入解释器 {PY}")
        return 2
    cmd = [str(PY), "-m", "pip", "install", "--target", str(SITE),
           "--upgrade", "--no-warn-script-location", "--no-cache-dir",
           "-r", str(REQ)]
    if index_url:
        cmd += ["-i", index_url]
    print("执行:", " ".join(cmd))
    return subprocess.call(cmd)


def verify() -> int:
    script = ROOT / "scripts" / "verify_embed_deps.py"
    if not (PY.exists() and script.exists()):
        print("（跳过校验：缺少解释器或守卫脚本）")
        return 0
    return subprocess.call([str(PY), str(script)])


def main() -> int:
    ap = argparse.ArgumentParser(description="同步嵌入版 Python 依赖")
    ap.add_argument("--from-env", metavar="SITE_PACKAGES", help="源环境的 site-packages 路径")
    ap.add_argument("--from-pip", action="store_true", help="用 pip 按清单安装")
    ap.add_argument("--index-url", default=None, help="pip 镜像地址")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    SITE.mkdir(parents=True, exist_ok=True)
    rc = 0
    if args.from_env:
        rc = sync_from_env(pathlib.Path(args.from_env), args.dry_run)
    elif args.from_pip:
        rc = sync_from_pip(args.index_url)
    else:
        ap.error("必须指定 --from-env 或 --from-pip")
    if rc or args.dry_run or args.no_verify:
        return rc
    return verify()


if __name__ == "__main__":
    sys.exit(main())
