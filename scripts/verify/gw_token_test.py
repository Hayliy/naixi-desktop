# -*- coding: utf-8 -*-
"""对等互联 WS token 鉴权 + 非本机可达性端到端测试(真实连接，不 mock)。"""
import asyncio, sys, json
import aiohttp

WS_PATH = "/ws/gateway"
TOKEN = "testtoken123"
HOSTS = ["127.0.0.1", "192.168.0.105"]  # 本机 + 局域网IP(模拟非本机)


async def try_connect(host, token=None, timeout=6):
    url = f"ws://{host}:18400{WS_PATH}"
    if token:
        url += f"?token={token}&provider=test-peer"
    else:
        url += "?provider=test-peer"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.ws_connect(url) as ws:
                # 发 hello(声明 provider) 后应收到 welcome
                await ws.send_str(json.dumps({
                    "type": "hello", "provider": "test-peer",
                    "capabilities": [], "remote": host,
                }))
                msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    return ("OK", data.get("type", "?"), data)
                return ("OK", f"msgtype={msg.type}", {})
    except aiohttp.WSServerHandshakeError as e:
        return (f"拒绝({e.status})", str(e.status), {})
    except Exception as e:
        return (f"失败({type(e).__name__})", str(e)[:60], {})


async def main():
    results = []
    print("=" * 60)
    for host in HOSTS:
        # 1) 带正确 token → 应成功拿到 welcome
        st, tp, data = await try_connect(host, TOKEN)
        ok = (st == "OK" and tp == "welcome")
        print(f"[{host}] 带正确token -> {st} / type={tp}  {'✅' if ok else '❌'}")
        if ok:
            print(f"    welcome: peers={len(data.get('peers', []))} "
                  f"capabilities={len(data.get('capabilities', []))}")
        results.append((host, "带token", ok))
        # 2) 不带 token → 应被拒(401)
        st, tp, _ = await try_connect(host, None)
        rejected = st.startswith("拒绝") or st.startswith("失败")
        print(f"[{host}] 不带token     -> {st}  {'✅' if rejected else '❌'}")
        results.append((host, "无token", rejected))
        # 3) 错 token → 应被拒
        st, tp, _ = await try_connect(host, "wrongtoken")
        rejected = st.startswith("拒绝") or st.startswith("失败")
        print(f"[{host}] 错token       -> {st}  {'✅' if rejected else '❌'}")
        results.append((host, "错token", rejected))
    passed = sum(1 for _, _, ok in results if ok)
    print("=" * 60)
    print(f"通过 {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
