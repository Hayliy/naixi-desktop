"""多角色直播 冒烟测试（无网络 / 无 ffmpeg）
验证：LiveBus / SpeechArbiter / 回声防护 / NaixiConnector / 引擎分发-发言-舞台提示-释麦 闭环。
运行：python -m desktop_core._smoke_live_multiagent
"""
import asyncio
import random

from desktop_core.live_bus import (
    LiveBus, SpeechArbiter, AgentConnector, NaixiConnector,
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
    ok("bot" in e._connectors and len(e.list_connectors()) == 2, "外部角色成功上台")

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


async def main():
    for t in (test_bus, test_arbiter, test_echo, test_normalize, test_engine_flow):
        await t()
    print(f"\n结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
