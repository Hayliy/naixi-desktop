# 更新日志 / Changelog

本文件记录奶昔·桌面智能体的所有历史版本。版本号遵循语义化版本（SemVer）：`主版本.次版本.修订号`。

- **修订号** `0.1.x`：安装器、稳定性、Bug 修复等向后兼容的小改动。
- **次版本号** `0.x.0`：新增功能（向后兼容）。
- **主版本号** `x.0.0`：架构调整或重大不兼容变更。

> 版本号唯一来源：`src-tauri/tauri.conf.json` 的 `version` 字段。修改后重新构建，安装包文件名与 GitHub Release tag 会自动跟随，无需在别处同步。

## [0.2.0] - 2026-09-02

### 新增（赞助防篡改全链路 / 2D-3D 切换 / 脱敏 / 真实收款码）
- **赞助防篡改全链路**：应用内 SHA-256 自检（收款码 base64 内联进已编译 bundle，零运行时 fetch、不受 CSP 限制）+ 收款实名双核对 + 仓库 CODEOWNERS 强制 review + main 分支保护（禁 force-push/删分支）+ 代码签名预留（Authenticode signCommand 读 `NAIXI_CODESIGN_*` env）+ 发布 SHA256 清单；威胁模型与全链路见 `docs/RELEASE_SECURITY.md`。
- **2D(Live2D)/3D(VRM) 切换**：设置页 `render_mode` 下拉，重启 pet 生效。
- **发布脱敏**：安装包/仓库去除本地 PII 路径与用户名残留。
- **真实收款码接入**：微信/支付宝真实收款码（收款昵称「苏婉」，隐藏真实实名）。
- **银狐应急防护（用户态前哨 + 一键急救）**：设置页「安全急救 · 银狐应急哨兵」面板，检测本机银狐类木马用户态痕迹（Defender 排除项被篡改 / 已知 IOC 进程名 / 可疑计划任务 / 银狐 C2 网段外连），命中红黄告警 + 断网改密安全模式查杀应急指引 + 火绒/国家病毒平台一键跳转；提供「一键急救」移除已检测到的用户态痕迹（结束 IOC 进程、删计划任务、恢复 Defender 排除项）。诚实边界：用户态清不掉内核级 rootkit（银狐 BYOVD wnBios），UI 已写明需专业杀软+安全模式；绝不内置反攻 C2 能力（违法且无效）。
- **安装包完整性自检**：设置页「安装包完整性 · 本程序哈希」展示主程序 SHA-256，供与官方 `sha256sums.txt` 人工比对（识别伪造/整包替换）。

### 修复与改进（2026-09-03 · 安全中心收尾）
- **「安全急救」区块移入「安全」tab**：银狐应急哨兵 / 安装包完整性 / 360 系统急救箱 / 自动监测哨兵四张卡片从「关于」tab 移到「安全」tab，与「安全设置」并置形成完整安全中心。
- **修复「安装包完整性」永远显示"读取失败"**：定位主程序时误用了 `(Get-Process -Id X).ParentProcessId`——Windows PowerShell 5.1 的 `Get-Process` 对象**没有该成员**（PowerShell 7 才加），且**静默返回空不报错**，导致进程祖先链第一跳就断、`exe_path` 恒空。改为**纯 ctypes 遍历祖先链**（`OpenProcess` + `NtQueryInformationProcess` + `QueryFullProcessImageNameW`）为首选，powershell CIM 与目录回溯依次降级；失败原因也会带上祖先链长度便于诊断。
- **修复「比不上」**：发布哈希清单原先只含安装包（msi/nsis），而卡片显示的是**安装后主程序** `naixi-desktop.exe` 的哈希——两者不是同一个文件，用户拿卡片哈希去清单里永远找不到对应行。`gen-release-hashes.mjs` 改为输出两组：`[安装包]`（下载后验下载到的文件）+ `[主程序]`（安装后验本机程序，`../naixi-desktop.exe`），并补充分组用法注释；`sha256sum -c` 实测 5 项全 OK（中文路径与注释行均正常）。发版前请务必重跑 `npm run gen:release-hashes`（旧清单里 0.2.0 的 msi 哈希已因重新构建而过期）。
- **卡片可用性**：新增**一键复制**按钮（64 位哈希无法手抄）；文案明确指向清单「主程序」段；dev 调试版（`target\debug`）会提示哈希与官方发布版必然不同，避免误判为被篡改。
- **全项目 TypeScript 错误清零**（`tsc --noEmit` 退出码 0）：修复 Chat / Dashboard / PetWindow / SetupGuide / Toast / TopBar / WorkflowEditor / sponsorIntegrity 的类型问题；`setIgnoreMouseEvents` 更正为 Tauri v2 的 `setIgnoreCursorEvents`；消除 `isTauri` 的 TDZ 隐患。dev 模式下 Vite 误扫 `vrm_html` importmap 裸模块的阻断性报错，用 `optimizeDeps.entries` 限定扫描入口解决（release 本就不扫描，故此前未暴露）。
- **新增文档** `docs/VM_SANDBOX_HARDENING.md`：在虚拟机中做银狐样本分析 / 对抗演示时的防逃逸加固清单——VMware .vmx 加固项、网络隔离三档、宿主机共享面收敛、数据外带通道封堵、快照生命周期、演示前后自检命令，以及「没有任何虚拟化隔离是 100%」的诚实边界。
- **README 诚实化**：明确 0.2.0 安装包**尚未做代码签名**（SmartScreen 提示"未知发布者"属预期、非篡改），补齐两步哈希校验（安装包段 / 主程序段）说明、安全中心章节与 VM 加固文档入口。

### 新增（渲染后端适配器层 AvatarBackend）
- 新增 `desktop_core/avatar_backends.py`：渲染后端统一接口（`capabilities` 声明 + `send_expression/send_motion/send_parameters`），角色按 `agent_id` 绑定后端类型（`vts`/`vmc`/`self`），持久化到 SQLite meta（`live_backend_kinds`）。
- **VmcBackend（第2级）**：VMC 协议 OSC/UDP 发送器（`python-osc`，端口公式 `39539 + index`），可驱动 VSeeFace/Warudo/VMagicMirror/REALITY 等 VRM 形象；Live2D 通用参数自动映射为 VRM BlendShape（MouthOpen→A 等），情绪关键词映射标准表情并 3s 自动淡出。
- **SelfRenderBackend（第0级/默认候选）**：自研 Live2D 渲染驱动，表情/动作/参数经桌宠 WebSocket 投递前端（`avatar_expression`/`avatar_motion`/`avatar_params` 消息，带 `model_id` 供多角色舞台路由）。
- 分发点收敛在 `_vts_send_expression/_vts_send_motion/_vts_send_parameters` 三个入口：角色绑定非 VTS 后端时改道，capabilities 不支持的能力静默跳过；存量 VTS 实例池路径零改动（即第1级后端）。口型/表情/动作/层2姿态所有调用点自动接入。
- 层2 姿态广播 `_vts_ambient_to_others` 放行非 VTS 后端（原"无 VTS 认证整体跳过"会挡住 vmc/self）。
- 新 API：`POST /api/live/backend`（`{agent_id, kind}`）切换角色渲染后端；`GET /api/live/vts-models` 响应新增 `backends` 字段（各角色后端类型/在线状态/能力/端口）。
- **前端接入（PetWindow）**：桌宠 WebSocket 新增处理 `avatar_expression`（情绪→表情模糊匹配）、`avatar_motion`（动作标签→motion 组模糊匹配）、`avatar_params`（参数字典批量注入，`PARAM_ALIASES` 表把 MouthOpen/FaceAngleX 等逻辑名映射为 Cubism 标准参数 ID）三类消息——`self` 后端全链路打通。
- **前端接入（Dashboard）**：角色卡片新增「渲染后端」下拉（VTube Studio / 自研渲染 / VMC 协议），调 `POST /api/live/backend` 即时切换；非 VTS 后端显示连接状态与端口，VTS 实例状态行仅在 vts 后端时展示。
- `SelfRenderBackend` 消息附带 `agent_id`（多角色舞台 StageWindow 按角色路由到对应 sprite 的前置协议）。

### 新增（StageWindow 多角色舞台）
- **新组件 `src/components/StageWindow.tsx`**（路由 `/stage`）：一个 Pixi stage 加载 N 个 `Live2DSprite`，横向等分布局；消息按 `agent_id` 路由到对应 sprite（`speak` 口型逐帧 / `avatar_expression` / `avatar_motion` / `avatar_params`），缺省投给奶昔（兼容旧消息）；每角色独立表情/动作自省、独立 speaking 状态、共享 idle 循环；顶部工具栏每角色独立模型下拉（localStorage `naixi_stage_models` 持久化）；真人角色不上自研舞台（真人自行操控）。
- **新公共库 `src/lib/avatarDriver.ts`**：情绪/动作关键词表、`PARAM_ALIASES`、`setMouth/applyEmotion/applyAction/applyParams` 等驱动函数，从 PetWindow 抽出，桌宠与舞台共用（消除重复代码）。
- **后端 live2d 通道升级为多客户端广播**：`_live2d_clients` 集合 + `live2d_broadcast()`，桌宠与舞台窗口可同时在线互不顶掉（原 `_live2d_ws` 单槽位保留兼容）；`SelfRenderBackend` 同步升级为向所有客户端广播。
- **`speak` 消息补 `agent_id` 字段**：`_vts_speak` 新增 `agent_id` 参数并由 `_agent_tts` 从发言动作透传——多角色口型路由的关键闭环。
- Dashboard 新增「舞台窗口」按钮：Tauri 模式开独立 WebviewWindow（label `stage`，已加入 capabilities），浏览器模式开新标签页。
- 修复：vite 代理补 `ws: true`——此前浏览器模式经 1420 连 `/api/live/live2d-stream` WebSocket 升级会失败（存量隐患）。

### 变更（VTS 多实例同框）
- **VTube Studio 接入从单实例重构为多实例连接池**（`live_engine.py`）。
- 端口公式改为 `8001 + index`：每个角色（agent_id）映射到一个独立 VTS 实例，参照 Lumi_Nox 的 `VTS_BASE_PORT + i` 契约。
- 新增 `VtsInstance` 数据类与 `_vts_inst_for_model(model_id)` 路由：表情/动作/口型/参数请求按 modelID(GUID) 反查实例，未命中则退回首个已认证实例（兼容单实例）。
- 角色上台（`register_connector`）、绑定模型（`bind_connector_model`）、引擎启动（`_vts_connect_all`）三处均会自动连接其专属实例端口。
- `list_vts_models()` / 状态输出新增 `instances` 字段（端口、当前模型、表情/动作数量）；前端绑定下拉读取 `models` 并集，向后兼容。
- 前端多角色舞台面板接入 `instances` 结构：每个角色卡片现显示其 VTS **端口**（如 8001/8002）与**当前模型**（实例认证后回显），未连/未授权有明确提示；`instances` 每项带 `agent_id`（角色→实例反查映射），前端按角色关联。
- 绑定下拉的「（当前）」标记修正为多实例语义（`current` 现为 `{index: modelID}` 字典，命中任一实例当前模型即标注）。
- 引擎停止时 `_vts_disconnect_all()` 干净断开所有实例并清空路由表。

## [0.1.0] - 2026-07-24

首个公开预览版「奶昔 · 桌面智能体」。

### 新增
- 桌面端应用（Tauri v2 + React 19），产品名「奶昔 · 桌面智能体」。
- 自定义 NSIS 安装器：欢迎 / 安装位置 / 安装进度 / 完成 四步向导，含猫娘立绘横幅。
- WebView2 运行时自动安装：检测到缺失时联网下载官方引导器并静默安装；完全离线环境给出中文手动安装提示。
- 3D 模型渲染脚手架（Godot）：模型文件（`.vrm`）不随仓库分发，克隆后自行放置到 `godot_renderer/scenes/`，缺失不影响核心能力。
- 本地后端 sidecar（Python aiohttp，端口 9845）与本地搜索能力。

### 修复
- 安装器卸载流程：资源分批删除带实时进度；卸载时自动杀掉主程序 + 后端整棵进程树，不再弹出空白覆盖窗；托盘退出改为非阻塞，不再卡顿。

### 说明
- 当前为早期预览版本，能力持续扩充中。
