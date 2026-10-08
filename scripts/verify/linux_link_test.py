#!/usr/bin/env python3
"""跨机互联真实验证 —— Linux 侧探针（WSL / Docker 容器 / 任意 Linux 机器）。

与本机自连验证的根本区别：这个脚本必须在**另一台设备**上跑，
才能证明"非本机真的能连进来"。

用法：
    python3 linux_link_test.py <宿主IP> <连接口令>

例：
    python3 linux_link_test.py 192.168.0.105 NAErLXdiFM

只依赖 Python 标准库，不需要 pip install 任何东西。
"""

import json
import socket
import sys
import urllib.error
import urllib.request


def probe_ws(host, port, path, token, timeout=8):
    """手搓 WebSocket 握手（RFC 6455），不依赖第三方库。"""
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    req = (
        f"GET {path}?provider=linux-test&token={token} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except Exception as e:
        return False, f"TCP 连接失败: {type(e).__name__}: {e}"
    try:
        s.settimeout(timeout)
        s.sendall(req.encode())
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 8192:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        head = data.decode("latin1", "replace")
        status = head.split("\r\n")[0] if head else "(空)"
        if "101" not in status:
            return False, f"握手被拒: {status.strip()}"
        return True, "握手成功 (HTTP 101 Switching Protocols)"
    finally:
        s.close()


def probe_mcp(host, port, token, timeout=12):
    """完整 MCP 握手：initialize 拿 session，验证真的能调能力。"""
    url = f"http://{host}:{port}/mcp"
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "linux-link-test", "version": "1.0"},
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        body = r.read(300).decode("utf-8", "replace")
        sid = r.headers.get("mcp-session-id", "")
        return True, f"initialize 成功 (session={sid[:12] or '无'}) | {body[:100]}"
    except urllib.error.HTTPError as e:
        return False, f"被拒: HTTP {e.code} {e.read(120).decode('utf-8', 'replace')}"
    except Exception as e:
        return False, f"失败: {type(e).__name__}: {str(e)[:80]}"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    host = sys.argv[1].strip()
    token = sys.argv[2].strip()

    print("=" * 68)
    print(" 跨机互联真实验证（Linux/WSL 侧发起）")
    print("=" * 68)
    try:
        print(f" 本机: {socket.gethostname()} / {socket.gethostbyname(socket.gethostname())}")
    except Exception:
        print(f" 本机: {socket.gethostname()}")
    print(f" 目标: {host}")
    print(f" 口令: {token[:4]}...{token[-4:]}（{len(token)} 位）")
    print()

    results = []

    print("--- 1) TCP 可达性 " + "-" * 50)
    for port, name in ((18400, "订阅通道 WS"), (9846, "能力调用 HTTP")):
        try:
            socket.create_connection((host, port), timeout=5).close()
            print(f" [OK]   {name} 端口 {port} 可达")
            results.append((f"{name} TCP 可达", True))
        except Exception as e:
            print(f" [FAIL] {name} 端口 {port} 不可达 —— {type(e).__name__}")
            results.append((f"{name} TCP 可达", False))
    print()

    print("--- 2) 订阅通道 WS 握手（正确口令）" + "-" * 32)
    ok, msg = probe_ws(host, 18400, "/ws/gateway", token)
    print(f" {'[OK]  ' if ok else '[FAIL]'} {msg}")
    results.append(("WS 正确口令握手", ok))

    ok, msg = probe_ws(host, 18400, "/ws/gateway", "WRONG_TOKEN_XYZ")
    ok2 = (not ok) and ("401" in msg or "拒绝" in msg)
    print(f" {'[OK]  ' if ok2 else '[FAIL]'} 错误口令应被拒 → {msg[:70]}")
    results.append(("WS 错误口令被拒", ok2))
    print()

    print("--- 3) 能力调用 MCP initialize（正确口令）" + "-" * 26)
    ok, msg = probe_mcp(host, 9846, token)
    print(f" {'[OK]  ' if ok else '[FAIL]'} {msg}")
    results.append(("MCP initialize", ok))
    print()

    print("=" * 68)
    passed = sum(1 for _, o in results if o)
    print(f" 结果：{passed}/{len(results)} 项通过")
    print("=" * 68)
    for name, o in results:
        print(f"  {'PASS' if o else 'FAIL'}  {name}")
    print()
    if passed == len(results):
        print("结论：Linux/WSL 跨机互联真实可用（真·第二设备发起）")
        return 0
    print("结论：存在问题，请把失败项发给开发者")
    return 1


if __name__ == "__main__":
    sys.exit(main())
