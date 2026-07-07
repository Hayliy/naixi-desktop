"""桌面端 API 路由 — 脱敏版，不含任何 QQ 机器人相关功能"""
import json, os, sys, time, logging, asyncio
from aiohttp import web
from datetime import datetime

# 权限确认：等待用户批准的高危工具
_PENDING_PERMISSIONS: dict[str, dict] = {}
# 会话级信任：{conv_key: {tool_name, ...}} — 用户勾选"始终允许"后不再对该工具弹出确认
_session_trust: dict[str, set[str]] = {}
# 活跃的 Agent 任务（用于取消）
_active_agent_tasks: dict[str, asyncio.Task] = {}
_agent_cancel_events: dict[str, asyncio.Event] = {}

# 高危工具列表（执行前需要用户确认）
HIGH_RISK_TOOLS = {"bash", "kill_process", "run_local_command"}

# tiktoken 精确估算（可选依赖）
_USE_TIKTOKEN = False
_TIKTOKEN_ENC = None
try:
    import tiktoken as _tk
    _TIKTOKEN_ENC = _tk.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except Exception:
    pass

def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。优先 tiktoken，降级到字符估算"""
    if not text:
        return 0
    if _USE_TIKTOKEN and _TIKTOKEN_ENC:
        try:
            return len(_TIKTOKEN_ENC.encode(text))
        except Exception:
            pass
    # 降级：中英文混合估算
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    rest = len(text) - cn
    return max(1, int(cn / 1.5 + rest / 3.5))

from desktop_core.context import ContextManager

from desktop_core.storage import meta_get, meta_set, encrypt_config, decrypt_config, decrypt_api_key, conv_list, conv_get_messages, conv_delete, conv_delete_message, conv_save_message_sync as conv_save_message
from desktop_core import tools

log = logging.getLogger("desktop")

# 延迟导入工作流引擎（从 naixi_py 引用，但 storage/config 已被桌面端覆盖）
_workflow_api = None
def _get_workflow_api():
    global _workflow_api
    if _workflow_api is None:
        from desktop_core.workflow_engine import (
            init_workflow_tables,
            api_list_workflows, api_get_workflow, api_save_workflow,
            api_delete_workflow, api_run_workflow, api_get_runs,
            api_get_node_types, api_export_dsl, api_import_dsl,
            api_publish_workflow, api_list_versions, api_register_webhook,
            api_submit_human_input, api_list_templates, api_use_template,
            api_template_categories, api_get_api_key, api_log_call,
            api_regenerate_api_key, api_list_keys, api_create_key,
            api_update_key, api_delete_key, api_get_usage_stats,
        )
        init_workflow_tables()
        _workflow_api = {
            "list": api_list_workflows,
            "get": api_get_workflow,
            "save": api_save_workflow,
            "delete": api_delete_workflow,
            "run": api_run_workflow,
            "runs": api_get_runs,
            "node_types": api_get_node_types,
            "export": api_export_dsl,
            "import": api_import_dsl,
            "publish": api_publish_workflow,
            "regenerate_key": api_regenerate_api_key,
            "list_keys": api_list_keys,
            "create_key": api_create_key,
            "update_key": api_update_key,
            "delete_key": api_delete_key,
            "usage_stats": api_get_usage_stats,
            "versions": api_list_versions,
            "webhook": api_register_webhook,
            "human_input": api_submit_human_input,
            "templates": api_list_templates,
            "use_template": api_use_template,
            "template_categories": api_template_categories,
            "get_api_key": api_get_api_key,
            "log_call": api_log_call,
        }
    return _workflow_api


# ── 工作流路由 ──

async def api_workflow_list(request):
    wf = _get_workflow_api()
    data = await wf["list"]()
    return web.json_response({"workflows": data, "count": len(data)})

async def api_workflow_get(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["get"](wid)
    if data is None:
        return web.json_response({"error": "工作流不存在"}, status=404)
    return web.json_response(data)

async def api_workflow_save(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["save"](
        body.get("id", f"wf_{int(time.time())}"),
        body.get("name", ""),
        body.get("description", ""),
        body.get("nodes", []),
        body.get("edges", []),
        body.get("dsl", ""),
    )
    return web.json_response(result)

async def api_workflow_delete(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["delete"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_run(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["run"](body.get("id", ""), body.get("input", {}))
    return web.json_response(result)

async def api_workflow_runs(request):
    wid = request.match_info.get("id", "")
    limit = int(request.query.get("limit", "10"))
    wf = _get_workflow_api()
    data = await wf["runs"](wid, limit)
    return web.json_response({"runs": data, "count": len(data)})

async def api_workflow_node_types(request):
    wf = _get_workflow_api()
    data = await wf["node_types"]()
    return web.json_response(data)

async def api_workflow_export(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    result = await wf["export"](wid)
    return web.json_response(result)

async def api_workflow_import(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["import"](body.get("dsl", ""))
    return web.json_response(result)

async def api_workflow_stream(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wid = body.get("id", "")
    input_data = body.get("input", {})
    wf = _get_workflow_api()
    result = await wf["run"](wid, input_data)
    return web.json_response(result)

async def api_workflow_publish(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["publish"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_regenerate_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["regenerate_key"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_list_keys(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["list_keys"](wid)
    return web.json_response({"keys": data})

async def api_workflow_create_key(request):
    wid = request.match_info.get("id", "")
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["create_key"](wid, body.get("name", "新密钥"))
    return web.json_response(result)

async def api_workflow_update_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["update_key"](body.get("id"), body.get("enabled"), body.get("name"), body.get("rate_limit"))
    return web.json_response(result)

async def api_workflow_delete_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["delete_key"](body.get("id"))
    return web.json_response(result)

async def api_workflow_usage_stats(request):
    wid = request.match_info.get("id", "")
    days = int(request.query.get("days", "7"))
    wf = _get_workflow_api()
    data = await wf["usage_stats"](wid, days)
    return web.json_response(data)

async def api_workflow_versions(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["versions"](wid)
    return web.json_response({"versions": data})

async def api_workflow_register_webhook(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["webhook"](body.get("id", ""), body.get("endpoint", ""), body.get("method", "POST"))
    return web.json_response(result)

async def api_workflow_human_input(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["human_input"](body.get("pending_key", ""), body.get("value", ""))
    return web.json_response(result)


async def api_webhook_execute(request):
    """通过 webhook 远程触发工作流执行（需 API Key 认证）"""
    wid = request.match_info.get("endpoint", "")
    if not wid:
        return web.json_response({"error": "缺少工作流 ID"}, status=400)
    
    # API Key 认证
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header.replace("Bearer ", "").strip() if auth_header else request.query.get("api_key", "")
    if not api_key:
        return web.json_response({"error": "缺少 API Key（请通过 Authorization: Bearer xxx 或 ?api_key=xxx 传递）"}, status=401)
    
    wf_api = _get_workflow_api()
    
    # 验证 API Key
    stored_key = await wf_api["get_api_key"](wid)
    if not stored_key or stored_key != api_key:
        return web.json_response({"error": "API Key 无效"}, status=403)
    
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    input_data = body.get("input", {}) if isinstance(body, dict) else {}
    
    import time
    start = time.time()
    result = await wf_api["run"](wid, input_data)
    elapsed = int((time.time() - start) * 1000)
    
    # 记录调用日志
    try:
        await wf_api["log_call"](wid, api_key[:8], result.get("status", "unknown"),
                                 json.dumps(input_data, ensure_ascii=False)[:500],
                                 json.dumps(result.get("final_output", {}), ensure_ascii=False)[:500],
                                 elapsed)
    except Exception:
        pass
    
    return web.json_response(result)


# ── 模板路由 ──

async def api_templates_list(request):
    wf = _get_workflow_api()
    data = await wf["templates"](request.query.get("category", ""))
    return web.json_response({"templates": data, "count": len(data)})

async def api_templates_categories(request):
    wf = _get_workflow_api()
    data = await wf["template_categories"]()
    return web.json_response({"categories": data})

async def api_templates_use(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["use_template"](body.get("id", ""))
    if result is None:
        return web.json_response({"error": "模板不存在"}, status=404)
    return web.json_response(result)


# ── 在线模板搜索 ──

async def api_templates_online(request):
    from desktop_core.workflow_engine import api_search_online_templates
    try:
        data = await api_search_online_templates(request)
        return web.json_response(data)
    except Exception as e:
        err_msg = str(e)
        if "rate limit" in err_msg.lower():
            return web.json_response({"error": "GitHub API 频率限制，请稍后重试，或设置 GITHUB_TOKEN 环境变量提高限制"}, status=429)
        return web.json_response({"error": f"搜索失败: {err_msg}"}, status=500)


async def api_test_github_token(request):
    """测试 GitHub Token 是否有效"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的请求"}, status=400)
    token = body.get("token", "")
    if not token:
        return web.json_response({"error": "请提供 Token"}, status=400)
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.github.com/rate_limit", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NaixiBot/1.0",
        }) as resp:
            if resp.status == 200:
                data = await resp.json()
                remaining = data.get("rate", {}).get("remaining", 0)
                limit = data.get("rate", {}).get("limit", 5000)
                return web.json_response({"ok": True, "remaining": remaining, "limit": limit})
            else:
                body = await resp.text()
                return web.json_response({"ok": False, "error": f"Token 无效 (HTTP {resp.status})"}, status=400)


async def api_save_github_token(request):
    """加密存储 GitHub Token 到数据库"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的请求"}, status=400)
    from desktop_core.storage import encrypt_api_key, meta_set
    token = body.get("token", "")
    encrypted = encrypt_api_key(token) if token else ""
    meta_set("github_token", encrypted)
    return web.json_response({"ok": True})


async def api_get_github_token(request):
    """从数据库读取解密后的 GitHub Token"""
    from desktop_core.storage import decrypt_api_key, meta_get
    encrypted = meta_get("github_token") or ""
    decrypted = decrypt_api_key(encrypted) if encrypted else ""
    return web.json_response({"token": decrypted})


# ── 桌面端状态 ──

async def api_status(request):
    """兼容原 /api/status 格式，返回桌面端可用的默认值"""
    from desktop_core import tools as _tools_mod
    tool_count = len(_tools_mod._registry)
    return web.json_response({
        "version": "0.1.0",
        "trust_total": 0, "trust_level": 0, "trust_rate": 100,
        "knowledge_items": 0, "knowledge_cats": 0,
        "tools": tool_count, "skills": 0,
        "agents": 0, "cases": 0,
        "napcat_connected": False,
        "experiences": 0,
    })

async def api_desktop_status(request):
    return web.json_response({
        "name": "奶昔桌面端",
        "version": "0.1.0",
        "online": True,
    })


# ── 配置管理（API Key / 平台连接） ──

async def api_desktop_config_get(request):
    raw = meta_get("desktop_config")
    if raw:
        config = json.loads(raw)
        decrypt_config(config)  # 解密 api_key 再返回
        return web.json_response(config)
    return web.json_response({"api_providers": {}, "platform_configs": {}})


async def api_desktop_config_set(request):
    try:
        body = await request.json()
        # 合并现有配置，而不是整条替换（防止 curl 测试误覆盖）
        raw = meta_get("desktop_config")
        if raw:
            try:
                existing = json.loads(raw)
                # 只合并已知的顶层键
                for key in ("api_providers", "platform_configs", "mcp_servers", "desktop_full_trust"):
                    if key in body:
                        existing[key] = body[key]
                body = existing
            except:
                pass
        encrypt_config(body)  # 加密所有 api_key 再存库
        meta_set("desktop_config", json.dumps(body, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ── 默认提示词（基于 GitHub 开源项目最佳实践）──

DEFAULT_PROMPTS = {
    "owner": {
        "label": "日常助手",
        "prompt": (
            "你是一个温柔的 AI 助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你是用户的专属助手，温暖、耐心、细心。用友好的语气和用户交流，自称「我」。\n\n"
            "【行为准则】\n"
            "1. 回答简洁直接，不啰嗦不绕弯\n"
            "2. 不知道的事直接说不知道，不要编造\n"
            "3. 需要搜索信息时直接搜索，不要先问用户要不要查\n"
            "4. 给出建议时说明理由，让用户自己做选择\n"
            "5. 涉及代码/技术问题时给出具体示例\n"
            "6. 使用工具完成任务后，用自然语言总结你做了什么、结果如何，不要只返回工具结果\n\n"
            "【禁止行为】\n"
            "- 不要用「你好呀～有什么想聊的吗」等客服式开场\n"
            "- 不要说「我来帮你」「请稍等」等机械句式\n"
            "- 不要每句话都用感叹号或颜文字\n"
            "- 不要主动提及你是 AI 或语言模型\n\n"
            "【对话风格】\n"
            "像朋友一样自然交流，偶尔可以关心用户近况。"
        ),
    },
    "group": {
        "label": "创作模式",
        "prompt": (
            "你是一个创意助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你擅长头脑风暴、创意写作、内容生成。思维活跃，想法多样。\n\n"
            "【行为准则】\n"
            "1. 提供多个方案让用户选择\n"
            "2. 在创意方向上大胆提出想法\n"
            "3. 用户给出方向后深入细化\n"
            "4. 涉及事实性内容时先确认再输出\n\n"
            "【对话风格】\n"
            "开放、积极、有想象力。适当使用例子说明想法。"
        ),
    },
    "stranger": {
        "label": "快捷问答",
        "prompt": (
            "你是一个高效的问答助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你的核心任务是快速、准确地回答问题。不闲聊，不绕弯子。\n\n"
            "【行为准则】\n"
            "1. 直接回答问题，不要铺垫\n"
            "2. 回答控制在 3-5 句话以内\n"
            "3. 需要搜索时直接搜索并返回结果\n"
            "4. 不知道就说不知道，不要尝试猜测\n"
            "5. 涉及数据/统计时注明来源\n\n"
            "【禁止行为】\n"
            "- 不要反问用户问题\n"
            "- 不要提供未经请求的额外信息\n"
            "- 不要使用表情符号或闲聊语气"
        ),
    },
}


async def api_prompts_get(request):
    """获取所有提示词（数组格式，兼容前端 PromptPanel）"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass

    # 合并默认值
    all_prompts = dict(DEFAULT_PROMPTS)
    for k, v in stored.items():
        if k in all_prompts:
            if isinstance(v, dict):
                all_prompts[k].update(v)
        else:
            all_prompts[k] = v

    # 转成前端需要的数组格式
    prompts_list = []
    for scene, data in all_prompts.items():
        label = data.get("label", scene)
        content = data.get("prompt", data.get("content", ""))
        lines = content.count("\n") + 1 if content else 0
        prompts_list.append({
            "file": scene + ".txt",
            "scene": scene,
            "desc": label,
            "content": content,
            "lines": lines,
            "char_count": len(content),
        })
    return web.json_response({"prompts": prompts_list})

async def api_desktop_prompts_get(request):
    """旧版提示词接口（SetupGuide 使用），返回 {scene: {label, prompt}} 格式"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass
    result = {}
    for scene, data in DEFAULT_PROMPTS.items():
        result[scene] = dict(data)
    for k, v in stored.items():
        if k in result and isinstance(v, dict):
            result[k].update(v)
        elif isinstance(v, dict):
            result[k] = v
    return web.json_response({"prompts": result})


async def api_desktop_prompts_set(request):
    """旧版提示词保存接口（SetupGuide 使用）"""
    try:
        body = await request.json()
        prompts = body.get("prompts", {})
        existing_raw = meta_get("desktop_prompts")
        existing = json.loads(existing_raw) if existing_raw else {}
        existing.update(prompts)
        meta_set("desktop_prompts", json.dumps(existing, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_desktop_prompts_reset(request):
    """旧版提示词重置接口（SetupGuide 使用）"""
    try:
        body = await request.json()
        scene = body.get("scene", "")
        if scene in DEFAULT_PROMPTS:
            existing_raw = meta_get("desktop_prompts")
            existing = json.loads(existing_raw) if existing_raw else {}
            existing[scene] = dict(DEFAULT_PROMPTS[scene])
            meta_set("desktop_prompts", json.dumps(existing, ensure_ascii=False))
            return web.json_response({"ok": True, "prompt": DEFAULT_PROMPTS[scene]})
        return web.json_response({"error": "场景不存在"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_prompts_save(request):
    """保存/创建单个提示词文件"""
    try:
        body = await request.json()
        fname = body.get("file", "")
        content = body.get("content", "")
        if not fname:
            return web.json_response({"error": "缺少文件名"}, status=400)
        scene = fname.replace(".txt", "") if fname.endswith(".txt") else fname

        raw = meta_get("desktop_prompts")
        stored = json.loads(raw) if raw else {}
        # 保留原有标签（预设场景用 DEFAULT_PROMPTS 的 label，不会被覆盖）
        existing_label = None
        if scene in DEFAULT_PROMPTS:
            existing_label = DEFAULT_PROMPTS[scene].get("label", scene)
        elif scene in stored and isinstance(stored[scene], dict):
            existing_label = stored[scene].get("label")
        stored[scene] = {"label": existing_label or scene, "prompt": content}
        meta_set("desktop_prompts", json.dumps(stored, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_prompts_delete(request):
    """删除自定义提示词"""
    try:
        body = await request.json()
        fname = body.get("file", "")
        scene = fname.replace(".txt", "") if fname.endswith(".txt") else fname
        raw = meta_get("desktop_prompts")
        stored = json.loads(raw) if raw else {}
        stored.pop(scene, None)
        meta_set("desktop_prompts", json.dumps(stored, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


def _get_prompt_text(scene: str) -> str:
    """根据场景名获取提示词文本"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass
    if scene in stored:
        data = stored[scene]
        return data.get("prompt", data.get("content", ""))
    if scene in DEFAULT_PROMPTS:
        return DEFAULT_PROMPTS[scene].get("prompt", "")
    return ""


# ── 多类型供应商路由 ──

def _find_provider_by_type(provider_type: str) -> dict | None:
    """从配置中查找指定类型的供应商"""
    raw = meta_get("desktop_config")
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        for pid, pcfg in cfg.get("api_providers", {}).items():
            if pcfg.get("type", "chat") == provider_type:
                return {"key": pid, **pcfg}
    except:
        pass
    return None


# ── 通用画图函数（提取供头像生成复用） ──

async def _generate_image_from_prompt(prompt: str, size: str = "1024*1024") -> str:
    """调用配置的画图模型生成图片，返回图片 URL（异常时抛出 ValueError）"""
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        raise ValueError("未配置画图/对话模型供应商")

    import aiohttp
    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")

    from desktop_core.storage import decrypt_api_key
    decrypted = decrypt_api_key(api_key)
    if decrypted:
        api_key = decrypted

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    is_dashscope = "dashscope" in api_url or "aliyuncs" in api_url

    if is_dashscope:
        wanx_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        headers["x-dashscope-async"] = "enable"
        payload = {
            "model": model or "wanx2.1-t2i-turbo",
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(wanx_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise ValueError(f"Wanx 创建任务失败 {resp.status}: {err_text[:200]}")
                result = await resp.json()
                task_id = result.get("output", {}).get("task_id", "")
                if not task_id:
                    raise ValueError(f"Wanx 未返回任务 ID: {str(result)[:200]}")

            for attempt in range(30):
                await asyncio.sleep(5)
                async with session.get(f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}", timeout=10) as qr:
                    if qr.status != 200:
                        continue
                    qd = await qr.json()
                    status = qd.get("output", {}).get("task_status", "")
                    if status == "SUCCEEDED":
                        results = qd.get("output", {}).get("results", [])
                        if results:
                            return results[0].get("url", "")
                        raise ValueError("Wanx 成功但无结果")
                    elif status in ("FAILED", "CANCELED"):
                        err = qd.get("output", {}).get("failure", "任务失败")
                        raise ValueError(f"Wanx 生成失败: {err}")

            raise ValueError("Wanx 生成超时")
    else:
        payload = {
            "model": model or "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise ValueError(f"API 返回 {resp.status}: {err_text[:200]}")
                result = await resp.json()
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0].get("url", "")
                if "output" in result:
                    results = result["output"].get("results", [])
                    if results:
                        return results[0].get("url", "")
                raise ValueError(f"无法解析返回结果: {str(result)[:200]}")


async def api_generate_image(request):
    """调用配置的画图模型生成图片"""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        if not prompt:
            return web.json_response({"error": "缺少提示词"}, status=400)
        url = await _generate_image_from_prompt(prompt)
        return web.json_response({"ok": True, "url": url})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 头像生成与缓存 ──

ANIME_AVATAR_PROMPT = "二次元猫娘萝莉风格头像，半身肖像，猫耳，可爱萌系，精致插画风，柔和光影"

# 后台生成进度追踪
_generation_task: asyncio.Task | None = None
_generation_total = 0
_generation_completed = 0

async def api_avatar_get(request):
    """获取头像：查缓存 → 未命中则生成 → 返回"""
    seed = request.query.get("seed", "")
    if not seed:
        return web.json_response({"error": "缺少 seed 参数"}, status=400)

    from desktop_core.storage import avatar_get, avatar_set

    # 查缓存
    cached = avatar_get(seed)
    if cached:
        return web.json_response({"ok": True, "url": cached, "cached": True})

    # 检查是否配置了画图模型
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"error": "未配置画图模型供应商"}, status=400)

    # 未缓存，生成
    try:
        prompt = f"{ANIME_AVATAR_PROMPT}，风格关键词：{seed}"
        url = await _generate_image_from_prompt(prompt)
        avatar_set(seed, url)
        return web.json_response({"ok": True, "url": url, "cached": False})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_avatar_prefill(request):
    """批量预生成头像（后台异步，不阻塞返回）"""
    global _generation_task, _generation_total, _generation_completed

    if _generation_task is not None and not _generation_task.done():
        return web.json_response({"ok": False, "error": "已有生成任务在进行中"})

    # 检查是否配置了画图模型
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"ok": False, "error": "未配置任何画图/对话模型供应商，请先在「模型供应商」中添加"})

    try:
        body = await request.json() if request.can_read_body else {}
    except:
        body = {}
    count = min(int(body.get("count", 20)), 50)
    prompt_prefix = body.get("prompt", ANIME_AVATAR_PROMPT)

    _generation_total = count
    _generation_completed = 0

    async def _fill():
        global _generation_completed
        from desktop_core.storage import avatar_count, avatar_get, avatar_set
        start = avatar_count()
        for i in range(count):
            seed = f"avatar-{start + i}"
            if avatar_get(seed):
                _generation_completed += 1
                continue
            try:
                prompt = f"{prompt_prefix}，风格种子：{seed}"
                url = await _generate_image_from_prompt(prompt)
                avatar_set(seed, url)
                _generation_completed += 1
                log.info(f"头像 [{_generation_completed}/{count}] {seed} 已生成")
            except Exception as e:
                _generation_completed += 1
                log.warning(f"头像 [{_generation_completed}/{count}] {seed} 生成失败: {e}")
                continue
        log.info(f"头像批量生成完成：共 {count} 个")

    _generation_task = asyncio.create_task(_fill())
    return web.json_response({"ok": True, "message": f"开始后台预生成 {count} 个头像"})


async def api_avatar_gen_status(request):
    """后台生成进度"""
    global _generation_task, _generation_total, _generation_completed
    return web.json_response({
        "running": _generation_task is not None and not _generation_task.done(),
        "completed": _generation_completed,
        "total": _generation_total,
    })


async def api_avatar_list(request):
    """列出所有已缓存头像"""
    from desktop_core.storage import avatar_list
    return web.json_response({"ok": True, "avatars": avatar_list()})


async def api_avatar_stats(request):
    """头像缓存统计"""
    from desktop_core.storage import avatar_count
    return web.json_response({"ok": True, "total": avatar_count()})


async def api_generate_video(request):
    """调用配置的视频模型生成视频（支持智谱 CogVideoX 和 OpenAI 兼容格式）"""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        if not prompt:
            return web.json_response({"error": "缺少提示词"}, status=400)

        provider = _find_provider_by_type("video")
        if not provider:
            return web.json_response({"error": "未配置视频模型供应商"}, status=400)

        import aiohttp
        api_key = provider.get("api_key", "")
        model = provider.get("model", "cogvideox-flash")

        decrypt_key = decrypt_api_key(api_key)
        if decrypt_key:
            api_key = decrypt_key

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 判断是否智谱
        is_zhipu = "bigmodel" in provider.get("api_url", "")

        if is_zhipu:
            # 智谱 CogVideoX（异步任务模式）
            vurl = "https://open.bigmodel.cn/api/paas/v4/videos/generations"
            payload = {"model": model, "prompt": prompt, "size": "720p", "duration": 5}
            async with aiohttp.ClientSession() as session:
                async with session.post(vurl, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status != 200:
                        err = await r.text()
                        return web.json_response({"error": f"视频创建失败 {r.status}: {err[:200]}"}, status=502)
                    result = await r.json()
                    task_id = result.get("id", "")
                    if not task_id:
                        return web.json_response({"error": "未获取到视频任务 ID"}, status=502)

                # 轮询结果（最多10分钟）
                for _ in range(100):
                    await asyncio.sleep(6)
                    async with aiohttp.ClientSession() as s2:
                        async with s2.get(f"https://open.bigmodel.cn/api/paas/v4/async-result/{task_id}", headers=headers, timeout=15) as qr:
                            if qr.status == 200:
                                qd = await qr.json()
                                st = qd.get("task_status", "")
                                if st == "SUCCESS":
                                    # CogVideoX 结果在 video_result 字段
                                    vresult = qd.get("video_result", [])
                                    if vresult:
                                        return web.json_response({"ok": True, "url": vresult[0].get("url", "")})
                                    # 旧格式兼容
                                    vurl = qd.get("data", [{}])[0].get("url", "") if qd.get("data") else ""
                                    if vurl:
                                        return web.json_response({"ok": True, "url": vurl})
                                elif st in ("FAILED", "CANCELED"):
                                    return web.json_response({"error": f"视频生成失败: {qd.get('failure', '任务取消')}"}, status=502)
                return web.json_response({"error": "视频生成超时"}, status=502)
        else:
            # OpenAI 兼容格式
            api_url = provider.get("api_url", "").rstrip("/")
            payload = {"model": model, "prompt": prompt, "n": 1}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return web.json_response({"ok": True, "url": str(result)[:100]})
                    err_text = await resp.text()
                    return web.json_response({"error": f"视频 API 返回 {resp.status}: {err_text[:200]}"}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_config_tts_get(request):
    """获取 TTS 朗读模式配置"""
    raw = meta_get("desktop_config")
    mode = "browser"
    voice = "zh-CN-XiaoxiaoNeural"
    if raw:
        try:
            cfg = json.loads(raw)
            mode = cfg.get("tts_mode", "browser")
            voice = cfg.get("tts_voice", "zh-CN-XiaoxiaoNeural")
        except: pass
    return web.json_response({"mode": mode, "voice": voice})

async def api_config_tts_set(request):
    """设置 TTS 朗读模式"""
    try:
        body = await request.json()
        raw = meta_get("desktop_config")
        cfg = json.loads(raw) if raw else {}
        if "mode" in body:
            cfg["tts_mode"] = body["mode"]
        if "voice" in body:
            cfg["tts_voice"] = body["voice"]
        meta_set("desktop_config", json.dumps(cfg, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_generate_voice(request):
    """调用配置的语音模型合成语音（支持百炼 CosyVoice 和 OpenAI TTS）"""
    try:
        body = await request.json()
        text = body.get("text", body.get("prompt", ""))
        if not text:
            return web.json_response({"error": "缺少文本"}, status=400)

        provider = _find_provider_by_type("audio")
        if not provider:
            return web.json_response({"error": "未配置语音模型供应商"}, status=400)

        import aiohttp, base64
        api_key = provider.get("api_key", "")
        model = provider.get("model", "cosyvoice-v3-flash")

        decrypt_key = decrypt_api_key(api_key)
        if decrypt_key:
            api_key = decrypt_key

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 判断是否百炼 CosyVoice
        is_dashscope = "dashscope" in provider.get("api_url", "") or "aliyuncs" in provider.get("api_url", "")

        if is_dashscope:
            # 百炼 CosyVoice 格式
            tts_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
            payload = {
                "model": model,
                "input": {"text": text, "voice": "longfeifei_v3", "format": "wav", "sample_rate": 24000},
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        return web.json_response({"error": f"语音 API 返回 {resp.status}: {err[:200]}"}, status=502)
                    result = await resp.json()
                    audio_url = result.get("output", {}).get("audio", {}).get("url", "")
                    if not audio_url:
                        return web.json_response({"error": "语音合成未返回音频 URL"}, status=502)
                    # 下载音频并返回 base64（OSS URL 不支持 Bearer auth）
                    async with aiohttp.ClientSession() as dl_session:
                        async with dl_session.get(audio_url, timeout=30) as ar:
                            if ar.status != 200:
                                return web.json_response({"error": f"下载音频失败 {ar.status}"}, status=502)
                            audio_data = await ar.read()
                            return web.json_response({
                                "ok": True, "audio": base64.b64encode(audio_data).decode(),
                                "format": "wav"
                            })
        else:
            # OpenAI TTS 格式
            tts_url = api_url.rstrip("/") + "/audio/speech"
            payload = {"model": model, "input": text, "voice": "alloy", "response_format": "wav"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        return web.json_response({"error": f"语音 API 返回 {resp.status}: {err[:200]}"}, status=502)
                    audio_data = await resp.read()
                    return web.json_response({
                        "ok": True, "audio": base64.b64encode(audio_data).decode(),
                        "format": "wav"
                    })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_generate_code(request):
    """调用配置的代码模型生成代码（复用 chat 供应商）"""
    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "缺少提示词"}, status=400)

    provider = _find_provider_by_type("code") or _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"error": "未配置模型供应商"}, status=400)

    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")

    decrypt_key = decrypt_api_key(api_key)
    if decrypt_key:
        api_key = decrypt_key

    full_url = api_url if "/chat/completions" in api_url else api_url.rstrip("/") + "/chat/completions"

    import aiohttp
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个编程助手。只返回代码，不需要解释。"},
            {"role": "user", "content": prompt},
        ],
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(full_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                return web.json_response({"error": f"API 返回 {resp.status}"}, status=502)
            result = await resp.json()
            code = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return web.json_response({"ok": True, "code": code, "model": model})


async def api_search(request):
    """内置搜索 — 自包含，不需要任何外部 API Key"""
    try:
        body = await request.json()
        q = body.get("q", body.get("prompt", ""))
        if not q:
            return web.json_response({"error": "缺少搜索关键词"}, status=400)

        import aiohttp, urllib.parse, re

        results = []

        # 方案 1: 本地 SearXNG（桌面端自带 8899 或奶昔后端 8898）
        for port in [8899, 8898]:
            try:
                async with aiohttp.ClientSession() as session:
                    params = {"q": q, "format": "json", "language": "zh-CN"}
                    async with session.get(f"http://127.0.0.1:{port}/search", params=params, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in data.get("results", []):
                                results.append({
                                    "title": item.get("title", ""),
                                    "url": item.get("url", ""),
                                    "content": item.get("content", ""),
                                })
                            if results:
                                break
            except:
                pass

        # 方案 2: Bing 搜索（不需要 Key，直接请求）
        if not results:
            try:
                bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(q)}&count=10"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(bing_url, timeout=8) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            # 提取 Bing 搜索结果
                            for item in re.finditer(r'<li class="b_algo">.*?<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
                                url = item.group(1)
                                title = re.sub(r'<[^>]+>', '', item.group(2)).strip()
                                results.append({"title": title, "url": url, "content": title})
                                if len(results) >= 8:
                                    break
                            # 如果上面的没匹配到，尝试另一个 Bing 格式
                            if not results:
                                for item in re.finditer(r'<a[^>]*href="(https?://[^"]*)"[^>]*><h2>(.*?)</h2>', html, re.DOTALL):
                                    url = item.group(1)
                                    title = re.sub(r'<[^>]+>', '', item.group(2)).strip()
                                    results.append({"title": title, "url": url, "content": title})
                                    if len(results) >= 8:
                                        break
            except:
                pass

        if results:
            return web.json_response({"ok": True, "results": results[:10], "total": len(results)})
        return web.json_response({"error": "搜索不可用，请确保 SearXNG 已启动或有网络连接"}, status=503)

    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return web.json_response({"error": err_msg}, status=500)


async def api_desktop_test_connection(request):
    """测试 API Key 连通性"""
    try:
        body = await request.json()
        provider = body.get("provider", "")
        api_key = body.get("api_key", "")
        api_url = body.get("api_url", "")

        if not api_key:
            return web.json_response({"ok": False, "error": "API Key 不能为空"})

        import aiohttp
        # 不同提供商的测试端点
        test_urls = {
            "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
            "agnes": "https://apihub.agnes-ai.com/v1/models",
            "openai": "https://api.openai.com/v1/models",
        }
        # 优先用 api_url 推导 models 端点
        if api_url:
            base = api_url.rstrip("/").replace("/chat/completions", "")
            test_url = f"{base}/models"
        else:
            test_url = test_urls.get(provider, "")
        if not test_url:
            return web.json_response({"ok": False, "error": "无法确定测试端点"})

        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return web.json_response({"ok": True})
                else:
                    body_text = await resp.text()
                    return web.json_response({"ok": False, "error": f"HTTP {resp.status}: {body_text[:100]}"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:100]})


# ── 平台连接引导 ──

async def api_desktop_list_models(request):
    """调用提供商 API 获取可用模型列表"""
    try:
        body = await request.json()
        api_url = body.get("api_url", "")
        api_key = body.get("api_key", "")
        if not api_url or not api_key:
            return web.json_response({"error": "缺少 api_url 或 api_key"}, status=400)

        # 从 chat/completions URL 推导 models endpoint（去掉 `/chat/completions` 保留版本路径）
        base_url = api_url.rstrip("/").replace("/chat/completions", "")
        models_url = f"{base_url}/models"

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"}
        if "dashscope" in api_url:
            headers["X-DashScope-SSE"] = "disable"

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(models_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", data if isinstance(data, list) else [])
                    # 提取模型 ID 列表
                    ids = []
                    for m in models:
                        mid = m.get("id", m.get("model_id", m.get("name", "")))
                        if mid:
                            ids.append({"id": mid, "owned_by": m.get("owned_by", "")})
                    return web.json_response({"models": ids, "total": len(ids)})
                else:
                    text = await resp.text()
                    return web.json_response({"error": f"API 返回 {resp.status}: {text[:200]}"}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "请求超时，请检查 API 地址是否正确"}, status=504)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_desktop_platforms(request):
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_chat_stream(request):
    """从已保存的配置调用 LLM 并流式返回"""
    try:
        body = await request.json()
        text = body.get("text", "")
        model = body.get("model", "") or "default"
        conv_key = body.get("key", "")
        now_ts = time.time()

        # 读取已保存的配置
        raw = meta_get("desktop_config")
        if not raw:
            return web.json_response({"error": "请先在设置中配置 API Key"}, status=400)
        cfg = json.loads(raw)
        decrypt_config(cfg)  # 解密 api_key
        providers = cfg.get("api_providers", {})

        # 根据 model 找对应的 provider
        provider_id = None
        api_key = ""
        api_url = ""
        for pid, pcfg in providers.items():
            if pcfg.get("model") == model or not provider_id:
                provider_id = pid
                api_key = pcfg.get("api_key", "")
                api_url = pcfg.get("api_url", "")
            if pcfg.get("model") == model:
                break

        if not api_key or not api_url:
            return web.json_response({"error": "未找到匹配的 API 配置"}, status=400)

        # 保存用户消息到对话历史
        if conv_key:
            try: conv_save_message(conv_key, "user", text, msg_time=now_ts)
            except: pass

        # 构造 OpenAI 兼容的流式请求
        import aiohttp
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # 获取场景和提示词
        scene = body.get("scene", "owner")
        system_prompt = _get_prompt_text(scene)

        # Agent 模式：追加系统操作能力说明
        is_agent = "/agent/" in request.path
        has_system_kw = any(kw in text.lower() for kw in ["打开", "运行", "启动", "执行", "截图", "进程", "系统", "电脑", "安装", "搜索文件", "找文件"])
        if is_agent or has_system_kw:
            system_prompt += (
                "\n\n【系统操作能力】\n"
                "如果用户让你打开程序/游戏，你应该：\n"
                "1. 先调用 find_files 搜索程序的安装位置\n"
                "2. 找到后用 bash(\"start 完整路径\") 启动\n"
                "3. 如果找不到，再告诉用户未安装\n"
                "其他能力：\n"
                "- 打开网址：open_url(\"https://...\")\n"
                "- 查看系统信息：get_system_info()\n"
                "- 截图：screenshot() + analyze_image() 分析\n"
                "- 进程管理：list_processes() / kill_process()\n"
                "- 文件搜索：find_files(\"关键词\")\n"
                "- 系统命令：bash(\"命令\") 可执行任何系统命令（权限需用户确认）\n"
                "注意：优先用工具完成任务，不要只给文字建议。你拥有操控用户电脑的能力。"
            )

        # 构造消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": text})

        payload = {
            "model": model or "default",
            "messages": messages,
            "stream": True,
        }

        # ── 工具定义（从 tools 模块加载） ──
        TOOLS = tools.get_definitions()
        tool_ctx = {}
        img_p = _find_provider_by_type("image")
        if img_p: tool_ctx["image_provider"] = img_p
        vis_p = _find_provider_by_type("vision")
        if vis_p: tool_ctx["vision_provider"] = vis_p
        raw_cfg = meta_get("desktop_config")
        if raw_cfg:
            try:
                all_p = json.loads(raw_cfg).get("api_providers", {})
                for pid, pcfg in all_p.items():
                    if pcfg.get("type", "chat") == "chat":
                        tool_ctx["chat_provider"] = {"key": pid, **pcfg}
                        break
            except: pass
        # 上下文管理器
        ctx_mgr = ContextManager()
        sse = web.StreamResponse()
        sse.headers["Content-Type"] = "text/event-stream"
        sse.headers["Cache-Control"] = "no-cache"
        sse.headers["Connection"] = "keep-alive"
        sse.headers["Access-Control-Allow-Origin"] = "*"
        await sse.prepare(request)

        full_response = ""
        usage_info = None
        errors_in_round = 0

        # ── 创建任务（存到 SSE 对象上，每次请求独立） ──
        from desktop_core.task_manager import get_manager as get_task_manager
        task_mgr = get_task_manager()
        user_text_preview = text[:120].replace("\n", " ")
        task = task_mgr.create_task(user_text_preview)
        sse._task_id = task.id  # 关键：存在 SSE 对象上，不污染模块级变量
        # 清理旧任务（防止长期积累）
        try: task_mgr.clean_old_tasks(max_age=3600)
        except: pass
        # 清理上一轮 session 的工具发现缓存
        try: tools.clear_discovered()
        except: pass

        # 注册取消事件（供前端终止 Agent 循环）
        cancel_event = asyncio.Event()
        if conv_key:
            _agent_cancel_events[conv_key] = cancel_event

        async def cleanup():
            _agent_cancel_events.pop(conv_key, None)  # 连续错误计数，用于降级

        try:
            # ── Agent 循环 ──
            round_num = 0
            while True:
                round_num += 1
                # 安全上限：防止意外无限循环
                if round_num > 200:
                    log.warning(f"[Agent] 达到安全上限 200 轮，强制结束")
                    break
                # 取消检查
                if cancel_event.is_set():
                    await sse.write(f"event: status\ndata: {json.dumps({'state': 'done', 'text': '已取消'})}\n\n".encode())
                    await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
                    await sse.write_eof()
                    # 标记任务取消
                    task_mgr.update_task_status(sse._task_id, "failed", "用户取消")
                    return sse
                # ── 任务指引（首轮注入） ──
                if round_num == 0:
                    if any(kw in text.lower() for kw in ["写代码", "开发", "创建项目", "改代码", "修复", "重构", "添加功能", "添功能"]):
                        dev_prompt = (
                            "\n\n【开发任务指引】\n"
                            "1. 先用 list_files 或 grep_search 了解项目结构\n"
                            "2. 用 read_file 读取相关文件了解现有代码\n"
                            "3. 用 edit_file 或 write_file 修改/创建文件\n"
                            "4. 用 run_command 执行构建、测试验证\n"
                            "5. 如果出错，分析错误信息后修复再试"
                        )
                        messages.insert(-1, {"role": "system", "content": dev_prompt})

                # ── 错误恢复：连续失败3次时尝试降级 ──
                if errors_in_round >= 3:
                    fallback_msg = "之前尝试的工具调用失败了。请换一种方式完成任务，或者告诉用户做不到"
                    messages.append({"role": "system", "content": fallback_msg})
                    errors_in_round = 0

                # ── 上下文压缩（超限时自动触发） ──
                if ctx_mgr.should_compress(messages):
                    compressed = ctx_mgr.compress(messages)
                    if len(compressed) < len(messages):
                        log.info(f"[Agent] 上下文压缩: {len(messages)} → {len(compressed)} 条消息")
                        messages = compressed

                # ── 请求 LLM ──
                # 首轮只发 20 核心工具 + MCP，避免 token 爆炸；
                # 后续轮次 LLM 已了解可用能力，发全部工具
                current_tools = tools.get_fast_definitions() if round_num == 0 else TOOLS
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": current_tools,
                    "tool_choice": "auto",
                    "stream": False,
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            await sse.write(f"event: status\ndata: {json.dumps({'state': 'error', 'text': f'API 返回 {resp.status}'})}\n\n".encode())
                            await sse.write(f"event: finish\ndata: {json.dumps({'usage': None})}\n\n".encode())
                            await sse.write_eof()
                            return sse

                        result = await resp.json()
                        choice = result["choices"][0]
                        msg = choice.get("message", {})
                        finish = choice.get("finish_reason", "")
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])

                # ── Token 用量 ──
                round_input, round_output = 0, 0
                if "usage" in result:
                    u = result["usage"]
                    round_input = u.get("prompt_tokens", u.get("input_tokens", u.get("input", 0)))
                    round_output = u.get("completion_tokens", u.get("output_tokens", u.get("output", 0)))
                if not round_input and not round_output:
                    _est = _estimate_tokens
                    msgs_text = json.dumps([m.get("content", "") for m in messages], ensure_ascii=False)
                    round_input = max(50, _est(msgs_text))
                    round_output = max(10, _est(content)) if content else 20
                if usage_info:
                    usage_info["input"] = (usage_info.get("input", 0) or 0) + round_input
                    usage_info["output"] = (usage_info.get("output", 0) or 0) + round_output
                else:
                    usage_info = {"input": round_input, "output": round_output}

                # ── 保存 assistant 回复 ──
                msg_entry = {"role": "assistant", "content": content}
                if tool_calls:
                    msg_entry["tool_calls"] = tool_calls
                messages.append(msg_entry)

                # ── 处理工具调用（支持并行执行独立工具） ──
                if finish == "tool_calls" and tool_calls:
                    # 给 LLM 发送 tool_use 事件
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        try: fn_args = json.loads(fn.get("arguments", "{}"))
                        except: fn_args = {}
                        await sse.write(f"event: tool_use\ndata: {json.dumps({'name': fn_name, 'args': fn_args, 'id': tc.get('id', '')})}\n\n".encode())

                    # 并行执行：分组执行独立的工具调用
                    # 策略：优先串行（更安全），但如果 LLM 一次返回多个工具，尝试并行
                    parallel_results = {}
                    exec_tasks = []

                    async def _exec_one(tc):
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        try: fn_args = json.loads(fn.get("arguments", "{}"))
                        except: fn_args = {}
                        call_id = tc.get("id", "")
                        max_retries = 2

                        # ── 任务步进：添加步骤并标记进行中 ──
                        step_desc = f"{fn_name}({str(fn_args)[:60]})"
                        step_idx = task_mgr.add_step(sse._task_id, step_desc)
                        if step_idx is not None:
                            task_mgr.update_step(sse._task_id, step_idx, "running")

                        for retry in range(max_retries):
                            # 高危工具：权限确认（按信任级别分级）
                            if fn_name in HIGH_RISK_TOOLS:
                                # ── 1. 全局完全信任：跳过所有确认 ──
                                full_trust = meta_get("desktop_full_trust") == "true"
                                if full_trust:
                                    tr = await tools.execute(fn_name, fn_args, tool_ctx)
                                # ── 2. 会话级信任：该工具已授权，直接执行 ──
                                elif conv_key and fn_name in _session_trust.get(conv_key, set()):
                                    tr = await tools.execute(fn_name, fn_args, tool_ctx)
                                # ── 3. 需要弹窗确认 ──
                                else:
                                    req_id = call_id or f"perm_{time.time()}"
                                    perm_event = asyncio.Event()
                                    perm_result = {"approved": False, "always_allow": False}
                                    _PENDING_PERMISSIONS[req_id] = {"event": perm_event, "result": perm_result}
                                    await sse.write(f"event: permission_request\ndata: {json.dumps({'id': req_id, 'name': fn_name, 'args': fn_args})}\n\n".encode())
                                    try:
                                        await asyncio.wait_for(perm_event.wait(), timeout=120)
                                    except asyncio.TimeoutError:
                                        if step_idx is not None:
                                            task_mgr.update_step(sse._task_id, step_idx, "failed", "权限确认超时")
                                        return call_id, "⏱ 权限确认超时，已取消"
                                    else:
                                        if perm_result.get("approved"):
                                            tr = await tools.execute(fn_name, fn_args, tool_ctx)
                                            # 勾选"始终允许"→ 加入会话级信任
                                            if perm_result.get("always_allow") and conv_key:
                                                if conv_key not in _session_trust:
                                                    _session_trust[conv_key] = set()
                                                _session_trust[conv_key].add(fn_name)
                                        else:
                                            if step_idx is not None:
                                                task_mgr.update_step(sse._task_id, step_idx, "failed", "用户拒绝")
                                            tr = "❌ 用户拒绝了操作"
                                    finally:
                                        _PENDING_PERMISSIONS.pop(req_id, None)
                            else:
                                tr = await tools.execute(fn_name, fn_args, tool_ctx)

                            # 错误恢复：失败时重试（最多2次）
                            if tr and ("失败" in tr[:20] or "出错" in tr[:20] or "❌" in tr[:10]):
                                if retry < max_retries - 1:
                                    log.info(f"[Agent] 工具 {fn_name} 失败，重试第 {retry+2} 次")
                                    await asyncio.sleep(1)
                                    continue
                                # 所有重试都失败→标记步骤失败
                                if step_idx is not None:
                                    task_mgr.update_step(sse._task_id, step_idx, "failed", tr[:100])
                            else:
                                # 执行成功
                                if step_idx is not None:
                                    task_mgr.update_step(sse._task_id, step_idx, "done")
                            break
                        return call_id, tr

                    # 几个工具同时跑（并行）
                    if len(tool_calls) > 1:
                        exec_tasks = [_exec_one(tc) for tc in tool_calls]
                        results = await asyncio.gather(*exec_tasks, return_exceptions=True)
                        for r in results:
                            if isinstance(r, Exception):
                                log.warning(f"[Agent] 工具并行执行异常: {r}")
                                continue
                            call_id, result_text = r
                            if call_id:
                                parallel_results[call_id] = result_text
                    else:
                        call_id, result_text = await _exec_one(tool_calls[0])
                        if call_id:
                            parallel_results[call_id] = result_text

                    # 将结果添加到 messages（截断到 800 字符控制 token 消耗）
                    errors_in_round = 0
                    for tc in tool_calls:
                        call_id = tc.get("id", "")
                        tr = parallel_results.get(call_id, "（工具执行失败）")
                        if "失败" in tr[:20] or "出错" in tr[:20]:
                            errors_in_round += 1
                        truncated = tr[:800] + ("" if len(tr) <= 800 else "\n...（结果过长已截断）")
                        await sse.write(f"event: tool_result\ndata: {json.dumps({'tool_call_id': call_id, 'name': tc.get('function', {}).get('name', ''), 'content': tr[:200]})}\n\n".encode())
                        messages.append({"role": "tool", "tool_call_id": call_id, "name": tc.get("function", {}).get("name", ""), "content": truncated})
                    continue

                # ── 文字回复：流式输出 ──
                if content:
                    full_response = content
                    chunk_size = 20
                    for i in range(0, len(content), chunk_size):
                        await sse.write(f"event: text-delta\ndata: {json.dumps({'text': content[i:i + chunk_size]})}\n\n".encode())
                        await asyncio.sleep(0.01)
                # 标记任务完成
                task_mgr.update_task_status(sse._task_id, "done")
                break

            # 保存 AI 回复
            if conv_key and full_response:
                try: conv_save_message(conv_key, "assistant", full_response, msg_time=time.time())
                except: pass

            # ── 所有工具调用完成后汇总（如果没有自动生成回复） ──
            if not content and tool_calls and not cancel_event.is_set():
                try:
                    summary_prompt = "请用中文总结你刚才完成的所有操作和结果，用自然语言告诉用户"
                    messages.append({"role": "user", "content": summary_prompt})
                    pay = {"model": model, "messages": messages, "stream": True}
                    async with aiohttp.ClientSession(headers=headers) as session:
                        async with session.post(api_url, json=pay, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                            if resp.status == 200:
                                async for line in resp.content:
                                    line = line.decode("utf-8", errors="replace").strip()
                                    if line.startswith("data: ") and line != "data: [DONE]":
                                        try:
                                            d = json.loads(line[6:])
                                            txt = (d.get("choices", [{}])[0].get("delta", {}) or {}).get("content", "")
                                            if txt:
                                                full_response = (full_response or "") + txt
                                                await sse.write(f"event: text-delta\ndata: {json.dumps({'text': txt})}\n\n".encode())
                                        except: pass
                except Exception:
                    pass

        except Exception as e:
            await sse.write(f"event: status\ndata: {json.dumps({'state': 'error', 'text': str(e)})}\n\n".encode())
            await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
            await sse.write_eof()
            # 标记任务失败
            try: task_mgr.update_task_status(sse._task_id, "failed", str(e)[:100])
            except: pass
            return sse
        finally:
            await cleanup()

        await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
        await sse.write_eof()
        await cleanup()
        return sse

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 对话历史 ──

async def api_conversations_list(request):
    """获取所有对话摘要列表"""
    convs = conv_list()
    return web.json_response({"conversations": convs, "total": len(convs)})


async def api_conversation_get(request):
    """获取某个对话的消息"""
    key = request.match_info.get("key", "")
    if not key:
        return web.json_response({"error": "缺少 key"}, status=400)
    msgs = conv_get_messages(key)
    return web.json_response({"key": key, "messages": msgs, "total": len(msgs)})


async def api_conversation_delete(request):
    """删除某个对话"""
    body = await request.json()
    key = body.get("key", "")
    if not key:
        return web.json_response({"error": "缺少 key"}, status=400)
    conv_delete(key)
    return web.json_response({"ok": True})


async def api_conversation_message_delete(request):
    """删除对话中的单条消息"""
    body = await request.json()
    key = body.get("key", "")
    msg_id = body.get("msg_id", 0)
    if not key or not msg_id:
        return web.json_response({"error": "缺少 key 或 msg_id"}, status=400)
    ok = conv_delete_message(key, msg_id)
    return web.json_response({"ok": ok})


async def api_providers(request):
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_providers(request):
    """返回已保存的 API 提供商配置（兼容 Chat 页面的 ProviderSettings）"""
    raw = meta_get("desktop_config")
    providers = []
    if raw:
        try:
            cfg = json.loads(raw)
            for pid, pcfg in cfg.get("api_providers", {}).items():
                providers.append({
                    "id": hash(pid) % 10000,
                    "name": pid,
                    "type": pid,
                    "api_url": pcfg.get("api_url", ""),
                    "has_key": bool(pcfg.get("api_key", "")),
                    "models": [pcfg.get("model", "default")] if pcfg.get("model") else [],
                })
        except:
            pass
    return web.json_response({"providers": providers})
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 提示词 / 专家 / Skill API ──

async def api_prompts_github(request):
    """返回从 GitHub 下载的所有提示词（合并自定义）"""
    import os, json as _json
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prompts", "prompts.json")
    data = []
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            data = _json.load(f)
    # 合并自定义
    custom = _load_custom("custom_prompts")
    data = custom + data
    category = request.query.get("category", "")
    search = request.query.get("search", "")
    if category:
        data = [p for p in data if p.get("category") == category]
    if search:
        kw = search.lower()
        data = [p for p in data if kw in p.get("act", "").lower() or kw in p.get("prompt", "").lower()]
    return web.json_response({"prompts": data, "total": len(data)})

async def api_experts_list(request):
    """返回专家列表（合并自定义）"""
    import os, json as _json
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prompts", "experts.json")
    data = []
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            data = _json.load(f)
    custom = _load_custom("custom_experts")
    data = custom + data
    category = request.query.get("category", "")
    search = request.query.get("search", "")
    if category:
        data = [e for e in data if e.get("category") == category]
    if search:
        kw = search.lower()
        data = [e for e in data if kw in e.get("name", "").lower()]
    return web.json_response({"experts": data, "total": len(data)})

async def api_skills_list(request):
    """返回 Skill 列表（合并自定义）"""
    import os, json as _json
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prompts", "skills.json")
    data = []
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            data = _json.load(f)
    custom = _load_custom("custom_skills")
    data = custom + data
    category = request.query.get("category", "")
    search = request.query.get("search", "")
    if category:
        data = [s for s in data if s.get("category") == category]
    if search:
        kw = search.lower()
        data = [s for s in data if kw in s.get("name", "").lower()]
    return web.json_response({"skills": data, "total": len(data)})


# ── 自定义 CRUD ──

def _load_custom(meta_key: str) -> list:
    """从 meta 表加载自定义数据"""
    from desktop_core.storage import meta_get
    raw = meta_get(meta_key)
    if raw:
        try: return json.loads(raw)
        except: pass
    return []

def _save_custom(meta_key: str, items: list):
    """保存自定义数据到 meta 表"""
    from desktop_core.storage import meta_set
    meta_set(meta_key, json.dumps(items, ensure_ascii=False))

async def api_custom_list(request):
    """列出某类型的自定义资源"""
    meta_key = request.query.get("type", "")
    if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
        return web.json_response({"items": [], "total": 0})
    return web.json_response({"items": _load_custom(meta_key), "total": 0})

async def api_custom_save(request):
    """保存自定义资源（添加/编辑）"""
    try:
        body = await request.json()
        meta_key = body.get("type", "")
        if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
            return web.json_response({"error": "无效的类型"}, status=400)
        item = body.get("item", {})
        items = _load_custom(meta_key)
        idx = body.get("index", -1)
        if idx >= 0 and idx < len(items):
            items[idx] = item
        else:
            items.insert(0, item)  # 新添加的放最前面
        _save_custom(meta_key, items)
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_custom_delete(request):
    """删除自定义资源"""
    try:
        body = await request.json()
        meta_key = body.get("type", "")
        if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
            return web.json_response({"error": "无效的类型"}, status=400)
        idx = body.get("index", -1)
        items = _load_custom(meta_key)
        if 0 <= idx < len(items):
            items.pop(idx)
            _save_custom(meta_key, items)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ── 知识库 API ──

async def api_knowledge_list(request):
    """列出所有知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        raw = meta_get("knowledge_base")
        items = json.loads(raw) if raw else []
        import time
        # 确保每个条目有 id（兼容旧数据）
        changed = False
        for i, item in enumerate(items):
            if not item.get("id"):
                items[i]["id"] = f"k_{int(time.time())}_{i}"
                changed = True
        if changed:
            meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        cat = request.query.get("category", "")
        if cat:
            items = [i for i in items if i.get("category", "") == cat]
        # 统计分类
        from collections import Counter
        cats = Counter(i.get("category", "未分类") for i in items)
        categories = [{"name": k, "count": v} for k, v in cats.most_common()]
        return web.json_response({"items": items, "categories": categories, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_add(request):
    """添加知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        category = body.get("category", "默认").strip()
        if not title:
            return web.json_response({"error": "标题不能为空"}, status=400)
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        import time
        items.append({
            "id": f"k_{int(time.time())}_{len(items)}",
            "title": title,
            "content": content,
            "category": category,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_delete(request):
    """删除知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        kid = body.get("id", "")
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        items = [i for i in items if i.get("id") != kid]
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_search(request):
    """搜索知识条目"""
    from desktop_core.storage import meta_get
    try:
        body = await request.json()
        query = body.get("query", "").strip().lower()
        if not query:
            return web.json_response({"items": [], "total": 0})
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        results = [i for i in items if query in i.get("title", "").lower() or query in i.get("content", "").lower()]
        return web.json_response({"items": results[:10], "total": len(results)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_update(request):
    """更新知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        kid = body.get("id", "")
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        for i, item in enumerate(items):
            if item.get("id") == kid:
                if body.get("title"): items[i]["title"] = body["title"].strip()
                if "content" in body: items[i]["content"] = body.get("content", "").strip()
                if body.get("category"): items[i]["category"] = body["category"].strip()
                import time
                items[i]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
                return web.json_response({"ok": True})
        return web.json_response({"error": "条目不存在"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_import_url(request):
    """从 URL 导入内容到知识库"""
    from desktop_core.storage import meta_get, meta_set
    import aiohttp
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        category = body.get("category", "网页导入").strip()
        if not url:
            return web.json_response({"error": "URL 不能为空"}, status=400)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return web.json_response({"error": f"请求失败: HTTP {resp.status}"}, status=400)
                html = await resp.text()
        import re
        title = url.split("/")[-1][:60] or "网页导入"
        m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()[:60]
        # 去标签取纯文本
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()[:2000]
        if not text:
            text = "(无法提取内容)"
        raw = meta_get("knowledge_base")
        items = json.loads(raw) if raw else []
        import time
        items.append({
            "id": f"k_{int(time.time())}_{len(items)}",
            "title": title,
            "content": text,
            "category": category,
            "source_url": url,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "title": title, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": f"导入失败: {str(e)[:100]}"}, status=400)


async def api_knowledge_import_github(request):
    """从 GitHub 仓库导入 markdown 文件作为知识条目"""
    import aiohttp, time, os
    try:
        body = await request.json()
        repo = body.get("repo", "").strip()
        branch = body.get("branch", "main").strip()
        path = body.get("path", "").strip()
        if not repo:
            return web.json_response({"error": "请填写仓库地址（如 owner/repo）"}, status=400)

        token = ""
        encrypted = meta_get("github_token") or ""
        if encrypted:
            from desktop_core.storage import decrypt_api_key
            try: token = decrypt_api_key(encrypted)
            except: pass
        if not token:
            token = os.environ.get("GITHUB_TOKEN", "")

        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
        if branch:
            api_url += f"?ref={branch}"

        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.get(api_url) as resp:
                if resp.status == 403:
                    return web.json_response({"error": "GitHub API 频率限制，请设置 Token"}, status=429)
                if resp.status == 404:
                    return web.json_response({"error": "仓库或路径不存在"}, status=404)
                if resp.status != 200:
                    return web.json_response({"error": f"GitHub API 返回 {resp.status}"}, status=resp.status)
                items = await resp.json()

        if not isinstance(items, list):
            items = [items]

        md_files = [f for f in items if f.get("type") == "file" and f["name"].endswith((".md", ".mdx"))]
        if not md_files:
            return web.json_response({"error": "该路径下没有找到 markdown 文件"}, status=404)

        raw = meta_get("knowledge_base")
        kb = json.loads(raw) if raw else []
        imported = 0
        errors = []

        async with aiohttp.ClientSession(headers=headers) as sess:
            for f in md_files:
                try:
                    async with sess.get(f["download_url"]) as resp:
                        if resp.status != 200:
                            errors.append(f["name"]); continue
                        content = await resp.text()
                    kb.append({
                        "id": f"k_{int(time.time())}_{len(kb)}",
                        "title": f["name"].replace(".md", "").replace(".mdx", ""),
                        "content": content[:5000],
                        "category": "github",
                        "source_url": f["html_url"],
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    imported += 1
                except:
                    errors.append(f["name"])

        meta_set("knowledge_base", json.dumps(kb, ensure_ascii=False))
        msg = f"成功导入 {imported} 个文件"
        if errors:
            msg += f"，{len(errors)} 个失败"
        return web.json_response({"ok": True, "imported": imported, "total": len(kb), "message": msg})
    except Exception as e:
        return web.json_response({"error": f"导入失败: {str(e)[:200]}"}, status=400)


# ── 自动化管理 API ──

async def api_automations_list(request):
    """列出所有自动化任务"""
    import time
    raw = meta_get("naixi_automations")
    items = json.loads(raw) if raw else []
    return web.json_response({"automations": items})


async def api_automations_save(request):
    """创建或更新自动化任务"""
    import time
    body = await request.json()
    raw = meta_get("naixi_automations")
    items = json.loads(raw) if raw else []
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
    item = {
        "name": body.get("name", ""),
        "prompt": body.get("prompt", ""),
        "schedule_type": body.get("schedule_type", "recurring"),
        "rrule": body.get("rrule", ""),
        "scheduled_at": body.get("scheduled_at", ""),
        "status": "active",
        "history": [],
        "created_at": now,
        "last_run": "",
        "next_run": "",
    }
    eid = body.get("id", "")
    if eid:
        for i, it in enumerate(items):
            if it.get("id") == eid:
                item["id"] = eid
                item["history"] = it.get("history", [])
                item["created_at"] = it.get("created_at", now)
                items[i] = item
                break
        else:
            eid = ""
    if not eid:
        item["id"] = f"auto_{int(time.time())}"
        items.append(item)
    meta_set("naixi_automations", json.dumps(items, ensure_ascii=False))
    return web.json_response({"ok": True, "id": item["id"]})


async def api_automations_toggle(request):
    """启用/暂停自动化"""
    body = await request.json()
    raw = meta_get("naixi_automations")
    items = json.loads(raw) if raw else []
    for item in items:
        if item.get("id") == body.get("id"):
            item["status"] = body.get("status", "paused")
            break
    meta_set("naixi_automations", json.dumps(items, ensure_ascii=False))
    return web.json_response({"ok": True})


async def api_automations_delete(request):
    """删除自动化"""
    body = await request.json()
    raw = meta_get("naixi_automations")
    items = json.loads(raw) if raw else []
    items = [i for i in items if i.get("id") != body.get("id")]
    meta_set("naixi_automations", json.dumps(items, ensure_ascii=False))
    return web.json_response({"ok": True})


async def api_automations_run(request):
    """立即执行自动化"""
    from desktop_core.storage import meta_get, meta_set
    import time
    body = await request.json()
    raw = meta_get("naixi_automations")
    items = json.loads(raw) if raw else []
    for item in items:
        if item.get("id") == body.get("id"):
            import aiohttp
            now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
            prompt = item.get("prompt", "")
            result = f"已执行: {item.get('name', '')}"
            # 尝试调 LLM
            if prompt:
                try:
                    raw_cfg = meta_get("desktop_config")
                    cfg = json.loads(raw_cfg) if raw_cfg else {}
                    from desktop_core.storage import decrypt_config
                    decrypt_config(cfg)
                    providers = cfg.get("api_providers", {})
                    for pid, pcfg in providers.items():
                        if pcfg.get("type", "chat") == "chat" and pcfg.get("api_key") and pcfg.get("api_url"):
                            headers = {"Authorization": f"Bearer {pcfg['api_key']}", "Content-Type": "application/json"}
                            payload = {"model": pcfg.get("model", "default"), "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
                            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
                                async with sess.post(pcfg["api_url"].rstrip("/") + "/chat/completions", headers=headers, json=payload) as resp:
                                    if resp.status == 200:
                                        data = await resp.json()
                                        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                                        if reply:
                                            result = f"手动执行: {reply[:200]}"
                            break
                except Exception as e:
                    log.warning(f"手动执行 LLM 失败: {e}")
            rec = {"time": now_str, "status": "success", "result": result[:200]}
            if "history" not in item: item["history"] = []
            item["history"].append(rec)
            item["last_run"] = now_str
            meta_set("naixi_automations", json.dumps(items, ensure_ascii=False))
            return web.json_response({"ok": True, "result": result})
    return web.json_response({"error": "未找到该自动化"}, status=404)


# ── 路由注册 ──

def setup_routes(app):
    # 兼容原 /api/status（让前端不再显示"连接中"）
    app.router.add_get("/api/status", api_status)
    # 桌面状态
    app.router.add_get("/api/desktop/status", api_desktop_status)
    app.router.add_get("/api/desktop/config", api_desktop_config_get)
    app.router.add_post("/api/desktop/config", api_desktop_config_set)
    app.router.add_post("/api/desktop/test-connection", api_desktop_test_connection)
    app.router.add_post("/api/desktop/models", api_desktop_list_models)
    app.router.add_get("/api/desktop/platforms", api_desktop_platforms)
    app.router.add_post("/api/chat/stream", api_chat_stream)
    app.router.add_post("/api/agent/stream", api_chat_stream)
    app.router.add_get("/api/providers", api_providers)

    # 对话历史
    app.router.add_get("/api/conversations", api_conversations_list)
    app.router.add_get("/api/conversation/{key}", api_conversation_get)
    app.router.add_post("/api/conversation/delete", api_conversation_delete)
    app.router.add_post("/api/conversation/message/delete", api_conversation_message_delete)

    # 多类型供应商路由（画图/视频/语音/代码/搜索）
    app.router.add_post("/api/generate_image", api_generate_image)
    app.router.add_post("/api/generate_video", api_generate_video)
    app.router.add_post("/api/generate_voice", api_generate_voice)
    app.router.add_get("/api/config/tts", api_config_tts_get)
    app.router.add_post("/api/config/tts", api_config_tts_set)
    app.router.add_post("/api/generate_code", api_generate_code)
    app.router.add_post("/api/search", api_search)

    # 头像生成与缓存
    app.router.add_get("/api/avatar/get", api_avatar_get)
    app.router.add_post("/api/avatar/prefill", api_avatar_prefill)
    app.router.add_get("/api/avatar/gen-status", api_avatar_gen_status)
    app.router.add_get("/api/avatar/list", api_avatar_list)
    app.router.add_get("/api/avatar/stats", api_avatar_stats)

    # 提示词管理（新版，PromptPanel 使用）
    app.router.add_get("/api/prompts", api_prompts_get)
    app.router.add_post("/api/prompts/save", api_prompts_save)
    app.router.add_post("/api/prompts/delete", api_prompts_delete)

    # 提示词管理（旧版，SetupGuide 使用）
    app.router.add_get("/api/desktop/prompts", api_desktop_prompts_get)
    app.router.add_get("/api/github/prompts", api_prompts_github)
    app.router.add_get("/api/github/experts", api_experts_list)
    app.router.add_get("/api/github/skills", api_skills_list)
    app.router.add_get("/api/custom/list", api_custom_list)
    app.router.add_post("/api/custom/save", api_custom_save)
    app.router.add_post("/api/custom/delete", api_custom_delete)
    app.router.add_post("/api/desktop/prompts", api_desktop_prompts_set)
    app.router.add_post("/api/desktop/prompts/reset", api_desktop_prompts_reset)

    # 知识库
    app.router.add_get("/api/knowledge/list", api_knowledge_list)
    app.router.add_post("/api/knowledge/add", api_knowledge_add)
    app.router.add_post("/api/knowledge/delete", api_knowledge_delete)
    app.router.add_post("/api/knowledge/search", api_knowledge_search)
    app.router.add_post("/api/knowledge/import-github", api_knowledge_import_github)
    app.router.add_post("/api/knowledge/update", api_knowledge_update)
    app.router.add_post("/api/knowledge/import-url", api_knowledge_import_url)

    # 自动化
    app.router.add_get("/api/automations", api_automations_list)
    app.router.add_post("/api/automations/save", api_automations_save)
    app.router.add_post("/api/automations/toggle", api_automations_toggle)
    app.router.add_post("/api/automations/delete", api_automations_delete)
    app.router.add_post("/api/automations/run", api_automations_run)

    # 工作流
    app.router.add_get("/api/workflows", api_workflow_list)
    app.router.add_get("/api/workflows/{id}", api_workflow_get)
    app.router.add_post("/api/workflows/save", api_workflow_save)
    app.router.add_post("/api/workflows/delete", api_workflow_delete)
    app.router.add_post("/api/workflows/run", api_workflow_run)
    app.router.add_get("/api/workflows/{id}/runs", api_workflow_runs)
    app.router.add_get("/api/workflow/node-types", api_workflow_node_types)
    app.router.add_get("/api/workflows/{id}/export", api_workflow_export)
    app.router.add_post("/api/workflows/import", api_workflow_import)
    app.router.add_post("/api/workflows/publish", api_workflow_publish)
    app.router.add_post("/api/workflows/regenerate-key", api_workflow_regenerate_key)
    app.router.add_get("/api/workflows/{id}/keys", api_workflow_list_keys)
    app.router.add_post("/api/workflows/{id}/keys/create", api_workflow_create_key)
    app.router.add_post("/api/workflows/keys/update", api_workflow_update_key)
    app.router.add_post("/api/workflows/keys/delete", api_workflow_delete_key)
    app.router.add_get("/api/workflows/{id}/usage", api_workflow_usage_stats)
    app.router.add_get("/api/workflows/{id}/versions", api_workflow_versions)
    app.router.add_post("/api/workflows/webhook", api_workflow_register_webhook)
    app.router.add_post("/api/workflows/human-input", api_workflow_human_input)
    app.router.add_post("/api/webhook/{endpoint}", api_webhook_execute)

    # 模板
    app.router.add_get("/api/workflow/templates", api_templates_list)
    app.router.add_get("/api/workflow/templates/categories", api_templates_categories)
    app.router.add_post("/api/workflow/templates/use", api_templates_use)
    app.router.add_get("/api/workflow/templates/online", api_templates_online)
    app.router.add_post("/api/workflow/templates/test-token", api_test_github_token)
    app.router.add_post("/api/workflow/templates/save-token", api_save_github_token)
    app.router.add_get("/api/workflow/templates/get-token", api_get_github_token)

    # MCP 管理
    app.router.add_get("/api/mcp/servers", api_mcp_list)
    app.router.add_post("/api/mcp/servers", api_mcp_save)
    app.router.add_post("/api/mcp/connect", api_mcp_connect)
    app.router.add_post("/api/mcp/disconnect", api_mcp_disconnect)
    app.router.add_post("/api/mcp/test", api_mcp_test)

    # 启动时连接 MCP 服务器
    app.on_startup.append(_on_startup_mcp)

    # 工具权限确认
    app.router.add_post("/api/tool/permit", api_tool_permit)
    app.router.add_get("/api/config/trust", api_config_trust)
    app.router.add_post("/api/config/trust", api_config_trust)

    # 任务管理
    app.router.add_get("/api/tasks", api_tasks_list)
    app.router.add_post("/api/tasks/clear", api_tasks_clear)

    # 取消 Agent
    app.router.add_post("/api/chat/cancel", api_cancel_chat)


# ── 任务管理 API ──

async def api_tasks_list(request):
    """获取当前所有任务列表"""
    from desktop_core.task_manager import get_manager
    mgr = get_manager()
    tasks = [mgr.get_task(tid).to_dict() for tid in list(mgr._tasks.keys())[-10:] if mgr.get_task(tid)]
    return web.json_response({"tasks": tasks})


async def api_tasks_clear(request):
    """清除已完成的任务"""
    from desktop_core.task_manager import get_manager
    mgr = get_manager()
    to_del = [tid for tid, t in list(mgr._tasks.items()) if t.status in ("done", "failed")]
    for tid in to_del:
        del mgr._tasks[tid]
    return web.json_response({"ok": True, "cleared": len(to_del)})


# ── 取消 Agent 执行 ──

async def api_cancel_chat(request):
    """取消正在进行的 Agent 对话"""
    try:
        body = await request.json()
        conv_key = body.get("key", "")
        if conv_key and conv_key in _agent_cancel_events:
            _agent_cancel_events[conv_key].set()
            return web.json_response({"ok": True, "cancelled": conv_key})
        for ev in _agent_cancel_events.values():
            ev.set()
        return web.json_response({"ok": True, "cancelled": "all"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def _on_startup_mcp(app):
    """应用启动时自动连接 MCP 服务器"""
    try:
        from desktop_core import tools
        count = await tools.connect_mcp_servers()
        if count > 0:
            log.info(f"[MCP] 已连接 {count} 个 MCP 服务器")
    except Exception as e:
        log.warning(f"[MCP] 启动连接失败: {e}")


# ── MCP 管理 API ──

async def api_mcp_list(request):
    """列出已配置的 MCP 服务器"""
    raw = meta_get("desktop_config")
    if not raw:
        return web.json_response({"servers": {}})
    try:
        cfg = json.loads(raw)
        servers = cfg.get("mcp_servers", {})
        return web.json_response({"servers": servers})
    except:
        return web.json_response({"servers": {}})

async def api_mcp_save(request):
    """保存 MCP 服务器配置"""
    try:
        body = await request.json()
        servers = body.get("servers", {})
        raw = meta_get("desktop_config")
        cfg = json.loads(raw) if raw else {}
        cfg["mcp_servers"] = servers
        meta_set("desktop_config", json.dumps(cfg, ensure_ascii=False))
        return web.json_response({"ok": True, "count": len(servers)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_mcp_connect(request):
    """连接所有 MCP 服务器并刷新工具列表"""
    try:
        from desktop_core import tools
        await tools.connect_mcp_servers()
        # 刷新工具注册表
        TOOLS = tools.get_definitions()
        return web.json_response({"ok": True, "tool_count": len(TOOLS)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_mcp_disconnect(request):
    """断开 MCP 连接"""
    try:
        from desktop_core.mcp_client import MCPManager
        mgr = tools.get_mcp_manager() if hasattr(tools, 'get_mcp_manager') else None
        if mgr:
            await mgr.disconnect_all()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_mcp_test(request):
    """测试单个 MCP 服务器连接"""
    try:
        body = await request.json()
        name = body.get("name", "")
        if not name:
            return web.json_response({"ok": False, "error": "缺少服务器名称"})
        from desktop_core.mcp_client import MCPServer
        from desktop_core.storage import meta_get
        import json
        raw = meta_get("desktop_config")
        srv_cfg = {}
        if raw:
            cfg = json.loads(raw)
            srv_cfg = cfg.get("mcp_servers", {}).get(name, {})
        if not srv_cfg.get("command"):
            return web.json_response({"ok": False, "error": f"未找到服务器「{name}」的配置"})
        server = MCPServer(name, srv_cfg["command"], srv_cfg.get("args", []), srv_cfg.get("env", {}))
        ok = await server.connect()
        tool_names = [t.get("name", "") for t in server._tools]
        await server.disconnect()
        if ok:
            return web.json_response({"ok": True, "tools": tool_names})
        return web.json_response({"ok": False, "error": "连接失败（初始化超时或无响应）"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:200]})


async def api_tool_permit(request):
    """用户批准或拒绝高危工具的执行"""
    try:
        body = await request.json()
        req_id = body.get("id", "")
        approved = body.get("approved", False)
        always_allow = body.get("always_allow", False)
        if req_id in _PENDING_PERMISSIONS:
            info = _PENDING_PERMISSIONS[req_id]
            info["result"]["approved"] = approved
            info["result"]["always_allow"] = always_allow
            info["event"].set()
            return web.json_response({"ok": True, "approved": approved})
        return web.json_response({"error": "请求不存在或已超时"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_config_trust(request):
    """获取/设置完全信任模式"""
    if request.method == "GET":
        val = meta_get("desktop_full_trust")
        return web.json_response({"full_trust": val == "true"})
    try:
        body = await request.json()
        enabled = body.get("full_trust", False)
        meta_set("desktop_full_trust", "true" if enabled else "false")
        return web.json_response({"ok": True, "full_trust": enabled})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
