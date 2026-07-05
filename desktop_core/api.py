"""桌面端 API 路由 — 脱敏版，不含任何 QQ 机器人相关功能"""
import json, os, time, logging, asyncio
from aiohttp import web
from datetime import datetime

from desktop_core.storage import meta_get, meta_set

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
            api_template_categories,
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
            "versions": api_list_versions,
            "webhook": api_register_webhook,
            "human_input": api_submit_human_input,
            "templates": api_list_templates,
            "use_template": api_use_template,
            "template_categories": api_template_categories,
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
    result = await wf["save"](body)
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
    data = await api_search_online_templates(request)
    return web.json_response(data)


# ── 桌面端状态 ──

async def api_status(request):
    """兼容原 /api/status 格式，返回桌面端可用的默认值"""
    return web.json_response({
        "version": "0.1.0",
        "trust_total": 0, "trust_level": 0, "trust_rate": 100,
        "knowledge_items": 0, "knowledge_cats": 0,
        "tools": 25, "skills": 0,
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
        return web.json_response(json.loads(raw))
    return web.json_response({"api_providers": {}, "platform_configs": {}})


async def api_desktop_config_set(request):
    try:
        body = await request.json()
        meta_set("desktop_config", json.dumps(body, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ── 默认提示词（基于 GitHub 开源项目最佳实践）──

DEFAULT_PROMPTS = {
    "assistant": {
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
            "5. 涉及代码/技术问题时给出具体示例\n\n"
            "【禁止行为】\n"
            "- 不要用「你好呀～有什么想聊的吗」等客服式开场\n"
            "- 不要说「我来帮你」「请稍等」等机械句式\n"
            "- 不要每句话都用感叹号或颜文字\n"
            "- 不要主动提及你是 AI 或语言模型\n\n"
            "【对话风格】\n"
            "像朋友一样自然交流，偶尔可以关心用户近况。"
        ),
    },
    "creative": {
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
    "qa": {
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
    """读取所有提示词，未自定义时返回默认值"""
    raw = meta_get("desktop_prompts")
    if raw:
        try:
            stored = json.loads(raw)
            # 合并默认值和已存储的（确保新增场景有默认值）
            result = dict(DEFAULT_PROMPTS)
            for k, v in stored.items():
                if k in result:
                    result[k].update(v)
            return web.json_response({"prompts": result})
        except:
            pass
    return web.json_response({"prompts": dict(DEFAULT_PROMPTS)})


async def api_prompts_set(request):
    """保存自定义提示词"""
    try:
        body = await request.json()
        prompts = body.get("prompts", {})
        # 只保存用户修改过的场景，不覆盖未发送的场景
        existing_raw = meta_get("desktop_prompts")
        existing = json.loads(existing_raw) if existing_raw else {}
        existing.update(prompts)
        meta_set("desktop_prompts", json.dumps(existing, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_prompts_reset(request):
    """恢复某个场景的默认提示词"""
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
        # 不同提供商的测试端点不同
        test_urls = {
            "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
            "agnes": "https://apihub.agnes-ai.com/v1/models",
            "openai": "https://api.openai.com/v1/models",
        }
        test_url = api_url or test_urls.get(provider, "")
        if not test_url:
            # 从 api_url 推测
            base = api_url.rstrip("/").replace("/v1/chat/completions", "").replace("/chat/completions", "")
            test_url = f"{base}/models"

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

async def api_desktop_platforms(request):
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 路由注册 ──

def setup_routes(app):
    # 兼容原 /api/status（让前端不再显示"连接中"）
    app.router.add_get("/api/status", api_status)
    # 桌面状态
    app.router.add_get("/api/desktop/status", api_desktop_status)
    app.router.add_get("/api/desktop/config", api_desktop_config_get)
    app.router.add_post("/api/desktop/config", api_desktop_config_set)
    app.router.add_post("/api/desktop/test-connection", api_desktop_test_connection)
    app.router.add_get("/api/desktop/platforms", api_desktop_platforms)

    # 提示词管理
    app.router.add_get("/api/desktop/prompts", api_prompts_get)
    app.router.add_post("/api/desktop/prompts", api_prompts_set)
    app.router.add_post("/api/desktop/prompts/reset", api_prompts_reset)

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
    app.router.add_get("/api/workflows/{id}/versions", api_workflow_versions)
    app.router.add_post("/api/workflows/webhook", api_workflow_register_webhook)
    app.router.add_post("/api/workflows/human-input", api_workflow_human_input)
    app.router.add_post("/api/webhook/{endpoint}", api_workflow_human_input)

    # 模板
    app.router.add_get("/api/workflow/templates", api_templates_list)
    app.router.add_get("/api/workflow/templates/categories", api_templates_categories)
    app.router.add_post("/api/workflow/templates/use", api_templates_use)
    app.router.add_get("/api/workflow/templates/online", api_templates_online)
