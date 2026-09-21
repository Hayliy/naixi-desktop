"""配置 schema 与版本化迁移（1.0.0 数据契约基础设施）。

背景：desktop_config / live_config 此前只是 meta 表的裸 JSON blob，无版本号、无 schema、
无迁移逻辑。一旦新增顶层键（如 update_source、desktop_full_trust），老用户库里没有该键 →
读出来是 None → 前端按「没配」渲染，甚至 KeyError。这正是 1.0.0 要消灭的「配置漂移」。

1.0.0 契约：任何配置结构演进必须登记于此，按 CONFIG_SCHEMA_VERSION 升版、幂等迁移、
向后兼容默认值。与 storage.py 的 SCHEMA 版本迁移框架同源设计，但作用于配置 JSON 而非表结构。
"""
from __future__ import annotations

import copy
import json
import logging

log = logging.getLogger("desktop")

CONFIG_SCHEMA_VERSION = 1

# 桌面配置当前已知顶层键与默认值。
# 注：嵌套 dict（api_providers / platform_configs / mcp_servers / settings）是用户数据，
# 不预填内部结构，只保证「键存在、类型对」。
DESKTOP_CONFIG_DEFAULTS = {
    "api_providers": {},
    "platform_configs": {},
    "mcp_servers": {},
    "desktop_full_trust": False,
    "settings": {},
    "update_source": "",
    "schema_version": CONFIG_SCHEMA_VERSION,
}

LIVE_CONFIG_DEFAULTS = {
    "schema_version": CONFIG_SCHEMA_VERSION,
}

# ── 迁移注册表：key=目标版本号，value=迁移函数（只拿 cfg dict 原地补全）──
# v1 = 基线：补齐当前所有已知顶层键 + 打 schema_version 戳。未来升级在此加 v2/v3…


def _migrate_desktop_v1(cfg: dict) -> dict:
    for k, v in DESKTOP_CONFIG_DEFAULTS.items():
        if k == "schema_version":
            continue
        if k not in cfg or cfg[k] is None:
            cfg[k] = copy.deepcopy(v)
    cfg["schema_version"] = max(int(cfg.get("schema_version", 0) or 0), 1)
    return cfg


DESKTOP_CONFIG_MIGRATIONS = {1: _migrate_desktop_v1}


def _parse(raw):
    """把任意来源（dict / JSON 串 / None）规整成 dict；坏数据返回 {} 不抛。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def migrate_desktop_config(raw) -> dict:
    """把任意来源的桌面配置迁移到最新 schema 版本。

    - 幂等：重跑不产生副作用（已是最新版直接返回）。
    - 向后兼容：只补默认值、绝不删除用户已有键。
    - 安全：坏 JSON 不抛异常，降级为 {} 后补全默认。
    """
    cfg = _parse(raw)
    current = int(cfg.get("schema_version", 0) or 0)
    for v in sorted(DESKTOP_CONFIG_MIGRATIONS):
        if v <= current:
            continue
        DESKTOP_CONFIG_MIGRATIONS[v](cfg)
    return cfg


def validate_desktop_config(cfg: dict) -> list[str]:
    """校验配置结构的已知问题（不抛异常，返回可读告警列表）。

    用于诊断端点与升级自检；空列表 = 结构健康。告警分两类：
    - 缺失/类型错（可被迁移自愈，列出仅为透明告知）
    - 未知顶层键（可能是前端新增未登记，或旧版残留，需关注）
    """
    if not isinstance(cfg, dict):
        return ["desktop_config 不是对象"]
    issues = []
    for k, v in DESKTOP_CONFIG_DEFAULTS.items():
        if k == "schema_version":
            continue
        if k not in cfg:
            issues.append(f"缺少顶层键 {k}（已用默认值补全）")
            continue
        if isinstance(v, dict) and not isinstance(cfg[k], dict):
            issues.append(f"键 {k} 应为对象，实际 {type(cfg[k]).__name__}")
        elif isinstance(v, bool) and not isinstance(cfg[k], bool):
            issues.append(f"键 {k} 应为布尔，实际 {type(cfg[k]).__name__}")
    known = set(DESKTOP_CONFIG_DEFAULTS)
    for k in cfg:
        if k not in known and k != "schema_version":
            issues.append(f"未知顶层键 {k}（未被 schema 登记，请确认是否前端新增）")
    return issues


def migrate_live_config(raw) -> dict:
    """直播配置同样版本化（live_engine 自管字段，这里只保证 schema_version 戳存在）。"""
    cfg = _parse(raw)
    cfg["schema_version"] = max(int(cfg.get("schema_version", 0) or 0), 1)
    return cfg
