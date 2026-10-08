#!/usr/bin/env python3
"""TCP 中继模拟（等价于 cloudflared / frp 的转发本质）。

真实公网中继的三段结构：
    外部客户端  →  中继（公网可达）  →  宿主真实服务（在 NAT 后面）
本机没有公网 IP，所以这里用「另一个容器/端口」充当"中继"这一跳，
客户端只知道中继地址，不知道宿主真实地址 —— 验证的正是这一段。

用法：
    python3 relay_sim.py <中继监听端口> <宿主IP> <宿主端口>
例：
    python3 relay_sim.py 39000 192.168.151.154 9846
"""

import socket
import socketserver
import sys
import threading


class Relay(socketserver.BaseRequestHandler):
    upstream = ("127.0.0.1", 0)

    def handle(self):
        try:
            up = socket.create_connection(self.upstream, timeout=20)
        except Exception:
            return

        def pipe(src, dst):
            try:
                while True:
                    data = src.recv(8192)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    dst.close()
                except Exception:
                    pass

        t = threading.Thread(target=pipe, args=(up, self.request), daemon=True)
        t.start()
        pipe(self.request, up)


class ThreadedRelay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    listen_port = int(sys.argv[1])
    host_ip = sys.argv[2]
    host_port = int(sys.argv[3])

    Relay.upstream = (host_ip, host_port)
    srv = ThreadedRelay(("0.0.0.0", listen_port), Relay)
    print(f"中继就绪: 0.0.0.0:{listen_port} -> {host_ip}:{host_port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
