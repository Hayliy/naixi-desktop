"""配额持久化端到端实测脚本（真实 SQLite + 模拟进程重启）

验证链路：
1. 刷屏 agent 触发速率隔离 -> 隔离状态落真实 SQLite 库（键 live_q:{agent_id}）
2. 模拟"进程重启"（丢弃内存 guard 实例，新建实例复用同一 SQLite）
   -> check_register 恢复隔离，刷屏 agent 无法靠断线重连洗白
3. 隔离自然到期 -> 自动解除并清除库记录（避免下次误恢复）
4. 重连不洗白：隔离期内的 agent 再次 check_register 仍被隔离

用法（在项目根目录 d:/naixi_desktop 执行）：
    python -m desktop_core._e2e_quota_persist

不依赖 aiohttp，不污染生产库 data/naixi_desktop.db（使用独立临时 SQLite 文件）。
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_core.live_bus import ConnectorGuard

AGENT = "spammer_bot"
RATE_WINDOW = 10.0
RATE_MAX = 20
QUARANTINE_SECS = 30.0

# 受控时钟：clock 与 wall 共用同一时间源，保证墙钟剩余时长能正确折算回内部单调时钟
_state = {"t": 1000.0}
clock = lambda: _state["t"]
wall = lambda: _state["t"]

# 临时 SQLite 库（独立文件，不污染生产库）
_tmp_db = os.path.join(tempfile.gettempdir(), "naixi_e2e_quota_test.db")
if os.path.exists(_tmp_db):
    os.remove(_tmp_db)

_conn = sqlite3.connect(_tmp_db)
_conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
_conn.commit()


def meta_get(key, default=""):
    row = _conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(key, value):
    _conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    _conn.commit()


class _FakeConn:
    """仅携带 agent_id 的假连接器（无 endpoint，跳过 token 校验，聚焦隔离持久化）。"""

    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.endpoint = ""
        self.token = ""


def _make_guard():
    return ConnectorGuard(
        require_token_for_remote=False,
        rate_window=RATE_WINDOW, rate_max=RATE_MAX, quarantine_secs=QUARANTINE_SECS,
        clock=clock, mem_get=meta_get, mem_set=meta_set, wall_clock=wall,
    )


def _run():
    failures = []

    def check(cond, msg):
        if cond:
            print(f"  [PASS] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            failures.append(msg)

    print("阶段 1：刷屏触发隔离 + 落库")
    g1 = _make_guard()
    for _ in range(RATE_MAX + 1):  # 速率窗口内连发 21 次（> 20 上限）
        g1.allow_emit(AGENT)
    check(g1.is_quarantined(AGENT), "刷屏后 agent 处于隔离")
    raw = meta_get(f"live_q:{AGENT}")
    check(raw != "", "隔离状态已写入 SQLite (live_q:{agent_id} 非空)")
    try:
        exp = float(raw)
        check(abs(exp - (_state["t"] + QUARANTINE_SECS)) < 0.5,
              f"库里存的是墙钟到期时间戳 ({exp})")
    except ValueError:
        check(False, "库里存的不是合法时间戳")

    print("阶段 2：模拟进程重启（新建实例复用同一 SQLite）")
    _state["t"] += 5.0  # 推进墙钟，模拟重启耗时（仍在隔离期内）
    g2 = _make_guard()
    ok, _reason = g2.check_register(_FakeConn(AGENT))
    check(ok, "check_register 通过（仅做恢复，不拒绝合法注册）")
    check(g2.is_quarantined(AGENT), "重启后 agent 仍在隔离期（未洗白）")
    check(meta_get(f"live_q:{AGENT}") != "", "重启后库记录仍在")

    print("阶段 3：隔离自然到期 -> 自动解除并清库")
    _state["t"] += QUARANTINE_SECS + 2.0  # 越过隔离到期
    check(not g2.is_quarantined(AGENT), "越过隔离时长后自动解除")
    check(meta_get(f"live_q:{AGENT}") == "", "解除后库记录被清除（不误恢复）")
    check(g2.allow_emit(AGENT), "解除后发言恢复正常")

    print("阶段 4：重连不洗白（隔离期内再次 check_register）")
    g3 = _make_guard()
    for _ in range(RATE_MAX + 1):
        g3.allow_emit(AGENT)
    check(g3.is_quarantined(AGENT), "再次刷屏触发隔离")
    _state["t"] += 1.0  # 模拟断线后重连的少量时间流逝
    g4 = _make_guard()
    g4.check_register(_FakeConn(AGENT))
    check(g4.is_quarantined(AGENT), "断线重连后仍在隔离期（无法靠重连洗白）")

    _conn.close()
    if os.path.exists(_tmp_db):
        os.remove(_tmp_db)

    print("")
    if failures:
        print(f"结果：{len(failures)} 项 FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
