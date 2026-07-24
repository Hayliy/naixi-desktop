# 奶昔 · 桌面智能体 (Naixi Desktop)

基于 Tauri 2 的本地桌面 AI 助手：前端 React 19 + Tailwind，后端 Python sidecar（aiohttp，端口 9845），常驻系统托盘，支持多模型路由、本地搜索与资源库（专家 / 技能 / 提示词）。

## 特性
- **桌面常驻**：系统托盘常驻，一键唤起与退出
- **多模型路由**：按任务类型自动选择视觉 / 文本 / 视频模型，并遵守各模型并发上限
- **资源库**：内置专家、技能、提示词数据（随包分发，开箱即用）
- **本地搜索**：内置 SearXNG 便携版，缺省降级到公共搜索引擎
- **中文界面**：全中文日志与提示，报错信息面向非技术用户

## 技术栈
- 宿主：Tauri 2（Rust）
- 前端：React 19 + Vite + Tailwind CSS
- 后端：Python sidecar（aiohttp，端口 9845）
- 安装包：NSIS 自定义向导（含横幅与四步向导）

## 环境要求
- Windows 10 或更高版本
- WebView2 运行时（安装程序会在缺失时自动联网安装；离线环境会提示手动安装）
- Python 运行时已随安装包自包含，无需单独安装

## 3D 模型资源（Godot 渲染）
本项目包含基于 Godot 的 3D 角色渲染能力（`godot_renderer/`），模型文件为 `.vrm` 格式。
由于 GitHub 单文件大小上限为 100MB，`.vrm` 模型文件未随仓库分发。克隆仓库后，请自行将模型放入：

    godot_renderer/scenes/

缺少模型时，3D 渲染相关功能不可用，但不影响对话、自动化、知识库等核心能力。

## 快速开始
1. 到 [Releases](../../releases) 下载 `奶昔_0.1.0_x64-setup.exe`
2. 运行安装程序，按向导完成安装
3. 从开始菜单或桌面快捷方式启动「奶昔」

## 从源码构建
```bash
npm install
npm run tauri build --bundles nsis
```
构建产物位于 `src-tauri/target/release/bundle/nsis/`。

> 注：构建会下载并附加 SearXNG 便携版（约 154MB），请确保网络可用。

## 目录结构
- `src/` — 前端 React 代码
- `src-tauri/` — Rust 宿主、NSIS 安装脚本、Tauri 配置
- `desktop_core/` — Python 后端（sidecar）
- `data/` — 运行时用户数据（不入库）

## 配置
- API Key 以 Fernet 加密存储于本地数据库，密钥由本机标识派生，不会明文落盘。
- 供应商与模型策略在应用内设置界面配置。

## 许可证
本项目以 [Apache License 2.0](LICENSE) 发布，版权归 **木枝** 所有。
第三方组件许可证见 [NOTICE](NOTICE)。
