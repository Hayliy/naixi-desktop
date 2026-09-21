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
  E. 基础模块回归     —— 定时任务 cron 匹配（0.2.6 类比：匹配错则任务永不执行）+ 系统指标
     健康分分段（0.2.8 类比：cpu 恒 0 曾致健康分虚高），对应差距一要求的两类自动化回归测试。
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import re
import sqlite3
import sys
import time

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


# ──────────────────────────── E. 基础模块回归（对应 0.2.6 / 0.2.8 交付事故） ────────────────────────────
# 这两类纯函数无副作用、可在 CI 直接断言，是"定时任务 / 系统指标"两大基础模块的回归防线。

def _mk_tm(hour: int, minute: int, wday: int, mday: int = 21, mon: int = 9, year: int = 2026):
    # wday 遵循 Python tm_wday：0=周一 … 6=周日（_cron_match 内部会转成 cron 的 0=周日）
    return time.struct_time((year, mon, mday, hour, minute, 0, wday, 0, 0))


def t_cron_match_regression() -> str:
    """0.2.6 事故类比：定时任务 cron 匹配逻辑——匹配错则任务永不执行或误执行。"""
    api = importlib.import_module("desktop_core.api")
    f = api._cron_match
    cases = [
        ("0 9 * * *",     _mk_tm(9, 0, 0),  True,  "周一9:00整点应触发"),
        ("0 9 * * *",     _mk_tm(9, 30, 0), False, "周一9:30非整点不触发"),
        ("* * * * *",     _mk_tm(3, 17, 4), True,  "全通配任意时刻触发"),
        ("*/15 * * * *",  _mk_tm(9, 0, 0),  True,  "分钟0是15的倍数"),
        ("*/15 * * * *",  _mk_tm(9, 10, 0), False, "分钟10非15的倍数"),
        ("0 9-17 * * 1-5", _mk_tm(9, 0, 0),  True,  "周一9点在工作日窗内"),
        ("0 9-17 * * 1-5", _mk_tm(9, 0, 5),  False, "周六不在周1-5"),
        ("0 9 * * 1",     _mk_tm(9, 0, 0),  True,  "cron周1=周一应匹配"),
        ("0 9 * * 0",     _mk_tm(9, 0, 0),  False, "cron周0=周日不匹配周一"),
        ("0 9 * *",       _mk_tm(9, 0, 0),  False, "4段非法表达式视为不匹配"),
    ]
    bad = []
    for expr, tm, want, desc in cases:
        got = f(expr, tm)
        if got != want:
            bad.append(f"{expr}@{desc}: 期望{want}实{got}")
    if bad:
        raise AssertionError("cron 匹配失败: " + "; ".join(bad))
    return f"{len(cases)} 个 cron 用例通过（含周字段换算与非法表达式）"


def t_health_score_regression() -> str:
    """0.2.8 事故类比：系统指标健康分分段——cpu 恒 0 曾导致健康分虚高、资源项永远满分。"""
    ops = importlib.import_module("desktop_core.ops_engine")
    f = ops.compute_health_score
    # 全健康 → 100
    total, bd = f(True, 2, 2, 1, 1, 0, 10.0, 20.0, 30.0)
    assert total == 100, f"全健康应100，实{total} bd={bd}"
    # CPU 真实飙高 → 资源项 cpu 段只拿 2 分（验证不再虚高）
    total_hi, bd_hi = f(True, 2, 2, 1, 1, 0, 90.0, 20.0, 30.0)
    assert bd_hi["resources"] == 2 + 6 + 6, f"cpu=90 时资源分应14，实{bd_hi['resources']}"
    assert total_hi == 94, f"cpu=90 总应94，实{total_hi}"
    # 后端挂 → backend 0 分 → 总分扣 30
    total_dead, bd_dead = f(False, 2, 2, 1, 1, 0, 10.0, 20.0, 30.0)
    assert bd_dead["backend"] == 0 and total_dead == 70, f"后端死应70，实{total_dead}"
    # 错误率分层：0→15分 / ≤3→10分 / ≤10→5分 / >10→0分
    t0, _ = f(True, 2, 2, 1, 1, 0, 10, 20, 30)
    t5, _ = f(True, 2, 2, 1, 1, 5, 10, 20, 30)
    t15, _ = f(True, 2, 2, 1, 1, 15, 10, 20, 30)
    # 真实分段：err=0→15分 / err≤3→10分 / err≤10→5分 / err>10→0分
    assert t0 == 100 and t5 == 90 and t15 == 85, f"错误率分层应100/90/85，实{t0}/{t5}/{t15}"
    return "健康分分段正确（cpu高扣分 / 后端死扣30 / 错误率4档）"


# ──────────────────────────── F. 配置 schema 迁移（差距二：配置冻结承诺） ────────────────────────────
# 1.0.0 数据契约：desktop_config 此前是裸 JSON blob，无版本/无 schema/无迁移。
# 这组测试守的是「升级不丢用户数据 + 缺失键自动补全 + 幂等 + 坏数据不崩」。

def t_config_migrate_preserves_user_data() -> str:
    """升级最关键的契约：老库缺新键时，用户已有的 api_providers / platform_configs 必须原样保留。"""
    cs = importlib.import_module("desktop_core.config_schema")
    old = {
        "api_providers": {"openai": {"api_key": "enc:REAL", "model": "gpt-4"}},
        "platform_configs": {"napcat": {"webhook_url": "http://a/b"}},
        # 故意缺：mcp_servers / desktop_full_trust / settings / update_source / schema_version
    }
    new = cs.migrate_desktop_config(old)
    assert new["api_providers"]["openai"]["api_key"] == "enc:REAL", "用户 api_key 不得丢"
    assert new["api_providers"]["openai"]["model"] == "gpt-4", "用户 model 不得丢"
    assert new["platform_configs"]["napcat"]["webhook_url"] == "http://a/b", "用户平台配置不得丢"
    # 缺失键必须被默认值补齐（升级不丢数据、且补齐结构）
    assert new["mcp_servers"] == {}, "缺失 mcp_servers 应补默认空对象"
    assert new["desktop_full_trust"] is False, "缺失 desktop_full_trust 应补默认 False"
    assert new["settings"] == {}, "缺失 settings 应补默认空对象"
    assert new["update_source"] == "", "缺失 update_source 应补默认空串"
    assert new["schema_version"] == cs.CONFIG_SCHEMA_VERSION, "必须打上当前 schema 版本戳"
    # 不得引入未登记顶层键污染配置
    known = set(cs.DESKTOP_CONFIG_DEFAULTS)
    for k in new:
        assert k in known or k == "schema_version", f"迁移引入了未登记键 {k}"
    return "老配置升级：用户数据全保留 + 缺失键补全 + 版本戳就位"


def t_config_migrate_idempotent() -> None:
    cs = importlib.import_module("desktop_core.config_schema")
    old = {"api_providers": {"x": {"api_key": "enc:A"}}}
    once = cs.migrate_desktop_config(old)
    twice = cs.migrate_desktop_config(once)
    assert once == twice, "迁移必须幂等（重跑不得改变结果）"
    third = cs.migrate_desktop_config(twice)
    assert third["schema_version"] == cs.CONFIG_SCHEMA_VERSION, "已是最新版不得改动版本戳"


def t_config_migrate_bad_json() -> None:
    cs = importlib.import_module("desktop_core.config_schema")
    out = cs.migrate_desktop_config("{not valid json")
    assert out["schema_version"] == 1 and out["api_providers"] == {}, "坏 JSON 降级为默认结构而非崩溃"
    assert cs.migrate_desktop_config(None)["schema_version"] == 1, "None 输入不得崩溃"
    assert cs.migrate_desktop_config(42)["schema_version"] == 1, "非 dict 输入不得崩溃"


def t_config_validate_flags_missing() -> None:
    cs = importlib.import_module("desktop_core.config_schema")
    issues = cs.validate_desktop_config({})
    assert any("缺少顶层键" in i for i in issues), "空配置应告警缺失键"
    full = cs.migrate_desktop_config({})
    assert cs.validate_desktop_config(full) == [], "完整默认配置应零告警"


# ──────────────────────────── G. 多平台连接器回归（差距：平台接入） ────────────────────────────
# 19 个平台连接器共享同一套 platform_configs 合并逻辑；这组测试守的是
# 「存平台配置不污染 api_key、存 api_provider 不污染平台配置」的双向隔离。

def t_platforms_json_valid() -> str:
    p = ROOT / "desktop_core" / "platforms.json"
    assert p.exists(), "platforms.json 缺失"
    data = json.loads(p.read_text(encoding="utf-8"))
    plats = data.get("platforms", [])
    assert len(plats) >= 1, "platforms 为空"
    ids = [x.get("id") for x in plats]
    assert len(ids) == len(set(ids)), f"平台 id 重复: {ids}"
    required = ("id", "name", "platform", "steps", "links")
    for x in plats:
        miss = [k for k in required if k not in x]
        assert not miss, f"平台 {x.get('id')} 缺必需字段 {miss}"
    return f"{len(plats)} 个平台连接器定义合法（id 唯一、字段完整）"


def t_platform_config_roundtrip() -> None:
    """模拟前端「先存 G 平台配置、再存某 api_provider」的两次合并，断言互不破坏。"""
    storage = importlib.import_module("desktop_core.storage")
    cs = importlib.import_module("desktop_core.config_schema")
    MERGE_KEYS = ("api_providers", "platform_configs", "mcp_servers",
                  "desktop_full_trust", "settings", "update_source")

    def merge_step(base, body):
        merged = dict(base)
        for key in MERGE_KEYS:
            if key in body:
                merged[key] = body[key]
        merged = storage.merge_preserve_keys(merged, base)
        return cs.migrate_desktop_config(merged)

    original = {"api_providers": {"openai": {"api_key": "enc:OLD"}}, "platform_configs": {}}
    # 第一次：前端存 napcat webhook 平台配置
    m1 = merge_step(original, {"platform_configs": {"napcat": {"webhook_url": "http://x/y", "enabled": True}}})
    assert m1["api_providers"]["openai"]["api_key"] == "enc:OLD", "存平台配置不得清掉已有 api_key"
    assert m1["platform_configs"]["napcat"]["webhook_url"] == "http://x/y", "平台配置应写入"
    # 第二次：前端存真实新 api_provider
    m2 = merge_step(m1, {"api_providers": {"openai": {"api_key": "sk-new"}}})
    assert m2["api_providers"]["openai"]["api_key"] == "sk-new", "真实新 key 应覆盖"
    assert m2["platform_configs"]["napcat"]["webhook_url"] == "http://x/y", "存 api_provider 不得清掉平台配置"


def t_diagnostics_collectable() -> str:
    """/api/diagnostics 聚合函数必须在无 HTTP 上下文也能跑出结构化快照（CI 可单测）。"""
    diag = importlib.import_module("desktop_core.diagnostics").collect_diagnostics()
    assert diag.get("backend") == "running", "后端存活标记缺失"
    assert "config_schema_version" in diag, "配置 schema 版本缺失"
    assert "platform_catalog_count" in diag and diag["platform_catalog_count"] >= 1, "平台清单未聚合"
    assert isinstance(diag.get("degradations"), list), "降级列表缺失（§4.3 可见性落地）"
    return f"诊断快照可聚合（{diag['platform_catalog_count']} 平台 / 配置v{diag['config_schema_version']}）"


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
        print("\n[E] 基础模块回归（定时任务 cron / 系统指标健康分）")
        check("cron 匹配逻辑（0.2.6 类比）", t_cron_match_regression)
        check("健康分分段逻辑（0.2.8 类比）", t_health_score_regression)
        print("\n[F] 配置 schema 迁移（1.0.0 数据契约 / 升级不丢数据）")
        check("老配置升级保留用户数据", t_config_migrate_preserves_user_data)
        check("迁移幂等", t_config_migrate_idempotent)
        check("坏 JSON / None 不崩溃", t_config_migrate_bad_json)
        check("结构校验告警缺失键", t_config_validate_flags_missing)
        print("\n[G] 多平台连接器回归 + 诊断聚合")
        check("platforms.json 定义合法", t_platforms_json_valid)
        check("平台配置 ↔ API Key 双向隔离", t_platform_config_roundtrip)
        check("诊断快照可聚合", t_diagnostics_collectable)
    else:
        print("\n[B/C/E] （--light 跳过：需完整依赖环境）")

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
