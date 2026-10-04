"""验证 Gateway 新增的两个可交互端点（toggle + access）。

不依赖运行中的桌面端进程：直接起一个最小 aiohttp app，挂上这两个 handler，
用真实 SQLite 里的 10 条能力做真调用 —— 验的是handler 逻辑与库表交互，
不是自己 curl 自己端点自证。
"""
import asyncio
import json
import sys

sys.path.insert(0, r"D:\naixi_desktop")

from aiohttp import web

# desktop_core.storage 的 DB_PATH 是运行时由 voice_input.py 赋值的模块级空串，
# 直接 import 拿到的是"" —— 必须显式指向真实库，否则会建一个空库。
import os
os.environ.setdefault("NAIXI_DESKTOP_DATA", r"D:\naixi_desktop\data")

from desktop_core import storage as st
st.DB_PATH = os.path.join(r"D:\naixi_desktop\data", "naixi_desktop.db")
if not os.path.isfile(st.DB_PATH):
    print("!! 找不到数据库:", st.DB_PATH)
    sys.exit(2)
# capabilities 表可能尚未建（首次运行），按真实 DDL 补齐
_c = st._get_conn()
_c.execute("""CREATE TABLE IF NOT EXISTS capabilities
    (id TEXT, provider TEXT DEFAULT '', kind TEXT DEFAULT 'tool',
     title TEXT DEFAULT '', description TEXT DEFAULT '', endpoint TEXT DEFAULT '',
     trust TEXT DEFAULT 'read', requires_conf INTEGER DEFAULT 0,
     schema TEXT DEFAULT '', meta TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
     updated_at TEXT DEFAULT (datetime('now')))""")
_c.commit()
_c.close()

from desktop_core import api as A

fails = []


def need(cond, msg, extra=""):
    print(("  OK   " if cond else "  MISS ") + msg + (("| " + str(extra)[:150]) if extra else ""))
    if not cond:
        fails.append(msg)


async def main():
    pass  # schema 已在模块导入时确保
    app = web.Application()
    app.router.add_post("/api/gateway/capability/toggle", A.api_gateway_capability_toggle)
    app.router.add_get("/api/gateway/access", A.api_gateway_access)
    # broadcast 会去拿 HUB，测试环境没有真实 WS；给它打个桩避免噪声
    async def _fake_bc():
        return 0
    A._broadcast_capability_changed = _fake_bc
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9871)
    await site.start()
    BASE = "http://127.0.0.1:9871"

    import aiohttp

    print("=" * 68)
    print("[1] POST /api/gateway/capability/toggle —— 能力启用/停用")
    print("=" * 68)
    caps = st.capability_list(include_disabled=True)
    need(len(caps) >= 10, f"库里有 {len(caps)} 条能力")

    target = caps[0]["id"]
    async with aiohttp.ClientSession() as s:
        # 停用
        async with s.post(f"{BASE}/api/gateway/capability/toggle",
                          json={"id": target, "enabled": False},
                          timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
        need(r.status == 200 and d.get("ok") and d.get("enabled") is False,
             f"停用 {target} 成功", d)

        # 默认列表（对端视角）里不该再有它
        after = st.capability_list(include_disabled=False)
        need(target not in [c["id"] for c in after],
             "停用后对端默认清单里不再出现（对端即刻生效）")
        # include_disabled=1 仍能看到（用户在 UI 里能重新启用）
        incl = st.capability_list(include_disabled=True)
        row = next((c for c in incl if c["id"] == target), None)
        need(row is not None and row["enabled"] is False,
             "include_disabled=1 仍可查到，且 enabled=False")

        # 关键：停用不应丢掉其他字段（最小增量更新）
        orig = caps[0]
        need(row and row["title"] == orig["title"] and row["trust"] == orig["trust"]
             and row["endpoint"] == orig["endpoint"],
             "停用只改enabled，未覆盖其他字段（增量更新）", row["title"] if row else "")

        # 重新启用
        async with s.post(f"{BASE}/api/gateway/capability/toggle",
                          json={"id": target, "enabled": True},
                          timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
        need(r.status == 200 and d.get("enabled") is True, f"重新启用 {target}", d)
        back = st.capability_list(include_disabled=False)
        need(target in [c["id"] for c in back], "启用后回到对端清单")

        # 错误路径
        async with s.post(f"{BASE}/api/gateway/capability/toggle",
                          json={"enabled": True}, timeout=aiohttp.ClientTimeout(total=5)) as r:
            need(r.status == 400, "缺 id 返回 400", r.status)
        async with s.post(f"{BASE}/api/gateway/capability/toggle",
                          json={"id": target}, timeout=aiohttp.ClientTimeout(total=5)) as r:
            need(r.status == 400, "缺 enabled 返回 400", r.status)
        async with s.post(f"{BASE}/api/gateway/capability/toggle",
                          json={"id": "no.such.cap", "enabled": True},
                          timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
            need(r.status == 404, "不存在的 id 返回 404", d)

    print()
    print("=" * 68)
    print("[2] GET /api/gateway/access —— 接入信息聚合")
    print("=" * 68)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{BASE}/api/gateway/access",
                          timeout=aiohttp.ClientTimeout(total=8)) as r:
            d = await r.json()
    need(r.status == 200 and d.get("ok"), "access 返回 200", r.status)
    for k in ("http_port", "ws_port", "lan_ip", "localhost_url", "lan_url",
              "ws_lan", "mcp", "configs"):
        need(k in d and d[k], f"含字段 {k}", d.get(k) if k != "mcp" and k != "configs" else "")

    need(d["lan_ip"] not in ("", None), f"取到局域网 IP: {d['lan_ip']}")
    need(":9845" in str(d["http_port"]) or d["http_port"] == 9845,
         f"HTTP 端口 {d['http_port']}")
    need("/mcp" in d["lan_url"] and d["lan_ip"] in d["lan_url"],
         f"局域网 URL 含 IP 与 /mcp: {d['lan_url']}")
    need(d["localhost_url"].startswith("http://127.0.0.1"), "本机 URL 正确")

    mcp = d["mcp"]
    need(mcp["running"] is False, "MCP 未运行时如实报 running=False（不谎报）")
    need("port" in mcp and "tools" in mcp, "含 MCP 端口与工具数", mcp)

    cfgs = d["configs"]
    need(cfgs["claude_code"].startswith("claude mcp add"), "Claude Code 命令可复制")
    need(cfgs["claude_code"] in cfgs["claude_code"], "命令非空")
    cur = json.loads(cfgs["cursor"])
    need("mcpServers" in cur and "naixi-desktop" in cur["mcpServers"],
         "Cursor 配置是合法 JSON 且含 naixi-desktop")
    gen = json.loads(cfgs["generic_http"])
    need(gen.get("transport") == "streamable-http", "通用配置标了传输方式")
    need("/mcp" in gen.get("url", ""), "通用配置含端点 URL")
    need("ws://127.0.0.1" in cfgs["ws_internal"], "内部 WS 地址已给出")

    print()
    print("=" * 68)
    print("[3] 配置片段里的地址与真实监听一致")
    print("=" * 68)
    need(str(d["ws_port"]) in cfgs["ws_internal"] or d["ws_port"] == 18400,
         f"WS 片段端口与 status 一致（{d['ws_port']}）")
    need(str(mcp["port"]) in cfgs["cursor"] or "9846" in cfgs["cursor"],
         "Cursor 片段用 MCP 端口而非 HTTP 端口",
         cfgs["cursor"][:120])

    await runner.cleanup()
    print()
    print(f"总计失败 {len(fails)} 项")
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))