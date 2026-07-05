"""桌面端 API 路由 — 脱敏版，不含任何 QQ 机器人相关功能"""
import json, os, sys, time, logging, asyncio
from aiohttp import web
from datetime import datetime

from desktop_core.context import ContextManager

from desktop_core.storage import meta_get, meta_set, encrypt_config, decrypt_config, decrypt_api_key, conv_list, conv_get_messages, conv_delete, conv_save_message_sync as conv_save_message
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
        config = json.loads(raw)
        decrypt_config(config)  # 解密 api_key 再返回
        return web.json_response(config)
    return web.json_response({"api_providers": {}, "platform_configs": {}})


async def api_desktop_config_set(request):
    try:
        body = await request.json()
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


async def api_generate_image(request):
    """调用配置的画图模型生成图片"""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        if not prompt:
            return web.json_response({"error": "缺少提示词"}, status=400)

        provider = _find_provider_by_type("image")
        if not provider:
            provider = _find_provider_by_type("chat")
        if not provider:
            return web.json_response({"error": "未配置画图/对话模型供应商"}, status=400)

        import aiohttp
        api_url = provider.get("api_url", "").rstrip("/")
        api_key = provider.get("api_key", "")
        model = provider.get("model", "")

        decrypt_key = decrypt_api_key(api_key)
        if decrypt_key:
            api_key = decrypt_key

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 判断是否是百炼 Wanx（需用专用端点+格式）
        is_dashscope = "dashscope" in api_url or "aliyuncs" in api_url

        if is_dashscope:
            # Wanx 异步任务模式
            wanx_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
            headers["x-dashscope-async"] = "enable"
            payload = {
                "model": model or "wanx2.1-t2i-turbo",
                "input": {"prompt": prompt},
                "parameters": {"size": "1024*1024", "n": 1},
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                # 创建任务
                async with session.post(wanx_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        return web.json_response({"error": f"Wanx 创建任务失败 {resp.status}: {err_text[:200]}"}, status=502)
                    result = await resp.json()
                    task_id = result.get("output", {}).get("task_id", "")
                    if not task_id:
                        return web.json_response({"error": f"Wanx 未返回任务 ID: {str(result)[:200]}"}, status=502)

                # 轮询任务结果
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
                                return web.json_response({"ok": True, "url": results[0].get("url", "")})
                            return web.json_response({"error": "Wanx 成功但无结果"}, status=502)
                        elif status in ("FAILED", "CANCELED"):
                            err = qd.get("output", {}).get("failure", "任务失败")
                            return web.json_response({"error": f"Wanx 生成失败: {err}"}, status=502)

                return web.json_response({"error": "Wanx 生成超时"}, status=502)
        else:
            # OpenAI 兼容格式
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
                        return web.json_response({"error": f"API 返回 {resp.status}: {err_text[:200]}"}, status=502)
                    result = await resp.json()
                    if "data" in result and len(result["data"]) > 0:
                        return web.json_response({"ok": True, "url": result["data"][0].get("url", "")})
                    if "output" in result:
                        results = result["output"].get("results", [])
                        if results:
                            return web.json_response({"ok": True, "url": results[0].get("url", "")})
                    return web.json_response({"error": f"无法解析返回结果: {str(result)[:200]}"}, status=502)

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


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

        try:
            # ── Agent 循环（最多 10 轮） ──
            for round_num in range(10):
                # 上下文压缩（超限时自动触发）
                if ctx_mgr.should_compress(messages):
                    compressed = ctx_mgr.compress(messages)
                    if len(compressed) < len(messages):
                        log.info(f"[Agent] 上下文压缩: {len(messages)} → {len(compressed)} 条消息")
                        messages = compressed
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": TOOLS,
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

                        if "usage" in result:
                            u = result["usage"]
                            usage_info = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}

                        # 保存 assistant 回复到历史
                        msg_entry = {"role": "assistant", "content": content}
                        if tool_calls:
                            msg_entry["tool_calls"] = tool_calls
                        messages.append(msg_entry)

                        # ── 处理工具调用 ──
                        if finish == "tool_calls" and tool_calls:
                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                fn_name = fn.get("name", "")
                                try:
                                    fn_args = json.loads(fn.get("arguments", "{}"))
                                except:
                                    fn_args = {}

                                await sse.write(f"event: tool_use\ndata: {json.dumps({'name': fn_name, 'args': fn_args, 'id': tc.get('id', '')})}\n\n".encode())

                                tool_result = await tools.execute(fn_name, fn_args, tool_ctx)

                                await sse.write(f"event: tool_result\ndata: {json.dumps({'tool_call_id': tc.get('id', ''), 'name': fn_name, 'content': tool_result[:200]})}\n\n".encode())

                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.get("id", ""),
                                    "name": fn_name,
                                    "content": tool_result,
                                })
                            continue

                        # ── 文字回复：流式输出 ──
                        if content:
                            full_response = content
                            chunk_size = 20
                            for i in range(0, len(content), chunk_size):
                                await sse.write(f"event: text-delta\ndata: {json.dumps({'text': content[i:i + chunk_size]})}\n\n".encode())
                                await asyncio.sleep(0.01)
                        break

            # 保存 AI 回复
            if conv_key and full_response:
                try: conv_save_message(conv_key, "assistant", full_response, msg_time=time.time())
                except: pass

        except Exception as e:
            await sse.write(f"event: status\ndata: {json.dumps({'state': 'error', 'text': str(e)})}\n\n".encode())
            await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
            await sse.write_eof()
            return sse

        await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
        await sse.write_eof()
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

    # 多类型供应商路由（画图/视频/语音/代码/搜索）
    app.router.add_post("/api/generate_image", api_generate_image)
    app.router.add_post("/api/generate_video", api_generate_video)
    app.router.add_post("/api/generate_voice", api_generate_voice)
    app.router.add_post("/api/generate_code", api_generate_code)
    app.router.add_post("/api/search", api_search)

    # 提示词管理（新版，PromptPanel 使用）
    app.router.add_get("/api/prompts", api_prompts_get)
    app.router.add_post("/api/prompts/save", api_prompts_save)
    app.router.add_post("/api/prompts/delete", api_prompts_delete)

    # 提示词管理（旧版，SetupGuide 使用）
    app.router.add_get("/api/desktop/prompts", api_desktop_prompts_get)
    app.router.add_post("/api/desktop/prompts", api_desktop_prompts_set)
    app.router.add_post("/api/desktop/prompts/reset", api_desktop_prompts_reset)

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
