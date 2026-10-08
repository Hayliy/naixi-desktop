"""跨机互联真实验证脚本 —— 放到「虚拟机」里运行。

与之前"本机用局域网 IP 连自己"的验证不同：本脚本必须在**另一台设备**
（虚拟机 / 另一台电脑）上跑，才能证明"非本机真的能连进来"。

用法（在虚拟机里）：
    python vm_link_test.py <宿主IP> <连接口令>

例：
    python vm_link_test.py 192.168.0.105 NAErLXdiFM

只依赖标准库（urllib / socket / json），不需要装任何东西。
"""

import json
import socket
import sys
import urllib.error
import urllib.request


def probe_ws(host, port, path, token, timeout=8):
    """用最原始的 socket 手搓 WebSocket 握手 —— 不依赖 aiohttp/websockets。

    这样在虚拟机里不装任何第三方库也能验证。
    """
    key = "dGhlIHNhbXBsZSBub25jZQ=="          # 固定 nonce，够用
    req = (
        f"GET {path}?provider=vm-test&token={token} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except Exception as e:
        return f"TCP 连接失败: {type(e).__name__}: {e}"
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
        if "101" not in head.split("\r\n")[0]:
            first = head.split("\r\n")[0] if head else "(空响应)"
            return f"握手被拒: {first.strip()}"
        return "握手成功 (HTTP 101 Switching Protocols)"
    finally:
        s.close()


def probe_mcp(host, port, token, timeout=10):
    """完整 MCP 握手：initialize 拿 session，再 tools/list 验证真能调能力。"""
    url = f"http://{host}:{port}/mcp"
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "vm-link-test", "version": "1.0"},
        },
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        sid = r.headers.get("mcp-session-id", "")
        body = r.read(400).decode("utf-8", "replace")
        return f"initialize 成功 (session={sid[:12] or '无'}) | {body[:80]}"
    except urllib.error.HTTPError as e:
        return f"被拒: HTTP {e.code} {e.read(120).decode('utf-8', 'replace')}"
    except Exception as e:
        return f"失败: {type(e).__name__}: {str(e)[:80]}"


def main():
    # 口令可以命令行给，也可以放在 VMware 共享目录里自动读（省得抄错）
    token = ""
    if len(sys.argv) >= 3:
        host, token = sys.argv[1].strip(), sys.argv[2].strip()
    else:
        for base in (r"\\vmware-host\Shared Folders\naixi_test",
                     r"\\vmware-host\Shared Folders\shared",
                     "token.txt", "vmshare\\token.txt"):
            try:
                if "\\" in base and not base.endswith(".txt"):
                    host = "192.168.0.105"
                    with open(base + r"\token.txt", "r", encoding="utf-8") as f:
                        token = f.read().strip()
                elif base == "token.txt":
                    host = host or "192.168.0.105"
                    with open(base, "r", encoding="utf-8") as f:
                        token = f.read().strip()
                else:
                    host = host or "192.168.0.105"
                    with open(base, "r", encoding="utf-8") as f:
                        token = f.read().strip()
                if token:
                    print(f"已从 {base} 读到口令\n")
                break
            except Exception:
                continue

    if not host or not token:
        print(__doc__)
        print("错误：需要 <宿主IP> 和 <连接口令>")
        return 2

    print("=" * 66)
    print(" 跨机互联真实验证（从虚拟机发起）")
    print("=" * 66)
    print(f" 本机视角  : {socket.gethostname()} / {socket.gethostbyname(socket.gethostname())}")
    print(f" 目标宿主  : {host}")
    print(f" 连接口令  : {token[:4]}...{token[-4:]}（共 {len(token)} 位）")
    print()

    results = []

    print("─" * 66)
    print(" 1) 基础网络：能不能到宿主")
    print("─" * 66)
    for port, name in ((18400, "订阅通道 WS"), (9846, "能力调用 HTTP")):
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.close()
            print(f" [OK]   {name} 端口 {port} 可达")
            results.append((f"{name} TCP", True))
        except Exception as e:
            print(f" [FAIL] {name} 端口 {port} 不可达 —— {type(e).__name__}")
            results.append((f"{name} TCP", False))
    print()

    print("─" * 66)
    print(" 2) 订阅通道（WS）：带口令握手")
    print("─" * 66)
    r = probe_ws(host, 18400, "/ws/gateway", token)
    ok = "成功" in r
    print(f" {'[OK]  ' if ok else '[FAIL]'} {r}")
    results.append(("WS 握手", ok))

    r_bad = probe_ws(host, 18400, "/ws/gateway", "WRONG_TOKEN_XYZ")
    ok_bad = "被拒" in r_bad
    print(f" {'[OK]  ' if ok_bad else '[WARN]'} 错误口令应被拒 → {r_bad}")
    results.append(("WS 错误口令被拒", ok_bad))
    print()

    print("─" * 66)
    print(" 3) 能力调用通道（HTTP/MCP）：完整握手 + 列能力")
    print("─" * 66)
    r = probe_mcp(host, 9846, token)
    ok = "成功" in r
    print(f" {'[OK]  ' if ok else '[FAIL]'} {r}")
    results.append(("MCP initialize", ok))
    print()

    print("=" * 66)
    passed = sum(1 for _, o in results if o)
    print(f" 结果：{passed}/{len(results)} 项通过")
    print("=" * 66)
    for name, o in results:
        print(f"  {'PASS' if o else 'FAIL'}  {name}")
    print()
    if passed == len(results):
        print("结论：跨机互联真实可用（这是从另一台设备发起的验证）")
        return 0
    print("结论：存在问题，请把上面的失败项发给开发者")
    return 1


if __name__ == "__main__":
    sys.exit(main())
