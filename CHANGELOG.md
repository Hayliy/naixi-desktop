# 更新日志 / Changelog

本文件记录奶昔·桌面智能体的所有历史版本。版本号遵循语义化版本（SemVer）：`主版本.次版本.修订号`。

- **修订号** `0.1.x`：安装器、稳定性、Bug 修复等向后兼容的小改动。
- **次版本号** `0.x.0`：新增功能（向后兼容）。
- **主版本号** `x.0.0`：架构调整或重大不兼容变更。

> 版本号唯一来源：`src-tauri/tauri.conf.json` 的 `version` 字段。修改后重新构建，安装包文件名与 GitHub Release tag 会自动跟随，无需在别处同步。

## [0.2.7] - 2026-09-20

> 本版本源自一轮「全模块深度测试 + 依赖审计」，主题是**依赖完整性**：安装包能装出来、界面能打开，但大量功能因依赖从未进包而静默失效。

### 修复（交付级 · 安装包「装得上、用不了」）
- **23 个第三方依赖从未进安装包**，对应功能全部静默失效（代码里是 `try/except` 降级，只在日志留一条 WARNING，用户完全无感）：
  | 缺失依赖 | 用户可感知的后果 |
  |---|---|
  | `pynput` | **全局热键完全失效** |
  | `psutil` | 仪表盘/运维页系统指标恒 0 |
  | `cv2` | 游戏 Agent 视觉接地不可用 |
  | `onnxruntime` / `kokoro_onnx` / `phonemizer` / `espeakng_loader` | 本地离线 TTS 兜底链路不可用 |
  | `vosk` | 真人语音（离线 ASR）不可用 |
  | `pypdf` / `pdfminer.six` / `python-docx` | PDF / Word 导入知识库不可用 |
  | `mcp` | MCP 服务器接入不可用 |
  | `bs4` / `lxml` | 网页解析（URL 导入、搜索清洗）降级 |
  | `tiktoken` | 对话 token 计数恒「-」 |
  | `jinja2` | 工作流模板渲染不可用 |
  | `soundfile` / `pygltflib` | 音频读写 / glTF 模型格式不可用 |
  根因：项目没有依赖清单，`python-embed` 长期手工维护、既无清单也无构建期校验；`src-tauri/resources/` 又在 `.gitignore` 内，依赖根本不在版本控制里，换机器构建必漏。

- **新增构建期依赖守卫**（`scripts/verify_embed_deps.py`，由 `build.rs` 强制调用）：AST 扫描代码实际 import → 逐个导入探针 → **RECORD 哈希一致性校验**。任一关键依赖缺失或与元数据不一致，**直接中止构建**，不再打出「能打开、但部分功能坏的」安装包。哈希校验专治**人工拷贝与 pip 混装**——测试中正是它抓出 `pydantic-core 2.46.5` 配 `pydantic 2.13.4` 导致 `mcp`/`openai` 抛 `SystemError`，而 `pip check` 报告 `No broken requirements found`，完全查不出来。
- **新增依赖清单与同步脚本**：`scripts/requirements-embed.txt`（118 个包，含发行名≠导入名映射说明）、`scripts/sync_embed_deps.py`（按依赖闭包从同版本环境同步，或 `--from-pip` 按清单安装）、`scripts/embed_deps_allowlist.txt`（登记有意的本地适配，如 `webrtcvad` 的 `pkg_resources`→`importlib.metadata`），使内嵌运行时**可复现重建**。

### 修复（P1 · 功能不可用）
- **工作流模块整体不可用**：`workflow_engine.py` 中有 **29 处 `from core import storage`**（包重命名前的旧包名，工程内不存在 `core` 包）→ `POST /api/workflows/save` 直接 500，保存/发布/密钥/版本/模板全部失效。已全部改为 `from desktop_core import storage`。
- **知识库节点返回假结果**：`KnowledgeNode` 里 `from core.knowledge_base import KnowledgeBase` 被 `except ImportError` 吞掉 → 节点永远返回 `{"title": "(模拟)", "content": "知识库搜索: …"}`，**用户拿到的是编造的结果**。现改为读 `meta` 表 `knowledge_base` 的真实检索（与 `/api/knowledge/search`、`tools._search_knowledge` 同源），本地单测 4/4 通过。
- **直播：选 VMC 形象完全不动**（两项根因）：
  - `python-osc` 从未进入依赖清单，`VmcBackend.connect()` 直接失败 → 现自实现最小 OSC 编码（地址 + 类型标签 + float/int/string，4 字节对齐），字节级单测与 VSeeFace 期望一致，UDP 实测收到表情/口型/复位共 6 包；
  - `_backend_for_model('')` 直接返回 `None`，弹幕互动路径不带 `model_id`，于是永远走 VTS 分支，把后端设为 `vmc`/`self` 的角色收不到任何表情与口型 → 空 `model_id` 回退主角色。
- **直播语音在所有客户端不出声**：无 ffmpeg 时 `_to_wav_base64` 直接返回空串 → 现已是 WAV 原样推，无 ffmpeg 时按原始格式（多为 mp3）直推，浏览器舞台 WebAudio 可解。
- **开「真人语音（本地）」把后端卡死数分钟**：`_download_asr_model` 用同步 `urlretrieve` + `zipfile.extractall` 跑在事件循环里，期间**所有接口无响应、连「停止引擎」也超时**（端口仍 LISTENING 但连不上）。现下载卸载到线程池并改为后台任务：toggle **57ms** 返回 `state=downloading`，关闭/停止引擎都会取消下载。

### 其它
- **调试注入的弹幕不进列表/统计**：`/api/live/inject-danmaku` 不写 `_danmaku_cache`，调试路径下弹幕列表恒 0，与真实 B 站路径行为不一致。
- **工作流 DSL 导出健壮性**：`export_to_dsl` 硬取 `e["source"]`，边字段命名稍异（`from`/`to`）即整单 500 → 兼容并跳过缺失端点的边。

### 验证
- 依赖守卫：**30 个第三方模块全部可导入、RECORD 哈希全部一致**（修复前 23 项缺失）；
- 工作流：本地 save/list/get/publish/delete 全通过；VM 端到端 `save → run` 三节点（start→llm→end）全 success、发布返回 api_key；
- 知识库节点：真实检索单测 4/4（命中/未命中/空 query 返回全量）；
- 直播：VM 假凭证启动引擎 5 个 Agent 全 running，UDP 监听收到 6 个 OSC 包（`/VMC/Ext/Blend/Val ,sf Joy 1.0` → `Apply` → `,sf A 0.75`（口型）→ `Apply` → 复位 → `Apply`），toggle 57ms / stop 24–28ms；
- `py_compile` 与 `tsc --noEmit` 全部通过。

## [0.2.6] - 2026-09-19

> 本版本源自一轮「用户视角黑盒测试」（VMware 真机安装 0.2.5 后，真实键鼠注入 + 截图 OCR + 后端 API 逐字段对拍），全部问题由测试发现。

### 新增（P1 · 定时任务此前永不执行）
- **自动化调度器**：定时任务此前只落库，没有任何后台循环触发——用户创建的「每天 9 点」任务永远不会自动执行。新增 `_automation_scheduler`（30s 扫描周期，随启动钩子常驻）：
  - `trigger_type=schedule`：极简 5 段 cron 匹配（支持 `*`、数字、逗号列表、`a-b` 范围、`*/n` 步长），分钟级防重；
  - `schedule_type=once`：到点触发一次后自动暂停；
  - `rrule`（HOURLY/DAILY/WEEKLY）：距 last_run 超过对应间隔触发；
  - 触发时内部调用 `/api/automations/run`，完整复用 Agent 执行、对话落库与执行记录链路。

### 修复
- **设置页供应商列表恒空**（同屏仪表盘却显示已配置）：`AppContext` 启动时首拉 `/api/desktop/config` 失败（启动竞态：前端早于后端监听）被 `catch` 静默吞掉且永不重试 → config 永空。改为指数退避重试（最多 5 次）；`api.ts` 恢复 `fetchWithRetry`（网络错误/5xx 重试、4xx 显式抛出不掩盖业务错误）。
- **记忆页统计卡恒 0**（仪表盘同端点却显示 4 条）：mount 一次性拉取失败被 `catch(() => {})` 吞掉且无重试。改为指数退避重试最多 4 次。
- **自动化列表触发类型显示错误**：`triggerLabel` 把 `workflow_id` 判断放在 `trigger_type` 之前，定时任务（cron）被显示成「工作流」，与统计卡「定时任务 N」口径矛盾。已调整判定顺序。
- **对话报错只显示「HTTP 400」天书**：`stream.ts` 丢弃了后端错误体（如「请先在设置中配置 API Key」）。现读取 response body 的 error 字段透出。
- **知识库空标题提交静默失败**：表单直接关闭、无任何提示（后端 400 被吞）。前端补「标题不能为空」校验 + 4xx 显式抛错。
- **会话标题一律显示「新对话」**：`convName` 的 `chat:` 分支在消息详情未加载时无信息可用。现回退到会话列表的 `last_msg` 摘要（截断 20 字）。
- **仪表盘「模型清单」与实际配置不符**：硬编码静态清单（qwen3-32b 等）误导用户。改为从 `/api/stats` 生成实际供应商模型列表，未配置时显示引导空态。
- **自动化时间戳 UTC/本地混用**：`created_at/updated_at` 用 `datetime('now')`（UTC，差 8 小时），且 `INSERT OR REPLACE` 每次编辑都重置创建时间。改用本地时间并保留首次创建时间。
- **ops_health_log 无限增长**：仪表盘每 3s 轮询、每次请求都插一条快照，3 小时 8000+ 行。现按 60s 节流（巡检强制写入不受限），并兜底仅保留最近 20000 条。
- **日志页被 HTTP 访问日志刷屏**（0.2.5 回归确认）：`/api/logs` 过滤 `aiohttp.access`，但「应用日志 <10 行时回退到全量」的分支在日志刚轮转时会把刷屏原样返回（0.2.6 第一轮 VM 实测 200/200 行仍是 access，第二轮 20/28 行）。现改为**始终不返回 access 行**，应用日志不足时从 `.1/.2/.3` 轮转文件回补——VM 终测 19 行全部为应用日志、access 0 行。
- **`/api/stats` 数据库大小整数截断**：0.5MB 显示成「0MB」，与运维端点口径不一致。统一为 1 位小数。
- **死代码**：删除 `api.py` 中被遮蔽的第一处 `api_providers` 定义。

### 验证
- cron 匹配器单元测试 12/12（含 `*/n`、范围、逗号列表、cron 周字段 0=周日）；
- 健康快照节流（快速双写=1 条、强制写=2 条）、自动化时间戳本地化与 created_at 保留、调度器模拟运行触发+last_run 回写（临时 DB，不污染真实数据）；
- `py_compile` 与 `tsc --noEmit` 全部通过；
- **VMware 真机端到端**（安装 0.2.6 后实测）：顶栏/接口版本 0.2.6；对话发送「hello」→ 模型回复入库；新建自动化 `created_at` 为本地时间；日志页显示应用日志（含 `自动化调度循环已启动` 启动钩子）；`/api/logs` access 行 = 0。

## [0.2.5] - 2026-09-18

### 修复（P0 · 安装后资源缺 3113 个文件 → 后端根本起不来）
- **症状**（用户在 VMware 里装 0.2.4 后报告）：点桌宠毫无反应，界面上也找不到任何导入模型的入口。抓屏取证时还看到 `pythonw.exe` 的系统错误框「**找不到 python313.dll**」。
- **取证**：装机后 `resources` 只有 11598 个文件，构建侧是 14711 个；逐卷比对后确认**丢的正好是第 14/15/16 卷整卷零产出**，而 `python-embed\python313.dll` 就在第 16 卷 ⇒ 嵌入的 Python 起不来 ⇒ 后端从未启动 ⇒ 前端所有接口失败。
- **责任划分**：把安装包内嵌的 16 个分卷在 guest 里用**同一句 7z 命令手动逐卷解压**，16 卷全部成功、14711 个文件一个不少 ⇒ 归档 / 7z / 系统环境全部清白，**丢卷发生在安装器的推进逻辑里**。
- **根因**：timer 靠「读 `res_done.flag` → `Delete` → 进下一卷」串行化多卷解压。一旦某次 `Delete` 因杀软/索引器瞬时占用而**静默失败**（0.2.4 现场 `_bundle` 清理反复出现同类瞬时占用），下一 tick 就会读到**上一卷的陈旧标记** ⇒ 循环以约 240ms/卷冲刺到底、把最后几卷的 7z 全部并发拉起；紧随其后的 `res_verify → res_finish` 的 `RMDir /r _bundle` 把归档删掉，正在启动的 7z 直接失败 ⇒ 那几卷零产出；而循环此时已退出，写回来的 `FAIL` 标记再没人读 ⇒ 界面照样显示「安装完成」。
- **修复**：完成标记改为**每卷唯一名** `res_done_NN.flag`，安装器只等待「自己刚启动的那一卷」⇒ 陈旧标记天然无害；卷号每 tick 按 `$CurPart` 重新格式化，不再跨 tick 依赖寄存器 `$R7`。
- **补齐完整性哨兵**：原先只校验 `desktop_core\api.py` 与 `python-embed\pythonw.exe`（两者都在，所以坏安装被当成成功交付），现补 `python-embed\python313.dll` 与 `desktop_core\pet_window.py`。
- **不再谎报成功**：新增 `ResBroken` 标记，任何告警或超时都会置位 ⇒ ①最终文案改为「安装完成，但核心资源不完整：请重新运行安装程序修复」②**保留** `_bundle` 归档与 7z.exe 便于重装与取证。超时兜底也改为直接判不完整。
- **真机验证**：见文末「验证」段。

### 修复（无模型时「找不到导入模型入口」）
- **症状**：全新机器上一个模型都没有时，桌宠只显示一张「未加载模型」的占位卡，卡上文字把用户指回「直播页点桌宠按钮」——点了还是同一张卡，形成死循环；右键的「导入模型文件…」更是**一点就崩**。
- **根因（导入崩）**：`pet_window.py` 的 `_import_model` / `_delete_model` 引用了模块级常量 `DATA_MODELS`，而它在 `95ec2ac` 重构时已被删除、引用没清 ⇒ 选完文件必抛 `NameError`，PySide6 6.11 把它从事件循环重抛后由 `run_pet` 兜底捕获 ⇒ **桌宠窗口直接消失**。
- **修复**：
  - 占位卡改为**可点击的导入入口**（点卡片即弹模型选择框），并把卡片几何并入 `setMask` 与 `WM_NCHITTEST` 命中区 —— 无模型时命中矩形是「窗口中央 45%」，会把卡片裁掉大半（只剩中间一条、点不到）。
  - 模型目录收敛为**单一真相源**：`l2d_discovery` 新增 `core_root() / data_dir() / models_dir() / invalidate_cache()`，Qt 桌宠与后端导入/列表/删除全部改用它，并按 `DESKTOP_DIR` + 逐级回溯解析（原先 Qt 与 `api.py` 各推一份路径，一旦漂移会各自留下 `.discover_cache.json`）。
  - 导入/删除后**失效模型发现缓存**（TTL 600s），否则表现为「导入成功但桌宠还说没有模型」。
  - 「管理模型」对话框在空列表时也给出「导入模型…」按钮；模型加载失败时把占位卡放回来。
  - **导入/切换模型成功后隐藏占位卡**：这个 `hide()` 原先只写在 `initializeGL`（启动路径）里，`_init_model`（切换/导入走的那条）没有 ⇒ 模型其实已经加载好、却被占位卡整个盖住，用户以为「导入没生效、还是没有模型」（真机实测：导入后截图里模型就藏在卡片后面）。
  - `pet-start` 回报 `has_model`（进程起来 ≠ 有形象可显示），前端据此提示「点桌宠上的卡片，或右键它选导入」而不是一句「桌宠已启动」。

### 修复（「点桌宠毫无反应」的真因：装了之后桌宠子进程根本起不来）
- **症状**：点「桌宠」后屏幕上什么都不出现（`pet-start` 却返回成功）；pythonw 进程随后消失，没有任何报错框、没有日志。
- **取证**：装完后 guest 里只有后端（`sidecar\naixi_api.py`）与 searxng 两个 `pythonw`，**桌宠窗口根本不存在**。用 `python.exe` 前台跑一次拿到 stderr：
  `from desktop_core.motion_engine import PoseEngine` → `ModuleNotFoundError: No module named 'desktop_core'`。
- **根因**（两件事叠加）：
  1. `_start_pet` 只向上找 `src-tauri/sidecar/pet_window.py`（**开发态**布局）。安装包把 `sidecar/*.py` 放在 `<INSTDIR>/sidecar/`（没有 `src-tauri` 这层），于是装完后永远落到兜底分支——直接跑 `resources/desktop_core/pet_window.py`。而 `sidecar/pet_window.py` 这个启动器**自己在代码里修 sys.path**，`desktop_core/pet_window.py` 作为库模块没有这个修复 ⇒ 模块级 import 直接炸。
  2. 那句「关键：注入 PYTHONPATH」在安装态**无效**：打包自带的 python-embed 里带 `python313._pth`，**PYTHONPATH 被完全忽略**。guest 实测 `PYTHONPATH=<resources>` 后 `import desktop_core` 仍失败，而走 `sidecar/pet_window.py` 启动器时进程能正常常驻。开发态之所以一直正常，纯粹是启动器那条路走通了 —— 典型的「只在装完后才犯」。
- **修复**：`_start_pet` 逐级查找时**同时认两种布局**；`desktop_core/pet_window.py` 加 `__main__` 守卫（直接当脚本跑时把包的父目录插入 `sys.path`）；`_start_pet` 增加**存活自检**（Popen 后等 1.2s，子进程已退出就记 warning 并返回 `False`）——pythonw 无控制台，秒退是完全静默的，必须主动识别；前端启动失败改为明确报错。

### 验证（VMware Win10 真机端到端，用户零操作）
用计划任务在登录会话内拉起「杀残留 → curl 下载安装器 → 起安装器 → 键盘 Enter 驱动向导」，
覆盖安装 0.2.5 后逐项取证：
- **安装完整性**：`version.json=0.2.5`；`resources` 实装清单与构建侧做**集合差为空**
  （构建侧 14711 个文件，0.2.4 现场缺 3113 个、含 `python-embed\python313.dll`）。
  同时把安装包内嵌的分卷抽出、「用同一句 7z 命令手动逐卷解压」得到 16 卷全部 OK、14711 个文件一个不少
  ⇒ 归档 / 7z / 系统环境全部清白，之前的丢卷确实出在安装器流程里（取证手法已写入 skill）。
- **后端**：`:9845` 就绪（覆盖安装后 12s / 重装后 3s），`pet-start` 如实回报
  `{"ok": true, "has_model": false}`（无模型时不再谎报"已启动"）。
- **桌宠闭环**：先把机器置成「一个模型都没有」→ 桌宠显示**可点击**的占位卡 →
  点卡片弹出「选择 Live2D 模型文件」→ 选中模型 → **整个模型文件夹被复制进 `data\models\`（8 个文件含贴图）**
  → `data/models` 立刻可被 `/api/live/config` 发现 → 模型成功渲染、**占位卡随之隐藏**、
  桌宠进程存活、`pet_error.log` 不存在；`pet_window.log` 记录到
  「点击占位卡 → 打开模型导入」与「模型已导入: …」，导入链路不再有黑盒。
- 取证材料落在 `D:\数据\Naixi-旧版留档\2026-09-18-安装丢卷修复\`（verify_025.py / verify_pet_light.py + 截图 + 日志）。

### 修复（全功能测试产出的 19 项缺陷 —— 真机全量测试，非静态推断）
对 0.2.5 安装态做了全功能测试：从安装包的 `api.py` 解析**真实路由表**逐条冒烟（180 条）、
带真实参数的冒烟第 2 轮、左侧 12 个导航页 + 设置页 11 个标签的 GUI 遍历取证、前端错误上报回读、
后端异常栈取证。其中两处是**核心功能 100% 不可用**：

- **P0「创建自动化」必失败**：`naixi_automations` 建表语句没有
  `workflow_id/trigger_type/config/description/last_result` 五列，而 `automation_save` 的 INSERT
  一直带着它们；`CREATE TABLE IF NOT EXISTS` **不会补列**。
  现场实证：`sqlite3.OperationalError: table naixi_automations has no column named workflow_id`（HTTP 500）。
- **P0「保存工作流」必失败**：`workflow_versions` 有两处互相矛盾的建表定义（`storage.py` 的旧定义
  `id INTEGER PRIMARY KEY AUTOINCREMENT` 且缺 `name/description/dsl`；`workflow_engine.py` 的 INSERT
  按**文本 id** + 这些列写），先建的旧表生效 ⇒ 先报缺列，补列后还会撞 datatype mismatch。
  现场实证：`[ERROR] workflow: 保存工作流失败: table workflow_versions has no column named name`，
  接口返回 `{"success": false}` 但 HTTP 200。
  → `storage.init_tables()` 增加显式迁移：自动化补 5 列（ALTER），`workflow_versions` 按引擎结构重建
  （旧表从未写入成功过，重建安全）。**规矩：以后给表加列必须在此补 ALTER。**
- **P0 后端日志写进用户 AppData 根目录**：`sidecar/naixi_api.py` 用 `dirname×3` 硬推日志目录
  （项目红线禁止的写法）⇒ 日志落到 `%LOCALAPPDATA%\logs\naixi_desktop.log`；而
  `/api/desktop/paths` 报的是 `<INSTDIR>\resources\logs`（**该目录根本不存在**），`models_dir` 同样报错。
  「设置 → 文件与存储」正是把这两个路径直接显示给用户的。→ 日志改用 `log_paths.log_dir()`
  （与桌宠/语音日志同源），`paths` 接口改用 `DB_PATH + log_dir() + models_dir()`。
- **「假功能」清理**：顶栏「桌宠」菜单三项全是空操作（操作的是 `visible:false`、全项目无人 `show()`
  的 `/pet` 网页窗口）→ 改为直接调 `pet-start/pet-stop/pet-switch`；「直播」菜单「启动引擎」发空 body
  必然失败、「保存配置」发 `{}` 空操作却报成功 → 合并为「打开直播设置…」；选专家后模型完全不知道人设
  （`expert_prompt` 前后端都没接）→ 前端带上、后端注入 system 提示；全局热键对 Qt 桌宠无效
  （只处理 `speak/audio`）→ 补 `avatar_expression/avatar_motion` 分支；舞台窗口选模型只写 localStorage
  → 同时回写后端；「连接」页 19 个平台只落库无实现 → 界面如实说明；快捷键面板改键位大多无效 → 如实标注。
- **设置项"只存不读"**：SearXNG 地址（后端硬编码 8899/8898）、日志级别（后端从不读取）→ 均已接上。
- **性能/卫生**：日志页每秒拉 56KB 全量日志（实测把日志刷到 15MB、轮转 3 次）→ 3s + 不可见不拉 +
  内容未变不重渲；`PAGE_TITLES/PAGE_ICONS` 缺 `connection` ⇒ 点「连接」标题回落成"仪表盘"；
  SearXNG 偶发两实例并存（启动钩子与看门狗竞态）→ 加互斥 + 90s 宽限期。
- **接口契约**：自动化保存/工作流 webhook/模型导入/工作流导出 分别改为 400/404/400/404 并给出可读原因
  （原先一律 500 "Server got itself in trouble"，或 200 包着错误体让调用方当成功）。

### 修复（全功能测试收尾：desktop/paths 回归）
- 上述「paths 接口改用 `DB_PATH` …」那次改动引入了一个**回归**：`DB_PATH` 只在 `storage.py`
  里定义（初始 `""`，由外层 `naixi_api.py` 在导入前注入真实值），`api.py` 作用域里**根本没有这个名字**
  ⇒ `db_path = DB_PATH` 直接 `NameError` ⇒ 该端点 `GET /api/desktop/paths` 永远 500
  （也就是「设置 → 文件与存储」整页打不开、控制台报红）。全功能复验的 180 路由冒烟把它抓了出来。
- **修复**：改为**调用时** `from desktop_core import storage; storage.DB_PATH or 兜底路径`，
  不再在模块加载时 import（避免拿到空串）。复验确认该端点恢复 200 且三处目录均真实存在。

### 已知遗留（不影响功能，下一轮处理）
- `resources\_bundle` 的收尾清理在「杀软/索引器长时间占用」时仍可能整批残留（本轮实测残留 240MB，
  即 16 个分卷 + 7z.exe/7z.dll）。已确认不是新改动的副作用：注册表 `PendingFileRenameOperations`
  里能看到 `_bundle` 的各项 ⇒ 清理**确实执行过**、只是当场删不掉；重启后会自动清，手动删也能立刻删掉。
  下一轮改成「应用启动时自清自己的 `_bundle` 残留」做兜底（比反复调安装器重试次数可靠）。

## [0.2.4] - 2026-09-17

### 修复（P0 · 安装器从来没真正解压过资源 —— 真机验证挖出）
- **症状**：进度页停在「正在解压核心资源... (1/16)」，右下角百分比长时间不动（旧版是 `0%`），约 10 分钟后**直接跳到 100%**。用户听到的「卡住」「只有 0% 和 100%」就是它。
- **根因**：解压命令写成 `cmd.exe /c "7z.exe" x -y -o"..." "part.7z" && echo done > "flag"`。cmd 对 `/c` 后**以引号开头**的命令行有一条特殊规则：剥掉**首尾各一个**引号 —— 于是「给 7z.exe 加的那个引号」被当成了整串的边界，命令被拆坏，**7z 根本没被执行**。真机对照实验（可复现）：
  | 写法 | cmd 退出码 | 7z 是否运行 | 目标目录产物 | 完成标记 |
  |---|---|---|---|---|
  | 原样（`/c "exe" args`） | 1 | **否** | 空 | 无 |
  | 整串加引号（`/c "exe args …"`） | 0 | 是 | 正常 | 正常写出 |
- **后果**：完成标记永不出现 ⇒ 安装器空等超时兜底 ⇒ 进度从 40% 一跳到底，**而资源（desktop_core / python-embed / searxng）从未从分卷里解压出来**，装完是残缺的。这条链路自 7z 聚合方案上线起就一直存在，属于「每次都被报告、每次都只改了表象」的那类缺陷。
- **修复**：整条命令用一对引号整体包给 `cmd /c`（上表 B 写法），并抽成唯一入口 `StartPartExtract` 宏，禁止再出现第二种写法；同时用 `&& / ||` 把**成功与失败都写进标记文件**，卷解压失败会如实显示「部分资源分卷解压失败，安装可能不完整」，不再静默吞掉。
- 超时兜底由约 10 分钟收紧到约 6 分钟（现在失败已能即时上报，超时只用于兜住真卡死）。

### 修复（安装进度反馈收口 —— 「百分比数字」）
- **百分比数字与进度条同源同值**：进度页右下角的百分比此前只在各阶段开头写成 `0%`、收尾写成 `100%`，中间从不更新 ⇒ 进度条在走、数字像卡死。现收敛为唯一入口 `SetInstallProgress`：核心资源 16 分卷解压按「已完成卷数/总卷数」由 40% 推进到 68%，其余阶段 8% / 25% / 70% / 82% / 90% / 100% 同步刷新。
- 删除旧宏 `SetProgressWidth`（只推条、不写数字），并清理 6 处冗余的 `$hCurPct "0%"` / `"100%"` 直写，确保数字只有一条写入路径。
- **解压期间新增「已用 N 秒」心跳**：单卷较大、解压较久时状态行每秒刷新，避免观感像卡死。
- **修正 Python 运行时完整性哨兵路径**：原先检查 `resources\python-embed\python\pythonw.exe`（多了一层 `python\`），而实际布局是 `resources\python-embed\pythonw.exe` ⇒ 完好安装也会被误报「Python 运行时缺失」，现按真实布局校验。

### 修复（`resources\_bundle` 残留当场清不掉 —— 真机二次验证挖出）
- **症状**：安装完成后（不重启的前提下）`resources\_bundle` 仍残留 `7z.exe`、`7z.dll` 与最后 3 个分卷（`res_part_12~14.7z`，约 38MB），要等下次重启才由 `/REBOOTOK` 清掉。
- **根因**：刚写出的分卷会被杀软实时防护 / 索引器占用**数十秒**，而收尾清理当时只做 6 次×600ms(3.6s)，后放宽到 20 次×1s(20s) 仍不够 —— 真机实测 20s 上限依然留下 5 个文件；而且这 20s 是**阻塞在进度页上白等**（观感就是「装完卡住」）。
- **修复**：当场阻塞重试压到 **3 次(3s)**（不再白卡 UI）；残留时改挂一个**脱离安装器的静默清道夫**：写 `%TEMP%\naixi_bundle_clean.vbs` 并以 `ExecShell` 交给 `wscript` 执行（无控制台窗口），先等 10s（安装器退出、7z 子进程结束、杀软扫完），再最多重试 40 次×2s 删除 `_bundle`，完成后自删；`/REBOOTOK` 保留为极端兜底。
- **真机验证**：新安装器重装后，`_bundle` 在安装结束 **30 秒内清理干净且无需重启**，`version.json=0.2.4`、`resources` 四项资源齐全。

### 验证
- 在 VMware Win10 虚拟机做真机端到端：由计划任务在登录会话内拉起安装器，以 UIAutomation 持续读取进度条数值与百分比/状态标签文本（宿主侧另做连续抓屏取证），并按分卷实测解压耗时。**本次修复即是该验证的直接产出**——先前的「安装器 demo + 只看首尾两个进度值」验不出这类缺陷。
- `_bundle` 残留另做**独立真机复验**（2026-09-17）：装完当场轮询 `resources\_bundle` 是否消失，并对照「只有重启后才被 `/REBOOTOK` 清掉」的修复前行为，确认修复有效。

## [0.2.3] - 2026-09-17

### 修复（用户实测 5 缺陷）
- **安装空窗**：关闭运行中的程序 / 卸载旧版等重活从 `nsDialogs::Show` 之前移到进度对话框显示之后，消除「灰白空窗」闪现。
- **进度跳变**：核心资源改为多分卷 7z 聚合包、逐卷后台解压并按卷推进进度，替代此前「0% → 100%」跳变。
- **SearXNG 资源缺失与启动误判**：修正资源打包清单与启动判定。
- **版本号与 README 同步**：装完版本号不再回落 `0.0.0-dev`。

## [0.2.2] - 2026-09-16

### 修复（安装器三缺陷修复版 · 修正重发）
- **安装明细布局重叠／溢出**：组件明细由单列 8 行（行距 10）改为两栏 4 行（行距 20、行高 16），完整落在页脚之上。
- **点「下一步」弹终端黑窗**：解压命令改 `SW_HIDE`，不再闪控制台窗口。
- **安装页「未响应」**：资源改为 7z 聚合打包，不再由 NSIS 单线程逐个解压 15000+ 散文件；并预热读取规避实时防护锁。

## [0.2.1] - 2026-09-16

### 修复（安装器 5 项缺陷）
- 安装卡顿 / 无明细 / 目录拖拽后跳回 / 版本号显示 `0.0.0-dev` / SearXNG 资源缺失。
- 把 `version.json`、`platforms.json` 等运行时配置补进安装包（原先只收 `*.py` 与 `vrm_html`，导致后端读不到自身版本号）。

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
