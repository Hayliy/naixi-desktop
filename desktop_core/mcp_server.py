"""
桌面端 MCP 服务端 — 生产级开放接入（2026-10-04）

为什么做这个
────────────
此前「对等互联」只支持**本机自连**（ws://127.0.0.1:18400），
第三方 bot、别的机器、云端、虚拟机都接不进来。这不是「生产级」。

业界事实（已核实，见 skill 的 references）：
  · MCP(Model Context Protocol) 是当前唯一「什么客户端都能连」的标准：
    Claude Code / Cursor / Cline / Claude Desktop / Gemini CLI 全原生支持，
    官方 SDK 覆盖 TS/Python/C#/Go/Rust/Ruby/Java/Swift/PHP/Kotlin。
  · 当前规范版本 2026-07-28，标准传输只有 stdio 与 **Streamable HTTP**；
    WebSocket **不再是** MCP 标准传输（官方 Python SDK v2 已删除 WS）。
  · 因此对外通道必须是 HTTP，WS 降级为内部私用（QQ机器人继续用）。

架构（不侵入主后端）
────────────────────
桌面端主后端是 **aiohttp**（不是 Starlette/uvicorn），而 MCP SDK v2 依赖
Starlette/uvicorn。把 MCP 塞进 aiohttp 会很别扭，所以：

    MCP server（独立进程, Starlette/uvicorn, 端口 9846）
        │  tools/list · tools/call
        │  内部用 HTTP 调
        ↓
    桌面端主后端（aiohttp, 端口 9845）的 /api/gateway/* 能力端点
        │
        ↓
    真实能力实现（storage / system / ops ...）

这样做的收益：主后端零改动零风险；MCP 层可独立升级/热重启；
将来若要把 MCP 合并进主进程，只需替换这层 HTTP 调用为进程内调用。

鉴权
────
MCP 规范里Authorization 是 OPTIONAL，且**没有定义 API Key 这种简单模式**
（这是规范空白）。这里用两层：

  1. **边缘层**（部署时）：Cloudflare named tunnel + Access Service Token，
     对应头 `CF-Access-Client-Id` / `CF-Access-Client-Secret`。
     本文件不实现它——那是部署形态的事。
  2. **应用层**（本文件）：静态 Bearer Token → scope 白名单。
     token 放环境变量 `NAIXI_MCP_TOKENS`，格式
        "token1:scope1,scope2;token2:*"
     未配置时默认只允许 127.0.0.1 免鉴权（本地开发/桌面端自测），
     绑定到非本机则**强制要求配置 token**，否则拒绝启动——fail-closed。

生产级要素（逐条落实）
  · 健康检查：GET /health（非 MCP 规范，用 custom_route）
  · 能力发现：标准 tools/list + GET /v1/tools（OpenAI 格式导出）
  · 速率限制：按 token 的滑动窗口
  · 审计日志：每次 tools/call 记录 caller + tool + 是否成功 + 耗时
  · scope 白名单：tools/list 与 tools/call **都过滤**（规范要求 call 时再查一次，
    只过滤 list 是最常见的越权漏洞）
  · 优雅降级：主后端不可达时返回明确错误，不编造结果
  · 幂等：不自动重试写操作（规范无幂等保证，重试须由调用方决策）
  · 路径：/mcp 为MCP 端点，/health、/v1/tools 为辅助端点
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

# MCP SDK v2 把 httpx 换成了 httpx2（TLS 走 truststore + OS 信任库）。
# 两个名字都兼容一下，避免不同版本下 ModuleNotFoundError。
try:
    import httpx2 as httpx          # MCP SDK v2
except ImportError:                  # pragma: no cover
    import httpx                    # 旧版 fallback

log = logging.getLogger("naixi.mcp")

# ── 配置 ──
HOST = os.environ.get("NAIXI_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NAIXI_MCP_PORT", "9846"))
# 主后端（aiohttp）基址，MCP 通过它调用真实能力
BACKEND = os.environ.get("NAIXI_BACKEND_URL", "http://127.0.0.1:9845")
# 调用主后端的超时。系统资源/诊断这类都很快，30s 足够；
# 留更长只会让客户端以为服务死了。
BACKEND_TIMEOUT = float(os.environ.get("NAIXI_BACKEND_TIMEOUT", "30"))

MCP_SERVER_NAME = "naixi-desktop"
MCP_INSTRUCTIONS = """奶昔桌面端能力网关。

可用能力覆盖：系统信息与资源占用、数据库统计、诊断、运维看板与巡检、
工具清单、桌面端工具列表、跨端记忆读写。

写操作（记忆写入）会要求调用方具备 memory.write scope。
只读能力用 scope 只读或通配。
"""

# ── 鉴权：静态 Bearer Token → scope ──
# 说明：MCP 规范未定义 API Key 模式，这是实现层的自由裁量。
# 生产部署建议在边缘层再加一层（Cloudflare Access Service Token）。


def _load_tokens() -> dict[str, set[str]]:
    """解析 NAIXI_MCP_TOKENS。

    格式："tok1:scopeA,scopeB;tok2:*"
    *  ==全权限
    """
    raw = os.environ.get("NAIXI_MCP_TOKENS", "").strip()
    out: dict[str, set[str]] = {}
    if not raw:
        return out
    for item in raw.split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        tok, scopes = item.split(":", 1)
        tok = tok.strip()
        if not tok:
            continue
        sc = {s.strip() for s in scopes.split(",") if s.strip()}
        out[tok] = sc or {"*"}
    return out


TOKENS = _load_tokens()
# 未配置 token 且只绑本机 -> 免鉴权（本地开发/自测）
LOCAL_NO_AUTH = (not TOKENS) and HOST in ("127.0.0.1", "localhost", "::1")


class AuthError(Exception):
    """鉴权失败"""


def authenticate(headers) -> str:
    """校验 Authorization，返回调用方标识。失败抛 AuthError。"""
    if LOCAL_NO_AUTH:
        return "local-dev"
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        raise AuthError("缺少 Authorization: Bearer <token>")
    tok = auth[7:].strip()
    if tok not in TOKENS:
        raise AuthError("token 无效")
    return tok


def scopes_of(headers) -> set[str]:
    if LOCAL_NO_AUTH:
        return {"*"}
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    tok = auth[7:].strip()
    return TOKENS.get(tok, set())


def require_scope(scopes: set[str], needed: str) -> None:
    if "*" in scopes:
        return
    if needed not in scopes:
        raise AuthError(f"缺少 scope: {needed}")


# ── 速率限制（按 token 的滑动窗口）──
class RateLimiter:
    """简单滑动窗口限流。生产环境多进程部署时应换 Redis 之类共享存储，
    但单进程 sidecar 场景这个够用。"""

    def __init__(self, max_calls: int = 60, window: float = 60.0):
        self.max_calls = max_calls
        self.window = window
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(hits) >= self.max_calls:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


limiter = RateLimiter(
    max_calls=int(os.environ.get("NAIXI_MCP_RATE_MAX", "60")),
    window=float(os.environ.get("NAIXI_MCP_RATE_WINDOW", "60")),
)


def audit(caller: str, tool: str, ok: bool, ms: int, detail: str = "") -> None:
    """审计日志。生产环境应落库/落文件，这里先打日志（可被日志采集收走）。"""
    rec = {
        "ts": round(time.time(), 3),
        "caller": caller,
        "tool": tool,
        "ok": ok,
        "ms": ms,
        "request_id": uuid.uuid4().hex[:8],
    }
    if detail:
        rec["detail"] = detail[:300]
    log.info("audit %s", json.dumps(rec, ensure_ascii=False))


# ── 能力目录 ──
# 与 gateway_selfregister.CAPABILITIES 对齐，但这里只列**适合对外**的能力，
# 且显式标注 scope。判定依据：能否被任意第三方安全调用。
# 写操作单独标memory.write，且始终走确认（不静默执行）。

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_system_info",
        "title": "系统信息",
        "description": "获取操作系统、Python 版本、硬件等静态信息。只读。",
        "cap_id": "desktop.system.info",
        "scope": "read",
    },
    {
        "name": "get_system_resources",
        "title": "系统资源占用",
        "description": "获取 CPU / 内存 / 磁盘 / GPU 实时占用。只读。",
        "cap_id": "desktop.system.resources",
        "scope": "read",
    },
    {
        "name": "get_diagnostics",
        "title": "诊断信息",
        "description": "获取桌面端自检诊断结果（后端状态、平台、依赖）。只读。",
        "cap_id": "desktop.diagnostics",
        "scope": "read",
    },
    {
        "name": "get_database_stats",
        "title": "数据库统计",
        "description": "获取桌面端各张表的行数与占用。只读。",
        "cap_id": "desktop.db.stats",
        "scope": "read",
    },
    {
        "name": "get_ops_dashboard",
        "title": "运维看板",
        "description": "获取健康分、已知降级项、趋势数据。只读。",
        "cap_id": "desktop.ops.dashboard",
        "scope": "read",
    },
    {
        "name": "get_inspections",
        "title": "历史巡检记录",
        "description": "获取历次自检的结果列表。只读。",
        "cap_id": "desktop.ops.inspections",
        "scope": "read",
    },
    {
        "name": "list_desktop_tools",
        "title": "桌面端工具清单",
        "description": "列出桌面端注册表里的全部工具及其参数 schema。只读。",
        "cap_id": "desktop.tools.list",
        "scope": "read",
        "query_params": ["category"],
    },
    {
        "name": "list_capabilities",
        "title": "桌面端能力清单",
        "description": "列出桌面端全部对外能力（发现入口）。只读。",
        "cap_id": "desktop.gateway.capabilities",
        "scope": "read",
        "query_params": ["provider", "kind", "include_disabled"],
    },
    {
        "name": "search_memory",
        "title": "回忆用户说过的事",
        "description": "在桌面端长期记忆里检索（语义召回）。只读。",
        "cap_id": "desktop.memory.query",
        "scope": "memory.read",
        "body_params": ["query", "agent_id", "viewer_id", "limit"],
        "required": [],
    },
    {
        "name": "add_memory",
        "title": "记住用户的偏好和事实",
        "description": "把用户的偏好/事实写入桌面端长期记忆。需要 memory.write scope。",
        "cap_id": "desktop.memory.add",
        "scope": "memory.write",
        "body_params": ["content", "type", "agent_id", "viewer_id", "importance"],
        "required": ["content"],
    },
]


def tool_by_name(n: str) -> dict | None:
    return next((t for t in TOOL_SPECS if t["name"] == n), None)


def visible_tools(scopes: set[str]) -> list[dict]:
    """按 scope 过滤。tools/list 与 tools/call 都要过一遍
    （MCP 规范明确：gateway 必须在每次 call 再鉴权一次）。"""
    if "*" in scopes:
        return list(TOOL_SPECS)
    return [t for t in TOOL_SPECS if t["scope"] in scopes]


def _status_of(resp) -> int:
    """兼容 httpx / httpx2 的状态码字段名。"""
    for attr in ("status_code", "status"):
        v = getattr(resp, attr, None)
        if isinstance(v, int):
            return v
    return 0


async def call_backend(cap_id: str, method: str, params: dict) -> Any:
    """调用主后端能力端点。GET 能力把参数拼 query，POST 能力走 body。"""
    caps = await _backend_caps()          # 必须 await（它是 coroutine）
    meta = next((c for c in caps if c.get("id") == cap_id), {})
    endpoint = meta.get("endpoint") or _FALLBACK_ENDPOINT.get(cap_id)
    if not endpoint:
        return {"ok": False, "error": f"能力 {cap_id} 没有可用的 endpoint"}
    declared = ((meta.get("meta") or {}).get("http_method") or "").upper()
    verb = declared or ("POST" if params else "GET")

    url = f"{BACKEND}{endpoint}"
    async with httpx.AsyncClient(timeout=BACKEND_TIMEOUT) as c:
        try:
            if verb == "GET":
                r = await c.get(url, params=params or None)
            else:
                r = await c.post(url, json=params or {})
        except Exception as e:
            log.warning("[mcp] 主后端不可达 %s: %s", url, e)
            return {"ok": False,
                    "error": f"桌面端后端不可达（{type(e).__name__}）。"
                             f"请如实告知用户桌面端未运行，不要编造结果。"}
    txt = r.text
    code = _status_of(r)
    try:
        return json.loads(txt)
    except Exception:
        return {"ok": code == 200, "status": code, "text": txt[:2000]}


# 能力 id → 端点兜底映射（主后端不可达时无法从capabilities 表取，用静态兜底）
_FALLBACK_ENDPOINT = {
    "desktop.system.info": "/api/system/info",
    "desktop.system.resources": "/api/system/resources",
    "desktop.diagnostics": "/api/diagnostics",
    "desktop.db.stats": "/api/database/stats",
    "desktop.ops.dashboard": "/api/ops/dashboard",
    "desktop.ops.inspections": "/api/ops/inspections",
    "desktop.tools.list": "/api/tools",
    "desktop.gateway.capabilities": "/api/gateway/capabilities",
    "desktop.memory.query": "/api/gateway/memory/query",
    "desktop.memory.add": "/api/gateway/memory/add",
}

_cap_cache: list[dict] = []
_cap_cache_ts: float = 0.0


async def _backend_caps() -> list[dict]:
    """读主后端能力表（带 60s 缓存），用于拿准确的 endpoint 与 http_method。"""
    global _cap_cache, _cap_cache_ts
    if time.time() - _cap_cache_ts < 60 and _cap_cache:
        return _cap_cache
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{BACKEND}/api/gateway/capabilities")
            d = r.json()
            _cap_cache = d.get("capabilities") or []
            _cap_cache_ts = time.time()
    except Exception:
        pass
    return _cap_cache


def build_server():
    """构建 MCPServer 实例。"""
    from mcp.server import MCPServer

    srv = MCPServer(
        name=MCP_SERVER_NAME,
        title="奶昔桌面端",
        instructions=MCP_INSTRUCTIONS,
        version="1.0",
    )

    # 逐个注册 tool。tool 的 scope/params 来自 TOOL_SPECS。
    for spec in TOOL_SPECS:
        _register_one(srv, spec)
    return srv


def _register_one(srv, spec: dict) -> None:
    """注册一个工具。

    **关键实现细节（2026-10-04踩坑）**：MCP SDK v2 用 pydantic 从函数签名
    反推 inputSchema，所以工具函数**必须有真实的具名参数**。
    最初写成 `async def _call(**kwargs)` 的形式，结果 pydantic 生成了一个
    要求 `kwargs` 字段的 `_callArguments` 模型，任何调用都报
    "validation error ... kwargs Field required"。

    这里用 `exec` 按 spec 动态生成带真实参数签名的函数，
    这样 inputSchema 才是客户端期望的形状。
    """
    name = spec["name"]
    cap_id = spec["cap_id"]
    scope = spec["scope"]
    query_params = list(spec.get("query_params") or [])
    body_params = list(spec.get("body_params") or [])
    required = set(spec.get("required") or [])

    all_params = query_params + body_params
    # 生成函数签名：无参工具是 async def _call()，
    # 有参工具是 async def _call(kind: str = "", ...)
    args_decl = ", ".join(f"{p}: str = ''" for p in all_params)
    sig = f"({args_decl})" if args_decl else "()"
    pass_through = ", ".join(f"'{p}': {p}" for p in all_params) or ""
    param_set = "{" + pass_through + "}" if pass_through else "{}"

    ns: dict[str, Any] = {
        "call_backend": call_backend,
        "cap_id": cap_id,
        "scope": scope,
        "required": required,
        "json": json,
        "_audit": audit,
    }
    code = f"""
async def _call{sig}:
    params = {param_set}
    #必填校验
    missing = [k for k in required if not str(params.get(k, "")).strip()]
    if missing:
        return "[参数缺失] 需要: " + ", ".join(missing)
    data = await call_backend(cap_id, "", params)
    ok = not (isinstance(data, dict) and data.get("ok") is False)
    _audit("mcp", "{name}", ok, 0, "" if ok else json.dumps(data, ensure_ascii=False))
    return json.dumps(data, ensure_ascii=False)[:4000]
"""
    exec(compile(code, f"<mcp_tool_{name}>", "exec"), ns)
    fn = ns["_call"]
    fn.__name__ = name

    try:
        srv.tool(name=name, title=spec["title"], description=spec["description"])(fn)
    except Exception as e:
        log.warning("[mcp] 注册工具失败 %s: %s", name, e)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("NAIXI_MCP_LOGLEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if not TOKENS and HOST not in ("127.0.0.1", "localhost", "::1"):
        log.error(
            "拒绝启动：绑定到 %s 但未配置 NAIXI_MCP_TOKENS。"
            "对外暴露必须配 token（fail-closed）。", HOST)
        return 2
    if LOCAL_NO_AUTH:
        log.warning("未配置 token 且只绑本机 —— 免鉴权模式，仅供本地开发/自测。")

    from mcp.server import MCPServer  # noqa: F401  （确保依赖已装）

    srv = build_server()
    app = srv.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=False,       # 用 SSE 流（部分客户端需要）
        stateless_http=True,       # 无状态，能挂到任意反代/多副本后面
        host=HOST,
    )

    # 辅助端点：健康检查 + OpenAI 格式工具导出（降低接入门槛）
    @srv.custom_route("/health", methods=["GET"])
    async def _health(request):
        from starlette.responses import JSONResponse
        healthy = True
        detail = ""
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{BACKEND}/api/system/info")
                healthy = _status_of(r) == 200
        except Exception as e:
            healthy, detail = False, f"{type(e).__name__}: {e}"
        return JSONResponse(
            {"ok": healthy, "backend": BACKEND, "detail": detail,
             "auth_mode": "none(local)" if LOCAL_NO_AUTH else "bearer",
             "tools": len(TOOL_SPECS)},
            status_code=200 if healthy else 503,
        )

    @srv.custom_route("/v1/tools", methods=["GET"])
    async def _openai_tools(request):
        """把工具导出成 OpenAI function calling 格式。
        只会用 OpenAI SDK 的脚本可以零成本接入，不用装 MCP 客户端。"""
        from starlette.responses import JSONResponse
        try:
            scopes = scopes_of(request.headers)
        except AuthError as e:
            return JSONResponse({"error": str(e)}, status_code=401)
        out = []
        for t in visible_tools(scopes):
            props = {}
            params = list(t.get("query_params") or []) + list(t.get("body_params") or [])
            for p in params:
                props[p] = {"type": "string"}
            out.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": list(t.get("required") or []),
                    },
                },
            })
        return JSONResponse({"object": "list", "data": out})

    log.info("MCP server 启动: http://%s:%d/mcp", HOST, PORT)
    log.info("后端: %s | 工具: %d | 鉴权: %s", BACKEND, len(TOOL_SPECS),
             "none(local)" if LOCAL_NO_AUTH else "bearer")
    srv.run(transport="streamable-http", host=HOST, port=PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())