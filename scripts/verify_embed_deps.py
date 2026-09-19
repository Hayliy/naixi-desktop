#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""嵌入版 Python（python-embed）依赖守卫。

用途：在打包前验证 `src-tauri/resources/python-embed` 里的第三方依赖
"装得对、装得全"。历史上这里出过一次交付级事故——安装包能装出来、界面能打开，
但 32 个功能依赖里有 23 个从未进包（全局热键 / 系统监控 / 游戏视觉 / 本地 TTS /
文档导入 / MCP / 网页解析 / token 计数 / 离线 ASR 全部静默失效），因为
`site-packages` 长期靠手工拷贝维护、没有清单也没有校验。

本脚本做四件事：
  1. **完整性**：按每个 dist 的 RECORD 校验文件 sha256/size —— 能查出
     "目录内容与元数据版本不一致"（手工拷贝与 pip 安装混用的典型后果，
     pip check 查不出，只有 import 或哈希校验才暴露）。
  2. **可导入性**：对 desktop_core 里实际出现的第三方模块逐个 import。
  3. **缺失清单**：给出缺失/损坏模块与影响的业务能力。
  4. **可选依赖**：单独列出"有降级路径的可选增强"（如 paddleocr），
     不计入失败，但会提示当前状态。

用法（必须用目标解释器运行才有效）：
    src-tauri/resources/python-embed/python.exe scripts/verify_embed_deps.py
退出码：0 = 关键依赖全通过；1 = 有缺失/损坏（构建应中止）。
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import importlib
import os
import pathlib
import sys

# 中文 Windows 控制台默认 GBK，本脚本用了 ✓/✗/○/· 等符号。若直接 print，
# 在 GBK 下遇到无法编码的字符会抛 UnicodeEncodeError，把"依赖校验失败"变成
# 看不懂的编码异常（VM 实测：构建/校验都被这个崩溃掩盖了真正原因）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _resolve_layout() -> tuple[pathlib.Path, pathlib.Path]:
    """确定 python-embed 与 desktop_core 的位置。

    解析优先级：
      1. `--embed-root <python-embed 目录>`（命令行）
      2. 环境变量 `EMBED_ROOT`
      3. 常见安装位置自动发现（%LOCALAPPDATA%\\奶昔|naixi|Programs\\naixi 下的 resources/python-embed，
         以及脚本同级/上级的 python-embed）
      4. 仓库默认布局 src-tauri/resources/python-embed

    第 3 条是为了让守卫在**安装态**能直接被调用——VM/远程通道里传中文路径容易编码损坏，
    自动发现可以只用纯 ASCII 参数（脚本路径 + --report）就在用户机器上跑起来。
    指定/发现到 python-embed 时，配套的 desktop_core 取其同级目录。
    """
    arg = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--embed-root" and i + 1 < len(argv):
            arg = argv[i + 1]
        elif a.startswith("--embed-root="):
            arg = a.split("=", 1)[1]
    raw = arg or os.environ.get("EMBED_ROOT")
    if raw:
        embed = pathlib.Path(raw)
        return embed, embed.parent / "desktop_core"

    # 仓库布局优先：开发机上同时装着奶昔时，避免误校验"已安装的那一份"
    repo = ROOT / "src-tauri" / "resources" / "python-embed"
    if (repo / "python.exe").exists():
        return repo, ROOT / "desktop_core"

    for cand in _install_candidates():
        if (cand / "python.exe").exists():
            return cand, cand.parent / "desktop_core"

    return repo, ROOT / "desktop_core"


def _install_candidates() -> list[pathlib.Path]:
    """安装态下 python-embed 的常见位置（按可能性排序）"""
    name = "\u5976\u6614"  # 奶昔（用转义写，避免脚本编码差异）
    cands: list[pathlib.Path] = []
    for env in ("LOCALAPPDATA", "APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base:
            continue
        b = pathlib.Path(base)
        cands += [
            b / name / "resources" / "python-embed",
            b / "Programs" / name / "resources" / "python-embed",
            b / "naixi" / "resources" / "python-embed",
            b / name / "resources" / "python-embed",
        ]
    here = pathlib.Path(__file__).resolve().parent
    cands += [here / "python-embed", here.parent / "python-embed"]
    return cands


EMBED, CORE = _resolve_layout()
SITE = EMBED / "Lib" / "site-packages"
ALLOWLIST = ROOT / "scripts" / "embed_deps_allowlist.txt"
if not ALLOWLIST.exists():
    # 安装态下没有仓库的 scripts/，白名单可能就在守卫脚本旁边
    ALLOWLIST = pathlib.Path(__file__).resolve().parent / "embed_deps_allowlist.txt"


def load_allowlist() -> list[tuple[str, str]]:
    """已知的、有正当理由的本地改动（每行：`子串  # 理由`，# 后为理由）。

    典型场景：上游包不支持当前 Python 版本，本地做了适配补丁
    （如 webrtcvad 用 pkg_resources，本地换成 importlib.metadata），
    哈希自然与 wheel 记录不符——这是**有意为之**，不应阻断打包。
    """
    rules: list[tuple[str, str]] = []
    if not ALLOWLIST.exists():
        return rules
    for ln in io.open(ALLOWLIST, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        pat, _, why = ln.partition("#")
        rules.append((pat.strip(), why.strip()))
    return rules


def allowlisted(rel: str, rules: list[tuple[str, str]]) -> str | None:
    for pat, why in rules:
        if pat and pat in rel:
            return why or "白名单"
    return None

# 有降级路径的可选增强：缺失不算失败（但要让人知道）
OPTIONAL = {
    "paddleocr": "场景感知/游戏视觉的本地中文 OCR（未装时自动降级为视觉模型描述）",
}

# 业务能力 ← 依赖映射，仅用于让报告说人话
CAPABILITY = {
    "pynput": "全局热键",
    "psutil": "系统监控（仪表盘/运维页指标）",
    "cv2": "游戏 agent 视觉接地",
    "onnxruntime": "本地离线 TTS（onnx 运行时）",
    "kokoro_onnx": "本地离线 TTS（kokoro 音色）",
    "phonemizer": "本地离线 TTS（音素化）",
    "espeakng_loader": "本地离线 TTS（音素化后端）",
    "vosk": "真人语音（离线 ASR）",
    "webrtcvad": "真人语音（VAD 门控）",
    "sounddevice": "麦克风采集",
    "pypdf": "PDF 文档导入",
    "pdfminer": "PDF 文本抽取（tools.py）",
    "docx": "Word 文档导入",
    "mcp": "MCP 服务器接入",
    "bs4": "网页解析（URL 导入/搜索清洗）",
    "lxml": "网页解析（HTML 后端）",
    "tiktoken": "对话 token 计数",
    "jinja2": "工作流模板渲染",
    "pygltflib": "3D 模型格式（glTF）",
    "soundfile": "音频文件读写",
    "edge_tts": "Edge-TTS 兜底",
    "dashscope": "百炼（云端 TTS/LLM）",
    "PySide6": "桌面端 Qt 界面/桌宠",
    "OpenGL": "桌面端 3D 渲染",
    "win32api": "Windows 系统集成（pywin32）",
    "websocket": "WebSocket 客户端（B站弹幕/语音）",
    "cryptography": "密钥加解密（凭据存储）",
    "yaml": "配置读写",
}


def local_module_names() -> set[str]:
    """desktop_core 自身与工程内可导入的顶层包名（不算第三方）"""
    names = {"desktop_core", "data", "resources", "scripts"}
    if CORE.is_dir():
        for p in CORE.iterdir():
            if p.name.endswith(".py"):
                names.add(p.stem)
            elif p.is_dir() and (p / "__init__.py").exists():
                names.add(p.name)
    return names


def scan_third_party() -> dict[str, set[str]]:
    """AST 扫描 desktop_core，返回 {顶层模块名: 使用它的文件集合}（已排除标准库与自有包）"""
    stdlib = set(sys.stdlib_module_names)
    local = local_module_names()
    found: dict[str, set[str]] = {}
    for p in sorted(CORE.rglob("*.py")):
        try:
            tree = ast.parse(io.open(p, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    if top not in stdlib and top not in local:
                        found.setdefault(top, set()).add(p.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    top = node.module.split(".")[0]
                    if top not in stdlib and top not in local:
                        found.setdefault(top, set()).add(p.name)
    return found


def check_records() -> tuple[list[str], list[str]]:
    """按 dist 的 RECORD 校验文件哈希。

    返回 (真不一致, 白名单内已知改动)。前者能发现手工拷贝 / pip 混装
    造成的"目录内容与元数据版本不符"——`pip check` 查不出，只有哈希校验
    或 import 才会暴露（曾导致 pydantic-core 2.46.5 配 pydantic 2.13.4，
    mcp / openai 直接 SystemError）。
    """
    bad: list[str] = []
    known: list[str] = []
    rules = load_allowlist()
    if not SITE.is_dir():
        return [f"site-packages 不存在: {SITE}"], []
    for dist in sorted(SITE.glob("*.dist-info")):
        record = dist / "RECORD"
        if not record.exists():
            continue
        for line in io.open(record, encoding="utf-8", errors="replace"):
            parts = line.rstrip("\n").split(",")
            if len(parts) < 2:
                continue
            rel, hash_field = parts[0], parts[1]
            if not hash_field.startswith("sha256="):
                continue  # 目录项 / 未记录哈希
            # 跳过编译产物（每次导入都会变）、RECORD 自身，
            # 以及安装到 site-packages 之外的脚本入口（../../Scripts/*.exe、
            # ../../bin/*.py）——嵌入版按模块导入运行，不使用这些 CLI 入口。
            if (rel.endswith((".pyc", "/RECORD"))
                    or rel.startswith(("__pycache__", ".."))):
                continue
            f = SITE / rel
            if not f.exists():
                why = allowlisted(rel, rules)
                (known if why else bad).append(
                    f"{dist.name}: 缺文件 {rel}" + (f"（白名单：{why}）" if why else ""))
                continue
            want = hash_field.split("=", 1)[1]
            h = hashlib.sha256()
            try:
                with open(f, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
            except OSError as e:
                bad.append(f"{dist.name}: 读失败 {rel} ({e})")
                continue
            got = base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode()
            if got != want:
                why = allowlisted(rel, rules)
                if why:
                    known.append(f"{rel}（白名单：{why}）")
                else:
                    bad.append(f"{dist.name}: 内容与元数据不符 {rel}"
                               f"（{dist.name} 被混装/覆盖过）")
    return bad, known


class _Tee:
    """同时写到控制台与报告文件（报告统一 UTF-8，避免控制台编码影响取证）"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            try:
                st.write(s)
            except Exception:
                pass

    def flush(self):
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def main() -> int:
    # 可选：--report <path> 额外写一份 UTF-8 完整报告。
    # VM/CI 里控制台常是 GBK，中文与符号容易乱码；报告文件可直接取回分析。
    argv = sys.argv[1:]
    report = None
    for i, a in enumerate(argv):
        if a == "--report" and i + 1 < len(argv):
            report = argv[i + 1]
        elif a.startswith("--report="):
            report = a.split("=", 1)[1]
    if report:
        sys.stdout = _Tee(sys.__stdout__, io.open(report, "w", encoding="utf-8"))

    if not (EMBED / "python.exe").exists() and os.name == "nt":
        print(f"[SKIP] 未找到嵌入解释器 {EMBED / 'python.exe'}，跳过依赖校验")
        return 0

    print("=" * 72)
    print("嵌入版依赖守卫 (verify_embed_deps)")
    print(f"  解释器   : {sys.executable}")
    print(f"  Python   : {sys.version.split()[0]}")
    print(f"  site-pkgs: {SITE}")
    print("=" * 72)

    mods = scan_third_party()
    print(f"\n[1/3] AST 扫描 desktop_core：第三方顶层模块 {len(mods)} 个")

    ok, fail, optional = [], [], []
    for m in sorted(mods):
        try:
            importlib.import_module(m)
            ok.append(m)
        except Exception as e:
            if m in OPTIONAL:
                optional.append((m, f"{type(e).__name__}: {str(e)[:80]}"))
            else:
                fail.append((m, f"{type(e).__name__}: {str(e)[:90]}"))

    print(f"[2/3] 导入探针：OK {len(ok)} / FAIL {len(fail)} / 可选未装 {len(optional)}")

    print("[3/3] RECORD 完整性校验 ...")
    rec_bad, rec_known = check_records()
    if rec_bad:
        print(f"      ✗ 发现 {len(rec_bad)} 处不一致")
    else:
        print("      ✓ 全部 dist 文件与元数据一致"
              + (f"（另有 {len(rec_known)} 处白名单内的本地改动）" if rec_known else ""))

    if ok:
        print("\n--- 可导入 ---")
        print("  " + ", ".join(ok))

    if optional:
        print("\n--- 可选增强未安装（有降级路径，不影响主功能）---")
        for m, msg in optional:
            print(f"  ○ {m:<16} {OPTIONAL.get(m, '')}")

    if fail:
        print("\n--- ✗ 缺失/损坏（会导致对应功能静默失效）---")
        for m, msg in fail:
            cap = CAPABILITY.get(m, "")
            print(f"  ✗ {m:<16} {msg}")
            if cap:
                print(f"                    影响能力：{cap}")

    if rec_bad:
        print("\n--- ✗ 依赖树不一致（手工拷贝 / pip 混装的典型症状）---")
        for b in rec_bad[:40]:
            print(f"  ✗ {b}")
        if len(rec_bad) > 40:
            print(f"  ... 另有 {len(rec_bad) - 40} 处")
    if rec_known:
        print("\n--- 白名单内的本地改动（有意为之，不算失败）---")
        for k in rec_known[:10]:
            print(f"  · {k}")
        if len(rec_known) > 10:
            print(f"  ... 另有 {len(rec_known) - 10} 处")

    healthy = not fail and not rec_bad
    print("\n" + "=" * 72)
    print("结论：" + ("✓ 关键依赖完整可用" if healthy else "✗ 依赖不完整/不一致，禁止打包发布"))
    if optional:
        print(f"      可选增强未装 {len(optional)} 项：" + ", ".join(m for m, _ in optional))
    print("=" * 72)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
