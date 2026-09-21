# 贡献指南（开发者文档）

> 这份文档是给**想读代码、改代码、提 PR** 的人看的。普通用户请直接看 [README.md](README.md) 和 [Releases](../../releases)。
> 仓库以中文为第一语言，本文也用中文；英文版说明见 [README_EN.md](README_EN.md)。

---

## 0. 先读这段：最致命的坑（三副本陷阱）

奶昔的后端 Python 代码在磁盘上有**三份**，新人 90% 的"我改了怎么不生效"都源于此：

| 位置 | 角色 | 你该碰吗 |
| --- | --- | --- |
| `desktop_core/`（仓库根） | **活代码，唯一编辑入口** | ✅ 只改这里 |
| `src-tauri/resources/desktop_core/` | 构建副本，由 `stage-core.cjs` 在 `tauri build` 时从仓库根同步 `.py` 过来 | ❌ 手改会被覆盖/丢失 |
| `src-tauri/target/{debug,release}/resources/desktop_core/` | 编译产物副本 | ❌ 同上，且随时被重建 |

运行时的 sidecar（`src-tauri/sidecar/naixi_api.py`、`pet_window.py`）通过 `_find_core_root()` **向上逐级查找**含 `desktop_core/` 的目录来定位代码。不同启动方式命中的可能是不同副本。结论只有一条：

> **永远只在仓库根 `desktop_core/` 里改代码。** 改完跑一次 `npm run stage-core` 把活代码同步进 `src-tauri/resources/desktop_core/`，确保 dev / build / 安装态加载的是同一份。

### 路径解析铁则（后端）

后端进程在 dev / 安装态下的工作目录、可执行文件位置都不一样，因此**严禁**用 `os.path.dirname(__file__)`、`dirname(dirname(__file__))` 之类硬编码推导数据/资源/日志目录——历史上这导致过"日志写进副本目录找不到""头像接口 404""数据落到空库"等坑。

- **日志**：一律 `from desktop_core.log_paths import log_file, log_dir`，用 `log_file("xxx.log")` 拿路径（`log_paths.py` 是路径单一真相源）。
- **数据 / 资源目录**：用各模块已有的共享解析器（候选清单 + 多级回溯 + APPDATA 兜底），读写必须共用同一解析器，不能各算各的。
- **环境隔离**：sidecar 启动时会把 `DESKTOP_DIR` 写进环境变量，子进程（桌宠、面捕桥）继承它来定位根目录，不要重新猜路径。

---

## 1. 技术全景（给贡献者的地图）

```
用户
 └─ 系统托盘 / 全局快捷键
      ├─ Tauri 2 宿主（Rust）        窗口、托盘、拉起子进程、安装
      │    ├─ React 19 前端（Vite）   dev: http://localhost:1420
      │    └─ Python sidecar（aiohttp） 默认 http://127.0.0.1:9845
      │         ├─ SQLite（data/naixi_desktop.db）对话/知识/记忆/配置
      │         ├─ SearXNG 本地搜索（随应用启动拉起）
      │         ├─ 模型供应商 API / MCP 服务器
      │         └─ WebSocket(:9877) → 摄像头面捕桥（MediaPipe）
      └─ Qt 桌宠子进程（PySide6）      Live2D / VRM 形象，经 WebSocket 与后端通信
           └─ Godot 3D 渲染（可选）     VRM 模型
```

- **三个常驻进程**：Tauri 宿主、Python 后端、Qt 桌宠（可选）。后端是唯一服务端，前端和桌宠都通过 HTTP/SSE/WebSocket 与它通信。
- **数据全本地**：所有用户数据在 `data/`（SQLite + 文件），不上云。
- **离线优先**：模型调用走你自己的供应商 Key；本地搜索优先 SearXNG，离线降级公共引擎。

---

## 2. 环境准备

- Windows 10 或更高版本
- Node.js 22+（前端）
- Rust 工具链（cargo，Rust 宿主）
- Python 3.13（开发机有个能跑的即可；打包时 `build.rs` 会把自包含的 python-embed 运行时塞进安装包，**不入库**）

```bash
npm install
```

> ⚠️ `python-embed` 运行时与 `searxng/` 便携版**不进仓库**（体积 + 版权），`tauri build` 时会下载并附加（SearXNG 约 154MB）。首次构建请确保网络可用；这俩目录因此也不会出现在 `git status` 里。

---

## 3. 开发循环（dev workflow）

```bash
npm run tauri dev
```

- 前端走 Vite dev server（`:1420`），改 `src/` 下文件 **HMR 热更新**，无需重启。
- Rust 宿主改动会触发重新编译并重启窗口。
- Python 后端（sidecar）随宿主启动，绑 `127.0.0.1:9845`。

**改后端 Python 后的生效方式**：编辑仓库根 `desktop_core/` 里的文件，然后**重启应用**（托盘退出再启动，或结束 `naixi-desktop` 进程由看门狗拉起）即可加载新代码。**不会自动热重载**——aiohttp 没有开 reload。改完顺手跑 `npm run stage-core` 可消除"dev 到底加载哪份"的疑虑（见第 0 节）。

**快速自查后端是否起服**：浏览器/命令行访问 `http://127.0.0.1:9845/api/status`，返回 JSON 即正常。

---

## 4. 后端代码规范

### 4.1 往哪加代码
- 新 API：在 `desktop_core/api.py` 注册 aiohttp 路由，handler 就地实现或抽到 `desktop_core/` 下对应模块。
- 新能力模块：在 `desktop_core/` 下新建 `xxx.py`，用 `from desktop_core.xxx import ...` 互相引用（包名 `desktop_core` 已被 sidecar 加进 `sys.path`）。
- 数据库：表结构在 `storage.py` / 各 `*.py` 的建表逻辑里；新增表走 SQLite `CREATE TABLE IF NOT EXISTS`，别手写迁移脚本金字塔。

### 4.2 绝不能做的事
- ❌ 手改 `src-tauri/resources/desktop_core/` 或 `target/` 下任何 `.py`——它们是副本，下次构建即覆盖。
- ❌ 用 `__file__` / `dirname(dirname(__file__))` 拼日志、数据、资源路径（见第 0 节）。
- ❌ 把密钥/PII 写进日志或提交进仓库（API Key 一律 Fernet 加密落本地库，密钥派生自本机标识）。

### 4.3 错误处理与降级规约（0.2.7 的教训）

0.2.7 的事故模式是：依赖缺失 → `try/except ImportError` → `log.warning` 一条 → 功能静默失效，用户完全无感知。因此确立以下规矩：

1. **允许降级，但降级必须可见**：功能降级时要在前端 UI 上留下痕迹（状态徽标、面板提示、首次使用引导），只写日志不算"已处理"。
2. **关键依赖缺失要 fail-loud**：构建期由依赖守卫拦截（`scripts/verify_embed_deps.py`）；运行期缺失核心依赖的功能入口应给出明确错误提示，而不是返回空结果。
3. **新加第三方依赖的必做三步**：写入 `scripts/requirements-embed.txt` →（如发行名≠导入名）在 `sync_embed_deps.py` 的 `ALIASES` 补映射 → 跑 `python tests/smoke_test.py` 确认"A. 依赖清单完整性"通过。漏第一步 = 重演 0.2.7，CI 的 `backend-light` 门会直接标红拦住。

### 4.4 发布前必须做
- `npm run tauri build --bundles nsis` 会在 `beforeBuildCommand` 自动跑 `npm run build && node scripts/stage-core.cjs`，把活代码同步进副本再打包。**只改了 `desktop_core/` 却没重新 build，发出的安装包还是旧代码。**

---

## 5. 前端代码规范

- 页面/组件在 `src/components/`，公共库在 `src/lib/`。
- **快捷键是唯一真相源**：`src/lib/shortcuts.ts` 导出 `SHORTCUT_ACTIONS` 与 `loadShortcuts/saveShortcuts` 等；新增/修改快捷键只动这里，组件通过它渲染提示与响应，不要散落 `keydown` 硬编码。
- **头像解析**：`src/lib/avatar.ts` 的 `resolveAvatarUrl` / `getAvatarUrl` 决定兜底图来源（内置猫娘 → DiceBear），默认头像的视觉风格改这里。
- 前端通过 `@tauri-apps/api` 调 Rust 命令，通过 `fetch` 调后端 `:9845` 的 REST/SSE。

---

## 6. 版本号

- **唯一真相源 = `src-tauri/tauri.conf.json` 的 `version` 字段。**
- 改版本只改这一处，然后跑 `npm run sync:version`（其实 `pretauri` 钩子每次构建都会自动跑），它会同步到 `Cargo.toml` / `package.json` / `version.json` / `src/lib/version.ts`。
- 不要手工改上面四个文件里的版本号，会被覆盖且造成不一致。

### 6.1 兼容性承诺（通往 1.0.0）

- **`0.y.z` 阶段**：快速迭代，不承诺 DB / 配置 schema 稳定，内部 API 随意变。
- **`1.0.0` 起**：进入稳定期，遵循 SemVer——
  - **MAJOR** = 破坏性数据 / schema 变更（必须配 `_SCHEMA_MIGRATIONS` 迁移且向前兼容）；
  - **MINOR** = 向后兼容的新功能；
  - **PATCH** = 向后兼容的缺陷修复。
- **用户数据是第一契约**：升级绝不允许丢数据、不允许静默覆盖用户配置。任何改表动作必须在 `storage.py` 登记迁移（见 §7）。
- 后端 REST API 是内部实现细节（仅绑 `127.0.0.1`），**不是公共契约**，不在此兼容承诺范围内。

---

## 7. 自测 / CI

**CI（GitHub Actions）**：每次 push / PR 自动跑三道门——① 前端构建；② 后端轻量门（依赖清单完整性 + schema 迁移框架语义，仅 stdlib，秒级）；③ 后端全量冒烟（按 `requirements-embed.txt` 装齐依赖后跑完整测试）。CI 红了必须先修再合并。见 `.github/workflows/ci.yml`。

**本地冒烟**（CI 同款，零测试框架依赖）：

```bash
python tests/smoke_test.py            # 全量（需依赖齐全的环境）
python tests/smoke_test.py --light    # 轻量（仅 stdlib，秒级）
```

覆盖四类回归：A 依赖清单完整性（0.2.7 事故防线）、B 核心模块导入、C 配置合并语义（API Key 掩码保护）、D schema 版本迁移框架。给 desktop_core 新加第三方 import 而不更新清单，A 类必红。

**改 DB 表结构**：从 v2 起必须在 `desktop_core/storage.py` 的 `_SCHEMA_MIGRATIONS` 登记版本化迁移（幂等或 meta 守护），禁止只改 `CREATE TABLE IF NOT EXISTS`（对旧库不生效——2026-09-18 的 P0 事故根因）。框架会按 `PRAGMA user_version` 顺序执行并逐版本提交。

- **后端健康**：`/api/status`、`/api/desktop_status`、`/api/ops/inspect`（运维面板数据也来自这里）。
- **启动看门狗**：SearXNG 等子服务挂了会被自动拉起，验证搜索前先看它是否 UP。
- **日志位置**：由 `log_paths.py` 决定（开发态在项目根 `logs/`），不要在代码里另起炉灶。
- **真机 / 虚拟机验证**：涉及安装器、桌宠渲染、面捕、直播等 GUI 行为的改动，建议在本机或 VMware 里真机走一遍（安装器改动尤需自证，参见 `naixi-nsis-installer-selfverify` 工作流），截图类验证注意模型能否读图。

---

## 8. 提交 / PR 流程

- `main` 是主分支；贡献请 **fork + PR**，或在授权下直接推分支后提 PR。
- **Commit 信息**：用中文或英文均可，但一条 commit 只做一类事，标题能看出改了什么。
- **推送方式**：本机 `github.com:443` 直连常被重置，**一律走 SSH**：
  ```bash
  git push git@github.com:Hayliy/naixi-desktop.git main
  ```
  （HTTPS 远程地址推不动时改用上面的 SSH 地址。）
- **发版三关**（任何 release 前必过）：① `commit` + `push` 到远程 → ② 真机端到端验证（VM 全新安装跑通、关键功能无回归）→ ③ 再按模板建 Release。未验证就上传 = 把用户当试验场。
- **Release 正文规范**：严格遵循 [.github/RELEASE_TEMPLATE.md](.github/RELEASE_TEMPLATE.md)（变更 / 可量化验证 / 下载含 SHA256 / 升级说明）。
- **发布资产**：≥300MB 的安装包上传 GitHub Releases 时要设大超时（默认 120s 会断流并留下同名空资产）；同名资产重传前先删旧的。

---

## 9. 行为准则与范围边界

- **安全边界（明确公示，不越界）**：银狐类木马防护只处理**用户态可见痕迹**；内核级 rootkit（BYOVD）任何用户态程序都杀不掉，引导用户用专业杀软 + 安全模式。奶昔**绝不内置任何反制 C2 的能力**（对 C2 发起 DoS / 未授权访问既违法也无效）。
- **数据隐私**：不默认可观用户数据，工具调用敏感操作前需用户授权（`/api/tool/permit`）。
- 提 Issue / PR 时请附复现步骤、版本号、相关日志路径；涉及安全的请走负责任的披露，不要公开 PoC。

---

欢迎提 PR。读不懂某块代码时，先按第 1 节定位进程、再按第 0 节确认你改的是不是"活代码的那一份"——这两步能省掉绝大多数无效调试。
