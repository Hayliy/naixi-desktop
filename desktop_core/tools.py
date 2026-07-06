"""桌面端工具系统 — 工具注册表 + 执行器"""
import asyncio, json, logging, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse
from datetime import datetime

log = logging.getLogger("tools")

# 工作区根目录
WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

# ── 工具注册表 ──
_registry = {}

def register(name, description, parameters, handler, category="core"):
    _registry[name] = {
        "name": name,
        "description": description,
        "parameters": parameters,
        "handler": handler,
        "category": category,
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

def load_mcp_tools(mcp_mgr):
    """从 MCP 管理器加载 MCP 工具到注册表"""
    if not mcp_mgr:
        return
    mcp_tools = mcp_mgr.get_all_tool_definitions()
    for mt in mcp_tools:
        fn = mt.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        if name and name not in _registry:
            register(name, desc, params, _make_mcp_handler(name, mcp_mgr))
            log.info(f"[工具] MCP 注册: {name}")

def _make_mcp_handler(tool_name, mcp_mgr):
    """为 MCP 工具生成 handler"""
    async def handler(args, ctx):
        try:
            return await mcp_mgr.execute_tool(tool_name, args)
        except Exception as e:
            return f"MCP 工具 {tool_name} 执行失败: {str(e)[:200]}"
    return handler

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

def get_definitions(category=None):
    """返回 OpenAI 兼容的工具定义列表
    category=None 返回全部, core/extra/system 返回对应类别的子集"""
    tools = _registry.values()
    if category:
        tools = [t for t in tools if t.get("category") == category]
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in tools
    ]

def get_fast_definitions():
    """返回常用工具子集（约 20 个）+ 已连接的 MCP 工具 + 动态发现的工具，避免首轮 token 爆炸"""
    fast_tools = {"search_web", "current_datetime", "calculate", "get_weather",
                   "bash", "find_files", "open_url", "generate_image",
                   "git", "web_fetch", "clipboard", "mkdir",
                   "visualize", "read_image", "read_file", "write_file",
                   "screenshot", "get_system_info", "list_files", "grep_search",
                   "search_tools"}
    result = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in _registry.values() if t["name"] in fast_tools
    ]
    # 额外包含已连接的 MCP 工具
    try:
        mgr = get_mcp_manager()
        if mgr:
            for srv_name, srv in mgr._servers.items():
                if srv.is_connected:
                    result.extend(srv.get_tool_definitions())
    except Exception:
        pass
    # 额外包含通过 search_tools 发现的 MCP 工具
    result.extend(get_discovered_definitions())
    return result

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
    offset_l = args.get("offset", 0)
    limit_l = args.get("limit", 0)
    show_lines = args.get("lines", False)
    if not path:
        return "缺少文件路径"
    if os.path.isabs(path):
        full = os.path.normpath(path)
    else:
        full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not os.path.exists(full):
        return f"文件不存在: {path}"
    if not os.path.isfile(full):
        return f"不是文件: {path}"
    try:
        # 尝试 UTF-8，失败则自动检测编码
        import codecs
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1", "shift_jis", "euc-kr"]
        content = None
        for enc in encodings:
            try:
                with codecs.open(full, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if content is None:
            return f"无法解码文件（尝试了 {len(encodings)} 种编码）"
        
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        
        if show_lines:
            # 行号模式
            start = int(offset_l) if offset_l else 0
            end = int(limit_l) if limit_l else min(total_lines, 50)
            result = "".join(f"{i+1:>6} {l}" for i, l in enumerate(lines[start:end], start))
            return f"文件: {path} ({total_lines} 行, 显示 {start+1}-{min(end, total_lines)})\n{result}"[:8000]
        
        if limit_l:
            start = int(offset_l) if offset_l else 0
            end = start + int(limit_l)
            return "".join(lines[start:end])[:8000] if start < total_lines else "（已到文件末尾）"
        
        result = content[:8000]
        if len(content) > 8000:
            result += f"\n\n...（文件共 {len(content)} 字符，只显示前 8000 字符）"
        return result
    except Exception as e:
        return f"读取失败: {str(e)[:100]}"

async def _write_file(args, ctx):
    path = args.get("path", "")
    content = args.get("content", "")
    # 绝对路径直接写，相对路径用工作区
    if os.path.isabs(path):
        full = os.path.normpath(path)
    else:
        full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {path} ({len(content)} 字符)"
    except Exception as e:
        return f"写入失败: {str(e)[:100]}"

async def _list_files(args, ctx):
    path = args.get("path", "")
    # 绝对路径直接列，相对路径用工作区
    target = os.path.normpath(path) if os.path.isabs(path) else os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not os.path.isdir(target):
        return f"目录不存在: {path or '/'}"
    try:
        items = os.listdir(target)
        lines = []
        for item in sorted(items):
            item_path = os.path.join(target, item)
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

# ── 开发工具：运行命令 ──

async def _run_command(args, ctx):
    """运行系统命令（通用入口，替代旧的 run_command + run_local_command）"""
    command = args.get("command", "")
    cwd = args.get("cwd", None)
    if not command:
        return "缺少要执行的命令"
    # 安全检查
    dangerous = ["rm -rf /", "format", "shutdown", "reboot", "init 0", "mkfs", "dd if=", ":(){ :|:& };:"]
    for d in dangerous:
        if d in command.lower():
            return f"❌ 禁止执行危险命令"
    try:
        # ── 启动 .exe 程序：避免弹终端窗口 ──
        cmd_stripped = command.strip().strip("\"")
        exe_to_launch = None
        if cmd_stripped.lower().startswith("start "):
            exe_to_launch = cmd_stripped[6:].strip().strip("\"")
        elif cmd_stripped.lower().endswith(".exe") and os.path.isfile(cmd_stripped):
            exe_to_launch = cmd_stripped
        if exe_to_launch and os.path.isfile(exe_to_launch):
            subprocess.Popen([exe_to_launch], shell=False, close_fds=True)
            return f"✅ 已启动: {os.path.basename(exe_to_launch)}"
        
        # ── 普通命令执行 ──
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd or os.path.expanduser("~"),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            return f"⏱ 命令执行超时（60秒）"
        out = (stdout or b"").decode("utf-8", errors="replace")[:5000]
        err = (stderr or b"").decode("utf-8", errors="replace")[:500]
        if err:
            out += f"\n--- stderr ---\n{err}"
        return out or "（执行完毕，无输出）"
    except Exception as e:
        return f"❌ 执行失败: {str(e)[:200]}"

# ── 开发工具：内容搜索 ──

async def _grep_search(args, ctx):
    pattern = args.get("pattern", "")
    path = args.get("path", "")
    if not pattern:
        return "缺少搜索模式"
    # 绝对路径直接搜，相对路径用工作区
    if path and os.path.isabs(path):
        search_dir = os.path.normpath(path)
    elif path:
        search_dir = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    else:
        search_dir = WORKSPACE_DIR
    if not os.path.isdir(search_dir):
        return f"目录不存在: {path or '/'}"
    try:
        matches = []
        for root, dirs, files in os.walk(search_dir):
            # 跳过 node_modules/.git/__pycache__/target/.workbuddy 等
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__", "target", ".workbuddy", "dist", ".venv")]
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if pattern.lower() in line.lower():
                                rel = os.path.relpath(fpath, search_dir)
                                matches.append(f"{rel}:{i}: {line.strip()[:120]}")
                                if len(matches) >= 30:
                                    break
                    if len(matches) >= 30:
                        break
                except: pass
            if len(matches) >= 30:
                break
        if matches:
            return f"找到 {len(matches)} 处匹配:\n" + "\n".join(matches)
        return "未找到匹配"
    except Exception as e:
        return f"搜索失败: {str(e)[:100]}"

# ── 开发工具：精确编辑文件（search-and-replace） ──

async def _edit_file(args, ctx):
    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    use_regex = args.get("regex", False)
    replace_all = args.get("replace_all", False)
    if not path or not old_string:
        return "缺少文件路径或要替换的内容"
    if os.path.isabs(path):
        full = os.path.normpath(path)
    else:
        full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not os.path.exists(full):
        return f"文件不存在: {path}"
    try:
        with open(full, "r", encoding="utf-8") as f:
            content = f.read()
        
        if use_regex:
            import re
            new_content, count = re.subn(old_string, new_string, content, flags=re.DOTALL)
        else:
            count = content.count(old_string)
            if count == 0:
                return f"未找到要替换的内容: {old_string[:60]}"
            if count > 1 and not replace_all:
                return f"找到 {count} 处匹配。设置 replace_all=true 可全部替换，或提供更精确的上下文"
            new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
            count = new_content.count(new_string) - content.count(new_string) + count if not replace_all else content.count(old_string)
        
        with open(full, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"已修改 {path}: 替换 {count} 处"
    except Exception as e:
        return f"编辑失败: {str(e)[:100]}"

async def _search_knowledge(args, ctx):
    query = args.get("query", "")
    if not query:
        return "缺少搜索关键词"
    from desktop_core.storage import meta_get
    try:
        raw = meta_get("knowledge_base")
    except Exception:
        return "知识库不可用（数据库未初始化）"
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

register("read_file", "读取文件内容。自动检测编码（UTF-8/GBK/GB2312等）。支持行号显示和分页。支持绝对路径",
    {"type": "object", "properties": {
        "path": {"type": "string", "description": "文件路径（绝对路径或工作区相对路径）"},
        "lines": {"type": "boolean", "description": "是否显示行号（默认 false）"},
        "offset": {"type": "integer", "description": "起始行号（从 0 开始，配合 limit 使用）"},
        "limit": {"type": "integer", "description": "最大行数/字符数"},
    }, "required": ["path"]},
    _read_file)

register("write_file", "将内容写入文件。支持绝对路径或工作区相对路径。注意：会覆盖已有文件",
    {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径（相对于工作区目录）"}, "content": {"type": "string", "description": "文件内容"}}, "required": ["path", "content"]},
    _write_file)

register("list_files", "列出目录中的文件和文件夹。支持绝对路径或工作区相对路径",
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

# ── 系统交互工具 ──

async def _get_system_info(args, ctx):
    from desktop_core.sandbox import Sandbox
    sbox = Sandbox()
    return await sbox.get_system_info()

async def _open_url(args, ctx):
    url = args.get("url", "")
    if not url: return "缺少 URL"
    from desktop_core.sandbox import Sandbox
    sbox = Sandbox()
    return await sbox.open_url(url)

# ── 注册系统工具 ──

register("get_system_info", "获取电脑系统信息，包括操作系统、CPU、内存使用情况等",
    {"type": "object", "properties": {}},
    _get_system_info)

register("open_url", "在默认浏览器中打开指定网址",
    {"type": "object", "properties": {"url": {"type": "string", "description": "要打开的完整 URL"}}, "required": ["url"]},
    _open_url)

# ── 文件搜索工具 ──

async def _find_files(args, ctx):
    """在电脑上搜索程序或文件。先找可执行程序，再找其他文件"""
    import subprocess
    name = args.get("name", "")
    if not name: return "缺少文件名"
    name_lower = name.lower()
    
    # 已知程序快速映射
    known_apps = {
        "记事本": "notepad.exe", "计算器": "calc.exe", "画图": "mspaint.exe",
        "cmd": "cmd.exe", "命令提示符": "cmd.exe", "powershell": "powershell.exe",
        "chrome": "chrome.exe", "edge": "msedge.exe", "浏览器": "msedge.exe",
        "任务管理器": "taskmgr.exe", "资源管理器": "explorer.exe",
        "控制面板": "control.exe", "注册表": "regedit.exe",
    }
    if name_lower in known_apps or name in known_apps:
        target = known_apps.get(name_lower) or known_apps.get(name, "")
        if target:
            try:
                proc = await asyncio.create_subprocess_exec("where", target, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                path = stdout.decode("utf-8", errors="replace").strip().split("\n")[0]
                if path:
                    return f"找到以下程序:\n{path}"
            except: pass
    
    exe_results = []  # .exe / 启动程序
    other_results = []  # 其他文件
    
    # 跳过这些缓存/临时目录
    skip_dirs = {"cache", "Cache", "caches", "Caches", "temp", "Temp", "tmp", "Tmp",
                 "node_modules", ".git", "__pycache__", "venv", ".venv",
                 "Media Cache Files", "Code Cache", "GPUCache", "Service Worker",
                 "Adobe", "AdobeGC", "adobe"}
    
    # ── 1. Windows 注册表搜索已安装程序（最高优先级） ──
    try:
        import winreg
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        ]
        for hkey, subkey in reg_paths:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    i = 0
                    while True:
                        try:
                            app_key_name = winreg.EnumKey(key, i)
                            i += 1
                        except OSError:
                            break
                        if name_lower in app_key_name.lower() or name_lower in app_key_name.lower().replace(".exe", ""):
                            try:
                                with winreg.OpenKey(key, app_key_name) as app_key:
                                    for vn in ["", "DisplayIcon", "InstallLocation", "DisplayName"]:
                                        try:
                                            val = winreg.QueryValueEx(app_key, vn)[0]
                                        except OSError:
                                            continue
                                        if val and os.path.isfile(val) and val.lower().endswith(".exe"):
                                            exe_results.append(val)
                                            break
                            except OSError:
                                continue
            except OSError:
                continue
    except ImportError:
        pass
    
    # ── 2. 常见安装目录搜索可执行程序 ──
    search_paths = [
        "D:\\Program Files", "D:\\Program Files (x86)",
        "D:\\Games", "D:\\游戏",
        "C:\\Program Files", "C:\\Program Files (x86)",
        "D:\\软件", "D:\\应用", "D:\\Apps",
        os.path.expanduser("~\\AppData\\Local"),
        os.path.expanduser("~\\AppData\\Roaming"),
    ]
    
    # 第一遍：深度2层内找 .exe 和目录名匹配
    for root in search_paths:
        if not os.path.isdir(root): continue
        try:
            for entry in os.listdir(root):
                if entry in skip_dirs: continue
                if name_lower in entry.lower():
                    full = os.path.join(root, entry)
                    if os.path.isdir(full):
                        # 目录匹配：找里面的 .exe
                        try:
                            for f in os.listdir(full):
                                if f.lower().endswith(".exe") and "uninstall" not in f.lower():
                                    exe_results.append(os.path.join(full, f))
                                    break
                        except: pass
                    elif full.lower().endswith(".exe"):
                        exe_results.append(full)
        except: pass
    
    # 第二遍：深度3层内搜 .exe（仅在 Games/Program Files 等目录）
    for root in search_paths:
        if not os.path.isdir(root): continue
        try:
            for dirpath, dirs, files in os.walk(root):
                dname = os.path.basename(dirpath)
                if dname in skip_dirs:
                    dirs.clear(); continue
                depth = dirpath.replace(root, "").count(os.sep)
                if depth >= 3:
                    dirs.clear(); continue
                # 只看目录名匹配的
                if name_lower in dname.lower():
                    for f in files:
                        if f.lower().endswith(".exe") and "uninstall" not in f.lower():
                            exe_results.append(os.path.join(dirpath, f))
        except: pass
    
    # ── 3. 开始菜单搜索快捷方式 ──
    start_menu = os.path.expanduser("~\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs")
    if os.path.isdir(start_menu):
        try:
            for root, dirs, files in os.walk(start_menu):
                for f in files:
                    if f.endswith(".lnk") and name_lower in f.lower():
                        exe_results.append(f"[快捷方式] {f.replace('.lnk','')}")
                        if len(exe_results) >= 8: break
                if len(exe_results) >= 8: break
        except: pass
    
    # ── 4. 桌面/下载目录搜文件（仅当没找到可执行程序时） ──
    if not exe_results:
        doc_dirs = [os.path.expanduser("~\\Desktop"), os.path.expanduser("~\\Downloads")]
        for root in doc_dirs:
            if not os.path.isdir(root): continue
            try:
                for f in os.listdir(root):
                    if name_lower in f.lower():
                        other_results.append(os.path.join(root, f))
            except: pass
    
    # ── 组装结果 ──
    if exe_results:
        # 去重（标准化路径）
        seen = set()
        unique = []
        for r in exe_results:
            norm = os.path.normpath(r.strip().lower())
            if norm not in seen: seen.add(norm); unique.append(r.strip())
        return "找到以下程序:\n" + "\n".join(unique[:8])
    if other_results:
        return "找到以下文件:\n" + "\n".join(other_results[:8])
    # ── 5. 中文名搜不到时自动试英文名 ──
    lang_map = {"鸣潮": ["Wuthering", "Wuthering Waves"],
                "微信": ["WeChat"],
                "浏览器": ["chrome", "msedge", "firefox"],
                "qq": ["QQ", "WeCom"]}
    for cn, ens in lang_map.items():
        if name_lower == cn or cn in name_lower:
            for en in ens:
                for root in ["D:\\Program Files", "D:\\软件", "D:\\Games",
                             "C:\\Program Files", "C:\\Program Files (x86)"]:
                    if not os.path.isdir(root): continue
                    try:
                        for entry in os.listdir(root):
                            if en.lower() in entry.lower():
                                full = os.path.join(root, entry)
                                if os.path.isdir(full):
                                    for f in os.listdir(full):
                                        if f.lower().endswith(".exe") and "uninstall" not in f.lower():
                                            exe_results.append(os.path.join(full, f))
                                            break
                    except: pass
            if exe_results:
                return "找到以下程序:\n" + "\n".join(exe_results[:8])
            break
    return f"未找到与「{name}」相关的程序或文件"

register("find_files", "在电脑上搜索程序或文件。自动搜索注册表、常见安装目录、开始菜单。先找可执行程序，再找其他文件。中文名搜不到时自动试英文名",
    {"type": "object", "properties": {"name": {"type": "string", "description": "文件名关键词，如「鸣潮」「Wuthering」"}}, "required": ["name"]},
    _find_files)

# ── 截图工具 ──

async def _screenshot(args, ctx):
    """截图并保存到工作区，返回图片路径"""
    try:
        from PIL import ImageGrab
        import os, time
        img = ImageGrab.grab()
        from desktop_core.tools import WORKSPACE_DIR
        fname = f"screenshot_{int(time.time())}.png"
        fpath = os.path.join(WORKSPACE_DIR, fname)
        img.save(fpath)
        return f"截图已保存: {fname} ({img.size[0]}x{img.size[1]}, {os.path.getsize(fpath)} bytes)"
    except Exception as e:
        return f"截图失败: {str(e)[:100]}"

# ── 进程管理工具 ──

async def _list_processes(args, ctx):
    """列出系统进程"""
    from desktop_core.sandbox import Sandbox
    sbox = Sandbox()
    return await sbox.run_system_command("tasklist /NH /FO CSV")

async def _kill_process(args, ctx):
    """终止进程"""
    pid = args.get("pid", "")
    name = args.get("name", "")
    if not pid and not name:
        return "请提供 pid 或 name"
    from desktop_core.sandbox import Sandbox
    sbox = Sandbox()
    if pid:
        return await sbox.run_system_command(f"taskkill /PID {pid} /F")
    else:
        # 安全检查：禁止杀掉关键系统进程
        dangerous = ["svchost", "winlogon", "csrss", "services", "lsass", "system", "smss"]
        for d in dangerous:
            if d.lower() in name.lower():
                return f"❌ 禁止终止系统关键进程: {name}"
        return await sbox.run_system_command(f"taskkill /IM {name} /F")

register("screenshot", "截取当前屏幕的截图，保存到工作区。适合查看用户界面、获取信息等",
    {"type": "object", "properties": {}},
    _screenshot)

register("list_processes", "列出当前系统正在运行的进程列表",
    {"type": "object", "properties": {}},
    _list_processes)

register("kill_process", "终止指定进程。通过 pid（进程ID）或 name（进程名，如 notepad.exe）",
    {"type": "object", "properties": {"pid": {"type": "string", "description": "进程 ID（可选）"}, "name": {"type": "string", "description": "进程名（可选，如 notepad.exe）"}}, "required": []},
    _kill_process)

register("bash", "在电脑上执行命令。适合启动程序、运行脚本、查看目录、安装依赖、执行构建等。注意：禁止 rm -rf /、shutdown 等危险命令",
    {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的命令"}, "cwd": {"type": "string", "description": "工作目录（可选）"}}, "required": ["command"]},
    _run_command)

register("grep_search", "在文件中搜索关键词或模式，支持正则。支持绝对路径或工作区相对路径。适合查找代码中的函数定义、变量引用、错误信息等",
    {"type": "object", "properties": {"pattern": {"type": "string", "description": "搜索关键词或模式"}, "path": {"type": "string", "description": "搜索的子目录（可选，默认全局搜索）"}}, "required": ["pattern"]},
    _grep_search)

register("edit_file", "精确编辑文件内容。用 old_string 定位要修改的位置，替换为 new_string。支持正则模式和全部替换。支持绝对路径",
    {"type": "object", "properties": {
        "path": {"type": "string", "description": "文件路径（绝对路径或工作区相对路径）"},
        "old_string": {"type": "string", "description": "要替换的原文（或正则模式）"},
        "new_string": {"type": "string", "description": "替换后的新内容"},
        "regex": {"type": "boolean", "description": "是否使用正则匹配（默认 false）"},
        "replace_all": {"type": "boolean", "description": "是否替换所有匹配处（默认 false，只替换第一处）"},
    }, "required": ["path", "old_string", "new_string"]},
    _edit_file)

register("translate_text", "将文本翻译成指定语言",
    {"type": "object", "properties": {"text": {"type": "string", "description": "要翻译的原文"}, "target": {"type": "string", "description": "目标语言，如「中文」「英文」「日语」"}}, "required": ["text"]},
    _translate_text)

register("read_document", "读取工作区中的文档文件，支持 PDF、Word(.docx)、CSV 等格式",
    {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径（相对于工作区目录）"}}, "required": ["path"]},
    _read_document)

# ── Git 工具 ──

async def _git(args, ctx):
    """执行 Git 命令"""
    cmd = args.get("command", "")
    if not cmd: return "请提供 git 命令，如 status/add/commit/log/diff"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *cmd.split(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = (stdout or b"").decode("utf-8", errors="replace")[:5000]
        err = (stderr or b"").decode("utf-8", errors="replace")[:500]
        return (out + "\n--- stderr ---\n" + err if err else out) or "（无输出）"
    except Exception as e:
        return f"Git 执行失败: {str(e)[:200]}"

register("git", "执行 Git 命令。支持 status/add/commit/diff/log/push/pull 等",
    {"type": "object", "properties": {"command": {"type": "string", "description": "Git 子命令，如 status / add -A / commit -m 'msg' / diff"}}, "required": ["command"]},
    _git)

# ── PowerShell 工具 ──

async def _powershell(args, ctx):
    """执行 PowerShell 命令"""
    cmd = args.get("command", "")
    if not cmd: return "缺少要执行的 PowerShell 命令"
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        out = (stdout or b"").decode("utf-8", errors="replace")[:5000]
        err = (stderr or b"").decode("utf-8", errors="replace")[:500]
        return (out + "\n--- stderr ---\n" + err if err else out) or "（执行完毕，无输出）"
    except Exception as e:
        return f"PowerShell 执行失败: {str(e)[:200]}"

register("powershell", "执行 PowerShell 命令。适合 Windows 系统管理、注册表操作、进程管理、文件操作等",
    {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的 PowerShell 命令"}}, "required": ["command"]},
    _powershell)

# ── 包管理工具 ──

async def _pip_install(args, ctx):
    """安装 Python 包"""
    packages = args.get("packages", "")
    if not packages: return "缺少要安装的包名"
    import sys
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", *packages.split(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        out = (stdout or b"").decode("utf-8", errors="replace")[:2000]
        err = (stderr or b"").decode("utf-8", errors="replace")[:1000]
        if "Successfully installed" in out:
            return f"✅ 安装成功: {packages}"
        return (out + "\n--- stderr ---\n" + err if err else out) or "安装完成"
    except Exception as e:
        return f"安装失败: {str(e)[:200]}"

register("pip_install", "安装 Python 包（pip install）。适合安装项目依赖",
    {"type": "object", "properties": {"packages": {"type": "string", "description": "要安装的包名，多个包用空格分隔"}}, "required": ["packages"]},
    _pip_install)

# ── WebFetch 工具 ──

async def _web_fetch(args, ctx):
    """抓取网页内容"""
    url = args.get("url", "")
    if not url: return "缺少 URL"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    import aiohttp
    try:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(url, timeout=15, allow_redirects=True) as r:
                if r.status != 200:
                    return f"抓取失败: HTTP {r.status}"
                html = await r.text()
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:5000] if text else "页面无内容"
    except Exception as e:
        return f"抓取失败: {str(e)[:100]}"

register("web_fetch", "抓取指定网页的文本内容。适合阅读新闻、文章、文档等在线内容。返回纯文本",
    {"type": "object", "properties": {"url": {"type": "string", "description": "网页完整 URL"}}, "required": ["url"]},
    _web_fetch)

# ── Glob 搜索工具 ──

async def _glob_search(args, ctx):
    """按模式匹配文件名"""
    pattern = args.get("pattern", "")
    root = args.get("path", "")
    if not pattern: return "缺少搜索模式（如 **/*.py）"
    import glob
    search_root = os.path.normpath(root) if root and os.path.isabs(root) else WORKSPACE_DIR
    full_pattern = os.path.join(search_root, pattern) if not os.path.isabs(pattern) else pattern
    try:
        matches = glob.glob(full_pattern, recursive=True)
        if not matches:
            return f"未找到匹配 {pattern} 的文件"
        # 只显示路径，不预览内容
        lines = [f"{i+1}. {os.path.relpath(m, search_root) if not root else m}" for i, m in enumerate(matches[:30])]
        return "找到以下文件:\n" + "\n".join(lines)
    except Exception as e:
        return f"搜索失败: {str(e)[:100]}"

register("glob_search", "按文件名模式搜索文件。支持通配符：* 匹配任意字符，** 匹配任意目录。如 **/*.py 或 src/**/*.tsx",
    {"type": "object", "properties": {"pattern": {"type": "string", "description": "文件名模式，如 **/*.py 或 *.json"}, "path": {"type": "string", "description": "搜索根目录（可选，默认工作区）"}}, "required": ["pattern"]},
    _glob_search)

# ── 环境变量工具 ──

async def _env(args, ctx):
    """读取环境变量"""
    name = args.get("name", "")
    if not name: return "请提供环境变量名"
    val = os.environ.get(name, "")
    if val:
        # 对 API Key 脱敏
        safe = val[:8] + "..." if len(val) > 12 and ("KEY" in name.upper() or "TOKEN" in name.upper() or "SECRET" in name.upper()) else val
        return f"{name}={safe}"
    return f"环境变量 {name} 未设置"

register("env", "读取系统环境变量的值。API Key 等敏感变量会自动脱敏",
    {"type": "object", "properties": {"name": {"type": "string", "description": "环境变量名"}}, "required": ["name"]},
    _env)

# ── 剪贴板工具 ──

async def _clipboard(args, ctx):
    """读写系统剪贴板"""
    action = args.get("action", "read")
    text = args.get("text", "")
    try:
        import subprocess
        if action == "write":
            # 用 PowerShell 写入剪贴板
            escaped = text.replace("'", "''")
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-Command", f"Set-Clipboard -Value '{escaped}'",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            await proc.communicate()
            return f"✅ 已写入剪贴板 ({len(text)} 字符)"
        else:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-Command", "Get-Clipboard",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return (stdout or b"").decode("utf-8", errors="replace").strip() or "（剪贴板为空）"
    except Exception as e:
        return f"剪贴板操作失败: {str(e)[:100]}"

register("clipboard", "读取或写入系统剪贴板内容。action=read 读取，action=write 写入",
    {"type": "object", "properties": {
        "action": {"type": "string", "description": "操作类型：read（读取剪贴板）或 write（写入剪贴板）"},
        "text": {"type": "string", "description": "要写入的内容（action=write 时需要）"},
    }, "required": ["action"]},
    _clipboard)

# ── 压缩/解压工具 ──

async def _compress(args, ctx):
    """压缩或解压文件"""
    action = args.get("action", "zip")
    source = args.get("source", "")
    target = args.get("target", "")
    if not source:
        return "缺少源路径"
    import shutil
    try:
        src = os.path.normpath(source) if os.path.isabs(source) else os.path.normpath(os.path.join(WORKSPACE_DIR, source))
        if action == "zip":
            dst = os.path.normpath(target) if target and os.path.isabs(target) else os.path.normpath(os.path.join(WORKSPACE_DIR, target or f"{source}.zip"))
            dst = dst if dst.endswith(".zip") else dst + ".zip"
            shutil.make_archive(dst.replace(".zip", ""), "zip", src)
            return f"✅ 已压缩: {os.path.basename(dst)} ({os.path.getsize(dst)} bytes)"
        elif action == "unzip":
            import zipfile
            dst = os.path.normpath(target) if target and os.path.isabs(target) else os.path.join(os.path.dirname(src), os.path.splitext(os.path.basename(src))[0])
            with zipfile.ZipFile(src, 'r') as zf:
                zf.extractall(dst)
            return f"✅ 已解压到: {dst}"
        return f"未知操作: {action}"
    except Exception as e:
        return f"压缩操作失败: {str(e)[:100]}"

register("compress", "压缩或解压文件。action=zip 压缩，action=unzip 解压",
    {"type": "object", "properties": {
        "action": {"type": "string", "description": "操作：zip（压缩）或 unzip（解压）"},
        "source": {"type": "string", "description": "源路径（文件或目录）"},
        "target": {"type": "string", "description": "目标路径（可选，默认自动生成）"},
    }, "required": ["action", "source"]},
    _compress)

# ── 创建目录工具 ──

async def _mkdir(args, ctx):
    """创建目录"""
    path = args.get("path", "")
    if not path: return "缺少目录路径"
    target = os.path.normpath(path) if os.path.isabs(path) else os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    try:
        os.makedirs(target, exist_ok=True)
        return f"✅ 已创建目录: {path}"
    except Exception as e:
        return f"创建目录失败: {str(e)[:100]}"

register("mkdir", "创建目录。支持绝对路径或工作区相对路径",
    {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径（绝对路径或工作区相对路径）"}}, "required": ["path"]},
    _mkdir)

# ── 批量替换工具 ──

async def _batch_edit(args, ctx):
    """在多个文件中批量替换文本"""
    pattern = args.get("pattern", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    root = args.get("path", "")
    use_regex = args.get("regex", False)
    if not pattern or not old_string:
        return "缺少文件匹配模式或要替换的内容"
    search_dir = os.path.normpath(root) if root and os.path.isabs(root) else WORKSPACE_DIR
    import glob, re
    full_pattern = os.path.join(search_dir, pattern)
    files = glob.glob(full_pattern, recursive=True)
    if not files:
        return f"未找到匹配 {pattern} 的文件"
    modified = 0
    errors = []
    for fpath in files:
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if use_regex:
                new_content, cnt = re.subn(old_string, new_string, content)
            else:
                cnt = content.count(old_string)
                if cnt == 0:
                    continue
                new_content = content.replace(old_string, new_string)
            if new_content != content:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                modified += cnt
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {str(e)[:50]}")
    result = f"✅ 批量替换完成: 修改 {modified} 处，涉及 {len(files)} 个文件"
    if errors:
        result += f"\n⚠ 以下文件出错: {', '.join(errors[:3])}"
    return result

register("batch_edit", "在多个文件中批量搜索替换文本。支持 glob 模式匹配文件（如 **/*.py），支持正则",
    {"type": "object", "properties": {
        "pattern": {"type": "string", "description": "文件匹配模式，如 **/*.py"},
        "old_string": {"type": "string", "description": "要替换的原文（或正则模式）"},
        "new_string": {"type": "string", "description": "替换后的新内容"},
        "path": {"type": "string", "description": "搜索根目录（可选，默认工作区）"},
        "regex": {"type": "boolean", "description": "是否使用正则匹配（默认 false）"},
    }, "required": ["pattern", "old_string", "new_string"]},
    _batch_edit)

# ── 图片读取工具 ──

async def _read_image(args, ctx):
    """读取本地图片文件并用 Vision API 分析内容"""
    path = args.get("path", "")
    question = args.get("question", "请描述这张图片的内容")
    if not path:
        return "缺少图片路径"
    if os.path.isabs(path):
        full = os.path.normpath(path)
    else:
        full = os.path.normpath(os.path.join(WORKSPACE_DIR, path))
    if not os.path.isfile(full):
        return f"文件不存在: {path}"
    # 检查文件格式
    ext = os.path.splitext(full)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
        return f"不支持的图片格式: {ext}（支持 PNG/JPG/GIF/BMP/WEBP）"
    try:
        import base64
        with open(full, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/gif" if ext == ".gif" else "image/webp"
        # 找 vision 供应商
        vision_provider = ctx.get("vision_provider") or ctx.get("chat_provider")
        if not vision_provider:
            return "未配置视觉/对话供应商，无法分析图片"
        p_url = vision_provider.get("api_url", "")
        p_key = vision_provider.get("api_key", "")
        p_model = vision_provider.get("model", "qwen-vl-plus")
        from desktop_core.storage import decrypt_api_key
        dec_key = decrypt_api_key(p_key)
        if dec_key:
            p_key = dec_key
        import aiohttp
        headers = {"Authorization": f"Bearer {p_key}", "Content-Type": "application/json"}
        payload = {
            "model": p_model,
            "messages": [
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                    {"type": "text", "text": question},
                ]}
            ],
            "stream": False,
        }
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.post(p_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status != 200:
                    err = await r.text()
                    return f"Vision API 返回 {r.status}: {err[:200]}"
                result = await r.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content[:2000] if content else "（模型未返回描述）"
    except Exception as e:
        return f"分析图片失败: {str(e)[:100]}"

register("read_image", "读取本地图片文件并用 AI 分析内容。支持 PNG/JPG/GIF/BMP/WEBP 格式。需要配置视觉供应商",
    {"type": "object", "properties": {
        "path": {"type": "string", "description": "图片文件路径（绝对路径或工作区相对路径）"},
        "question": {"type": "string", "description": "对图片的问题，如「图中有什么？」"},
    }, "required": ["path"]},
    _read_image)

# ── 可视化工具 ──

async def _visualize(args, ctx):
    """生成 SVG 图表/流程图"""
    chart_type = args.get("type", "bar")
    title = args.get("title", "")
    data = args.get("data", "")
    labels = args.get("labels", "")
    if not data:
        return "缺少数据"
    try:
        items = [x.strip() for x in data.split(",")]
        lbs = [x.strip() for x in labels.split(",")] if labels else [f"项{i+1}" for i in range(len(items))]
        values = [float(x) for x in items]
        if len(lbs) > len(values):
            lbs = lbs[:len(values)]
        elif len(lbs) < len(values):
            lbs.extend([f"项{i+1}" for i in range(len(lbs), len(values))])
        
        max_val = max(values) if values else 1
        w, h = 680, 400
        bar_w = max(30, min(60, (w - 80) // len(values)))
        
        if chart_type == "bar":
            bars = []
            for i, (lb, v) in enumerate(zip(lbs, values)):
                bh = int((v / max_val) * (h - 120))
                x = 50 + i * (bar_w + 15)
                y = h - 60 - bh
                bars.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" rx="3" fill="url(#grad{i%5})"/>')
                bars.append(f'<text x="{x + bar_w//2}" y="{h - 42}" text-anchor="middle" font-size="11" fill="#888">{lb[:6]}</text>')
                bars.append(f'<text x="{x + bar_w//2}" y="{y - 6}" text-anchor="middle" font-size="10" fill="#666">{v}</text>')
            
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
<defs>
  <linearGradient id="grad0" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f472b6"/><stop offset="100%" stop-color="#ec4899"/></linearGradient>
  <linearGradient id="grad1" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#a78bfa"/><stop offset="100%" stop-color="#8b5cf6"/></linearGradient>
  <linearGradient id="grad2" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#60a5fa"/><stop offset="100%" stop-color="#3b82f6"/></linearGradient>
  <linearGradient id="grad3" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#34d399"/><stop offset="100%" stop-color="#10b981"/></linearGradient>
  <linearGradient id="grad4" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#f59e0b"/></linearGradient>
</defs>
<rect width="{w}" height="{h}" fill="#fefdfb" rx="8"/>
<text x="{w//2}" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#444">{title or "图表"}</text>
{chr(10).join(bars)}
</svg>"""
        elif chart_type == "pie":
            total = sum(values)
            angles = [(v / total) * 360 for v in values]
            cx, cy, r = w//2, h//2, 120
            colors = ["#f472b6", "#a78bfa", "#60a5fa", "#34d399", "#fbbf24", "#fb923c", "#f87171", "#e879f9"]
            sectors = []
            start = 0
            for i, (lb, v, ang) in enumerate(zip(lbs, values, angles)):
                end = start + ang
                rad_s = start * 3.14159 / 180
                rad_e = end * 3.14159 / 180
                x1 = cx + r * __import__("math").cos(rad_s)
                y1 = cy + r * __import__("math").sin(rad_s)
                x2 = cx + r * __import__("math").cos(rad_e)
                y2 = cy + r * __import__("math").sin(rad_e)
                large = 1 if ang > 180 else 0
                d = f"M {cx} {cy} L {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z"
                sectors.append(f'<path d="{d}" fill="{colors[i%len(colors)]}" stroke="white" stroke-width="2"/>')
                # 图例
                lx, ly = 30, 60 + i * 22
                sectors.append(f'<rect x="{lx}" y="{ly}" width="12" height="12" rx="2" fill="{colors[i%len(colors)]}"/>')
                sectors.append(f'<text x="{lx+18}" y="{ly+10}" font-size="11" fill="#666">{lb}</text>')
                start = end
            svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
<rect width="{w}" height="{h}" fill="#fefdfb" rx="8"/>
<text x="{w//2}" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#444">{title or "饼图"}</text>
{chr(10).join(sectors)}
</svg>"""
        else:
            return f"不支持的图表类型: {chart_type}（支持: bar, pie）"
        
        # 保存为文件
        fname = f"chart_{int(time.time())}.svg"
        fpath = os.path.join(WORKSPACE_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(svg)
        return f"✅ 图表已生成: {fname}\n可以发送SVG标记使用:\n```svg\n{svg[:2000]}\n```"
    except Exception as e:
        return f"生成图表失败: {str(e)[:100]}"

register("visualize", "生成数据图表（柱状图/饼图）或流程图。返回 SVG 格式",
    {"type": "object", "properties": {
        "type": {"type": "string", "description": "图表类型：bar（柱状图）或 pie（饼图）"},
        "title": {"type": "string", "description": "图表标题"},
        "data": {"type": "string", "description": "数据，逗号分隔，如 30,50,20"},
        "labels": {"type": "string", "description": "标签，逗号分隔，如 一月,二月,三月"},
    }, "required": ["data"]},
    _visualize)

# ── 工具发现机制（MCP 动态注入） ──

async def _search_tools(args, ctx):
    """搜索当前未展示的可用工具（如 MCP 工具），找到后下一轮自动出现在工具列表中"""
    keyword = args.get("keyword", "")
    if not keyword:
        return "请提供搜索关键词，例如「fetch」「数据库」「GitHub」"
    mgr = get_mcp_manager()
    found = []
    if mgr:
        for srv_name, srv in mgr._servers.items():
            if not srv.is_connected:
                continue
            for t in srv._tools:
                name = t.get("name", "")
                desc = t.get("description", "")
                kw = keyword.lower()
                if kw in name.lower() or kw in desc.lower():
                    # 记录发现的工具到上下文，供下一轮注入
                    _discovered_mcp_tools[name] = (srv_name, t)
                    found.append(f"{name}: {desc[:120]}")
    if found:
        return f"找到 {len(found)} 个「{keyword}」工具，已自动加载到下一轮：\n" + "\n".join(found)
    return f"未找到「{keyword}」相关工具"

# 动态注入：记录通过 search_tools 发现的 MCP 工具
_discovered_mcp_tools: dict = {}

def get_discovered_definitions():
    """返回通过 search_tools 发现的 MCP 工具定义"""
    if not _discovered_mcp_tools:
        return []
    mgr = get_mcp_manager()
    if not mgr:
        return []
    result = []
    for name in list(_discovered_mcp_tools.keys()):
        srv_name, t = _discovered_mcp_tools[name]
        srv = mgr._servers.get(srv_name)
        if srv and srv.is_connected:
            for td in srv.get_tool_definitions():
                if td.get("function", {}).get("name") == name:
                    result.append(td)
    return result

def clear_discovered():
    """清除上一轮的工具发现缓存"""
    _discovered_mcp_tools.clear()

register("search_tools", "当你需要某种能力但在当前工具列表中找不到时调用此功能。"
    "输入关键词搜索可用的额外工具，找到后会自动出现在下一轮的工具列表中。"
    "例如：搜'fetch'返回网页抓取工具，搜'database'返回数据库工具，搜'git'返回代码工具。"
    "如果觉得当前工具有点勉强或不确定，也值得搜一下看看有没有更好的。",
    {"type": "object", "properties": {
        "keyword": {"type": "string", "description": "搜索关键词，如'fetch''数据库''图片''视频''代码'等"}
    }, "required": ["keyword"]},
    _search_tools)

# 加载外部插件
load_plugins()

# MCP 管理器（延迟初始化）
_mcp_manager = None

def get_mcp_manager():
    global _mcp_manager
    if _mcp_manager is None:
        from desktop_core.mcp_client import MCPManager
        _mcp_manager = MCPManager()
        # 从配置加载 MCP 服务器列表
        try:
            from desktop_core.storage import meta_get
            import json
            raw = meta_get("desktop_config")
            if raw:
                cfg = json.loads(raw)
                for name, srv in cfg.get("mcp_servers", {}).items():
                    cmd = srv.get("command", "")
                    args = srv.get("args", [])
                    env = srv.get("env", {})
                    if cmd:
                        _mcp_manager.add_server(name, cmd, args, env)
        except: pass
    return _mcp_manager

async def connect_mcp_servers():
    """连接所有 MCP 服务器并注册其工具"""
    mgr = get_mcp_manager()
    count = await mgr.connect_all()
    if count > 0:
        load_mcp_tools(mgr)
    return count
