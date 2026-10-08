# 对等互联：跨机 / 跨网配置

桌面端控制平面（WS，默认 18400）默认**只绑本机**（安全设计，防浏览器跨域/DNS 重绑定）。
要让虚拟机 / Linux / 另一台电脑的奶昔加入 mesh，按下面配。所有项都可自定义。

## 1. 桌面端（Hub 侧，被连接方）

设两个环境变量后重启桌面端即可：

```bash
# 绑到所有网卡（局域网可达）
GATEWAY_WS_HOST=0.0.0.0
# 配置访问 token（格式同 MCP："tok1:scope1,scope2;tok2:*"，* = 全权限）
NAIXI_GATEWAY_TOKENS="mytoken:*"
```

- **fail-closed**：设了 `GATEWAY_WS_HOST=0.0.0.0` 却**不配 token** → WS 拒绝启动（业务端口 9845 不受影响），
  避免控制平面裸露到网络。
- 其它可配项：`GATEWAY_WS_PORT`（WS 端口）、`NAIXI_MCP_HOST/NAIXI_MCP_TOKENS/NAIXI_MCP_PORT`（MCP 通道，同策略）。
- 桌面端「对等互联」页面（右侧「开放接入」→「对等互联 Mesh」）会如实显示当前绑定地址、
  是否局域网可达、token 是否已配。

## 2. 对端（QQ 侧 / 另一台机器的奶昔，连接方）

在 `naixi_py` 侧设：

```bash
# 指向桌面端的 WS 地址（换成本机或对方局域网 IP）
GATEWAY_PEER_WS="ws://192.168.1.10:18400/ws/gateway"
# 填上面配置的 token（本机免鉴权时留空）
GATEWAY_PEER_TOKEN="mytoken"
```

对端会自动重连；连上后互相发现（peers）并能调用对方能力（read 类直接调，write/dangerous 需确认）。

## 3. 公网 / 跨网段（跨 NAT）

跨网段或要暴露到公网，端口无法被直连，需要一条**隧道中继**把 WS 端口转发出去。
项目已用 cloudflared，可直接复用（也可用 ngrok / frp / Tailscale，思路相同）：

```bash
# 先按第 1 步把桌面端起成 0.0.0.0 + token，再把 18400 挂到隧道：
cloudflared tunnel --url ws://127.0.0.1:18400
# 或固定隧道：cloudflared tunnel run <隧道名>（配置里 ingress → ws://127.0.0.1:18400）
```

对端则连隧道给的公网地址，并带 token：

```bash
GATEWAY_PEER_WS="wss://<隧道子域名>/ws/gateway"
GATEWAY_PEER_TOKEN="mytoken"
```

> 暴露到公网时**务必**保留 token 认证（fail-closed 已保证：不配 token 不会绑 0.0.0.0）。
> 如需更强防护，可在隧道前再加一层 IP 白名单 / mTLS。

## 安全边界

- 控制平面一旦绑 `0.0.0.0`，**任何能路由到本机的人都能尝试连入** —— token 是唯一防线，务必用强随机 token。
- HTTP 业务端口（9845）**始终只绑本机**，不随 WS 一起暴露。
- write / dangerous 能力不提供直接调用，需人工确认（对端只能发起提议）。
