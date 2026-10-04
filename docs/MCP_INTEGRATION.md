# 奶昔桌面端 · 开放接入指南

任何 AI bot / 脚本 / 任何部署位置（本机、云服务器、虚拟机）都能接入奶昔桌面端的能力。

---

## 一、两种接入方式

### 方式 A：MCP（推荐，通用性最强）

MCP（Model Context Protocol）是当前唯一「什么客户端都能连」的标准。
Claude Code / Cursor / Cline / Claude Desktop / Gemini CLI 全部原生支持，
官方 SDK 覆盖 TypeScript / Python / C# / Go / Rust / Ruby / Java / Swift / PHP / Kotlin。

**端点**：`http://127.0.0.1:9846/mcp`（默认本机；对外需自行配隧道，见第三节）

**Python 接入**（官方 SDK）：

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client("http://127.0.0.1:9846/mcp") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        for t in tools.tools:
            print(t.name, "-", t.description)
        result = await session.call_tool("get_system_resources", {})
        print(result.content[0].text)
```

**TypeScript 接入**：

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const client = new Client({ name: "my-bot", version: "1.0.0" });
await client.connect(new StreamableHTTPClientTransport(
  new URL("http://127.0.0.1:9846/mcp")
));
const { tools } = await client.listTools();
const r = await client.callTool({ name: "get_system_resources", arguments: {} });
```

**其它语言**：用对应语言的官方 SDK，传输一律选 `streamable-http`。

### 方式 B：OpenAI Function Calling 格式（零依赖）

只会用 OpenAI SDK 的脚本可以直接拿工具定义，不需要装 MCP 客户端。

```
GET http://127.0.0.1:9846/v1/tools
```

返回标准 `{"type":"function","function":{...}}` 数组，直接塞进
OpenAI / DeepSeek / 通义等任意模型的 `tools` 参数即可。

---

## 二、可用的 10 个能力

| 工具名 | 说明 | scope |
|---|---|---|
| `get_system_info` | 操作系统 / Python 版本 / 主机名 / PID | read |
| `get_system_resources` | CPU / 内存 / 磁盘 / GPU 实时占用 | read |
| `get_diagnostics` | 后端状态、平台、依赖自检 | read |
| `get_database_stats` | 各表行数与占用 | read |
| `get_ops_dashboard` | 健康分、降级项、趋势 | read |
| `get_inspections` | 历史巡检记录 | read |
| `list_desktop_tools` | 桌面端工具清单及参数 schema | read |
| `list_capabilities` | 桌面端全部对外能力（发现入口） | read |
| `search_memory` | 长期记忆语义检索 | memory.read |
| `add_memory` | 写入长期记忆 | **memory.write** |

参数化工具的参数（客户端从 `input_schema` 自动获知）：

- `list_desktop_tools(category=...)`
- `list_capabilities(provider=..., kind=..., include_disabled=...)`
- `search_memory(query=..., agent_id=..., viewer_id=..., limit=...)`
- `add_memory(content=【必填】, type=..., agent_id=..., viewer_id=..., importance=...)`

---

## 三、让远程/云端能连

MCP 只监听 `127.0.0.1`，这是**有意的**（fail-closed）。
要让外网访问，按需求选一种：

### 方案 1：Tailscale Serve（私有可达，最推荐）

双方都装 Tailscale（无需域名、无需公网 IP、无需 VPS）：

```bash
tailscale serve --bg 9846          # 桌面端
# 另一台机器用 https://<你的-magic>.<tailnet>.ts.net:9846/mcp
```

### 方案 2：Cloudflare Tunnel（公开可达）

⚠️ 必须用 **named tunnel**，Quick Tunnel **不支持 SSE**（MCP 依赖它）。

1. 买域名托管到 Cloudflare
2. 建 named tunnel，配 `http://127.0.0.1:9846`
3. 叠加 **Access Service Token** 做鉴权：
   客户端加两个头
   `CF-Access-Client-Id` / `CF-Access-Client-Secret`
4. Windows 常驻注意事项（社区经验）：
   - 用 NSSM 注册服务 + **绝对路径** config（`cloudflared service install` 在 Windows 易报 Error 1033）
   - 显式加 `--logfile`（默认不写日志）
   - 笔记本需关闭休眠，否则休眠即断隧道
   - `net stop cloudflared` 常卡死，备好 `taskkill /F /IM cloudflared.exe`
5. **125 秒超时**：Cloudflare 代理读超时是 125s，长任务需靠流保活

### 方案 3：frp 自建 VPS（完全自控）

```
外部客户端 ──HTTPS──> VPS(frps) ──►桌面端 frpc ──► 127.0.0.1:9846
```
适合不想依赖 Cloudflare / Tailscale 的场景。

---

## 四、鉴权

MCP 规范里 Authorization 是 OPTIONAL，且**没有定义 API Key 这种简单模式**
（规范空白，官方 ext-auth 只有 OIDC 与 Client Credentials）。

本实现用**静态 Bearer Token → scope 白名单**：

```bash
# 环境变量格式："token1:scopeA,scopeB;token2:*"
NAIXI_MCP_TOKENS="tok_read:read,memory.read;tok_all:*"
NAIXI_MCP_HOST="0.0.0.0"        # 非本机绑定时必填
NAIXI_MCP_PORT="9846"
```

客户端加头：

```
Authorization: Bearer tok_read
```

行为：
- **未配置 token 且只绑本机** → 免鉴权（本地开发/自测）
- **绑到非本机却没配 token** → **拒绝启动**（fail-closed，绝不裸奔）
- scope 不含所需权限 → 返回权限不足，不执行

生产环境建议**两层**：边缘层（Cloudflare Access Service Token / Tailscale）
+ 应用层（本文件的 token）。规范要求 `tools/call` **每次都要再鉴权一次**，
只过滤 `tools/list` 是最常见的越权漏洞 —— 本实现两边都做了。

---

## 五、运维

### 健康检查

```
GET http://127.0.0.1:9846/health
→ 200 {"ok":true,"backend":"...","auth_mode":"...","tools":10}
→ 503 {"ok":false,...}   # 后端 9845 不可达
```

### 速率限制

环境变量：
- `NAIXI_MCP_RATE_MAX`（默认 60）
- `NAIXI_MCP_RATE_WINDOW`（默认 60 秒）

按 token 计滑动窗口。⚠️ 单进程内存计数 —— 多副本部署需换共享存储。

### 审计

每次 `tools/call` 打一条结构化日志：
```json
{"ts":1784..., "caller":"mcp", "tool":"get_system_resources", "ok":true, "ms":0, "request_id":"ab12cd34"}
```

### 故障排查

| 现象 | 原因 |
|---|---|
| 连不上 | MCP 进程未起；或端口被占 |
| `401` | 缺/错 `Authorization` 头 |
| 启动即退出、日志写「拒绝启动」 | 绑了非本机但没配 `NAIXI_MCP_TOKENS` |
| 工具返回「桌面端后端不可达」 | 主后端 9845 没起 |
| 长任务中途断 | Cloudflare 125s 超时，需流保活 |
| 写操作无响应 | token 缺 `memory.write` scope |

---

## 六、与既有通道的关系

桌面端现有三套通道，**并存互不干扰**：

| 通道 | 端口 | 面向 | 协议 |
|---|---|---|---|
| HTTP 能力端点 | 9845 | 本机内部调用 | REST |
| WS 控制平面 | 18400 | 奶昔自己的 QQ 机器人 | 自定义帧协议 |
| **MCP** | **9846** | **任意第三方** | **MCP 2026-07-28** |

为什么不把 MCP 塞进 9845：主后端是 **aiohttp**，而 MCP SDK v2 依赖
Starlette/uvicorn。强行合并需要重写栈，风险高。独立进程通过 HTTP 调 9845，
主后端零改动、零风险，MCP 层还能独立升级热重启。

保留 WS 是因为 MCP 2026 规范**移除了服务端主动推送**，而 QQ 机器人需要
事件通知（自己的机器人通知自己做不到）。这是 OpenClaw 同样的双轨设计。
---

## 七、打包环境下的依赖说明

MCP server 依赖 `mcp>=2.0`（会带入 starlette / uvicorn / pydantic 等，约 30MB）。

**当前打包（`src-tauri/resources/python-embed/`）不含这些依赖**，
所以安装版启动 MCP 会报 `ModuleNotFoundError: No module named 'mcp'`。

这是有意的取舍：MCP 是可选增强，不该让所有用户的安装包变大 30MB。

需要时按环境装一次：

```bash
# 开发环境（本机已装）
python -m pip install "mcp>=2.0"

# 打包版：装进 python-embed
src-tauri\resources\python-embed\python.exe -m pip install "mcp>=2.0"
```

若决定把它纳入默认打包，需要：
1. `python -m pip install "mcp>=2.0" -t src-tauri/resources/python-embed/Lib/site-packages`
2. 若依赖守卫报「混装污染」，在 `scripts/embed_deps_allowlist.txt` 里
   逐条写明理由（该文件要求每条都有技术依据）

**主后端（9845）不受影响** —— 它是 aiohttp，与 MCP 完全解耦。
