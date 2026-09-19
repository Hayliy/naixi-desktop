# -*- coding: utf-8 -*-
"""系统资源指标采集（Windows ctypes，零子进程）。

## 为什么不用 psutil 取指标
2026-09-20 深度测试在真机实测到 psutil 7.2.2 的以下行为，**直接导致运维指标失真**：

| 调用 | 实测结果 |
|---|---|
| `psutil.cpu_percent(interval=0.3)` 第 1 次 | 19.5 ✓ |
| `psutil.cpu_percent(interval=0.3)` 第 2 次 | **0.0** ✗（同版本下重复调用失真） |
| `psutil.cpu_percent()`（非阻塞）前两次 | 0.0 / 0.0，第三次才有值 |
| `psutil.Process().cpu_percent(interval=0.3)` | **恒 0.0** |
| `psutil.disk_usage("/")` | Windows 上按**当前工作目录所在盘**解释（CWD 一变盘就变） |

后果（用户可见）：
- 运维总览「后端 CPU」恒 0；`compute_health_score(sys_cpu=0)` 让 CPU 项**永远满分** → 健康分虚高；
- 自愈里 `cpu_pct > 95` **永不成立** → 「后端资源回收」这条自愈路径完全失效；
- 巡检报告里的 CPU 项恒 0。

本模块改用 GetSystemTimes / GlobalMemoryStatusEx / GetDiskFreeSpaceEx / GetProcessTimes
直接取数：口径稳定、与任务管理器一致、不 spawn 子进程（不触发安全软件拦截），
并且提供 **async 版本**（采样等待交给事件循环，不阻塞其它请求）。
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import time
from ctypes import Structure, byref, sizeof, wintypes

__all__ = [
    "cpu_times", "cpu_percent", "cpu_percent_async",
    "memory", "memory_percent", "disk", "disk_percent",
    "process_times", "process_cpu_percent",
]


# ────────────────────────── CPU ──────────────────────────

def cpu_times() -> tuple[int, int, int]:
    """返回 (idle, kernel, user) 累计 100ns 时间片。"""
    idle, kernel, user = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
    ok = ctypes.windll.kernel32.GetSystemTimes(byref(idle), byref(kernel), byref(user))

    def _to_int(ft) -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    if not ok:
        return 0, 0, 0
    return _to_int(idle), _to_int(kernel), _to_int(user)


def _cpu_from_times(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    idle = b[0] - a[0]
    kernel = b[1] - a[1]
    user = b[2] - a[2]
    # Windows 的 kernel 时间**包含** idle，故总时间为 kernel + user
    total = kernel + user
    if total <= 0:
        return 0.0
    busy = total - idle
    return round(max(0.0, min(100.0, busy / total * 100.0)), 1)


def cpu_percent(interval: float = 0.3) -> float:
    """阻塞式采样 CPU 占用（两次 GetSystemTimes 求差）。interval 秒。"""
    a = cpu_times()
    if interval > 0:
        time.sleep(interval)
    return _cpu_from_times(a, cpu_times())


async def cpu_percent_async(interval: float = 0.3) -> float:
    """异步版：采样间隔交给事件循环，避免阻塞其它请求。"""
    a = cpu_times()
    if interval > 0:
        await asyncio.sleep(interval)
    return _cpu_from_times(a, cpu_times())


# ────────────────────────── 内存 ──────────────────────────

class _MEMORYSTATUSEX(Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory() -> tuple[float, int, int]:
    """返回 (占用百分比, 总字节, 可用字节)。"""
    st = _MEMORYSTATUSEX()
    st.dwLength = sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(st)):
        return 0.0, 0, 0
    total = int(st.ullTotalPhys)
    avail = int(st.ullAvailPhys)
    pct = round((1 - avail / total) * 100, 1) if total > 0 else 0.0
    return pct, total, avail


def memory_percent() -> float:
    return memory()[0]


# ────────────────────────── 磁盘 ──────────────────────────

def _system_drive() -> str:
    """系统盘根路径（不写死 C:，也不依赖当前工作目录）。"""
    drive = os.environ.get("SystemDrive") or "C:"
    return drive.rstrip("\\/") + "\\"


def disk(drive: str | None = None) -> tuple[int, int]:
    """返回 (总字节, 可用字节)。drive 省略时取系统盘。"""
    path = drive or _system_drive()
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(path), None, byref(total), byref(free)
    )
    if not ok:
        return 0, 0
    return int(total.value), int(free.value)


def disk_percent(drive: str | None = None) -> float:
    total, free = disk(drive)
    if total <= 0:
        return 0.0
    return round((1 - free / total) * 100, 1)


# ────────────────────────── 进程 CPU（替代 psutil.Process.cpu_percent） ──────────────────────────

class _FILETIME(Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_cpu_baseline: dict[int, tuple[float, float]] = {}


def process_times(pid: int) -> tuple[float, float] | None:
    """返回进程 (user+kernel) 累计秒数；失败返回 None。

    用 GetProcessTimes，不需要 psutil，也不受其进程级 cpu_percent 恒 0 的影响。
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        creation, exit_, kernel, user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        ok = ctypes.windll.kernel32.GetProcessTimes(
            h, byref(creation), byref(exit_), byref(kernel), byref(user)
        )
        if not ok:
            return None

        def _secs(ft) -> float:
            return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7

        return _secs(kernel), _secs(user)
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def process_cpu_percent(pid: int) -> float:
    """进程 CPU 占用百分比（0-100 * 核心数上限按单核口径归一，与任务管理器一致取 ÷ 核心数）。

    采用「与上次调用求差」的方式：首次调用无基线，返回 0.0（这是必然的，
    任何两次采样法都一样），后续调用返回真实值。调用方按固定周期轮询即可。
    """
    t = process_times(pid)
    if t is None:
        return 0.0
    busy = t[0] + t[1]
    now = time.time()
    prev = _cpu_baseline.get(pid)
    _cpu_baseline[pid] = (now, busy)
    if not prev:
        return 0.0
    dw = now - prev[0]
    dp = busy - prev[1]
    if dw <= 0.05:
        return 0.0
    ncpu = os.cpu_count() or 1
    pct = (dp / dw) / ncpu * 100.0
    return round(max(0.0, min(pct, 100.0)), 1)


def prime_process_cpu(pid: int) -> None:
    """预热：先取一次基线，使紧接着的 process_cpu_percent() 能立刻给出有效值。"""
    t = process_times(pid)
    if t is not None:
        _cpu_baseline[pid] = (time.time(), t[0] + t[1])
