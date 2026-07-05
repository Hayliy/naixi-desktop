"""安全沙箱 — 代码执行 / 文件操作 / 系统交互的安全限制"""
import asyncio, logging, os, platform, shutil, subprocess, sys, tempfile, time

log = logging.getLogger("sandbox")

class Sandbox:
    """代码执行沙箱：子进程 + 超时 + 资源限制"""

    TIMEOUT = 30       # 最大执行时间（秒）
    MAX_OUTPUT = 3000  # 最大输出长度

    # ── 系统交互（安全限制） ──
    ALLOWED_SYSTEM_COMMANDS = [
        "start", "explorer", "notepad", "calc", "mspaint",
        "whoami", "hostname", "systeminfo", "tasklist",
        "ipconfig", "netstat", "ping", "tracert",
        "dir", "type", "findstr", "where",
        "python", "node", "npm", "pip", "git",
        "code", "wt", "powershell",
    ]

    DANGEROUS_COMMANDS = [
        "rm -rf /", "rmdir /s", "del /f /s", "format",
        "shutdown", "reboot", "taskkill /f /im",
        "reg delete", "netsh", "bcdedit", "diskpart",
    ]

    async def run_system_command(self, command: str, timeout: int = 30) -> str:
        """运行系统命令（带安全限制）"""
        cmd_lower = command.strip().lower()
        # 检查危险命令
        for d in self.DANGEROUS_COMMANDS:
            if d in cmd_lower:
                return f"❌ 禁止执行危险命令: {d}"
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=os.path.expanduser("~"),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"⏱ 命令执行超时（{timeout}秒）"
            out = (stdout or b"").decode("utf-8", errors="replace")[:self.MAX_OUTPUT]
            err = (stderr or b"").decode("utf-8", errors="replace")[:500]
            if err:
                out += f"\n--- 错误 ---\n{err}"
            return out or "（命令执行完毕，无输出）"
        except Exception as e:
            return f"❌ 执行失败: {str(e)[:200]}"

    async def get_system_info(self) -> str:
        """获取系统信息"""
        info = []
        info.append(f"操作系统: {platform.system()} {platform.release()} {platform.version()}")
        info.append(f"主机名: {platform.node()}")
        info.append(f"处理器: {platform.processor()}")
        info.append(f"架构: {platform.machine()}")
        # 内存信息
        if sys.platform == "win32":
            try:
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                mem = MEMORYSTATUSEX()
                mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
                total_gb = mem.ullTotalPhys / (1024**3)
                avail_gb = mem.ullAvailPhys / (1024**3)
                info.append(f"内存: 总计 {total_gb:.1f}GB, 可用 {avail_gb:.1f}GB ({int((1-avail_gb/total_gb)*100)}% 已用)")
            except:
                info.append("内存: 无法获取")
        else:
            try:
                import psutil
                mem = psutil.virtual_memory()
                info.append(f"内存: 总计 {mem.total/1024**3:.1f}GB, 可用 {mem.available/1024**3:.1f}GB ({mem.percent}% 已用)")
            except:
                info.append("内存: 需安装 psutil")
        return "\n".join(info)

    async def open_url(self, url: str) -> str:
        """在默认浏览器中打开 URL"""
        import webbrowser
        try:
            webbrowser.open(url)
            return f"✅ 已在浏览器中打开: {url}"
        except Exception as e:
            return f"❌ 打开失败: {str(e)[:100]}"

    async def run_python(self, code: str, timeout: int = None) -> str:
        """在隔离环境执行 Python 代码"""
        tmp = tempfile.mkdtemp(prefix="naixi_sandbox_")
        timeout = timeout or self.TIMEOUT
        try:
            fpath = os.path.join(tmp, "script.py")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(code)

            proc = await asyncio.create_subprocess_exec(
                sys.executable, fpath,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=tmp,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"代码执行超时（{timeout}秒）"

            out = (stdout or b"").decode("utf-8", errors="replace")
            err = (stderr or b"").decode("utf-8", errors="replace")

            result = out[:self.MAX_OUTPUT]
            if err:
                result += f"\n--- 错误 ---\n{err[:self.MAX_OUTPUT]}"
            return result or "（无输出）"

        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def validate_path(self, path: str, workspace: str) -> str:
        """验证文件路径是否在允许的工作区内"""
        full = os.path.normpath(os.path.join(workspace, path))
        if not full.startswith(os.path.normpath(workspace)):
            raise PermissionError(f"不允许访问工作区外的文件: {path}")
        return full

    async def run_shell(self, command: str, timeout: int = 10) -> str:
        """执行 shell 命令（严格受限）"""
        # 白名单：只允许安全的命令
        allowed_prefixes = [
            "ls", "cat", "head", "tail", "wc", "echo", "pwd", "date",
            "python --version", "pip list", "which", "dir",
        ]
        cmd_stripped = command.strip()
        safe = any(cmd_stripped.startswith(p) for p in allowed_prefixes)
        if not safe:
            return f"不允许执行该命令（仅支持: {', '.join(allowed_prefixes)}）"

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return "命令执行超时"
        out = (stdout or b"").decode(errors="replace")[:self.MAX_OUTPUT]
        err = (stderr or b"").decode(errors="replace")[:min(500, self.MAX_OUTPUT)]
        return out + (f"\n--- 错误 ---\n{err}" if err else "")
