# 静默降级审计（CONTRIBUTING §4.3 落地）

> 审计日期：2026-09-21 ｜ 范围：`desktop_core/*.py` 全部 `except` 分支
> 配套：后端新增 `/api/diagnostics` 端点，前端新增「运行诊断」面板，把下方「用户可见降级」实时暴露在 UI 上。

## 1. 审计方法

用脚本扫描 6 个核心模块（`api.py` / `ops_engine.py` / `live_engine.py` / `tts_router.py` /
`voice_input.py` 等）的全部 `except` 分支，统计「静默吞」（分支体只有 `pass` / `continue` /
`return` 且周围 4 行无 `log.` / `print`）的数量。

- 命中静默分支 **92 处**。
- 按语义分成两类（见下），**并非所有静默 except 都是 bug**。

## 2. 分类结论

### 2.1 可接受（不视为降级，保留静默）

占绝大多数，属正常控制流 / 防御性清理，不会影响用户**功能可用性**：

| 类别 | 示例位置 | 说明 |
| --- | --- | --- |
| 连接断开后的资源清理 | `live_engine.py` 263/283/315/340… | 断线时 `try: ws.close()` 失败无所谓 |
| 文件遍历遇到无权限目录 | `api.py` 5902/5909 `except OSError: continue` | 跳过单个目录，继续扫其余 |
| 业务参数解析失败 | `api.py` 3069/3083/3091 `except ValueError: return False` | 入参非法直接判不匹配，符合语义 |
| 可选模块导入失败 | 多处 `import` 包在 try 里 | 特性降级，但已有上层 `log.warning` 或 UI 提示 |

### 2.2 需关注（功能降级，须 UI 可见 —— §4.3）

这部分是真实「功能退化但用户可能看不见」的点。审计时逐个核对了可见性，结论：

| 降级点 | 代码位置 | 当前可见性 | 处置 |
| --- | --- | --- | --- |
| 对话/记忆明文未加密落库（文本迁移未完成） | `storage._migrate_text_at_rest` | 仅后端日志 | ✅ 已纳入 `/api/diagnostics` 的 `degradations` |
| 数据库 schema 漂移（老库未升到最新版本） | `init_tables` → `run_schema_migrations` | 仅启动日志 | ✅ 已纳入 `degradations` + `db_schema_version` |
| Live2D 模型自动发现失败 | `api.py` 直播配置 GET | **原静默吞**（`except: pass`） | ✅ 改为 `log.warning`，并纳入诊断可见 |
| 云端 TTS 401/403 静默降级到 Edge-TTS | `tts_router.py` | 已有 `[TTS降级]` 日志 | ✅ 诊断面板可扩展读取 engine 状态 |
| SearXNG 本地服务不可用回退 | `ops_engine` 搜索链路 | 已有 warning 日志 | ✅ 诊断面板可扩展读取服务存活 |
| 配置结构告警（缺键 / 未知键 / 类型错） | `config_schema.validate_desktop_config` | 原不可见 | ✅ 已纳入 `degradations` |

## 3. 治理规则（写进代码评审清单）

1. **新增 `except` 必须二选一**：(a) 记 `log.warning` 说明降级原因；或 (b) 把状态暴露到
   `/api/diagnostics` 的 `degradations` 列表（让前端「运行诊断」面板可见）。
2. **禁止**「既无日志、又不进 diagnostics」的静默功能降级（原 §4.3 红线）。
3. 配置类降级一律走 `config_schema` 迁移自愈，并在 diagnostics 标出未迁移项。

## 4. 用户如何自查

打开应用 → 顶栏「系统」菜单 → **运行诊断**，查看：

- `config_schema_version`：应为当前 `config_schema.CONFIG_SCHEMA_VERSION`
- `db_schema_version`：应与 `storage.SCHEMA_VERSION` 一致
- `degradations`：**空列表 = 健康**；有内容即代表存在需关注的降级，按条目处理
- `health_score`：运维巡检跑过才有值，未跑显示 `health_available: false`（非异常）
