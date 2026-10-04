"""Gateway 能力自注册 —— 桌面端启动时把自己暴露的能力写进能力表。

设计约束（2026-10-04）：
  · 第一批**只注册只读类（trust=read）**。写操作/执行命令等dangerous 能力
    等安全边界（requires_confirm 机制 + 人工确认流程）落地后再开。
    理由：QQ 侧发一条消息就能触发本地能力，若无确认环节等于远程执行入口。
  · endpoint 一律填**真实存在的路由**，不允许写"计划中的"端点——
    对端会照着调，编造的路径会变成静默失败。
  · 同 id 幂等覆盖：能力增减直接改本文件，重新执行即可。

用法：python -m desktop_core.gateway_selfregister
或：  python desktop_core/gateway_selfregister.py
"""

PROVIDER = "desktop-9845"

# 本端对外暴露的能力清单。
# kind:     tool / workflow / channel / mcp / model
# trust:    read（无副作用） / write（有副作用） / dangerous（不可逆）
# endpoint: 相对本端 9845 的 HTTP 路径，供对端调用
CAPABILITIES = [
    {
        "id": "desktop.tools.list",
        "kind": "tool",
        "title": "列出桌面端工具",
        "description": "返回桌面端注册表里的全部工具及其参数 schema（只读）",
        "endpoint": "/api/tools",
        "trust": "read",
        "schema": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "按分类过滤，可留空"}},
        },
    },
    {
        "id": "desktop.system.resources",
        "kind": "tool",
        "title": "系统资源占用",
        "description": "CPU / 内存 / 磁盘 / GPU 实时占用（只读）",
        "endpoint": "/api/system/resources",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "id": "desktop.system.info",
        "kind": "tool",
        "title": "系统信息",
        "description": "操作系统 / Python / 硬件等静态信息（只读）",
        "endpoint": "/api/system/info",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "id": "desktop.ops.dashboard",
        "kind": "tool",
        "title": "运维看板数据",
        "description": "健康分、已知降级项、数据库版本、趋势（只读）",
        "endpoint": "/api/ops/dashboard",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "id": "desktop.ops.inspections",
        "kind": "tool",
        "title": "历史巡检记录",
        "description": "历次自检的结果列表（只读）",
        "endpoint": "/api/ops/inspections",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "id": "desktop.diagnostics",
        "kind": "tool",
        "title": "诊断信息",
        "description": "桌面端自检诊断结果（只读）",
        "endpoint": "/api/diagnostics",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "id": "desktop.db.stats",
        "kind": "tool",
        "title": "数据库统计",
        "description": "各表行数与占用（只读）",
        "endpoint": "/api/database/stats",
        "trust": "read",
        "schema": {"type": "object", "properties": {}},
    },
    # ── 能力目录类（供对端发现本端能做什么）──
    {
        "id": "desktop.gateway.capabilities",
        "kind": "channel",
        "title": "能力清单",
        "description": "列出桌面端全部对外能力（对等互联的发现入口）",
        "endpoint": "/api/gateway/capabilities",
        "trust": "read",
        "schema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "kind": {"type": "string"},
                "include_disabled": {"type": "string"},
            },
        },
    },
    # ── 记忆互通（桌面端为唯一真相源；QQ 侧不可达时用本地库兜底）──
    # trust=write：写入记忆是持久化副作用，故标write。但**不含敏感信息**，
    # 且 QQ 侧 bridge 仍只放行 read，实际调用需等requires_confirm 流程接入后再开。
    {
        "id": "desktop.memory.query",
        "kind": "tool",
        "title": "回忆用户说过的事",
        # 同样精简（理由同 memory.add：长描述稀释信号 + 与 add 互相挤掉）
        "description": "回忆用户之前说过的事。当用户问「你还记得…」「我之前说过…」"
                       "「我告诉过你…」时使用。",
        "endpoint": "/api/gateway/memory/query",
        "trust": "read",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词；留空取最近记忆"},
                "agent_id": {"type": "string", "description": "默认 naixi"},
                "viewer_id": {"type": "string", "description": "聊天对象标识（群号/QQ号），空为通用记忆"},
                "limit": {"type": "integer", "description": "返回条数，默认 10"},
            },
        },
    },
    {
        "id": "desktop.memory.add",
        "kind": "tool",
        "title": "记住用户的偏好和事实",
        # 描述要**短而聚焦**，不能塞满触发词。实测（2026-10-04 真机数据）：
        #   · 长描述（含 14 个触发词）会稀释 embedding 信号——
        #     "记住我最适合猫" 对长描述只有 0.405，低于 _select_tools 的 0.5 阈值 → 被砍掉
        #   · 触发词塞太多还会让 add 与 query 描述互相相似度达 0.885，两者互相挤掉
        # 结论：只留 3~4 个最高频口语说法，短句 embedding 反而更准。
        "description": "把用户的偏好、习惯、事实长期存起来。当用户说「记住」「记一下」"
                       "「别忘了我…」「我最喜欢…」时使用。",
        "endpoint": "/api/gateway/memory/add",
        "trust": "write",
        "requires_confirm": True,
        "schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆内容"},
                "type": {"type": "string", "description": "episodic（事件）或 profile（画像）"},
                "agent_id": {"type": "string"},
                "viewer_id": {"type": "string"},
                "importance": {"type": "number", "description": "重要度 0-1"},
            },
            "required": ["content"],
        },
    },
]


def register_all(verbose: bool = True) -> dict:
    """把CAPABILITIES 全部写入能力表。返回统计。幂等，可反复执行。"""
    import os
    from desktop_core import storage as st
    if not st.DB_PATH:
        st.DB_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "naixi_desktop.db",
        )
    st.init_tables()

    ok_n, errs = 0, []
    for cap in CAPABILITIES:
        c = dict(cap)
        c["provider"] = PROVIDER
        r = st.capability_register(c)
        if r.get("ok"):
            ok_n += 1
            if verbose:
                print(f"  [OK] {c['id']:<34} trust={c['trust']}")
        else:
            errs.append(f"{c.get('id')}: {r.get('error')}")
            if verbose:
                print(f"  [FAIL] {c.get('id')}: {r.get('error')}")
    return {"ok": not errs, "registered": ok_n, "total": len(CAPABILITIES), "errors": errs}


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"注册桌面端能力到provider={PROVIDER} ...")
    res = register_all()
    print(f"\n完成: {res['registered']}/{res['total']}")
    if res["errors"]:
        print("错误:", res["errors"])
        raise SystemExit(1)
    # 通知对端立即重同步（若对端已连上）。失败静默——可能对端还没起。
    try:
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        op.open(urllib.request.Request("http://127.0.0.1:9845/api/gateway/notify",
                                       data=b"{}", method="POST"), timeout=3).read()
        print("已通知对端重同步")
    except Exception:
        print("（对端未运行，跳过通知；它会在下次定时同步时拉取）")
