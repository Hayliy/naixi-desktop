"""桌面端工具系统 — 工具注册表 + 执行器"""
import asyncio, json, logging, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse
from datetime import datetime

log = logging.getLogger("tools")

# 工作区根目录
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ── 工具注册表 ──
_registry = {}

def register(name, description, parameters, handler):
    _registry[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
    }

def load_plugins():
    """从插件目录加载外部工具"""
    try:
        from desktop_core.plugin_mgr import get_plugin_tools
        existing = get_definitions()
        plugin_tools = get_plugin_tools(existing)
        for pt in plugin_tools:
            fn = pt.get("function", {})
            name = fn.get("name", "")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
            if name and name not in _registry:
                # 注册一个动态执行的 handler，从 plugin_mgr 调用
                register(name, desc, params, _make_plugin_handler(name))
                log.info(f"[工具] 插件注册: {name}")
    except Exception as e:
        log.warning(f"[工具] 插件加载失败: {e}")

def _make_plugin_handler(tool_name):
    """为插件工具生成一个异步 handler"""
    async def handler(args, ctx):
        try:
            # 在 plugin_mgr 中查找对应的执行器
            from desktop_core.plugin_mgr import execute_plugin_tool
            return await execute_plugin_tool(tool_name, args)
        except Exception as e:
            return f"插件工具 {tool_name} 执行失败: {str(e)[:200]}"
    return handler

def get_definitions():
    """返回 OpenAI 兼容的工具定义列表"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in _registry.values()
    ]

async def execute(name, args, context=None):
    """执行工具，返回结果文本"""
    tool = _registry.get(name)
    if not tool:
        return f"未知工具: {name}"
    try:
        result = await tool["handler"](args, context or {})
        return str(result)[:5000]
    except Exception as e:
        log.warning(f"[工具] {name} 执行失败: {e}")
        return f"工具 {name} 执行出错: {str(e)[:200]}"

# ── 工具实现 ──

async def _search_web(args, ctx):
    query = args.get("query", args.get("q", ""))
    if not query:
        return "缺少搜索关键词"
    import aiohttp
    async with aiohttp.ClientSession() as s:
        for port in [8899, 8898]:
            try:
                params = {"q": query, "format": "json", "language": "zh-CN"}
                async with s.get(f"http://127.0.0.1:{port}/search", params=params, timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        results = data.get("results", [])[:5]
                        if results:
                            lines = [f"- {item.get('title', '')}: {item.get('content', '')[:100]}" for item in results]
                            return "\n".join(lines)
            except:
                pass
        try:
            bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
            h = {"User-Agent": "Mozilla/5.0"}
            async with s.get(bing_url, headers=h, timeout=8) as r:
                if r.status == 200:
                    html = await r.text()
                    items = re.findall(r'<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
                    lines = [f"- {re.sub(r'<[^>]+>', '', t)}: {u}" for u, t in items[:5]]
                    return "\n".join(lines) if lines else "未找到搜索结果"
        except:
            pass
    return "搜索服务暂不可用"

async def _web_extractor(args, ctx):
    url = args.get("url", "")
    if not url:
        return "缺少 URL"
    import aiohttp
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(url, headers=headers, timeout=15, allow_redirects=True) as r:
                if r.status != 200:
                    return f"抓取失败: HTTP {r.status}"
                html = await r.text()
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:3000] if text else "页面无内容"
        except Exception as e:
            return f"抓取失败: {str(e)[:100]}"

async def _image_search(args, ctx):
    query = args.get("query", "")
    if not query:
        return "缺少搜索关键词"
    import aiohttp
    try:
        bing_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as s:
            async with s.get(bing_url, headers=headers, timeout=8) as r:
                if r.status == 200:
                    html = await r.text()
                    urls = re.findall(r'<img[^>]*src="(https?://[^"]*)"[^>]*alt="([^"]*)"', html)
                    lines = [f"- {alt}: {u}" for u, alt in urls[:8]]
                    return "\n".join(lines) if lines else "未找到图片"
                return f"搜索失败: HTTP {r.status}"
    except Exception as e:
        return f"搜索失败: {str(e)[:100]}"

async def _current_datetime(args, ctx):
    now = datetime.now()
    weekdays = ['一', '二', '三', '四', '五', '六', '日']
    return f"当前时间：{now.year}年{now.month}月{now.day}日 星期{weekdays[now.weekday()]} {now.strftime('%H:%M:%S')}"

async def _calculate(args, ctx):
    expr = args.get("expression", "")
    if not expr:
        return "缺少表达式"
    safe = re.sub(r'[\d\s+\-*/().,%]', '', expr)
    if safe:
        return f"表达式包含非法字符: {safe}"
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return f"{expr} = {result}"
    except Exception as e:
        return f"计算失败: {str(e)[:100]}"

async def _generate_image(args, ctx):
    prompt = args.get("prompt", "")
    if not prompt:
        return "缺少提示词"
    provider = ctx.get("image_provider")
    if not provider:
        return "未配置画图模型供应商，请在设置中添加类型为「画图」的供应商"
    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")
    # 解密 Key
    from desktop_core.storage import decrypt_api_key
    decrypted = decrypt_api_key(api_key)
    if decrypted:
        api_key = decrypted
    import aiohttp
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # 判断是否百炼 DashScope
    if "dashscope" in api_url.lower():
        wanx_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        payload = {"model": model or "wanx2.1-t2i-turbo", "input": {"prompt": prompt}, "parameters": {"size": "1024*1024", "n": 1}}
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(wanx_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    return f"画图失败: HTTP {r.status}"
                result = await r.json()
                task_id = result.get("output", {}).get("task_id", "")
                if not task_id:
                    return f"画图返回异常: {str(result)[:200]}"
                for _ in range(30):
                    await asyncio.sleep(4)
                    async with s.get(f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}", headers=headers, timeout=15) as qr:
                        if qr.status == 200:
                            qd = await qr.json()
                            status = qd.get("output", {}).get("task_status", "")
                            if status == "SUCCEEDED":
                                url = qd.get("output", {}).get("results", [{}])[0].get("url", "")
                                if url:
                                    return f"图片已生成: {url}"
                            elif status in ("FAILED", "CANCELED"):
                                return f"画图失败: {qd.get('output', {}).get('message', '任务失败')}"
                return "画图超时"
    # OpenAI 兼容格式
    payload = {"model": model or "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"}
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as r:
            if r.status != 200:
                err = await r.text()
                return f"画图失败: {err[:200]}"
            result = await r.json()
            if "data" in result and result["data"]:
                return f"图片已生成: {result['data'][0].get('url', '')}"
            return f"画图返回异常: {str(result)[:200]}"

async def _code_interpreter(args, ctx):
    code = args.get("code", "")
    if not code:
        return "缺少代码"
    from desktop_core.sandbox import Sandbox
    sbox = Sandbox()
    return await sbox.run_python(code)

async def _read_file(args, ctx):
    path = args.get("path", "")
    full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not full.startswith(WORKSPACE_DIR):
        return "不允许访问工作区外的文件"
    if not os.path.exists(full):
        return f"文件不存在: {path}"
    try:
        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
        return content[:3000]
    except Exception as e:
        return f"读取失败: {str(e)[:100]}"

async def _write_file(args, ctx):
    path = args.get("path", "")
    content = args.get("content", "")
    full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not full.startswith(WORKSPACE_DIR):
        return "不允许访问工作区外的文件"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        return f"写入失败: {str(e)[:100]}"

async def _list_files(args, ctx):
    path = args.get("path", "")
    full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not full.startswith(WORKSPACE_DIR):
        return "不允许访问工作区外的文件"
    if not os.path.isdir(full):
        return f"目录不存在: {path or '/'}"
    try:
        items = os.listdir(full)
        lines = []
        for item in sorted(items):
            item_path = os.path.join(full, item)
            if os.path.isdir(item_path):
                lines.append(f"📁 {item}/")
            else:
                size = os.path.getsize(item_path)
                lines.append(f"📄 {item} ({size} bytes)")
        return "\n".join(lines) if lines else "(空目录)"
    except Exception as e:
        return f"列出失败: {str(e)[:100]}"

async def _get_weather(args, ctx):
    city = args.get("city", "")
    if not city:
        return "缺少城市名"
    import aiohttp
    query = f"{city} 天气"
    try:
        bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
        h = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as s:
            async with s.get(bing_url, headers=h, timeout=8) as r:
                if r.status == 200:
                    html = await r.text()
                    snippets = re.findall(r'<p[^>]*class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
                    lines = [re.sub(r'<[^>]+>', '', snip).strip() for snip in snippets if snip.strip()]
                    return "\n".join(lines[:3]) if lines else f"未找到{city}天气信息"
                return f"查询失败: HTTP {r.status}"
    except Exception as e:
        return f"查询天气失败: {str(e)[:100]}"

async def _search_knowledge(args, ctx):
    query = args.get("query", "")
    if not query:
        return "缺少搜索关键词"
    from desktop_core.storage import meta_get
    raw = meta_get("knowledge_base")
    if not raw:
        return "知识库为空"
    try:
        kb = json.loads(raw)
        results = []
        query_lower = query.lower()
        for item in kb:
            title = item.get("title", "")
            content = item.get("content", "")
            if query_lower in title.lower() or query_lower in content.lower():
                results.append(f"- {title}: {content[:200]}")
        return "\n".join(results[:5]) if results else "未找到匹配的知识"
    except:
        return "知识库读取失败"

# ── 新增工具：图片分析 ──

async def _analyze_image(args, ctx):
    """调用视觉模型分析图片"""
    image_url = args.get("url", "")
    question = args.get("question", "请描述这张图片")
    if not image_url:
        return "缺少图片 URL"
    provider = ctx.get("vision_provider")
    if not provider:
        provider = ctx.get("chat_provider")
    if not provider:
        return "未配置视觉模型供应商"
    import aiohttp
    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "qwen-vl-plus")
    from desktop_core.storage import decrypt_api_key
    decrypted = decrypt_api_key(api_key)
    if decrypted: api_key = decrypted
    chat_url = api_url.rstrip("/chat/completions") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}, {"type": "text", "text": question}]}],
        "max_tokens": 1024,
    }
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.post(chat_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as r:
            if r.status != 200:
                err = await r.text()
                return f"图片分析失败: {err[:200]}"
            result = await r.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content or "未获取到分析结果"

# ── 新增工具：翻译 ──

async def _translate_text(args, ctx):
    text = args.get("text", "")
    target = args.get("target", "中文")
    if not text:
        return "缺少要翻译的文本"
    provider = ctx.get("chat_provider")
    if not provider:
        return "未配置对话模型供应商"
    import aiohttp
    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")
    from desktop_core.storage import decrypt_api_key
    decrypted = decrypt_api_key(api_key)
    if decrypted: api_key = decrypted
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    prompt = f"请将以下文本翻译成{target}，只返回翻译结果，不要多余解释：\n\n{text}"
    payload = {"model": model or "default", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2048}
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                return f"翻译失败: HTTP {r.status}"
            result = await r.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "") or "翻译失败"

# ── 新增工具：文档读取 ──

async def _read_document(args, ctx):
    filepath = args.get("path", "")
    if not filepath:
        return "缺少文件路径"
    full = os.path.normpath(os.path.join(WORKSPACE_DIR, filepath))
    if not full.startswith(WORKSPACE_DIR):
        return "不允许访问工作区外的文件"
    if not os.path.exists(full):
        return f"文件不存在: {filepath}"
    ext = os.path.splitext(full)[1].lower()
    try:
        if ext == ".pdf":
            try:
                import pdfminer.high_level
                text = pdfminer.high_level.extract_text(full)
                return text[:5000] if text.strip() else "（PDF 无提取到文本）"
            except ImportError:
                return "需要安装 pdfminer.six 库以支持 PDF 解析"
        elif ext in (".docx", ".doc"):
            try:
                import docx
                doc = docx.Document(full)
                text = "\n".join(p.text for p in doc.paragraphs)
                return text[:5000] if text.strip() else "（文档无内容）"
            except ImportError:
                return "需要安装 python-docx 库以支持 Word 解析"
        elif ext in (".csv", ".tsv"):
            try:
                import csv, io
                with open(full, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                if not rows:
                    return "（CSV 无数据）"
                header = ", ".join(rows[0].keys())
                preview = "\n".join(", ".join(r.values()) for r in rows[:20])
                return f"列: {header}\n共 {len(rows)} 行\n数据预览:\n{preview}"[:5000]
            except Exception as e:
                return f"CSV 解析失败: {str(e)[:100]}"
        else:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:5000]
    except Exception as e:
        return f"读取失败: {str(e)[:100]}"

# ── 注册所有工具 ──

register("search_web", "搜索网络获取实时信息，如新闻、天气、百科知识等",
    {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]},
    _search_web)

register("web_extractor", "抓取指定网页的内容，返回纯文本。适合阅读新闻、文章、文档等在线内容",
    {"type": "object", "properties": {"url": {"type": "string", "description": "网页完整 URL"}}, "required": ["url"]},
    _web_extractor)

register("image_search", "搜索图片，返回图片URL列表",
    {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]},
    _image_search)

register("current_datetime", "获取当前的日期和时间",
    {"type": "object", "properties": {}},
    _current_datetime)

register("calculate", "执行数学计算，支持 + - * / 和括号",
    {"type": "object", "properties": {"expression": {"type": "string", "description": "数学表达式，如 (12 + 34) * 5"}}, "required": ["expression"]},
    _calculate)

register("generate_image", "根据文字描述生成图片",
    {"type": "object", "properties": {"prompt": {"type": "string", "description": "对图片的详细描述"}}, "required": ["prompt"]},
    _generate_image)

register("code_interpreter", "运行 Python 代码并返回执行结果。适合数据处理、计算、可视化、文件格式转换等任务",
    {"type": "object", "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}}, "required": ["code"]},
    _code_interpreter)

register("read_file", "读取工作区中的文件内容，支持 txt/json/csv/python 等文本格式",
    {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径（相对于工作区目录）"}}, "required": ["path"]},
    _read_file)

register("write_file", "将内容写入工作区中的文件。注意：会覆盖已有文件",
    {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径（相对于工作区目录）"}, "content": {"type": "string", "description": "文件内容"}}, "required": ["path", "content"]},
    _write_file)

register("list_files", "列出工作区中指定目录内的文件和文件夹",
    {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径，默认根目录"}}, "required": []},
    _list_files)

register("get_weather", "查询某个城市的天气信息",
    {"type": "object", "properties": {"city": {"type": "string", "description": "城市名称"}}, "required": ["city"]},
    _get_weather)

register("search_knowledge", "在本地知识库中搜索信息",
    {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]},
    _search_knowledge)

register("analyze_image", "分析图片内容，识别图片中的物体、场景、文字等信息。需要先获取图片 URL",
    {"type": "object", "properties": {"url": {"type": "string", "description": "图片 URL"}, "question": {"type": "string", "description": "对图片的问题，如「图中有什么？」"}}, "required": ["url"]},
    _analyze_image)

register("translate_text", "将文本翻译成指定语言",
    {"type": "object", "properties": {"text": {"type": "string", "description": "要翻译的原文"}, "target": {"type": "string", "description": "目标语言，如「中文」「英文」「日语」"}}, "required": ["text"]},
    _translate_text)

register("read_document", "读取工作区中的文档文件，支持 PDF、Word(.docx)、CSV 等格式",
    {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径（相对于工作区目录）"}}, "required": ["path"]},
    _read_document)

# 加载外部插件
load_plugins()
