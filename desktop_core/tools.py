"""桌面端工具系统 — 工具注册表 + 执行器"""
import asyncio, json, logging, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse
from datetime import datetime

log = logging.getLogger("tools")

# 工作区根目录
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ── 工具注册表 ──
_registry = {}

def register(name, description, parameters, handler, category="core"):
    _registry[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "category": category,
    }

def load_plugins():
    """从插件目录加载外部工具"""
    try:
        from desktop_core.plugin_mgr import get_plugin_tools
        existing = get_definitions()
        plugin_tools = get_plugin_tools(existing)
        for pt in plugin_tools:
            fn = pt.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
            if name and name not in _registry:
                # 注册一个动态执行的 handler，从 plugin_mgr 调用
                register(name, desc, params, _make_plugin_handler(name))
                log.info(f"[工具] 插件注册: {name}")
    except Exception as e:
        log.warning(f"[工具] 插件加载失败: {e}")

def load_mcp_tools(mcp_mgr):
    """从 MCP 管理器加载 MCP 工具到注册表"""
    if not mcp_mgr:
        return
    mcp_tools = mcp_mgr.get_all_tool_definitions()
    for mt in mcp_tools:
        fn = mt.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        if name and name not in _registry:
            register(name, desc, params, _make_mcp_handler(name, mcp_mgr))
            log.info(f"[工具] MCP 注册: {name}")

def _make_mcp_handler(tool_name, mcp_mgr):
    """为 MCP 工具生成 handler"""
    async def handler(args, ctx):
        try:
            return await mcp_mgr.execute_tool(tool_name, args)
        except Exception as e:
            return f"MCP 工具 {tool_name} 执行失败: {str(e)[:200]}"
    return handler

def _make_plugin_handler(tool_name):
    """为插件工具生成一个异步 handler"""
    async def handler(args, ctx):
        try:
            # 在 plugin_mgr 中查找对应的执行器
            from desktop_core.plugin_mgr import execute_plugin_tool
            return await execute_plugin_tool(tool_name, args)
        except Exception as e:
            return f"插件工具 {tool_name} 执行失败: {str(e)[:200]}"
    return handler

def get_definitions(category=None):
    """返回 OpenAI 兼容的工具定义列表
    category=None 返回全部, core/extra/system 返回对应类别的子集"""
    tools = _registry.values()
    if category:
        tools = [t for t in tools if t.get("category") == category]
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in tools
    ]

def get_fast_definitions():
    """返回全部工具定义（当前 36+ 个工具，含 MCP，直接返回全部）"""
    return get_definitions()


def get_mcp_manager():
    global _mcp_manager
    if _mcp_manager is None:
        from desktop_core.mcp_client import MCPManager
        _mcp_manager = MCPManager()
        # 从配置加载 MCP 服务器列表
        try:
            from desktop_core.storage import meta_get
            import json
            raw = meta_get("desktop_config")
            if raw:
                cfg = json.loads(raw)
                for name, srv in cfg.get("mcp_servers", {}).items():
                    cmd = srv.get("command", "")
                    args = srv.get("args", [])
                    env = srv.get("env", {})
                    if cmd:
                        _mcp_manager.add_server(name, cmd, args, env)
        except: pass
    return _mcp_manager

async def connect_mcp_servers():
    """连接所有 MCP 服务器并注册其工具"""
    mgr = get_mcp_manager()
    count = await mgr.connect_all()
    if count > 0:
        load_mcp_tools(mgr)
    return count
