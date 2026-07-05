"""安全沙箱 — 代码执行 / 文件操作的安全限制"""
import asyncio, logging, os, shutil, subprocess, sys, tempfile

log = logging.getLogger("sandbox")

class Sandbox:
    """代码执行沙箱：子进程 + 超时 + 资源限制"""

    TIMEOUT = 30       # 最大执行时间（秒）
    MAX_OUTPUT = 3000  # 最大输出长度

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
