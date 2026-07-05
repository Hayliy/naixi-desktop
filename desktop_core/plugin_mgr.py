"""插件系统 — 从 plugins/ 目录动态加载工具"""
import asyncio, importlib.util, json, logging, os, sys

log = logging.getLogger("plugins")

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")

# 缓存已加载的插件模块
_plugin_modules = {}

def discover_plugins() -> list:
    global _plugin_modules
    if not os.path.isdir(PLUGINS_DIR):
        os.makedirs(PLUGINS_DIR, exist_ok=True)
        return []
    plugins = []
    for fname in sorted(os.listdir(PLUGINS_DIR)):
        if fname.endswith(".py") and not fname.startswith("_"):
            fpath = os.path.join(PLUGINS_DIR, fname)
            try:
                mod_name = f"plugin_{fname[:-3]}"
                spec = importlib.util.spec_from_file_location(mod_name, fpath)
                if not spec or not spec.loader: continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _plugin_modules[mod_name] = mod
                if hasattr(mod, "register_plugin"):
                    tool_defs = mod.register_plugin()
                    if isinstance(tool_defs, list):
                        plugins.extend(tool_defs)
                        log.info(f"[插件] 加载: {fname}")
                else:
                    log.warning(f"[插件] {fname}: 缺少 register_plugin()")
            except Exception as e:
                log.warning(f"[插件] {fname} 加载失败: {e}")
    return plugins

def get_plugin_tools(existing_tools: list) -> list:
    plugin_tools = discover_plugins()
    existing_names = {t.get("function", {}).get("name", "") for t in existing_tools}
    return [pt for pt in plugin_tools if pt.get("function", {}).get("name", "") not in existing_names]

async def execute_plugin_tool(tool_name: str, args: dict) -> str:
    """执行插件工具"""
    for mod_name, mod in _plugin_modules.items():
        if hasattr(mod, "execute_tool"):
            try:
                result = mod.execute_tool(tool_name, args)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is not None:
                    return str(result)[:5000]
            except Exception as e:
                log.warning(f"[插件] {mod_name}.{tool_name} 失败: {e}")
    return f"插件工具 {tool_name} 未找到"

