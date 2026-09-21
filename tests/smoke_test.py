#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""奶昔桌面端 · 后端冒烟测试（自包含，零第三方测试框架依赖）。

用法：
    python tests/smoke_test.py            # 全量（需装好 requirements-embed.txt 的环境）
    python tests/smoke_test.py --light    # 轻量：仅 stdlib 可跑的部分（CI 快速门 / 无依赖环境）
退出码：0 = 全部通过；1 = 有失败（CI 应标红）。

覆盖的回归类（对应 0.2.x 交付事故）：
  A. 依赖清单完整性   —— 0.2.7 事故（23 个依赖从未进包 → 功能静默失效）的防线：
     desktop_core 里出现的每个第三方顶层模块，必须能映射到 requirements-embed.txt。
  B. 核心模块导入冒烟 —— 关键纯逻辑模块在干净解释器下可导入。
  C. 配置合并语义     —— API Key 掩码回传不得清掉旧密文（历史踩坑）。
  D. schema 版本迁移框架 —— 1.0.0 数据契约基础设施：版本戳、幂等、失败回滚语义。
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # 让 desktop_core 可导入（--light 也需要）
LIGHT = "--light" in sys.argv[1:]

# GBK 控制台防编码崩溃（同 verify_embed_deps.py 的处理）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

_results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        detail = fn() or ""
        _results.append((name, True, detail))
        print(f"  ✓ {name}" + (f" —— {detail}" if detail else ""))
    except Exception as e:
        _results.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  ✗ {name} —— {type(e).__name__}: {e}")


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────── A. 依赖清单完整性 ────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[-_.]+", "", s).lower()


def _dist_names(req_path: pathlib.Path) -> set[str]:
    out = set()
    for ln in io.open(req_path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        out.add(_norm(ln.split("==")[0].split(">=")[0].split("[")[0]))
    return out


def t_dependency_manifest() -> str:
    guard = _load("verify_embed_deps", ROOT / "scripts" / "verify_embed_deps.py")
    sync = _load("sync_embed_deps", ROOT / "scripts" / "sync_embed_deps.py")
    req = ROOT / "scripts" / "requirements-embed.txt"
    if not req.exists():
        raise AssertionError(f"缺少依赖清单 {req}")
    dists = _dist_names(req)
    found = guard.scan_third_party()   # {顶层模块名: 使用文件集合}
    missing = []
    for m in sorted(found):
        if m in guard.OPTIONAL:
            continue
        cands = [_norm(x) for x in sync.ALIASES.get(m, [])] + [_norm(m)]
        if not any(any(d == c or d.startswith(c) for d in dists) for c in cands):
            missing.append(f"{m}（使用于 {','.join(sorted(found[m]))[:3]}）")
    if missing:
        raise AssertionError(f"{len(missing)} 个第三方模块不在 requirements-embed.txt: "
                             + "; ".join(missing))
    return f"desktop_core 第三方模块 {len(found)} 个全部可映射到清单"


# ──────────────────────────── B. 核心模块导入冒烟 ────────────────────────────

# 只挑"导入即安全"（无 GUI、无摄像头、无端口监听）的模块；GUI/重资源模块不进冒烟。
SAFE_MODULES = [
    "desktop_core.storage",
    "desktop_core.html_util",
    "desktop_core.log_paths",
]


def t_core_module_imports() -> str:
    ok = 0
    for name in SAFE_MODULES:
        importlib.import_module(name)
        ok += 1
    return f"{ok} 个核心模块导入正常"


# ──────────────────────────── C. 配置合并语义 ────────────────────────────

def t_merge_preserve_keys_masked() -> None:
    storage = importlib.import_module("desktop_core.storage")
    old = {"api_providers": {"p1": {"api_key": "enc:REAL_CIPHERTEXT"}}}
    new = {"api_providers": {"p1": {"api_key": storage._KEY_MASK}}}
    merged = storage.merge_preserve_keys(new, old)
    assert merged["api_providers"]["p1"]["api_key"] == "enc:REAL_CIPHERTEXT", \
        "前端回传掩码时必须保留旧密文"


def t_merge_preserve_keys_empty() -> None:
    storage = importlib.import_module("desktop_core.storage")
    old = {"api_providers": {"p1": {"api_key": "enc:REAL_CIPHERTEXT"}}}
    new = {"api_providers": {"p1": {"api_key": ""}}}
    merged = storage.merge_preserve_keys(new, old)
    assert merged["api_providers"]["p1"]["api_key"] == "enc:REAL_CIPHERTEXT", \
        "前端回传空 key 时必须保留旧密文"


def t_merge_preserve_keys_real() -> None:
    storage = importlib.import_module("desktop_core.storage")
    old = {"api_providers": {"p1": {"api_key": "enc:OLD"}}}
    new = {"api_providers": {"p1": {"api_key": "sk-new-real-key"}}}
    merged = storage.merge_preserve_keys(new, old)
    assert merged["api_providers"]["p1"]["api_key"] == "sk-new-real-key", \
        "真实新 key 必须覆盖旧值（不能把用户锁死在旧 key 上）"


def t_merge_preserve_keys_non_dict() -> None:
    storage = importlib.import_module("desktop_core.storage")
    new = {"api_providers": {"bad": "not-a-dict"}}
    merged = storage.merge_preserve_keys(new, {})
    assert merged["api_providers"]["bad"] == "not-a-dict", "非 dict 供应者原样保留，不抛异常"


# ──────────────────────────── D. schema 版本迁移框架 ────────────────────────────

def t_schema_baseline_stamped() -> None:
    storage = importlib.import_module("desktop_core.storage")
    conn = sqlite3.connect(":memory:")
    calls = []
    storage._SCHEMA_MIGRATIONS = {1: lambda c: calls.append(1)}
    try:
        v = storage.run_schema_migrations(conn)
        assert v == 1, f"应迁移到 v1，实际 v{v}"
        assert storage.get_schema_version(conn) == 1
        # 幂等：重跑不再执行迁移函数
        storage.run_schema_migrations(conn)
        assert len(calls) == 1, f"迁移函数必须只执行一次，实际 {len(calls)} 次"
    finally:
        storage._SCHEMA_MIGRATIONS = {1: lambda conn: None}


def t_schema_incremental() -> None:
    storage = importlib.import_module("desktop_core.storage")
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 1")   # 模拟 0.2.10 老库
    applied = []

    def m2(c):
        c.execute("CREATE TABLE IF NOT EXISTS t_new_v2 (id INTEGER)")
        applied.append("v2")

    storage._SCHEMA_MIGRATIONS = {1: lambda c: None, 2: m2}
    try:
        v = storage.run_schema_migrations(conn)
        assert v == 2 and applied == ["v2"], f"老库应增量迁移到 v2，实际 v{v} applied={applied}"
        conn.execute("INSERT INTO t_new_v2 (id) VALUES (1)")   # 迁移产物真实可用
        storage.run_schema_migrations(conn)
        assert applied == ["v2"], "重跑不得重复执行 v2"
    finally:
        storage._SCHEMA_MIGRATIONS = {1: lambda conn: None}


def t_schema_failure_keeps_version() -> None:
    storage = importlib.import_module("desktop_core.storage")
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA user_version = 1")

    def bad(c):
        raise RuntimeError("boom")

    storage._SCHEMA_MIGRATIONS = {1: lambda c: None, 2: bad}
    try:
        try:
            storage.run_schema_migrations(conn)
            raise AssertionError("迁移失败必须抛异常（不得静默吞掉）")
        except RuntimeError:
            pass
        assert storage.get_schema_version(conn) == 1, "失败时版本号不得前进（下次启动可重试）"
    finally:
        storage._SCHEMA_MIGRATIONS = {1: lambda conn: None}


# ──────────────────────────── 主流程 ────────────────────────────

def main() -> int:
    print("=" * 68)
    print(f"奶昔后端冒烟测试  mode={'light' if LIGHT else 'full'}  "
          f"python={sys.version.split()[0]}")
    print("=" * 68)

    print("\n[A] 依赖清单完整性")
    check("第三方模块全部映射到 requirements-embed.txt", t_dependency_manifest)

    if not LIGHT:
        print("\n[B] 核心模块导入冒烟")
        check("SAFE_MODULES 导入", t_core_module_imports)
        print("\n[C] 配置合并语义（API Key 掩码保护）")
        check("掩码回传保留旧密文", t_merge_preserve_keys_masked)
        check("空 key 回传保留旧密文", t_merge_preserve_keys_empty)
        check("真实新 key 正常覆盖", t_merge_preserve_keys_real)
        check("非 dict 供应者不炸", t_merge_preserve_keys_non_dict)
    else:
        print("\n[B/C] （--light 跳过：需完整依赖环境）")

    print("\n[D] schema 版本迁移框架")
    check("基线版本戳 + 幂等", t_schema_baseline_stamped)
    check("老库增量迁移 v1→v2", t_schema_incremental)
    check("迁移失败版本号不前进", t_schema_failure_keeps_version)

    failed = [r for r in _results if not r[1]]
    print("\n" + "=" * 68)
    print(f"结果: {len(_results) - len(failed)}/{len(_results)} 通过"
          + (f"；失败 {len(failed)} 个" if failed else " ✓"))
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
