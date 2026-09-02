# 奶昔 · 桌面智能体 (Naixi Desktop)

一款**本地优先**的桌面 AI 智能体。基于 Tauri 2 构建，常驻系统托盘，把「对话、桌宠、直播互动、工作流、自动化、本地搜索、知识库、记忆」整合进一个随开随用的桌面应用。所有 AI 推理所需的模型调用、本地搜索、语音处理都在本机或你自己的账号下完成，数据留在本地。

- 宿主：Tauri 2（Rust）+ 系统托盘常驻
- 前端：React 19 + Vite + Tailwind CSS
- 后端：Python sidecar（aiohttp，默认 `http://127.0.0.1:9845`）
- 桌宠：PySide6（Qt）驱动 Live2D / VRM 形象，支持摄像头面捕
- 搜索：内置 SearXNG 便携版，可降级到公共引擎

---

## 功能一览

### 1. 智能对话与多模型路由
- 流式对话（`/api/chat/stream`）与 Agent 对话（`/api/agent/stream`），支持中途取消（`/api/chat/cancel`）。
- 多模型路由：按任务类型（文本 / 视觉 / 视频 / 代码 / 语音）自动选择供应商与模型，并遵守各模型的并发上限。
- 对话历史本地留存，可按会话检索、删除单条消息。
- 多模态生成：文生图（`/api/generate_image`）、文生视频（`/api/generate_video`）、文生语音（`/api/generate_voice`）、代码生成（`/api/generate_code`）。

### 2. 桌宠（PetWindow）
- Qt 桌宠本体，支持 Live2D 与 VRM 两种形象；右键菜单可切换动作、表情、开发者模式、摄像头面捕等。
- **动作 / Idle 引擎**：内置多组鲜活动作与默认 idle 循环（歪头、头发飘动、身体浮动等），可在菜单勾选启用。
- **摄像头面捕**：基于 MediaPipe FaceLandmarker 离线检测，驱动 VRM 表情与头部姿态、Live2D 口型；默认关闭，仅从右键菜单开启。
- **3D 渲染适配器（AvatarBackend）**：统一 `send_expression / send_motion / send_parameters` 接口，按角色绑定后端：
  - `self`（自研 Live2D 渲染，默认）+ `vts`（VTube Studio 多实例连接池）+ `vmc`（VMC 协议 OSC/UDP，可驱动 VSeeFace / Warudo / VMagicMirror 等）。
- **多角色舞台（StageWindow）**：Pixi 加载 N 个 Live2D 精灵，消息按 `agent_id` 路由到对应角色，支持独立模型下拉、独立表情/动作/口型。

### 3. 直播互动引擎（Live2D / VRM）
- 弹幕接入、语音播报、麦克风上麦（真人语音闭环：ASR → 自动上麦）、场景切换、直播测试。
- VTube Studio 多实例同框（每角色独立端口），VTS 全局热键管理（`/api/hotkeys`）。
- QQ 机器人接入状态（`/api/napcat/status`）、连接凭证一键获取（`/api/live/connect_credentials`）。
- 直播记忆层：角色能记住观众画像与事件流（`/api/live/memory`），用于更有连续性的互动。

### 4. 语音
- **语音输入**：麦克风采集 + VAD（WebRTC/能量门控）+ ASR（云端与本地双通道），可在设置中切换。
- **语音输出（TTS）**：统一路由（CosyVoice 主 + Edge-TTS 兜底 + 故障转移），客户端本体播放；可一键配置 VoiceMeeter 虚拟音频路由。
- 音频设备枚举、直播 TTS 测试。

### 5. 知识库
- 本地知识条目增删改查与语义搜索（`/api/knowledge/*`）。
- 支持从 GitHub 仓库、网页 URL 批量导入，自动摘要与切片入库。

### 6. 记忆系统
- 对话内容分层检索（`/api/memory/*`）：短期上下文 + 长期记忆画像（观众/用户画像、近期事件流）。
- 反思模块（`reflection.py`）周期性提炼长期记忆，供对话与直播复用。

### 7. 资源库（专家 / 技能 / 提示词）
- 内置专家、技能、提示词数据（随包分发，开箱即用）。
- 提示词管理（`/api/prompts`）：本地保存/删除，或从 GitHub 拉取社区提示词、专家、技能（`/api/github/*`）。
- 自定义资源（`/api/custom/*`）：用户自建提示词/专家/技能。

### 8. 工作流
- 可视化工作流编辑器（`WorkflowEditor`），丰富节点类型（`/api/workflow/node-types`）。
- 保存 / 运行 / 导出 / 导入 / 发布；支持 Webhook 触发（`/api/webhook/{endpoint}`）、版本管理、人工输入节点。
- 发布为对外服务：API Key 管理（`/api/workflows/{id}/keys`）、用量统计、GitHub 模板市场（在线/本地模板）。

### 9. 自动化
- 定时与事件触发的自动化任务（`/api/automations/*`）：保存、开关、运行、删除、Webhook 触发。
- 可编排多步操作（调用工具、对话、工作流等），无需手动干预。

### 10. 运维与自检
- 运维面板（`/api/ops/*`）：实例自检（inspect）、自修复（self-heal）、事件（incidents）、维护模式、变更日志、健康检查历史与趋势。
- 启动看门狗自动拉起离线服务（SearXNG 等）。
- 任务管理（`/api/tasks`）、运行日志（`/api/logs`）、前端运行时错误自动上报（`/api/client-error`）。

### 11. 工具与 MCP
- 工具权限确认机制（`/api/tools`、`/api/tool/permit`）：Agent 调用敏感工具前需用户授权。
- MCP 服务器管理（`/api/mcp/*`）：添加、连接、断开、测试；启动自动连接已配置服务器。

### 12. 游戏 Agent（看屏操控）
- 思路：截图输入 + 键鼠输出，**不读取游戏内部内存**，像真人一样操控用户自己的游戏窗口（单机 / 当前窗口）。
- 支持场景：Minecraft（只读 MOD 注入 + 视觉 grounding）、Mindustry（看屏决策）、扫雷（视觉 grounding 实验）。
- 组件：`game_agent.py`、`game_agent_mindustry.py`、`ui_grounding.py`（UI 定位）、`semantic_grounding.py`（语义理解）、`mc_bridge.cjs` / `mc_observer.cjs`（Minecraft 桥接）、`mc_readonly_mod`（只读 MOD）。

---

## 技术架构

```mermaid
graph TB
    User([用户]) -->|系统托盘 / 快捷键| Tauri[Tauri 2 宿主<br/>Rust]
    Tauri --> React[React 19 前端<br/>Vite + Tailwind]
    Tauri --> Python[Python 后端 sidecar<br/>aiohttp :9845]
    React <-->|HTTP / SSE / WebSocket| Python
    Python --> Search[(SearXNG<br/>本地搜索)]
    Python --> DB[(SQLite<br/>对话/知识/记忆/配置)]
    Python --> LLM[模型供应商 API<br/>文本/视觉/视频/语音]
    Python --> MCP[MCP 服务器]
    Python -->|WebSocket :9877| Face[摄像头面捕桥<br/>MediaPipe]
    Tauri -->|启动子进程| Pet[Qt 桌宠<br/>Live2D / VRM]
    Pet <-->|WebSocket| Python
    Pet --> Godot[Godot 3D 渲染<br/>VRM 模型]
```

**关键进程**
- **主应用（Tauri）**：负责窗口、托盘、安装、拉起后端与桌宠子进程。
- **后端（Python）**：所有 AI 能力、搜索、知识库、工作流、运维的统一服务端。
- **桌宠（Qt）**：可选的 Live2D / VRM 形象进程，经 WebSocket 与后端通信。
- **面捕桥**：摄像头视频流 → MediaPipe 检测 → 姿态/表情数据，独立端口。

---

## 目录结构

```
naixi-desktop/
├── src/                     # 前端 React 代码（页面、组件、公共库）
│   ├── components/          # Dashboard / Chat / KnowledgePanel / WorkflowEditor
│   │                       # AutomationPanel / PetWindow / StageWindow / SettingsPage ...
│   ├── lib/                 # 流式请求、avatar 驱动等公共库
│   └── ...
├── src-tauri/               # Rust 宿主、Tauri 配置、NSIS 安装脚本
│   ├── src/                 # Rust 命令与启动流程
│   ├── installer/           # NSIS 向导（横幅、四步向导）
│   └── resources/           # 打包资源（自包含 Python 运行时，不入库）
├── desktop_core/            # Python 后端（sidecar）
│   ├── api.py               # aiohttp 路由注册（所有 /api/* 端点）
│   ├── pet_window.py        # Qt 桌宠主窗
│   ├── vrm_pet.py           # VRM 3D 渲染
│   ├── face_bridge.py       # 摄像头面捕桥
│   ├── voice_input.py / tts_router.py   # 语音输入 / 输出
│   ├── workflow_engine.py / ops_engine.py / orchestrator.py
│   ├── memory*.py / storage.py / reflection.py   # 记忆与存储
│   ├── mcp_client.py / tools.py      # 工具与 MCP
│   ├── live_engine.py / avatar_backends.py  # 直播与渲染后端
│   ├── game_agent*.py / *grounding.py / mc_*.cjs  # 游戏 Agent
│   └── vrm_html/           # 面捕前端资源（index.html / MediaPipe vendor）
├── godot_renderer/          # Godot 3D 渲染工程（.vrm 模型不入库）
├── scripts/                 # 构建 / 打包辅助脚本
├── public/                  # 前端静态资源（logo 等）
├── data/                    # 运行时用户数据（不入库）
├── searxng/                 # 内置 SearXNG 实例（不入库，构建时附加）
├── CHANGELOG.md             # 版本历史
├── NOTICE                   # 第三方组件许可证
└── LICENSE                  # Apache 2.0
```

---

## 快速开始（安装包）

1. 到 [Releases](../../releases) 下载 `奶昔_0.1.0_x64-setup.exe`
2. 运行安装程序，按向导完成安装（含 WebView2 运行时自动安装）
3. 从开始菜单或桌面快捷方式启动「奶昔」

> 离线环境若 WebView2 缺失，安装程序会给出中文手动安装提示。

---

## 从源码构建

环境要求：
- Windows 10 或更高版本
- Node.js 22+ 与 Rust 工具链（cargo）
- Python 3.13（构建脚本会自动处理运行时打包）

```bash
npm install
npm run tauri build --bundles nsis
```

构建产物位于 `src-tauri/target/release/bundle/nsis/`。

> 构建会下载并附加 SearXNG 便携版（约 154MB）与自包含 Python 运行时，请确保网络可用。

---

## 资源自备说明

以下大体积 / 版权资源**不随仓库分发**，克隆后需自备：

| 资源 | 位置 | 说明 |
| --- | --- | --- |
| VRM 3D 模型 | `godot_renderer/scenes/` 或 `godot_renderer/models/` | 单文件超 GitHub 100MB 上限，且涉游戏 IP；缺失不影响对话/自动化等核心能力 |
| 本地 TTS 模型（kokoro-onnx） | `naixi_tts_models/`（自动生成） | 首次使用自动下载，无需手动放置 |
| Minecraft 客户端/服务端 | `mc_test/`（已忽略） | 仅游戏 Agent 自验用，含第三方版权文件 |

---

## 配置

- **模型供应商**：API Key 以 Fernet 加密存储于本地数据库，密钥由本机标识派生，不明文落盘；供应商与模型策略在应用内设置界面配置。
- **本地搜索**：SearXNG 随应用启动自动拉起，离线时降级到公共引擎。
- **MCP**：在设置中添加 MCP 服务器地址，启动自动连接。
- **知识库 / 工作流 / 自动化**：均在应用内 UI 完成配置，数据存于本地 `data/`。

---

## 常见问题（FAQ）

**Q：模型 API Key 安全吗？**
A：密钥在本地以 Fernet 加密存储，密钥派生自本机标识，不会以明文写入磁盘或上传。

**Q：没有 VRM 模型能用吗？**
A：可以。VRM 仅影响 3D 渲染；对话、自动化、知识库、Live2D 桌宠、直播等核心能力不受影响。

**Q：摄像头面捕会一直开吗？**
A：不会。面捕默认关闭，仅当用户从桌宠右键菜单手动开启时才调用摄像头。

**Q：游戏 Agent 会读取游戏内存或连服务器吗？**
A：不会。游戏 Agent 采用「截图输入 + 键鼠输出」范式，只操控用户自己的当前窗口，不读取游戏内部、不连接任何服务器。

**Q：数据存在哪？**
A：全部存于本地 `data/` 目录（SQLite + 文件），不上传云端。

---

## 赞助支持

如果这个项目对你有帮助，欢迎赞助作者 ☕

- **渠道**：微信 / 支付宝（GitHub Sponsors 在中国大陆不可用，故用国内最正规的个人收款方式）。
- **怎么赞助**：打开应用 → 设置 → 关于 → 「赞助支持」，扫码即可。
- **防篡改双核对**：收款码以 SHA-256 固化在应用内，打开时自动校验完整性；同时固定显示**收款人实名**，付款前请核对姓名一致。若提示「完整性校验未通过」，说明安装包可能被篡改，请只从官方 Releases 重新下载。

---

## 安全与完整性

本项目**只通过 [GitHub Releases](../../releases) 分发**。任何网盘、论坛、QQ 群、第三方站点的「奶昔」安装包都**不是官方**，请勿下载——银狐类木马常伪造开源项目安装包投毒。

下载后建议校验：

```bash
sha256sum -c sha256sums.txt
```

`sha256sums.txt` 随每次发布附在 Releases 里（由 `npm run gen:release-hashes` 生成）。安装包经代码签名，未签名或签名不匹配的包不是官方构建。

发布安全规范（代码签名、哈希清单、官方渠道、分支保护、防银狐）见 [docs/RELEASE_SECURITY.md](docs/RELEASE_SECURITY.md)。

---

## 许可证

本项目以 [Apache License 2.0](LICENSE) 发布。第三方组件许可证见 [NOTICE](NOTICE)。
