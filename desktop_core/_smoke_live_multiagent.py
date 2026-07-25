"""多角色直播 冒烟测试（无网络 / 无 ffmpeg）
验证：LiveBus / SpeechArbiter / 回声防护 / NaixiConnector / 引擎分发-发言-舞台提示-释麦 闭环。
运行：python -m desktop_core._smoke_live_multiagent
"""
import asyncio
import random

from desktop_core.live_bus import (
    LiveBus, SpeechArbiter, AgentConnector, NaixiConnector, HttpAgentConnector,
    WsAgentConnector, HumanConnector, ConnectorGuard,
    normalize_utterance, should_react_to_cue, make_speech_request,
    PRIORITY_HOST, PRIORITY_GUEST, PRIORITY_LOW, MAX_CUE_DEPTH,
)

PASS, FAIL = [], []
def ok(cond, name):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name)


async def test_bus():
    print("[1] LiveBus 发布订阅")
    bus = LiveBus()
    q = bus.subscribe("t")
    await bus.publish("t", {"x": 1})
    ev = q.get_nowait()
    ok(ev["x"] == 1, "发布的事件能被订阅者收到")
    bus.unsubscribe("t", q)
    ok(bus.subscriber_count("t") == 0, "退订后订阅数归零")


async def test_arbiter():
    print("[2] SpeechArbiter 占麦仲裁")
    arb = SpeechArbiter(queue_cap=3)
    r1 = {"name": "A", "priority": PRIORITY_GUEST, "text": "a"}
    admitted = await arb.submit(r1)
    ok(admitted is r1 and arb.busy, "麦位空闲时首个直接占麦")
    r2 = {"name": "B", "priority": PRIORITY_GUEST, "text": "b"}
    admitted2 = await arb.submit(r2)
    ok(admitted2 is None, "麦位忙时同级进队列")
    r3 = {"name": "奶昔", "priority": PRIORITY_HOST, "text": "host"}
    admitted3 = await arb.submit(r3)
    ok(admitted3 is r3, "主咖高优可打断当前低优发言")
    nxt = await arb.release()
    ok(nxt is r2, "释放后取出排队中的下一句")

    # 队列上限丢弃最旧低优
    arb2 = SpeechArbiter(queue_cap=2)
    await arb2.submit({"name": "cur", "priority": PRIORITY_GUEST, "text": "c"})  # 占麦
    await arb2.submit({"name": "low1", "priority": PRIORITY_LOW, "text": "1"})
    await arb2.submit({"name": "low2", "priority": PRIORITY_LOW, "text": "2"})
    await arb2.submit({"name": "low3", "priority": PRIORITY_LOW, "text": "3"})  # 触发溢出丢最旧低优
    got = []
    while True:
        n = await arb2.release()
        if not n: break
        got.append(n["name"])
    ok("low1" not in got and "low3" in got, "队列溢出丢弃最旧低优发言")


async def test_echo():
    print("[3] 回声防护 should_react_to_cue")
    random.seed(0)
    ok(should_react_to_cue({"cue_depth": MAX_CUE_DEPTH}) is False, "达到最大链深不再反应")
    # depth 0 概率 0.7，depth 1 概率 0.4，用大样本估计
    random.seed(42)
    c0 = sum(should_react_to_cue({"cue_depth": 0}) for _ in range(2000)) / 2000
    c1 = sum(should_react_to_cue({"cue_depth": 1}) for _ in range(2000)) / 2000
    ok(0.6 < c0 < 0.8, f"depth0 反应概率约0.7 (实测{c0:.2f})")
    ok(0.3 < c1 < 0.5, f"depth1 反应概率约0.4 (实测{c1:.2f})")


async def test_normalize():
    print("[4] normalize_utterance")
    ok(normalize_utterance(None) is None, "None → None")
    ok(normalize_utterance("  hi ") == {"text": "hi", "emotion": "开心", "action": ""}, "str 规整")
    ok(normalize_utterance({"text": "yo", "emotion": "害羞"})["emotion"] == "害羞", "dict 保留情绪")
    ok(normalize_utterance({"text": "  "}) is None, "空文本 → None")


async def test_engine_flow():
    print("[5] 引擎多角色闭环（分发→占麦→发言→舞台提示→释麦）")
    # 测试机的受管 Python 未装 aiohttp（真实 sidecar 自带）；本用例不走网络，
    # 用最小桩顶替 aiohttp 以便导入 live_engine。
    import sys, types
    if "aiohttp" not in sys.modules:
        stub = types.ModuleType("aiohttp")
        stub.WSMsgType = types.SimpleNamespace(TEXT=1, BINARY=2, ERROR=258, CLOSED=257)
        stub.ClientSession = object
        stub.ClientWebSocketResponse = object
        stub.WebSocketResponse = object
        sys.modules["aiohttp"] = stub
    from desktop_core.live_engine import LiveEngine
    e = LiveEngine()

    # 屏蔽网络/合成：奶昔决策用固定文本，外部角色回声一次
    async def fake_decide(text, user):
        return (f"奶昔收到:{text[:8]}", "开心", "wave")
    e._decide_reply = fake_decide
    e._connectors["naixi"] = NaixiConnector(e._decide_reply)

    class EchoBot(AgentConnector):
        def __init__(self):
            super().__init__("bot", "小助手", PRIORITY_GUEST)
            self.dm = 0; self.cue = 0
        async def handle_danmaku(self, d):
            self.dm += 1
            return {"text": f"小助手也说:{d.get('text','')[:6]}", "emotion": "开心"}
        async def handle_cue(self, c):
            self.cue += 1
            return None  # 不接舞台提示，避免无限
    bot = EchoBot()
    e.register_connector(bot)
    ok("bot" in e._connectors and len(e.list_connectors()) == 3, "外部角色成功上台（含内置奶昔+人类副播）")

    # 分发一条弹幕：两个角色都想说 → 一个占麦，一个排队
    await e._dispatch_danmaku({"type": "danmaku", "text": "大家好", "user": "路人"})
    ok(e._scene_queue.qsize() == 1, "分发后仅一句进语音管道（单麦位）")
    ok(e._arbiter.busy, "占麦仲裁处于忙碌")

    # 模拟这句说完：释麦 + 广播舞台提示
    first = await e._scene_queue.get()
    await e._after_speak(first, spoken=True)
    ok(e._scene_queue.qsize() == 1, "释麦后放行排队中的下一句")
    ok(bot.cue >= 1, "已说的一句被广播为舞台提示，其他角色收到")

    # 把剩余队列走完，确认最终收敛、不无限对喷
    steps = 0
    while e._scene_queue.qsize() and steps < 50:
        item = await e._scene_queue.get()
        await e._after_speak(item, spoken=True)
        steps += 1
    ok(steps < 50, f"发言链有限收敛（{steps}步内清空）")

    # @路由：只投给被点名的角色
    tgt, cleaned = e._match_mention("@小助手 在吗")
    ok(tgt is bot and cleaned == "在吗", "@路由 命中指定角色并清理@标记")


async def test_evict():
    print("[6] SpeechArbiter.evict 下台清理麦位")
    arb = SpeechArbiter(queue_cap=5)
    await arb.submit({"name": "奶昔", "agent_id": "naixi", "priority": PRIORITY_HOST, "text": "h"})
    g1 = {"name": "甲", "agent_id": "g1", "priority": PRIORITY_GUEST, "text": "a"}
    g2 = {"name": "乙", "agent_id": "g2", "priority": PRIORITY_GUEST, "text": "b"}
    await arb.submit(g1)
    await arb.submit(g2)
    ok(arb.busy and len(arb._pending) == 2, "初始化：主咖占麦，两嘉宾排队")
    # 拔掉排队中的 g1 → 其排队请求被丢弃，g2 仍在
    await arb.evict("g1")
    pending_ids = [r["agent_id"] for r in arb._pending]
    ok("g1" not in pending_ids and len(arb._pending) == 1, "evict 丢弃排队中的目标请求")
    # 拔掉当前占麦的主咖 → 麦位顺给下一等待者(g2)，不卡死
    await arb.evict("naixi")
    ok(arb._current is not None and arb._current["agent_id"] == "g2", "evict 当前占麦者，麦位交给下一等待者")
    ok(arb.busy, "evict 后仍忙碌（下一句接管）")


def _make_http_stub(fail_first_n=0, status=200, body='{"text": "ok"}'):
    """构造可用的 aiohttp 桩：前 fail_first_n 次 post 抛 ClientError，之后返回指定响应。"""
    import sys, types, json as _json
    stub = types.ModuleType("aiohttp")
    class ClientError(Exception):
        pass
    stub.ClientError = ClientError
    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total
    stub.ClientTimeout = ClientTimeout
    counter = {"n": 0}
    class FakeResp:
        def __init__(self, status, body):
            self.status = status
            self._body = body
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def json(self):
            return _json.loads(self._body) if isinstance(self._body, str) else self._body
        async def text(self):
            return self._body if isinstance(self._body, str) else ""
    class FakeSession:
        def __init__(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        def post(self, *a, **k):
            counter["n"] += 1
            if counter["n"] <= fail_first_n:
                raise ClientError(f"simulated transient #{counter['n']}")
            return FakeResp(status, body)
    stub.ClientSession = FakeSession
    return stub, counter


async def test_http_retry():
    print("[7] HttpAgentConnector 抗瞬时故障 + 逻辑跳过")
    import sys
    saved = sys.modules.get("aiohttp")

    # 场景1：首次 ClientError，二次成功 → 重试后拿到文本
    try:
        stub, counter = _make_http_stub(fail_first_n=1, body='{"text": "你好我是外部角色"}')
        sys.modules["aiohttp"] = stub
        conn = HttpAgentConnector("ext1", "外部甲", "http://x/y", max_retries=2, timeout=5)
        res = await conn.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res is not None and "你好" in str(res), "瞬时故障后重试成功拿到回复")

    # 场景2：持续失败 → 安全返回 None，不崩溃（重试耗尽）
    try:
        stub2, counter2 = _make_http_stub(fail_first_n=99, body='{}')
        sys.modules["aiohttp"] = stub2
        conn2 = HttpAgentConnector("ext2", "外部乙", "http://x/y", max_retries=2, timeout=5)
        res2 = await conn2.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res2 is None, "持续失败后安全返回 None（不崩溃）")
    ok(counter2["n"] == 3, "重试次数 = max_retries+1（共3次尝试）")

    # 场景3：HTTP 非200 → 逻辑不可达，不重试直接跳过
    try:
        stub3, counter3 = _make_http_stub(fail_first_n=0, status=500, body='err')
        sys.modules["aiohttp"] = stub3
        conn3 = HttpAgentConnector("ext3", "外部丙", "http://x/y", max_retries=2, timeout=5)
        res3 = await conn3.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res3 is None and counter3["n"] == 1, "HTTP 非200 不重试直接跳过本轮")


def _make_ws_stub(fail_first_n=0, reply=None):
    """构造可用的 aiohttp 桩（ws 版）：前 fail_first_n 次 ws_connect 抛 ClientError，之后返回给定回复。"""
    import sys, types
    stub = types.ModuleType("aiohttp")
    class ClientError(Exception):
        pass
    stub.ClientError = ClientError
    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total
    stub.ClientTimeout = ClientTimeout
    counter = {"n": 0}
    class FakeWS:
        def __init__(self, reply):
            self._reply = reply
        async def send_json(self, p):
            pass
        async def receive_json(self):
            return self._reply
        async def close(self):
            pass
    class FakeSession:
        def __init__(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def ws_connect(self, *a, **k):
            counter["n"] += 1
            if counter["n"] <= fail_first_n:
                raise ClientError(f"ws transient #{counter['n']}")
            return FakeWS(reply)
    stub.ClientSession = FakeSession
    return stub, counter


async def test_ws_connector():
    print("[8] WsAgentConnector 协议 + 抗瞬时故障")
    import sys
    saved = sys.modules.get("aiohttp")
    # 场景1：首次 ClientError → 二次成功
    try:
        stub, counter = _make_ws_stub(fail_first_n=1, reply={"text": "ws回复内容"})
        sys.modules["aiohttp"] = stub
        conn = WsAgentConnector("w1", "远程甲", "ws://x/y", max_retries=2, timeout=5)
        res = await conn.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res is not None and "ws回复内容" in str(res), "ws 瞬时故障后重试拿到回复")
    # 场景2：远端 ok=false → 跳过本轮
    try:
        stub2, _ = _make_ws_stub(fail_first_n=0, reply={"ok": False})
        sys.modules["aiohttp"] = stub2
        conn2 = WsAgentConnector("w2", "远程乙", "ws://x/y")
        res2 = await conn2.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res2 is None, "ws 远端拒答(ok=false) 跳过本轮")
    # 场景3：持续故障 → None 不崩溃
    try:
        stub3, c3 = _make_ws_stub(fail_first_n=99, reply={})
        sys.modules["aiohttp"] = stub3
        conn3 = WsAgentConnector("w3", "远程丙", "ws://x/y", max_retries=2)
        res3 = await conn3.handle_danmaku({"text": "hi", "user": "u"})
    finally:
        if saved is not None:
            sys.modules["aiohttp"] = saved
        else:
            sys.modules.pop("aiohttp", None)
    ok(res3 is None and c3["n"] == 3, "ws 持续失败安全返回 None（3次尝试）")


async def test_human_inject():
    print("[9] 人类副播 inject_human_speech")
    import sys, types
    if "aiohttp" not in sys.modules:
        stub = types.ModuleType("aiohttp")
        stub.WSMsgType = types.SimpleNamespace(TEXT=1)
        stub.ClientSession = object
        stub.ClientWebSocketResponse = object
        stub.WebSocketResponse = object
        sys.modules["aiohttp"] = stub
    from desktop_core.live_engine import LiveEngine
    e = LiveEngine()
    async def fake(text, user):
        return (f"奶昔:{text[:6]}", "开心", "wave")
    e._decide_reply = fake
    e._connectors["naixi"] = NaixiConnector(e._decide_reply)
    ok("human" in e._connectors, "内置人类副播槽位存在")
    ok(isinstance(e._connectors["human"], HumanConnector), "human 是 HumanConnector")
    ok(await e.inject_human_speech("human", "大家好我是真人") is True, "注入人类发言成功")
    ok(e._scene_queue.qsize() == 1, "注入的发言进入语音管道")
    item = await e._scene_queue.get()
    ok(item.get("text") == "大家好我是真人" and item.get("agent_id") == "human", "注入内容正确带 agent_id=human")
    ok(await e.inject_human_speech("human", "   ") is False, "空文本注入被拒")
    ok(await e.inject_human_speech("naixi", "x") is False, "对非人类连接器注入被拒")


async def test_guard():
    print("[10] ConnectorGuard 鉴权 + 限流隔离")
    g = ConnectorGuard(require_token_for_remote=True)
    ok(g.check_register(HttpAgentConnector("x", "X", "http://x", token=""))[0] is False, "远程无 token 注册被拒")
    ok(g.check_register(HttpAgentConnector("x", "X", "http://x", token="sec"))[0] is True, "带 token 注册通过")
    ok(g.check_register(NaixiConnector(lambda t, u: (t, "开心", "")))[0] is True, "本地连接器免 token")
    # 限流：注入可控时钟
    clock = {"t": 0.0}
    g2 = ConnectorGuard(rate_window=10.0, rate_max=3, quarantine_secs=30.0,
                        trusted_ids=("naixi", "human"), clock=lambda: clock["t"])
    results = [g2.allow_emit("bot") for _ in range(4)]
    ok(results == [True, True, True, False], "超过速率上限第4次被拒并隔离")
    ok(g2.is_quarantined("bot") is True, "隔离生效")
    ok(g2.allow_emit("naixi") is True and g2.allow_emit("human") is True, "信任角色不受限流")
    clock["t"] = 31.0
    ok(g2.is_quarantined("bot") is False, "冷却结束后解除隔离")
    ok(g2.allow_emit("bot") is True, "解除后可再次发言")


async def test_guard_persist():
    print("[11] ConnectorGuard 隔离状态持久化（重启/重连不洗白）")
    store = {}
    def mget(k): return store.get(k, "")
    def mset(k, v): store[k] = v
    clock = {"t": 0.0}       # 内部单调时钟
    wall = {"t": 1000.0}     # 墙钟
    g = ConnectorGuard(rate_window=10.0, rate_max=3, quarantine_secs=30.0,
                       trusted_ids=("naixi",), clock=lambda: clock["t"],
                       wall_clock=lambda: wall["t"], mem_get=mget, mem_set=mset)
    res = [g.allow_emit("bot") for _ in range(4)]
    ok(res == [True, True, True, False], "刷屏第4次触发隔离")
    ok(bool(store.get("live_q:bot")), "隔离到期墙钟已落库")

    # 模拟重启：新建 guard（内部单调时钟归零），墙钟前进 10s → 隔离剩 20s
    g2 = ConnectorGuard(rate_window=10.0, rate_max=3, quarantine_secs=30.0,
                        trusted_ids=("naixi",), clock=lambda: 0.0,
                        wall_clock=lambda: 1010.0, mem_get=mget, mem_set=mset)
    g2.restore("bot")
    ok(g2.is_quarantined("bot") is True, "重启后恢复隔离态（剩余约20s仍隔离）")

    # 墙钟越过隔离结束点再新建 → 恢复为不隔离并清库
    g3 = ConnectorGuard(clock=lambda: 0.0, wall_clock=lambda: 1031.0,
                        trusted_ids=("naixi",), mem_get=mget, mem_set=mset)
    g3.restore("bot")
    ok(g3.is_quarantined("bot") is False, "隔离期已过：恢复为不隔离")
    ok(store.get("live_q:bot", "") == "", "过期后清除持久化记录")

    # check_register 也触发 restore：重连不能靠断线洗白
    store["live_q:bot"] = f"{1000.0 + 25:.3f}"   # 手动置一个未到期隔离
    g4 = ConnectorGuard(clock=lambda: 0.0, wall_clock=lambda: 1000.0,
                        trusted_ids=("naixi",), mem_get=mget, mem_set=mset)
    g4.check_register(HttpAgentConnector("bot", "刷屏bot", "http://x", token="t"))
    ok(g4.is_quarantined("bot") is True, "重连(check_register)自动恢复隔离，不能靠断线洗白")


async def test_ws_server():
    print("[12] WsServerConnector 服务端热插拔 + req_id 多路复用")
    from desktop_core.live_bus import WsServerConnector

    class FakeServerWS:
        def __init__(self):
            self.sent = []
            self.closed = False
            self.on_send = None
        async def send_json(self, obj):
            self.sent.append(obj)
            if self.on_send:
                self.on_send(obj)
        async def close(self):
            self.closed = True

    # 场景1：正常问答，远端按 req_id 回复被正确路由
    ws = FakeServerWS()
    conn = WsServerConnector("rbot", "反向bot", ws, token="t", timeout=2.0)
    ws.on_send = lambda obj: conn.feed_reply(
        obj["req_id"], {"text": "反向回复:" + obj["data"].get("text", ""), "emotion": "开心"})
    res = await conn.handle_danmaku({"text": "hi", "user": "u"})
    ok(res is not None and "反向回复:hi" in res["text"], "反向连入：req_id 关联的回复被正确路由")
    ok(conn.endpoint == "ws-in:rbot", "endpoint 标记为 ws-in（治理层判定远程需 token）")

    # 场景2：远端回 None → 不接话
    ws2 = FakeServerWS()
    conn2 = WsServerConnector("rbot2", "反向bot2", ws2, token="t", timeout=2.0)
    ws2.on_send = lambda obj: conn2.feed_reply(obj["req_id"], None)
    ok(await conn2.handle_cue({"text": "x", "name": "同台"}) is None, "远端回 None → 不接话")

    # 场景3：远端 ok=false → 不接话
    ws3 = FakeServerWS()
    conn3 = WsServerConnector("rbot3", "反向bot3", ws3, token="t", timeout=2.0)
    ws3.on_send = lambda obj: conn3.feed_reply(obj["req_id"], {"ok": False})
    ok(await conn3.handle_danmaku({"text": "y", "user": "u"}) is None, "远端 ok=false → 不接话")

    # 场景4：远端不回复 → 超时安全返回 None，不卡死
    ws4 = FakeServerWS()
    conn4 = WsServerConnector("rbot4", "反向bot4", ws4, token="t", timeout=0.2)
    ok(await conn4.handle_danmaku({"text": "z", "user": "u"}) is None, "远端不回复 → 超时安全返回 None")

    # 场景5：并发多问乱序回复不串答（req_id 多路复用）
    ws5 = FakeServerWS()
    conn5 = WsServerConnector("rbot5", "反向bot5", ws5, token="t", timeout=2.0)
    pend = []
    ws5.on_send = lambda obj: pend.append(obj)
    ta = asyncio.create_task(conn5.handle_danmaku({"text": "AAA", "user": "u"}))
    tb = asyncio.create_task(conn5.handle_danmaku({"text": "BBB", "user": "u"}))
    await asyncio.sleep(0.05)                       # 让两请求都发出
    for obj in reversed(pend):                      # 乱序回复：先回后发的
        conn5.feed_reply(obj["req_id"], {"text": "R:" + obj["data"]["text"]})
    ra, rb = await ta, await tb
    ok(ra["text"] == "R:AAA" and rb["text"] == "R:BBB", "并发多问乱序回复不串答（req_id 隔离）")

    # 场景6：close 取消挂起请求并关闭 socket
    ws6 = FakeServerWS()
    conn6 = WsServerConnector("rbot6", "反向bot6", ws6, token="t", timeout=5.0)
    t6 = asyncio.create_task(conn6.handle_danmaku({"text": "hang", "user": "u"}))
    await asyncio.sleep(0.02)
    await conn6.close()
    r6 = await t6
    ok(r6 is None and ws6.closed, "close 取消挂起请求并关闭 socket")


async def main():
    for t in (test_bus, test_arbiter, test_echo, test_normalize, test_engine_flow,
              test_evict, test_http_retry, test_ws_connector, test_human_inject, test_guard,
              test_guard_persist, test_ws_server):
        await t()
    print(f"\n结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
