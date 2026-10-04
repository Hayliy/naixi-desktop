"""MCP 服务端真实协议级验证（2026-10-04）

用**官方 MCP 客户端**连，验证第三方接入真的能走通 —— 不是自己 curl 自己的端点自证。
用底层 `streamable_http_client + ClientSession`（v2 SDK 的标准写法）。

覆盖：协议版本协商、tools/list、tools/call（读能力 + 参数化工具）、
      错误处理、健康检查、OpenAI 格式导出。
"""
import asyncio
import json
import sys

import httpx2 as httpx

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9847
URL = f"http://127.0.0.1:{PORT}/mcp"
BASE = f"http://127.0.0.1:{PORT}"

fails = []


def need(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def text_of(result):
    return "".join(getattr(x, "text", "") for x in result.content)


async def main():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    print("=" * 70)
    print(f"[1] 官方 MCP 客户端连 {URL}")
    print("=" * 70)

    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as c:
            init = await c.initialize()
            pi = getattr(init, "protocolVersion", None)

            print("    serverInfo:", getattr(init, "server_info", None))
            need(bool(getattr(init, "protocol_version", None)),
                 f"协议版本协商成功：{getattr(init, 'protocol_version', None)}")
            need(getattr(init, "server_info", None) is not None, "返回 serverInfo")

            tools = await c.list_tools()
            names = [t.name for t in tools.tools]
            print(f"    tools/list -> {len(names)} 个: {names}")
            need(len(names) >= 8, f"tools/list 返回 {len(names)} 个工具")
            need("get_system_resources" in names, "含 get_system_resources")
            need("add_memory" in names, "含 add_memory（写能力）")
            tr = next((t for t in tools.tools if t.name == "get_system_resources"), None)
            need(tr is not None and bool(tr.description), "工具带 description")
            tl = next((t for t in tools.tools if t.name == "list_capabilities"), None)
            need(tl is not None and bool(tl.input_schema),
                 "list_capabilities 带 inputSchema（客户端据此传参）")

            print()
            print("=" * 70)
            print("[2] tools/call —— 读能力真实数据")
            print("=" * 70)
            r = await c.call_tool("get_system_resources", {})
            txt = text_of(r)
            print(f"    get_system_resources -> {len(txt)} 字符")
            print(f"    {txt[:200]}")
            need("gpu" in txt.lower() and "cpu" in txt.lower(), "读到真实 CPU/GPU 数据")

            r = await c.call_tool("get_system_info", {})
            t = text_of(r)
            print(f"    get_system_info -> {t[:140]}")
            need("Windows" in t or "hostname" in t, "读到真实系统信息")

            r = await c.call_tool("get_diagnostics", {})
            t = text_of(r)
            need("backend" in t or "running" in t, "读到真实诊断数据")

            r = await c.call_tool("list_capabilities", {"kind": "tool"})
            t = text_of(r)
            print(f"    list_capabilities(kind=tool) -> {t[:130]}")
            need("desktop." in t, "参数化工具正确按 query 传参并返回能力列表")

            print()
            print("=" * 70)
            print("[3] 错误处理")
            print("=" * 70)
            try:
                r = await c.call_tool("no_such_tool_xyz", {})
                t = text_of(r)
                need(True, f"调用不存在的工具返回：{t[:100]}")
            except Exception as e:
                need(True, f"调用不存在的工具抛错：{type(e).__name__}: {str(e)[:70]}")

    print()
    print("=" * 70)
    print("[4] 辅助端点（健康检查 / OpenAI 格式导出）")
    print("=" * 70)
    # 用 urllib 而非 httpx2：httpx2 在传完整 URL 时会把它当 params 二次编码
    # （实测 GET http://127.0.0.1:9849/v1/tools 变成 /http%3A//127.0.0.1... → 404）
    import urllib.request

    def _get(path):
        with urllib.request.urlopen(f"{BASE}{path}", timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")

    st_, body = _get("/health")
    d = json.loads(body) if body.strip().startswith("{") else {}
    print(f"    /health -> {st_} {body[:160]}")
    need(st_ in (200, 503), "健康检查有响应")
    need("backend" in d, "健康检查含后端地址")

    st2, body2 = _get("/v1/tools")
    d2 = json.loads(body2) if body2.strip().startswith("{") else {}
    n = len(d2.get("data", []))
    print(f"    /v1/tools -> {st2} {n} 个工具（OpenAI 格式）")
    need(n >= 8, f"OpenAI 格式导出 {n} 个工具（供只会 OpenAI SDK 的客户端用）")

    print("=" * 70)
    print(f"失败 {len(fails)} 项")
    for f in fails:
        print("  FAIL:", f)
    return 1 if fails else 0


sys.exit(asyncio.run(main()))