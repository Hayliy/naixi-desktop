"""MCP 客户端 — 连接 MCP 服务器发现并执行工具"""
import asyncio, json, logging, os
from typing import Optional

log = logging.getLogger("mcp")

class MCPServer:
    """单个 MCP 服务器连接"""
    
    def __init__(self, name: str, command: str, args: list[str] = None, env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools: list = []
        self._req_id = 0

    async def connect(self):
        """启动子进程并等待就绪"""
        import shutil
        merged_env = dict(os.environ)
        if self.env:
            merged_env.update(self.env)
        # 自动解析命令路径（支持 npx 等不在系统 PATH 中的命令）
        node_bin = r"C:\Users\21222\.workbuddy\binaries\node\versions\22.22.2"
        # 确保 Node.js 目录在 PATH 中（npx.cmd 需要 node.exe）
        if node_bin not in merged_env.get("PATH", ""):
            merged_env["PATH"] = node_bin + os.pathsep + merged_env.get("PATH", "")
        # 搜索命令
        resolved_command = shutil.which(self.command)
        if not resolved_command:
            # Windows 上 npx 需要 .cmd 扩展名
            if os.name == "nt":
                cmd_path = os.path.join(node_bin, self.command + ".cmd")
                if os.path.exists(cmd_path):
                    resolved_command = cmd_path
                elif os.path.exists(self.command):
                    resolved_command = self.command
            else:
                resolved_command = self.command
        import subprocess as _sp
        startup_kw = {}
        if os.name == "nt":  # Windows: 彻底隐藏 cmd 窗口，不闪屏
            startup_kw["creationflags"] = _sp.CREATE_NO_WINDOW
            # 额外用 STARTUPINFO 隐藏（对 bat/cmd 有效）
            si = _sp.STARTUPINFO()
            si.dwFlags |= _sp.STARTF_USESHOWWINDOW
            si.wShowWindow = _sp.SW_HIDE
            startup_kw["startupinfo"] = si
        self._process = await asyncio.create_subprocess_exec(
            resolved_command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
            **startup_kw,
        )
        log.info(f"[MCP] {self.name}: 已启动 {resolved_command} {' '.join(self.args)}")
        # 发送 initialize 请求（首次可能需下载依赖，给 60 秒）
        init_result = await self._request("initialize", {
            "protocolVersion": "2025-11-05",
            "capabilities": {},
            "clientInfo": {"name": "naixi-desktop", "version": "1.0"},
        }, timeout=60)
        if init_result:
            await self._request("notifications/initialized", {})
            # 获取工具列表
            tools_result = await self._request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self._tools = tools_result["tools"]
                log.info(f"[MCP] {self.name}: 发现 {len(self._tools)} 个工具")
        return len(self._tools) > 0

    async def _request(self, method: str, params: dict, timeout: float = 10) -> Optional[dict]:
        """发送 JSON-RPC 请求并等待响应"""
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None
        try:
            data = (json.dumps(request) + "\n").encode("utf-8")
            self._process.stdin.write(data)
            await self._process.stdin.drain()
            
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=timeout
            )
            if line:
                response = json.loads(line.decode("utf-8").strip())
                if "result" in response:
                    return response["result"]
                elif "error" in response:
                    log.warning(f"[MCP] {self.name} 请求错误: {response['error']}")
                    return None
        except asyncio.TimeoutError:
            log.warning(f"[MCP] {self.name} 请求超时: {method}")
        except Exception as e:
            log.warning(f"[MCP] {self.name} 请求失败: {e}")
        return None

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具"""
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        if result:
            content = result.get("content", [])
            # 提取文本内容
            texts = []
            for c in content:
                if c.get("type") == "text":
                    texts.append(c.get("text", ""))
                elif c.get("type") == "resource":
                    texts.append(str(c.get("resource", {})))
            return "\n".join(texts) if texts else str(result)[:2000]
        return f"MCP 工具 {name} 执行失败"

    def get_tool_definitions(self) -> list:
        """返回 OpenAI 兼容的工具定义"""
        result = []
        for t in self._tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            params = t.get("inputSchema", {})
            if not name:
                continue
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params,
                }
            })
        return result

    async def disconnect(self):
        """关闭连接"""
        if self._process:
            try:
                self._process.stdin.close()
            except: pass
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except: pass

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

class MCPManager:
    """管理多个 MCP 服务器连接"""

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}

    def add_server(self, name: str, command: str, args: list[str] = None, env: dict = None):
        """注册一个 MCP 服务器"""
        self._servers[name] = MCPServer(name, command, args, env)

    async def connect_all(self) -> int:
        """连接所有已注册的服务器"""
        count = 0
        for name, server in self._servers.items():
            try:
                if await server.connect():
                    count += 1
            except Exception as e:
                log.warning(f"[MCP] {name} 连接失败: {e}")
        return count

    def get_all_tool_definitions(self) -> list:
        """获取所有 MCP 服务器的工具定义"""
        tools = []
        for name, server in self._servers.items():
            tools.extend(server.get_tool_definitions())
        return tools

    async def execute_tool(self, name: str, arguments: dict) -> str:
        """在所有 MCP 服务器中查找并执行工具"""
        for srv_name, server in self._servers.items():
            for t in server._tools:
                if t.get("name") == name and server.is_connected:
                    return await server.call_tool(name, arguments)
        return f"MCP 工具 {name} 未找到（服务器未连接或无此工具）"

    async def disconnect_all(self):
        """断开所有连接"""
        for server in self._servers.values():
            await server.disconnect()
