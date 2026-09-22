#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""奶昔桌面端 · 后端单元测试（自包含，零第三方测试框架依赖）。

与 tests/smoke_test.py 的分工：
  smoke_test.py  —— 「装得上、导得进」这类交付级冒烟（依赖清单完整性、模块可导入、schema 框架语义）
  unit_test.py   —— 「逻辑对不对」这类行为级单测（迁移幂等、掩码保留、路径解析不变量、诊断契约）

用法：
    python tests/unit_test.py            # 全量
    python tests/unit_test.py --light    # 仅 stdlib 可跑的部分（无依赖环境 / CI 快速门）
退出码：0 = 全部通过；1 = 有失败。

覆盖的回归类：
  U1 日志/数据路径解析不变量 —— 对应本项目最大的一类历史缺陷："用 dirname(dirname(__file__))
     推目录"在开发树与安装树之间行为不同，导致日志/资源写到错位置（曾致 issue #6 一类问题）。
  U2 桌面配置 schema 迁移不变量 —— 幂等、绝不删用户键、坏数据退化不抛、迁移后结构必然健康。
  U3 API Key 掩码语义 —— 前端回传掩码/空值必须保留旧密文；mask 后绝不出现明文。
  U4 数据库 schema 迁移框架 —— 幂等；失败时不推进版本号（下次启动可重试）。
  U5 诊断契约（1.0 功能）—— collect_diagnostics 的键集与 degradations 类型不漂移。
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LIGHT = "--light" in sys.argv[1:]

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


# ══════════════════════ U1 路径解析不变量 ══════════════════════
def u1_log_paths():
    print("[U1] 日志/数据路径解析不变量")
    from desktop_core import log_paths

    def absolute_and_consistent():
        d = log_paths.log_dir()
        assert os.path.isabs(d), f"log_dir 不是绝对路径: {d}"
        assert os.path.isdir(d), f"log_dir 未创建目录: {d}"
        f = log_paths.log_file("unit_test_probe.log")
        assert os.path.isabs(f), f"log_file 不是绝对路径: {f}"
        assert os.path.dirname(f) == d.rstrip("\\/"), f"log_file 不在 log_dir 内: {f} vs {d}"
        return d

    def project_root_is_ancestor():
        # project_root() 必须是 ROOT 本身或其祖先，不能是 __file__ 上溯错位出来的旁支
        pr = log_paths.project_root()
        assert os.path.isabs(pr), f"project_root 不是绝对路径: {pr}"
        assert str(ROOT).lower().startswith(pr.rstrip("\\/").lower()), f"project_root 与仓库根不匹配: {pr}"
        return pr

    def dev_tree_flag_self_consistent():
        # 开发树判定必须与 project_root() 一致（同一套解析器，不允许两处各推一次）
        assert log_paths.is_dev_tree(str(ROOT)) is True, "仓库根应被判为开发树"
        tmp = tempfile.gettempdir()
        assert log_paths.is_dev_tree(tmp) is False, "临时目录不应被判为开发树"
        return "ok"

    check("log_dir/log_file 绝对路径且同源", absolute_and_consistent)
    check("project_root 是仓库根", project_root_is_ancestor)
    check("is_dev_tree 与解析器自洽", dev_tree_flag_self_consistent)


# ══════════════════════ U2 配置 schema 迁移不变量 ══════════════════════
def u2_config_schema():
    print("[U2] 桌面配置 schema 迁移不变量")
    from desktop_core import config_schema as cs

    def defaults_filled():
        cfg = cs.migrate_desktop_config({})
        assert cfg.get("schema_version") == cs.CONFIG_SCHEMA_VERSION, "schema_version 未打戳"
        for k in cs.DESKTOP_CONFIG_DEFAULTS:
            assert k in cfg, f"迁移后仍缺键 {k}"
        return f"schema_version={cfg['schema_version']}"

    def idempotent():
        once = cs.migrate_desktop_config({})
        twice = cs.migrate_desktop_config(copy.deepcopy(once))
        assert once == twice, "迁移不幂等：两次结果不同"
        return "两次结果一致"

    def never_drops_user_keys():
        raw = {
            "my_custom_key": {"deep": [1, 2]},
            "api_providers": {"dashscope": {"api_key": "cipher-text"}},
            "platform_configs": {"napcat": {"enabled": True}},
        }
        cfg = cs.migrate_desktop_config(copy.deepcopy(raw))
        assert cfg["my_custom_key"] == raw["my_custom_key"], "迁移删改/破坏了用户自定义键"
        assert cfg["api_providers"] == raw["api_providers"], "迁移破坏了 api_providers"
        assert cfg["platform_configs"] == raw["platform_configs"], "迁移破坏了 platform_configs"
        return "自定义键与嵌套用户数据均保留"

    def bad_input_degrades():
        for bad in (None, "", "not-json{{", [], 123):
            cfg = cs.migrate_desktop_config(bad)
            assert isinstance(cfg, dict) and cfg.get("schema_version") == cs.CONFIG_SCHEMA_VERSION, \
                f"坏输入 {bad!r} 未退化为合法配置"
        return "5 类坏输入均退化为合法配置"

    def migrated_is_structurally_healthy():
        cfg = cs.migrate_desktop_config(json.dumps({"platform_configs": {}}))
        issues = cs.validate_desktop_config(cfg)
        assert issues == [], f"迁移后的配置仍有结构告警: {issues}"
        # 反向：真正有问题的配置必须能报出来（否则校验等于没做）
        bad_issues = cs.validate_desktop_config({"desktop_full_trust": "yes", "unknown_top": 1})
        assert any("未知顶层键" in i for i in bad_issues), "未知顶层键未被告警"
        assert any("desktop_full_trust" in i for i in bad_issues), "类型错未被告警"
        return f"健康配置 0 告警；坏配置 {len(bad_issues)} 条告警"

    check("补齐默认值并打版本戳", defaults_filled)
    check("迁移幂等", idempotent)
    check("绝不删用户键", never_drops_user_keys)
    check("坏输入退化不抛", bad_input_degrades)
    check("迁移后结构必然健康（且坏配置能报出）", migrated_is_structurally_healthy)


# ══════════════════════ U3 API Key 掩码语义 ══════════════════════
def u3_mask_semantics():
    print("[U3] API Key 掩码语义")
    if LIGHT:
        print("  - 跳过（--light）")
        return
    try:
        from desktop_core import storage
    except Exception as e:
        print(f"  - 跳过（依赖不可用：{type(e).__name__}: {e}）")
        return

    def is_masked_detection():
        mask = storage._KEY_MASK
        assert storage.is_masked_key("") is True, "空串应视为需保留旧值"
        assert storage.is_masked_key(mask) is True, "掩码占位符应被识别"
        assert storage.is_masked_key("sk-abcdef123456") is False, "真实密钥被误判为掩码"
        return f"_KEY_MASK={mask!r}"

    def merge_preserves_cipher():
        old = {"api_providers": {"dashscope": {"api_key": "CIPHER-OLD"}}}
        new = {"api_providers": {"dashscope": {"api_key": storage._KEY_MASK, "model": "qwen"}}}
        merged = storage.merge_preserve_keys(new, old)
        assert merged["api_providers"]["dashscope"]["api_key"] == "CIPHER-OLD", \
            "回传掩码时未保留旧密文（会误删用户密钥）"
        assert merged["api_providers"]["dashscope"]["model"] == "qwen", "掩码保留时丢了其它字段"

    def merge_keeps_new_real_key():
        old = {"api_providers": {"a": {"api_key": "CIPHER-OLD"}}}
        new = {"api_providers": {"a": {"api_key": "sk-new-real"}}}
        merged = storage.merge_preserve_keys(new, old)
        assert merged["api_providers"]["a"]["api_key"] == "sk-new-real", "用户填了新密钥却被旧值覆盖"
        return "新密钥生效"

    def empty_incoming_preserves():
        old = {"api_providers": {"a": {"api_key": "CIPHER-OLD"}}}
        new = {"api_providers": {"a": {"api_key": ""}}}
        merged = storage.merge_preserve_keys(new, old)
        assert merged["api_providers"]["a"]["api_key"] == "CIPHER-OLD", "空值未保留旧密文"
        return "空值保留旧密文"

    def mask_never_leaks_plaintext():
        cfg = {"api_providers": {"a": {"api_key": "PLAINTEXT-SECRET"}}}
        storage.mask_config(cfg)
        assert "PLAINTEXT-SECRET" not in json.dumps(cfg), "mask_config 泄露了明文密钥"
        return "未泄露明文"

    check("掩码/空值识别", is_masked_detection)
    check("回传掩码保留旧密文", merge_preserves_cipher)
    check("新密钥不被旧值覆盖", merge_keeps_new_real_key)
    check("空值保留旧密文", empty_incoming_preserves)
    check("mask_config 不泄露明文", mask_never_leaks_plaintext)


# ══════════════════════ U4 数据库 schema 迁移框架 ══════════════════════
def u4_db_schema_migration():
    print("[U4] 数据库 schema 迁移框架")
    if LIGHT:
        print("  - 跳过（--light）")
        return
    from desktop_core import storage

    def fresh_db_reaches_latest_and_is_idempotent():
        with tempfile.TemporaryDirectory() as td:
            conn = sqlite3.connect(os.path.join(td, "unit.db"))
            try:
                assert storage.get_schema_version(conn) == 0, "新库 user_version 应为 0"
                v1 = storage.run_schema_migrations(conn)
                assert v1 == storage.SCHEMA_VERSION, f"迁移后版本应为 {storage.SCHEMA_VERSION}，实为 {v1}"
                v2 = storage.run_schema_migrations(conn)
                assert v2 == v1, "迁移不幂等：第二次返回不同版本"
                # 版本戳必须真的落库（PRAGMA 是连接级的，但 user_version 持久在文件里）
                assert storage.get_schema_version(conn) == storage.SCHEMA_VERSION
                return f"v0 -> v{v1}（幂等）"
            finally:
                conn.close()

    def failure_does_not_advance_version():
        # 往迁移表里塞一个必然失败的版本，断言：抛异常 + 版本号停在上一版（下次启动可重试）
        original = dict(storage._SCHEMA_MIGRATIONS)
        bad_version = storage.SCHEMA_VERSION + 1

        def boom(conn):
            raise RuntimeError("模拟迁移失败")

        storage._SCHEMA_MIGRATIONS[bad_version] = boom
        try:
            with tempfile.TemporaryDirectory() as td:
                conn = sqlite3.connect(os.path.join(td, "fail.db"))
                try:
                    raised = False
                    try:
                        storage.run_schema_migrations(conn)
                    except RuntimeError:
                        raised = True
                    assert raised, "失败的迁移没有抛出异常（静默吞掉最危险）"
                    got = storage.get_schema_version(conn)
                    assert got == storage.SCHEMA_VERSION, \
                        f"迁移失败后版本号被推进到 v{got}（应为 v{storage.SCHEMA_VERSION}，否则永不重试）"
                    return f"失败后版本停在 v{got}"
                finally:
                    conn.close()
        finally:
            storage._SCHEMA_MIGRATIONS.clear()
            storage._SCHEMA_MIGRATIONS.update(original)

    check("新库迁移到最新且幂等", fresh_db_reaches_latest_and_is_idempotent)
    check("迁移失败不推进版本号", failure_does_not_advance_version)


# ══════════════════════ U5 诊断契约（1.0 功能）══════════════════════
def u5_diagnostics_contract():
    print("[U5] 诊断契约（/api/diagnostics 的数据形状）")
    if LIGHT:
        print("  - 跳过（--light）")
        return
    from desktop_core import diagnostics

    REQUIRED = {
        "ok", "backend", "python", "platform", "config_schema_version",
        "configured_providers", "configured_platforms", "platform_catalog_count",
        "db_path", "db_exists", "degradations",
    }

    def required_keys_present():
        d = diagnostics.collect_diagnostics()
        missing = sorted(REQUIRED - set(d))
        assert not missing, f"诊断快照缺键: {missing}"
        return f"{len(d)} 个键"

    def types_are_stable():
        d = diagnostics.collect_diagnostics()
        assert isinstance(d["ok"], bool), "ok 应为 bool"
        assert isinstance(d["degradations"], list), "degradations 应为 list"
        assert all(isinstance(x, str) for x in d["degradations"]), "degradations 元素应为字符串"
        assert isinstance(d["platform_catalog_count"], int), "平台目录数应为 int"
        assert isinstance(d["configured_providers"], list), "configured_providers 应为 list"
        return f"degradations={len(d['degradations'])} 项"

    def json_serializable():
        d = diagnostics.collect_diagnostics()
        s = json.dumps(d, ensure_ascii=False)
        assert len(s) > 50, "诊断快照序列化异常"
        return f"{len(s)} 字节 JSON"

    def degradations_surfaces_bad_config():
        # 降级必须真的能暴露问题（CONTRIBUTING §4.3：降级必须 UI 可见）
        from desktop_core import config_schema as cs
        bad = cs.migrate_desktop_config({"unknown_top_key": 1})
        out = diagnostics._detect_degradations(bad)
        assert any("未知顶层键" in x for x in out), "有问题的配置未进入 degradations"
        return f"坏配置产生 {len(out)} 条降级"

    check("诊断快照键集完整", required_keys_present)
    check("关键字段类型稳定", types_are_stable)
    check("可 JSON 序列化", json_serializable)
    check("degradations 能暴露配置问题", degradations_surfaces_bad_config)


def main() -> int:
    print("=" * 62)
    print(f"奶昔后端单元测试（{'--light 轻量模式' if LIGHT else '全量模式'}）")
    print("=" * 62)
    u1_log_paths()
    u2_config_schema()
    u3_mask_semantics()
    u4_db_schema_migration()
    u5_diagnostics_contract()

    total = len(_results)
    failed = [r for r in _results if not r[1]]
    print()
    print("=" * 62)
    print(f"结果：{total - len(failed)}/{total} 通过")
    for name, _ok, detail in failed:
        print(f"  失败：{name} —— {detail}")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
