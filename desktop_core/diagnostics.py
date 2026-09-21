"""应用内诊断聚合（1.0.0 要求：让用户与 1.0 支持能一键自查状态）。

纯函数 collect_diagnostics()：不依赖 HTTP 请求对象，可在 CI 单测中直接调用。
暴露：后端存活、配置 schema 版本、各连接器/平台配置状态、直播引擎状态、系统健康分
（若运维巡检已跑过）、已知降级状态（让 CONTRIBUTING §4.3「降级必须 UI 可见」落地）、
数据库 schema 版本。所有外部依赖懒加载 + try/except 兜底，绝不因某个子项失败而整页报错。
"""
from __future__ import annotations

import json
import os
import platform

from desktop_core import config_schema

# 与 storage.SCHEMA_VERSION 同源但避免循环 import：直接引用常量
try:
    from desktop_core.storage import SCHEMA_VERSION as DB_SCHEMA_VERSION
except Exception:  # pragma: no cover
    DB_SCHEMA_VERSION = 1


def _detect_degradations(config: dict) -> list[str]:
    """暴露当前已知的「功能降级但用户可能不可见」状态（CONTRIBUTING §4.3 落地）。

    只列可观测、且与用户数据/契约相关的降级；纯防御性 except（如连接断开清理）不在此列。
    """
    out: list[str] = []
    try:
        from desktop_core import storage

        # ① 文本落库加密迁移：未完成意味着历史明文还在库里（隐私降级）
        if storage.meta_get("_text_at_rest_v1", "") != "1":
            out.append("对话/记忆明文未加密落库（_text_at_rest_v1 迁移未完成）")

        # ② 数据库 schema 漂移：老库未升到最新版本（数据契约降级）
        if storage.DB_PATH and os.path.exists(storage.DB_PATH):
            try:
                import sqlite3
                c = sqlite3.connect(storage.DB_PATH)
                cur = int(c.execute("PRAGMA user_version").fetchone()[0])
                c.close()
                if cur < DB_SCHEMA_VERSION:
                    out.append(f"数据库 schema 未升级到最新（当前 v{cur} → 期望 v{DB_SCHEMA_VERSION}）")
            except Exception:
                pass
    except Exception:
        pass

    # ③ 配置结构告警（缺失键 / 未知键 / 类型错）
    out.extend(config_schema.validate_desktop_config(config))
    return out


def collect_diagnostics() -> dict:
    """聚合一份诊断快照。任何子项失败都不影响其它子项。"""
    from desktop_core import storage

    diag: dict = {
        "ok": True,
        "backend": "running",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "config_schema_version": config_schema.CONFIG_SCHEMA_VERSION,
    }

    # ── 配置态（自修复后读取，保证 schema_version 戳存在）──
    # 防御：测试/未初始化场景下 storage.DB_PATH 未设，meta 表可能不存在 → 退化为空配置。
    try:
        cfg = config_schema.migrate_desktop_config(storage.meta_get("desktop_config", ""))
    except Exception:
        cfg = config_schema.migrate_desktop_config({})
    diag["config_schema_version"] = cfg.get("schema_version", 0)
    diag["configured_providers"] = [
        k for k, v in (cfg.get("api_providers") or {}).items()
        if isinstance(v, dict) and v.get("api_key")
    ]
    diag["configured_platforms"] = list((cfg.get("platform_configs") or {}).keys())
    diag["update_source"] = (cfg.get("update_source") or "") or "(默认 GitHub Releases)"

    # ── 平台连接器清单 ──
    try:
        catalog = os.path.join(os.path.dirname(__file__), "platforms.json")
        with open(catalog, encoding="utf-8") as fh:
            pj = json.load(fh)
        platforms = pj.get("platforms", [])
        diag["platform_catalog_count"] = len(platforms)
        diag["platform_catalog_ids"] = [p.get("id") for p in platforms]
    except Exception as e:
        diag["platform_catalog_error"] = str(e)

    # ── 直播引擎状态 ──
    try:
        from desktop_core.live_engine import engine
        st = engine.status
        diag["live_running"] = bool(st and st.get("running"))
        diag["live_room"] = (st or {}).get("room_id")
    except Exception as e:
        diag["live_error"] = str(e)

    # ── 系统健康分（需运维巡检已写入 ops_health_log；未跑过则标记不可用）──
    try:
        from desktop_core import ops_engine
        h = ops_engine.get_latest_health()
        if h:
            diag["health_score"] = h.get("score")
            diag["health_backend_alive"] = h.get("backend_alive")
            diag["health_details"] = h.get("details")
        else:
            diag["health_available"] = False
    except Exception as e:
        diag["health_error"] = str(e)

    # ── 数据库 ──
    diag["db_path"] = storage.DB_PATH
    diag["db_exists"] = bool(storage.DB_PATH) and os.path.exists(storage.DB_PATH)
    try:
        if storage.DB_PATH and os.path.exists(storage.DB_PATH):
            import sqlite3
            c = sqlite3.connect(storage.DB_PATH)
            diag["db_schema_version"] = int(c.execute("PRAGMA user_version").fetchone()[0])
            c.close()
    except Exception:
        pass

    # ── 降级可见性（§4.3 落地）──
    diag["degradations"] = _detect_degradations(cfg)
    return diag
