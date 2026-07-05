"""工作流引擎 v2 — Dify 风格 DAG 执行器（VariablePool + GraphEngine + BaseNode + DSL）"""
import json, logging, asyncio, time, uuid, re, copy, os
from datetime import datetime
from typing import Optional, Any

log = logging.getLogger("workflow")

# ══════════════════════════════════════════════
# 第一部分：变量池 (VariablePool)
# ══════════════════════════════════════════════

class VariablePool:
    """全局变量池 — 节点间数据流的运行时状态管理
    
    引用语法: {{node_id.output_name}}
    示例: {{llm_1.text}} → 取 llm_1 节点的 text 输出
    """
    
    VAR_PATTERN = re.compile(r"\{\{(.+?)\}\}")
    
    def __init__(self):
        self._store: dict[str, dict] = {}  # node_id -> {output_name: value}
        self._types: dict[str, str] = {}   # variable_path -> type name
    
    def set(self, node_id: str, output: dict, type_hints: dict = None):
        """设置节点输出到变量池"""
        self._store[node_id] = output or {}
        if type_hints:
            for k, v in type_hints.items():
                self._types[f"{node_id}.{k}"] = v
    
    def get(self, node_id: str, key: str = None, default: Any = None) -> Any:
        """获取变量值（支持嵌套路径：node_id.key.subkey）"""
        node_data = self._store.get(node_id, {})
        if key is None:
            return node_data
        # 支持嵌套路径: "code_output.length" → node_data["code_output"]["length"]
        parts = key.split(".")
        current = node_data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return default
            else:
                return default
        return current if current is not None else default
    
    def resolve(self, template: str) -> str:
        """解析模板中的变量引用 {{node_id.key}}"""
        def _replace(match):
            path = match.group(1).strip()
            parts = path.split(".")
            if len(parts) >= 2:
                node_id = parts[0]
                key = ".".join(parts[1:])
                val = self.get(node_id, key)
                if val is not None:
                    if isinstance(val, (dict, list)):
                        return json.dumps(val, ensure_ascii=False)
                    return str(val)
                log.warning("[变量池] 变量未找到: %s", path)
                return match.group(0)  # 保留原样
            return match.group(0)
        
        return self.VAR_PATTERN.sub(_replace, template)
    
    def snapshot(self) -> dict:
        """获取完整快照（用于持久化）"""
        return copy.deepcopy(self._store)
    
    @property
    def all_variables(self) -> list[dict]:
        """列出所有可用变量（供前端选择）"""
        result = []
        for node_id, outputs in self._store.items():
            if isinstance(outputs, dict):
                for key, value in outputs.items():
                    result.append({
                        "node_id": node_id,
                        "key": key,
                        "path": f"{node_id}.{key}",
                        "type": self._types.get(f"{node_id}.{key}", 
                                  "array" if isinstance(value, list) else
                                  "number" if isinstance(value, (int, float)) else
                                  "boolean" if isinstance(value, bool) else
                                  "object" if isinstance(value, dict) else
                                  "string"),
                    })
        return result


# ══════════════════════════════════════════════
# 第二部分：节点基类 (BaseNode)
# ══════════════════════════════════════════════

class BaseNode:
    """节点基类 — 所有节点类型继承此类"""
    
    type_name = "base"
    label = "基础节点"
    color = "#6b7280"
    icon = "circle"
    inputs = 1
    outputs = 1
    
    def __init__(self, node_id: str, config: dict, variable_pool: VariablePool):
        self.id = node_id
        self.config = config or {}
        self.vp = variable_pool
    
    async def run(self) -> dict:
        """执行节点（含重试逻辑）"""
        max_retries = self.config.get("max_retries", 0)
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                result = await self._run()
                result["_attempt"] = attempt + 1
                result["_retries"] = 0
                return result
            except Exception as e:
                last_error = str(e)
                log.warning("[节点 %s] 执行失败 (尝试 %d/%d): %s",
                           self.id, attempt + 1, max_retries + 1, e)
                if attempt < max_retries:
                    await asyncio.sleep(1 * (attempt + 1))  # 退避等待
        
        return {"error": last_error or "未知错误", "_retries": max_retries}
    
    async def _run(self) -> dict:
        """子类实现此方法"""
        raise NotImplementedError
    
    def _resolve(self, text: str) -> str:
        """解析模板变量"""
        return self.vp.resolve(text)


class StartNode(BaseNode):
    type_name = "start"
    label = "开始"
    color = "#10b981"
    icon = "play"
    inputs = 0
    
    async def _run(self) -> dict:
        return {"output": self.config.get("input_data", {})}


class EndNode(BaseNode):
    type_name = "end"
    label = "结束"
    color = "#6b7280"
    icon = "stop"
    outputs = 0
    
    async def _run(self) -> dict:
        # 收集所有上游输出
        return {"output": self.config.get("input_data", {})}


class LLMNode(BaseNode):
    type_name = "llm"
    label = "LLM"
    color = "#6366f1"
    icon = "bot"
    
    async def _run(self) -> dict:
        prompt_template = self.config.get("prompt", "{input}")
        model = self.config.get("model", "")
        temperature = float(self.config.get("temperature", 0.7))
        max_tokens = int(self.config.get("max_tokens", 4096))
        system_prompt = self.config.get("system_prompt", "")
        
        # 解析模板变量
        prompt = self._resolve(prompt_template)
        sys_prompt = self._resolve(system_prompt) if system_prompt else ""
        
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # 真实调用 LLM
        result_text = ""
        token_usage = {}
        
        try:
            # 从 config 获取模型配置
            from config import API_BASE, API_KEY, DEFAULT_MODEL
            effective_model = model or DEFAULT_MODEL
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": effective_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                }
                async with session.post(
                    f"{API_BASE}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choice = data.get("choices", [{}])[0]
                        result_text = choice.get("message", {}).get("content", "")
                        token_usage = data.get("usage", {})
                    else:
                        body = await resp.text()
                        log.warning("[LLM] API 错误 %d: %s", resp.status, body[:200])
                        result_text = f"[API错误 {resp.status}]"
        except ImportError:
            log.warning("[LLM] config 模块不可用，使用模拟")
            result_text = f"[模拟 LLM] {prompt[:100]}..."
        except Exception as e:
            log.error("[LLM] 调用异常: %s", e)
            result_text = f"[异常] {e}"
        
        return {
            "text": result_text,
            "usage": token_usage,
            "model": model or "default",
            "type_hints": {"text": "string", "usage": "object"},
        }


class ToolNode(BaseNode):
    type_name = "tool"
    label = "工具"
    color = "#f59e0b"
    icon = "wrench"
    
    async def _run(self) -> dict:
        tool_name = self.config.get("tool_name", "")
        tool_args_raw = self.config.get("tool_args", {})
        
        if not tool_name:
            return {"result": "", "error": "未指定工具名称"}
        
        # 解析参数中的变量
        tool_args = {}
        for k, v in tool_args_raw.items():
            if isinstance(v, str):
                tool_args[k] = self._resolve(v)
            else:
                tool_args[k] = v
        
        result = ""
        try:
            # 尝试通过 ToolAggregator 调用
            from tools.aggregator import ToolAggregator
            from tools.plugin import PluginManager
            from tools.mcp_manager import MCPClientManager
            
            plugin_mgr = PluginManager()
            plugin_mgr.discover()
            plugin_mgr.load_all()
            
            mcp_mgr = MCPClientManager()
            
            agg = ToolAggregator(registry=None, plugin_mgr=plugin_mgr, mcp_mgr=mcp_mgr)
            result = await agg.execute(tool_name, tool_args, user_id="workflow", scene="workflow")
            if result is None:
                result = f"工具 {tool_name} 未找到"
        except ImportError:
            log.warning("[工具] ToolAggregator 不可用")
            result = f"[模拟工具] {tool_name}({tool_args})"
        except Exception as e:
            log.error("[工具] 调用异常: %s", e)
            result = f"[异常] {e}"
        
        return {"result": str(result), "tool": tool_name, "type_hints": {"result": "string"}}


class CodeNode(BaseNode):
    type_name = "code"
    label = "代码"
    color = "#3b82f6"
    icon = "code"
    
    async def _run(self) -> dict:
        code = self.config.get("code", "result = input_data")
        language = self.config.get("language", "python")
        
        # 获取上游输入
        input_data = self.config.get("input_data", {})
        
        result = None
        error = None
        
        if language == "python":
            try:
                safe_globals = {
                    "__builtins__": {
                        "len": len, "str": str, "int": int, "float": float,
                        "bool": bool, "list": list, "dict": dict, "range": range,
                        "min": min, "max": max, "sum": sum, "abs": abs,
                        "sorted": sorted, "reversed": reversed, "enumerate": enumerate,
                        "zip": zip, "map": map, "filter": filter,
                        "print": lambda *a: None,  # 捕获 print
                    },
                    "input_data": input_data,
                }
                local_vars = {}
                exec(code, safe_globals, local_vars)
                result = local_vars.get("result", local_vars.get("output", input_data))
            except Exception as e:
                error = str(e)
                log.warning("[代码] 执行错误: %s", e)
        else:
            error = f"不支持的语言: {language}"
        
        output = {"code_output": result}
        if error:
            output["code_error"] = error
        
        return output | {"type_hints": {"code_output": type(result).__name__ if result is not None else "null"}}


class ConditionNode(BaseNode):
    type_name = "condition"
    label = "条件分支"
    color = "#ef4444"
    icon = "git-branch"
    outputs = 2
    
    async def _run(self) -> dict:
        expression = self.config.get("expression", "True")
        
        # 获取上游输入
        input_data = self.config.get("input_data", {})
        
        # 安全求值（只允许基础类型操作）
        result = False
        error = None
        
        try:
            safe_globals = {
                "__builtins__": {
                    "True": True, "False": False, "None": None,
                    "len": len, "str": str, "int": int, "float": float,
                    "bool": bool, "list": list, "dict": dict,
                    "min": min, "max": max, "sum": sum, "abs": abs,
                    "any": any, "all": all,
                },
                "input": input_data,
            }
            # 安全去除外层引号（仅当整串被引号包裹时）
            cleaned = expression
            if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
                cleaned = cleaned[1:-1]
            result = bool(eval(cleaned, safe_globals, {}))
        except Exception as e:
            error = str(e)
            log.warning("[条件] 表达式求值失败: %s | expr=%s", e, expression)
            result = True  # 失败时走 true 分支
        
        return {
            "result": result,
            "expression": expression,
            "branch": "true" if result else "false",
            "type_hints": {"result": "boolean"},
        }


class HttpNode(BaseNode):
    type_name = "http"
    label = "HTTP请求"
    color = "#8b5cf6"
    icon = "globe"
    
    async def _run(self) -> dict:
        url = self._resolve(self.config.get("url", ""))
        method = self.config.get("method", "GET").upper()
        headers = self.config.get("headers", {})
        body_template = self.config.get("body", "")
        timeout = int(self.config.get("timeout", 15))
        
        # 解析 headers 和 body 中的变量
        resolved_headers = {}
        for k, v in headers.items():
            resolved_headers[k] = self._resolve(str(v))
        
        body = self._resolve(body_template) if body_template else None
        
        import aiohttp
        result = {"status_code": 0, "body": "", "headers": {}}
        
        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {
                    "url": url,
                    "headers": resolved_headers,
                    "timeout": aiohttp.ClientTimeout(total=timeout),
                }
                if method in ("POST", "PUT", "PATCH") and body:
                    kwargs["json"] = body if body.startswith("{") else body
                    kwargs["data"] = body if not body.startswith("{") else None
                
                async with session.request(method, **kwargs) as resp:
                    result["status_code"] = resp.status
                    result["headers"] = dict(resp.headers)
                    result["body"] = await resp.text()
        
        except asyncio.TimeoutError:
            result["error"] = f"请求超时 ({timeout}s)"
        except Exception as e:
            result["error"] = str(e)
        
        return result | {"type_hints": {"status_code": "number", "body": "string"}}


class KnowledgeNode(BaseNode):
    type_name = "knowledge"
    label = "知识库"
    color = "#14b8a6"
    icon = "book-open"
    
    async def _run(self) -> dict:
        query = self._resolve(self.config.get("query", "{input}"))
        top_k = int(self.config.get("top_k", 3))
        
        results = []
        try:
            try:
                from core.knowledge_base import KnowledgeBase
                kb = KnowledgeBase()
            except ImportError:
                kb = None
            if kb is None:
                results = []
            else:
                results = await kb.search(query, top_k=top_k)
        except Exception:
            log.warning("[知识库] KnowledgeBase 不可用")
            results = [{"title": "(模拟)", "content": f"知识库搜索: {query}"}]
        except Exception as e:
            log.error("[知识库] 查询异常: %s", e)
            results = [{"error": str(e)}]
        
        return {
            "results": results,
            "query": query,
            "top_k": top_k,
            "type_hints": {"results": "array"},
        }


class IterationNode(BaseNode):
    type_name = "iteration"
    label = "迭代"
    color = "#ec4899"
    icon = "layers"
    
    async def _run(self) -> dict:
        items_raw = self.config.get("items", "[]")
        mode = self.config.get("mode", "sequential")  # sequential / parallel
        
        # 解析变量或 JSON
        resolved = self._resolve(items_raw)
        try:
            items = json.loads(resolved) if isinstance(resolved, str) else resolved
        except:
            items = []
        
        if not isinstance(items, list):
            items = [items]
        
        results = []
        
        if mode == "parallel":
            # 并行执行
            async def _process_item(item, idx):
                return {"index": idx, "item": item, "status": "processed"}
            
            tasks = [_process_item(item, i) for i, item in enumerate(items)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # 顺序执行
            for i, item in enumerate(items):
                results.append({"index": i, "item": item, "status": "processed"})
                await asyncio.sleep(0.05)  # 避免过快
        
        return {
            "items": items,
            "results": results,
            "count": len(items),
            "mode": mode,
            "type_hints": {"items": "array", "results": "array", "count": "number"},
        }


# ══════════════════════════════════════════════
# 新增节点类型
# ══════════════════════════════════════════════

class TemplateTransformNode(BaseNode):
    """模板转换节点 — Jinja2 模板渲染"""
    type_name = "template-transform"
    label = "模板转换"
    color = "#f97316"
    icon = "file-text"
    
    async def _run(self) -> dict:
        template = self.config.get("template", "{{ input }}")
        variables = self.config.get("variables", {})
        input_data = self.config.get("input_data", {})
        
        # 合并变量
        ctx = dict(input_data)
        if isinstance(variables, dict):
            for k, v in variables.items():
                resolved = self._resolve(str(v))
                ctx[k] = resolved
        
        # 步骤1: 解析 VariablePool 引用 {{node_id.key}} → 实际值
        # 注意: 模板可能同时包含 VariablePool 引用和 Jinja2 语法
        # VariablePool 用 {{node_id.key}}，Jinja2 也用它
        # 优先解析 VariablePool 引用
        def _resolve_vp(match):
            path = match.group(1).strip()
            parts = path.split(".")
            if len(parts) >= 2:
                val = self.vp.get(parts[0], ".".join(parts[1:]))
                if val is not None:
                    if isinstance(val, (dict, list)):
                        return json.dumps(val, ensure_ascii=False)
                    return str(val)
            return match.group(0)
        
        resolved_template = VariablePool.VAR_PATTERN.sub(_resolve_vp, template)
        
        # 步骤2: Jinja2 渲染
        try:
            import jinja2
            env = jinja2.Environment(undefined=jinja2.Undefined)
            tpl = env.from_string(resolved_template)
            output = tpl.render(**ctx)
        except ImportError:
            log.warning("[模板] jinja2 未安装，使用简单替换")
            output = resolved_template
        except Exception as e:
            return {"error": f"模板渲染失败: {e}", "output": resolved_template}
        
        return {"output": output, "type_hints": {"output": "string"}}


class ParameterExtractorNode(BaseNode):
    """参数提取节点 — LLM 从文本提取结构化参数"""
    type_name = "parameter-extractor"
    label = "参数提取"
    color = "#8b5cf6"
    icon = "list"
    
    async def _run(self) -> dict:
        query = self._resolve(self.config.get("query", "{input}"))
        parameters = self.config.get("parameters", [])
        
        if not parameters:
            return {"error": "未定义提取参数", "parameters": {}}
        
        # 构建提取提示
        fields_desc = "\n".join([
            f"- {p.get('name')} ({p.get('type', 'string')}): {p.get('description', '')}"
            for p in parameters
        ])
        prompt = f"""请从以下文本中提取指定信息，以 JSON 格式返回。

文本: {query}

需要提取的字段:
{fields_desc}

只返回 JSON，不要其他文字。"""
        
        result = {"parameters": {}}
        try:
            from config import API_BASE, API_KEY, DEFAULT_MODEL
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{API_BASE}/chat/completions",
                    json={
                        "model": self.config.get("model", DEFAULT_MODEL),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                    },
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        try:
                            parsed = json.loads(text.strip().strip("`").replace("json\n", ""))
                            result["parameters"] = parsed
                        except json.JSONDecodeError:
                            result["parameters"] = {"_raw": text}
        except ImportError:
            # 模拟模式：为每个参数生成默认值
            mock_params = {}
            for p in parameters:
                pname = p.get("name", "")
                ptype = p.get("type", "string")
                if ptype == "number":
                    mock_params[pname] = 0
                elif ptype == "boolean":
                    mock_params[pname] = False
                else:
                    mock_params[pname] = f"[{pname}]"
            result["parameters"] = mock_params
        except Exception as e:
            result["error"] = str(e)
        
        return result | {"type_hints": {"parameters": "object"}}


class QuestionClassifierNode(BaseNode):
    """问题分类节点 — LLM 进行意图分类路由"""
    type_name = "question-classifier"
    label = "问题分类"
    color = "#ec4899"
    icon = "git-branch"
    outputs = 2
    
    async def _run(self) -> dict:
        query = self._resolve(self.config.get("query", "{input}"))
        categories = self.config.get("categories", [])
        
        if not categories:
            return {"category": "default", "confidence": 0, "error": "未定义分类"}
        
        cats_desc = "\n".join([f"{c.get('name')}: {c.get('description', '')}" for c in categories])
        prompt = f"""请将以下问题分类到最合适的类别。

问题: {query}

可选类别:
{cats_desc}

只返回类别名称，不要其他文字。"""
        
        category = "default"
        try:
            from config import API_BASE, API_KEY, DEFAULT_MODEL
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{API_BASE}/chat/completions",
                    json={
                        "model": self.config.get("model", DEFAULT_MODEL),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 100,
                    },
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                        if text in [c.get("name") for c in categories]:
                            category = text
        except ImportError:
            category = categories[0].get("name", "default") if categories else "default"
        except Exception as e:
            log.warning("[分类] 失败: %s", e)
        
        return {
            "category": category,
            "query": query,
            "branch": category,
            "type_hints": {"category": "string"},
        }


class DocumentExtractorNode(BaseNode):
    """文档提取节点 — 从文件提取文本"""
    type_name = "document-extractor"
    label = "文档提取"
    color = "#14b8a6"
    icon = "file"
    
    async def _run(self) -> dict:
        file_path = self.config.get("file_path", "")
        
        if not file_path or not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}", "text": ""}
        
        text = ""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in (".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv", ".xml"):
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(50000)
            elif ext in (".pdf",):
                try:
                    import pypdf
                    reader = pypdf.PdfReader(file_path)
                    text = "\n".join([page.extract_text() or "" for page in reader.pages])
                except ImportError:
                    text = f"[需安装 pypdf 库来解析 PDF]"
            elif ext in (".docx", ".doc"):
                try:
                    import docx
                    doc = docx.Document(file_path)
                    text = "\n".join([p.text for p in doc.paragraphs])
                except ImportError:
                    text = f"[需安装 python-docx 库来解析 Word]"
            else:
                text = f"[不支持的文件格式: {ext}]"
        except Exception as e:
            text = f"[读取错误: {e}]"
        
        return {
            "text": text[:50000],
            "filename": os.path.basename(file_path) if file_path else "",
            "size": len(text),
            "type_hints": {"text": "string", "size": "number"},
        }


class VariableAssignerNode(BaseNode):
    """变量赋值节点 — 表达式变换变量值"""
    type_name = "assigner"
    label = "变量赋值"
    color = "#06b6d4"
    icon = "equal"
    
    async def _run(self) -> dict:
        input_data = self.config.get("input_data", {})
        assignments = self.config.get("assignments", [])
        
        result = dict(input_data)
        for assign in assignments:
            var_name = assign.get("variable", "")
            expression = assign.get("expression", "")
            if not var_name:
                continue
            try:
                safe_globals = {
                    "__builtins__": {
                        "str": str, "int": int, "float": float, "bool": bool,
                        "len": len, "list": list, "dict": dict, "min": min, "max": max,
                        "sum": sum, "abs": abs, "round": round, "type": type,
                        "True": True, "False": False, "None": None,
                    },
                    "input": input_data,
                    "result": result,
                }
                value = eval(expression, safe_globals, {})
                result[var_name] = value
            except Exception as e:
                result[var_name] = f"[错误: {e}]"
        
        return {"output": result, "type_hints": {"output": "object"}}


class VariableAggregatorNode(BaseNode):
    """变量聚合节点 — 合并多个分支的输出"""
    type_name = "variable-aggregator"
    label = "变量聚合"
    color = "#a855f7"
    icon = "combine"
    
    async def _run(self) -> dict:
        input_data = self.config.get("input_data", {})
        merge_strategy = self.config.get("merge_strategy", "overwrite")
        
        if merge_strategy == "overwrite":
            result = dict(input_data)
        elif merge_strategy == "keep_existing":
            result = dict(input_data)
        else:
            result = dict(input_data)
        
        return {"output": result, "type_hints": {"output": "object"}}


class ListOperatorNode(BaseNode):
    """列表操作节点 — 数组过滤/映射/归约"""
    type_name = "list-operator"
    label = "列表操作"
    color = "#0ea5e9"
    icon = "list-filter"
    
    async def _run(self) -> dict:
        input_data = self.config.get("input_data", {})
        items = input_data.get("items", input_data.get("list", input_data.get("input", [])))
        if not isinstance(items, list):
            items = []
        
        operation = self.config.get("operation", "filter")
        expression = self.config.get("expression", "True")
        
        result = items
        try:
            if operation == "filter":
                result = [item for item in items if self._evaluate(expression, item)]
            elif operation == "map":
                result = [self._evaluate(expression, item) for item in items]
            elif operation == "sort":
                result = sorted(items, key=lambda x: self._evaluate(expression, x) if callable(self._evaluate(expression, x)) else str(x))
            elif operation == "first":
                result = items[0] if items else None
            elif operation == "count":
                result = len(items)
        except Exception as e:
            return {"error": str(e), "result": items, "type_hints": {"result": "array"}}
        
        return {"result": result, "count": len(result) if isinstance(result, list) else 1,
                "type_hints": {"result": "array", "count": "number"}}
    
    def _evaluate(self, expr: str, item) -> Any:
        safe_globals = {
            "__builtins__": {
                "True": True, "False": False, "None": None,
                "len": len, "str": str, "int": int, "float": float,
                "bool": bool, "list": list, "dict": dict,
                "min": min, "max": max, "any": any, "all": all,
            },
            "item": item,
        }
        return eval(expr, safe_globals, {})


class AnswerNode(BaseNode):
    """中间输出节点 — 工作流运行中输出结果"""
    type_name = "answer"
    label = "中间输出"
    color = "#22c55e"
    icon = "message-square"
    
    async def _run(self) -> dict:
        input_data = self.config.get("input_data", {})
        output_template = self.config.get("output", "{input}")
        answer = self._resolve(output_template)
        
        return {"answer": answer, "output": input_data, "type_hints": {"answer": "string"}}


# ══════════════════════════════════════════════
# 第三批节点：Agent / HumanInput / Webhook / Schedule / KnowledgeIndex / DataSource / Plugin
# ══════════════════════════════════════════════

class AgentNode(BaseNode):
    """Agent 节点 — 自主 Agent（LLM + 工具循环）"""
    type_name = "agent"
    label = "智能体"
    color = "#e11d48"
    icon = "bot"
    
    async def _run(self) -> dict:
        system_prompt = self.config.get("system_prompt", "你是一个智能助手，使用工具来回答问题。")
        instruction = self._resolve(self.config.get("instruction", "{input}"))
        max_iterations = int(self.config.get("max_iterations", 5))
        available_tools = self.config.get("tools", ["search_web", "execute_command"])
        
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": instruction}]
        final_answer = ""
        tool_calls_log = []
        
        for iteration in range(max_iterations):
            try:
                from config import API_BASE, API_KEY, DEFAULT_MODEL
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{API_BASE}/chat/completions",
                        json={"model": self.config.get("model", DEFAULT_MODEL), "messages": messages,
                              "max_tokens": 4096, "temperature": 0.7},
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status != 200:
                            final_answer = f"[API错误 {resp.status}]"
                            break
                        data = await resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        messages.append({"role": "assistant", "content": content})
                        
                        # 判断是否包含工具调用或已给出最终答案
                        if not any(cmd in content for cmd in ["<tool>", "调用工具"]):
                            final_answer = content
                            break
                        
                        # 简化：记录工具意图
                        tool_calls_log.append(f"第{iteration+1}轮: {content[:100]}")
            except ImportError:
                final_answer = f"[模拟Agent] {instruction[:100]}..."
                break
            except Exception as e:
                final_answer = f"[异常] {e}"
                break
        
        return {
            "answer": final_answer,
            "tool_calls": tool_calls_log,
            "iterations": len(tool_calls_log) + 1,
            "type_hints": {"answer": "string", "tool_calls": "array", "iterations": "number"},
        }


class HumanInputNode(BaseNode):
    """人工输入节点 — 暂停工作流等待人工输入"""
    type_name = "human-input"
    label = "人工输入"
    color = "#0ea5e9"
    icon = "user"
    outputs = 1
    
    def __init__(self, node_id: str, config: dict, variable_pool: VariablePool, pending_inputs: dict = None):
        super().__init__(node_id, config, variable_pool)
        self._pending = pending_inputs if pending_inputs is not None else {}
    
    async def _run(self) -> dict:
        prompt = self.config.get("prompt", "请输入:")
        input_type = self.config.get("input_type", "text")
        run_id = self.config.get("_run_id", "")
        
        # 检查是否已有用户提交的输入
        pending_key = f"{run_id}_{self.id}" if run_id else self.id
        if pending_key in self._pending:
            user_input = self._pending.pop(pending_key)
            return {"user_input": user_input, "prompt": prompt, "status": "completed",
                    "type_hints": {"user_input": "string"}}
        
        # 无输入，返回等待状态
        return {"status": "waiting", "prompt": prompt, "input_type": input_type,
                "pending_key": pending_key, "type_hints": {"status": "string"}}


class WebhookTriggerNode(BaseNode):
    """Webhook 触发节点 — HTTP 回调启动工作流"""
    type_name = "trigger-webhook"
    label = "Webhook触发"
    color = "#10b981"
    icon = "webhook"
    inputs = 0
    
    async def _run(self) -> dict:
        endpoint = self.config.get("endpoint", f"/webhook/{self.id}")
        method = self.config.get("method", "POST")
        # 在 api 层注册对应的 HTTP 端点
        return {
            "endpoint": endpoint,
            "method": method,
            "payload": self.config.get("input_data", {}),
            "webhook_data": self.config.get("_webhook_payload", {}),
            "type_hints": {"endpoint": "string"},
        }


class ScheduleTriggerNode(BaseNode):
    """定时触发节点 — Cron 表达式定时执行"""
    type_name = "trigger-schedule"
    label = "定时触发"
    color = "#f59e0b"
    icon = "clock"
    inputs = 0
    
    async def _run(self) -> dict:
        cron = self.config.get("cron", "0 * * * *")
        from datetime import datetime
        return {
            "triggered_at": datetime.now().isoformat(),
            "cron": cron,
            "type_hints": {"triggered_at": "string"},
        }


class KnowledgeIndexNode(BaseNode):
    """知识库索引节点 — 写入内容到知识库"""
    type_name = "knowledge-index"
    label = "知识库索引"
    color = "#14b8a6"
    icon = "book-plus"
    
    async def _run(self) -> dict:
        content = self._resolve(self.config.get("content", "{input}"))
        title = self._resolve(self.config.get("title", "工作流写入"))
        category = self.config.get("category", "工作流")
        
        indexed = False
        try:
            kb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "奶昔-知识库", category)
            os.makedirs(kb_dir, exist_ok=True)
            fname = f"{title}_{int(time.time())}.md"
            fpath = os.path.join(kb_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            indexed = True
        except Exception as e:
            return {"error": str(e), "indexed": False, "type_hints": {"indexed": "boolean"}}
        
        return {"indexed": indexed, "title": title, "category": category,
                "type_hints": {"indexed": "boolean"}}


class DataSourceNode(BaseNode):
    """数据源入口节点 — 从外部数据源读取"""
    type_name = "datasource"
    label = "数据源"
    color = "#6366f1"
    icon = "database"
    inputs = 0
    
    async def _run(self) -> dict:
        source_type = self.config.get("source_type", "file")
        source_path = self.config.get("source_path", "")
        
        if source_type == "file" and source_path:
            if os.path.isfile(source_path):
                with open(source_path, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read(50000)
                return {"data": data, "source": source_path, "size": len(data),
                        "type_hints": {"data": "string", "size": "number"}}
        
        return {"data": "", "source": source_path, "error": "数据源不可用",
                "type_hints": {"data": "string"}}


class PluginTriggerNode(BaseNode):
    """插件触发节点 — 通过插件机制启动"""
    type_name = "trigger-plugin"
    label = "插件触发"
    color = "#8b5cf6"
    icon = "puzzle"
    inputs = 0
    
    async def _run(self) -> dict:
        plugin_name = self.config.get("plugin_name", "")
        plugin_input = self.config.get("input_data", {})
        return {"plugin": plugin_name, "input": plugin_input,
                "type_hints": {"plugin": "string"}}


class LoopNode(BaseNode):
    """条件循环节点 — 按条件重复执行"""
    type_name = "loop"
    label = "条件循环"
    color = "#f43f5e"
    icon = "rotate-ccw"
    
    async def _run(self) -> dict:
        input_data = self.config.get("input_data", {})
        max_iterations = int(self.config.get("max_iterations", 10))
        condition_expr = self.config.get("condition", "True")
        
        iteration = 0
        should_continue = True
        state = dict(input_data)
        
        while should_continue and iteration < max_iterations:
            iteration += 1
            safe_globals = {
                "__builtins__": {"True": True, "False": False, "len": len,
                                "str": str, "int": int},
                "input": state,
                "iteration": iteration,
            }
            try:
                should_continue = bool(eval(condition_expr, safe_globals, {}))
            except:
                should_continue = False
            
            if should_continue:
                state["_loop_iteration"] = iteration
        
        return {
            "total_iterations": iteration,
            "output": state,
            "condition_met": iteration < max_iterations,
            "type_hints": {"total_iterations": "number", "condition_met": "boolean"},
        }


# 节点类型注册表
NODE_CLASSES: dict[str, type[BaseNode]] = {
    "start": StartNode,
    "end": EndNode,
    "llm": LLMNode,
    "tool": ToolNode,
    "code": CodeNode,
    "condition": ConditionNode,
    "http": HttpNode,
    "knowledge": KnowledgeNode,
    "iteration": IterationNode,
    "template-transform": TemplateTransformNode,
    "parameter-extractor": ParameterExtractorNode,
    "question-classifier": QuestionClassifierNode,
    "document-extractor": DocumentExtractorNode,
    "assigner": VariableAssignerNode,
    "variable-aggregator": VariableAggregatorNode,
    "list-operator": ListOperatorNode,
    "answer": AnswerNode,
    "loop": LoopNode,
    "agent": AgentNode,
    "human-input": HumanInputNode,
    "trigger-webhook": WebhookTriggerNode,
    "trigger-schedule": ScheduleTriggerNode,
    "knowledge-index": KnowledgeIndexNode,
    "datasource": DataSourceNode,
    "trigger-plugin": PluginTriggerNode,
}

# 节点类型元信息
NODE_TYPE_INFO = {
    name: {
        "type": name,
        "label": cls.label,
        "color": cls.color,
        "icon": cls.icon,
        "inputs": cls.inputs,
        "outputs": cls.outputs,
    }
    for name, cls in NODE_CLASSES.items()
}

# ══════════════════════════════════════════════
# Layer 系统（Dify 风格责任链拦截器）
# ══════════════════════════════════════════════

class BaseLayer:
    """Layer 基类 — 每个 Layer 可以拦截/修改/监控节点执行"""
    async def before_node(self, node_id: str, node_type: str, config: dict) -> bool:
        """节点执行前调用，返回 False 阻止执行"""
        return True
    async def after_node(self, node_id: str, node_type: str, result: dict):
        """节点执行后调用"""
        pass
    async def on_error(self, node_id: str, node_type: str, error: str):
        """节点出错时调用"""
        pass


class ExecutionLimitsLayer(BaseLayer):
    """执行限制 Layer — 步数上限 + 超时控制"""
    def __init__(self, max_steps: int = 200, max_time: int = 300):
        self.max_steps = max_steps
        self.max_time = max_time
        self.step_count = 0
        self.start_time = None
    
    async def before_node(self, node_id: str, node_type: str, config: dict) -> bool:
        self.step_count += 1
        if self.step_count > self.max_steps:
            raise RuntimeError(f"超过最大执行步数 ({self.max_steps})")
        if self.start_time and time.time() - self.start_time > self.max_time:
            raise RuntimeError(f"超过最大执行时间 ({self.max_time}秒)")
        return True


class ObservabilityLayer(BaseLayer):
    """可观测性 Layer — 记录节点执行日志"""
    def __init__(self):
        self.node_timings: list[dict] = []
        self._start_times: dict[str, float] = {}
    
    async def before_node(self, node_id: str, node_type: str, config: dict) -> bool:
        self._start_times[node_id] = time.time()
        return True
    
    async def after_node(self, node_id: str, node_type: str, result: dict):
        start = self._start_times.pop(node_id, time.time())
        elapsed = time.time() - start
        self.node_timings.append({
            "node_id": node_id,
            "type": node_type,
            "elapsed_ms": round(elapsed * 1000),
            "has_error": "error" in result,
        })
    
    async def on_error(self, node_id: str, node_type: str, error: str):
        start = self._start_times.pop(node_id, time.time())
        elapsed = time.time() - start
        self.node_timings.append({
            "node_id": node_id,
            "type": node_type,
            "elapsed_ms": round(elapsed * 1000),
            "error": error[:100],
        })


class LayerStack:
    """Layer 堆叠 — 管理多个 Layer 的执行链"""
    def __init__(self):
        self._layers: list[BaseLayer] = []
    
    def add(self, layer: BaseLayer):
        self._layers.append(layer)
    
    async def run_before(self, node_id: str, node_type: str, config: dict) -> bool:
        for layer in self._layers:
            try:
                ok = await layer.before_node(node_id, node_type, config)
                if not ok:
                    return False
            except Exception as e:
                log.warning("[Layer] %s 执行前拦截失败: %s", type(layer).__name__, e)
                raise
        return True
    
    async def run_after(self, node_id: str, node_type: str, result: dict):
        for layer in self._layers:
            try:
                await layer.after_node(node_id, node_type, result)
            except Exception as e:
                log.warning("[Layer] %s 执行后回调失败: %s", type(layer).__name__, e)
    
    async def run_error(self, node_id: str, node_type: str, error: str):
        for layer in self._layers:
            try:
                await layer.on_error(node_id, node_type, error)
            except Exception as e:
                log.warning("[Layer] %s 错误回调失败: %s", type(layer).__name__, e)


# 新增 SSE 事件类型
WORKFLOW_EVENT_NODE_START = "node_start"
WORKFLOW_EVENT_NODE_END = "node_end"
WORKFLOW_EVENT_NODE_ERROR = "node_error"
WORKFLOW_EVENT_NODE_STREAM = "node_stream"  # LLM 流式输出
WORKFLOW_EVENT_STATE_CHANGE = "state_change"
WORKFLOW_EVENT_FINAL = "final"

# ══════════════════════════════════════════════
# 第三部分：图引擎 (GraphEngine)
# ══════════════════════════════════════════════

class GraphEngine:
    """异步状态机图执行引擎
    
    执行流程:
    INIT → 构建图、初始化变量池
    RUNNING → 持续从就绪队列取节点执行
    WAITING → 等待异步节点完成
    SUCCESS/FAILED → 全部完成或某个节点致命错误
    """
    
    STATE_INIT = "init"
    STATE_RUNNING = "running"
    STATE_WAITING = "waiting"
    STATE_SUCCESS = "success"
    STATE_FAILED = "failed"
    
    def __init__(self, nodes_data: list[dict], edges_data: list[dict], input_data: dict = None, layers: LayerStack = None):
        self.nodes_data = nodes_data
        self.edges_data = edges_data
        self.input_data = input_data or {}
        
        self.vp = VariablePool()
        self.state = self.STATE_INIT
        self.layers = layers or LayerStack()
        
        # 图结构
        self.node_map: dict[str, dict] = {n["id"]: n for n in nodes_data}
        self.adj: dict[str, list[dict]] = {}  # node_id -> [{target, sourceHandle}]
        self.in_degree: dict[str, int] = {}
        
        # 运行时状态
        self.node_instances: dict[str, BaseNode] = {}
        self.node_status: dict[str, str] = {}  # pending/running/success/error/skipped
        self.node_inputs: dict[str, dict] = {}
        self.node_outputs: dict[str, dict] = {}
        self.node_errors: dict[str, str] = {}
        self.node_logs: dict[str, list[str]] = {}
        
        # 事件回调
        self._on_node_start = None
        self._on_node_end = None
        self._on_node_error = None
        self._on_state_change = None
        self._on_node_stream = None  # SSE 流式数据
    
    def _build_graph(self):
        """构建图结构"""
        for n in self.nodes_data:
            nid = n["id"]
            self.adj[nid] = []
            self.in_degree[nid] = 0
            self.node_status[nid] = "pending"
            self.node_logs[nid] = []
        
        for edge in self.edges_data:
            source = edge.get("source")
            target = edge.get("target")
            if source in self.adj and target in self.adj:
                self.adj[source].append({
                    "target": target,
                    "sourceHandle": edge.get("sourceHandle", "output"),
                    "targetHandle": edge.get("targetHandle", "input"),
                })
                self.in_degree[target] = self.in_degree.get(target, 0) + 1
    
    def _get_ready_nodes(self) -> list[str]:
        """获取所有就绪节点（上游全部完成且自身未执行）"""
        ready = []
        for nid in self.node_map:
            if self.node_status.get(nid) != "pending":
                continue
            
            incoming_edges = [e for e in self.edges_data if e.get("target") == nid]
            if not incoming_edges:
                # 无入边（如 start 节点）
                ready.append(nid)
                continue
            
            all_skipped = True
            has_blocking = False
            
            for edge in incoming_edges:
                source = edge.get("source")
                source_status = self.node_status.get(source, "pending")
                source_handle = edge.get("sourceHandle", "output")
                src_type = self.node_map.get(source, {}).get("type", "")
                
                # 条件分支：检查是否不在激活路径上
                if src_type == "condition" and source_status == "success":
                    src_output = self.node_outputs.get(source, {})
                    branch = src_output.get("branch", "true")
                    if source_handle != branch:
                        continue  # 不在激活路径，忽略此边
                
                # 上游被跳过 → 忽略此边（不设置 all_skipped = False）
                if source_status == "skipped":
                    continue
                
                all_skipped = False
                
                if source_status not in ("success", "error"):
                    has_blocking = True
                    break
            
            if all_skipped:
                # 所有入边都不在激活路径 → 标记跳过
                self.node_status[nid] = "skipped"
                self.node_logs[nid].append("已跳过（未在上游激活路径上）")
            elif not has_blocking:
                ready.append(nid)
        
        return ready
    
    def _compute_node_input(self, node_id: str) -> dict:
        """计算节点输入（合并所有上游的输出）"""
        merged = dict(self.input_data)
        for edge in self.edges_data:
            if edge.get("target") == node_id:
                source = edge.get("source")
                source_handle = edge.get("sourceHandle", "output")
                source_output = self.node_outputs.get(source, {})
                
                # 条件分支：只取对应的输出
                if source_handle in ("true", "false"):
                    branch_key = "true" if source_output.get("branch") == "true" else "false"
                    merged.update(source_output.get("input_data", merged))
                else:
                    if isinstance(source_output, dict):
                        merged.update(source_output)
        
        return merged
    
    def on_node_start(self, callback):
        self._on_node_start = callback
        return self
    
    def on_node_end(self, callback):
        self._on_node_end = callback
        return self
    
    def on_node_error(self, callback):
        self._on_node_error = callback
        return self
    
    def on_state_change(self, callback):
        self._on_state_change = callback
        return self
    
    def on_node_stream(self, callback):
        self._on_node_stream = callback
        return self
    
    def _emit(self, event: str, data: dict):
        """触发事件"""
        if event == "node_start" and self._on_node_start:
            asyncio.ensure_future(self._on_node_start(data))
        elif event == "node_end" and self._on_node_end:
            asyncio.ensure_future(self._on_node_end(data))
        elif event == "node_error" and self._on_node_error:
            asyncio.ensure_future(self._on_node_error(data))
        elif event == "state_change" and self._on_state_change:
            asyncio.ensure_future(self._on_state_change(data))
        elif event == "node_stream" and self._on_node_stream:
            asyncio.ensure_future(self._on_node_stream(data))
    
    async def run(self) -> dict:
        """执行工作流"""
        self._build_graph()
        self.state = self.STATE_RUNNING
        self._emit("state_change", {"state": self.state})
        
        start_nodes = [n["id"] for n in self.nodes_data if n.get("type") == "start"]
        
        # 注入起始输入到 start 节点
        for sid in start_nodes:
            self.vp.set(sid, {"output": self.input_data})
            self.node_outputs[sid] = {"output": self.input_data}
            self.node_status[sid] = "success"
        
        # 主循环
        max_iterations = len(self.nodes_data) * 2  # 安全上限
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # 检查是否全部完成
            all_done = all(
                s in ("success", "error", "skipped")
                for s in self.node_status.values()
            )
            if all_done:
                break
            
            ready = self._get_ready_nodes()
            if not ready:
                # 没有就绪节点但还没完成 → 死锁或等待中
                await asyncio.sleep(0.1)
                continue
            
            # 并行执行就绪节点
            async def _execute(nid):
                node_data = self.node_map.get(nid)
                if not node_data:
                    return
                
                ntype = node_data.get("type", "")
                config = node_data.get("data", {}).get("config", {})
                config["input_data"] = self._compute_node_input(nid)
                
                # Layer 前置拦截
                try:
                    ok = await self.layers.run_before(nid, ntype, config)
                    if not ok:
                        self.node_status[nid] = "skipped"
                        self.node_logs[nid].append("被 Layer 拦截跳过")
                        return
                except Exception as e:
                    self.node_status[nid] = "error"
                    self.node_errors[nid] = f"Layer拦截: {e}"
                    await self.layers.run_error(nid, ntype, str(e))
                    return
                
                # 创建节点实例
                node_class = NODE_CLASSES.get(ntype)
                if not node_class:
                    self.node_status[nid] = "error"
                    self.node_errors[nid] = f"未知节点类型: {ntype}"
                    return
                
                instance = node_class(nid, config, self.vp)
                self.node_instances[nid] = instance
                
                self.node_status[nid] = "running"
                self._emit("node_start", {"id": nid, "type": ntype})
                
                result = await instance.run()
                
                if "error" in result and result["error"]:
                    self.node_status[nid] = "error"
                    self.node_errors[nid] = result["error"]
                    self.node_logs[nid].append(f"错误: {result['error']}")
                    self._emit("node_error", {"id": nid, "type": ntype, "error": result["error"]})
                    await self.layers.run_error(nid, ntype, result["error"])
                else:
                    self.node_status[nid] = "success"
                    # 提取输出（不含元字段）
                    output = {k: v for k, v in result.items() 
                             if not k.startswith("_") and k != "type_hints"}
                    self.node_outputs[nid] = output
                    
                    # 更新变量池
                    type_hints = result.get("type_hints", {})
                    self.vp.set(nid, output, type_hints)
                    
                    self.node_logs[nid].append(f"完成: {ntype}")
                    self._emit("node_end", {"id": nid, "type": ntype, "output": output})
                    
                    # SSE 流式输出（LLM 节点）
                    if ntype == "llm" and "text" in output:
                        self._emit("node_stream", {
                            "id": nid, "type": ntype,
                            "content": output.get("text", ""),
                            "done": True,
                        })
                
                # Layer 后置处理
                await self.layers.run_after(nid, ntype, result)
            
            # 就绪节点并行执行
            await asyncio.gather(*[_execute(nid) for nid in ready], return_exceptions=True)
        
        # 最终状态：标记未执行的节点为跳过
        for nid in self.node_map:
            if self.node_status.get(nid) == "pending":
                self.node_status[nid] = "skipped"
                self.node_logs[nid].append("已跳过（未在上游激活路径上）")
        
        has_error = any(s == "error" for s in self.node_status.values())
        self.state = self.STATE_FAILED if has_error else self.STATE_SUCCESS
        self._emit("state_change", {"state": self.state})
        
        # 收集结果
        end_nodes = [n["id"] for n in self.nodes_data if n.get("type") == "end"]
        final_output = {}
        for en in end_nodes:
            if en in self.node_outputs:
                final_output = {**final_output, **self.node_outputs[en]}
        
        node_results = []
        for n in self.nodes_data:
            nid = n["id"]
            node_results.append({
                "id": nid,
                "type": n.get("type", ""),
                "label": n.get("data", {}).get("label", nid),
                "status": self.node_status.get(nid, "pending"),
                "output": str(self.node_outputs.get(nid, {}))[:200],
                "error": self.node_errors.get(nid, ""),
                "logs": self.node_logs.get(nid, []),
            })
        
        return {
            "status": self.state,
            "final_output": final_output,
            "node_results": node_results,
            "variables": self.vp.all_variables,
        }


# ══════════════════════════════════════════════
# 第四部分：DSL 导入导出
# ══════════════════════════════════════════════

def export_to_dsl(nodes: list[dict], edges: list[dict], name: str = "", description: str = "") -> str:
    """导出为 DSL YAML 格式"""
    dsl = {
        "version": "2.0",
        "name": name or "未命名工作流",
        "description": description or "",
        "graph": {
            "nodes": [],
            "edges": [],
        },
    }
    
    for n in nodes:
        node_data = n.get("data", {})
        dsl_node = {
            "id": n["id"],
            "type": node_data.get("type", "llm"),
            "label": node_data.get("label", ""),
            "position": {"x": n.get("position", {}).get("x", 0), "y": n.get("position", {}).get("y", 0)},
            "config": node_data.get("config", {}),
        }
        dsl["graph"]["nodes"].append(dsl_node)
    
    for e in edges:
        dsl_edge = {
            "source": e["source"],
            "target": e["target"],
        }
        if e.get("sourceHandle") and e["sourceHandle"] != "output":
            dsl_edge["sourceHandle"] = e["sourceHandle"]
        if e.get("targetHandle") and e["targetHandle"] != "input":
            dsl_edge["targetHandle"] = e["targetHandle"]
        dsl["graph"]["edges"].append(dsl_edge)
    
    return json.dumps(dsl, ensure_ascii=False, indent=2)


def import_from_dsl(dsl_input: str) -> dict:
    """从 DSL 导入（兼容多种格式：原生 JSON DSL / Dify YAML/JSON DSL）"""
    import json

    # 尝试解析为 JSON
    if isinstance(dsl_input, str):
        dsl_input = dsl_input.strip()
        # 尝试 YAML 解析（如果安装了 PyYAML 且看起来是 YAML）
        if not dsl_input.startswith("{"):
            try:
                import yaml
                data = yaml.safe_load(dsl_input)
            except ImportError:
                # 没有 yaml 库，尝试当 JSON 解析
                try:
                    data = json.loads(dsl_input)
                except json.JSONDecodeError:
                    return {"error": "无法解析文件格式，请使用 JSON 或 YAML"}
            except Exception:
                return {"error": "YAML 解析失败"}
        else:
            try:
                data = json.loads(dsl_input)
            except json.JSONDecodeError:
                return {"error": "JSON 格式错误"}
    else:
        data = dsl_input

    # 兼容多种 DSL 格式
    graph_source = None
    name = data.get("name", "")
    description = data.get("description", "")

    # 1. 原生格式: { "graph": { "nodes": [...], "edges": [...] } }
    if "graph" in data and isinstance(data["graph"], dict):
        graph_source = data["graph"]
    # 2. Dify 格式: { "workflow": { "nodes": [...], "edges": [...] } }
    elif "workflow" in data and isinstance(data["workflow"], dict):
        wf = data["workflow"]
        if "nodes" in wf or "edges" in wf:
            graph_source = wf
            if not name:
                name = data.get("app", {}).get("name", "") or wf.get("title", "")
    # 3. 顶层节点/边格式: { "nodes": [...], "edges": [...] }
    elif "nodes" in data:
        graph_source = data

    if graph_source is None:
        return {"error": "无法识别的 DSL 格式：找不到节点数据"}

    nodes_raw = graph_source.get("nodes", [])
    edges_raw = graph_source.get("edges", [])

    nodes = []
    for n in nodes_raw:
        nid = n.get("id", "")
        ntype = n.get("type", "llm")
        # Dify 格式: 节点用 "title" 作标签，我们用 "label"
        nlabel = n.get("label", n.get("title", nid))
        npos = n.get("position", {})
        nconfig = n.get("config", n.get("data", {}))
        nodes.append({
            "id": nid,
            "type": "base",
            "position": {"x": npos.get("x", 0), "y": npos.get("y", 0)},
            "data": {
                "label": nlabel,
                "type": ntype,
                "config": nconfig,
            },
        })

    edges = []
    for e in edges_raw:
        eid = e.get("id", f"e_{e.get('source','')}_{e.get('target','')}")
        edges.append({
            "id": eid,
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "sourceHandle": e.get("sourceHandle", e.get("sourceHandle", "output")),
            "targetHandle": e.get("targetHandle", e.get("targetHandle", "input")),
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "name": name or "导入的工作流",
        "description": description,
    }


# ══════════════════════════════════════════════
# 第五部分：数据库操作
# ══════════════════════════════════════════════

def _init_db():
    from core import storage
    conn = storage._get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                trigger TEXT DEFAULT 'manual',
                input TEXT DEFAULT '{}',
                output TEXT DEFAULT '',
                node_results TEXT DEFAULT '[]',
                variables TEXT DEFAULT '[]',
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id)
            );
            CREATE TABLE IF NOT EXISTS workflow_versions (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT DEFAULT 'draft',
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id)
            );
            CREATE TABLE IF NOT EXISTS workflow_webhooks (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                method TEXT DEFAULT 'POST',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id)
            );
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT '通用',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                author TEXT DEFAULT 'Naixi',
                usage_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS automations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                workflow_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                config TEXT DEFAULT '{}',
                status TEXT DEFAULT 'active',
                last_run TEXT,
                last_result TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS automation_runs (
                id TEXT PRIMARY KEY,
                automation_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                trigger TEXT DEFAULT 'manual',
                input TEXT DEFAULT '{}',
                output TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _get_all_workflows() -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_workflow(wid: str) -> Optional[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        row = conn.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _save_workflow(wid: str, name: str, description: str, nodes: list, edges: list, dsl: str = "", status: str = "draft"):
    from core import storage
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    try:
        if not dsl:
            dsl = export_to_dsl(nodes, edges, name, description)
        conn.execute("""
            INSERT OR REPLACE INTO workflows (id, name, description, nodes, edges, dsl, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM workflows WHERE id=?), ?), ?)
        """, (wid, name, description, json.dumps(nodes, ensure_ascii=False),
              json.dumps(edges, ensure_ascii=False), dsl, wid, now, now))
        
        # 创建版本记录
        version = 1
        existing = conn.execute("SELECT MAX(version) as v FROM workflow_versions WHERE workflow_id=?", (wid,)).fetchone()
        if existing and existing["v"]:
            version = existing["v"] + 1
        conn.execute("""
            INSERT INTO workflow_versions (id, workflow_id, version, status, name, description, nodes, edges, dsl, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (f"{wid}_v{version}", wid, version, status, name, description,
              json.dumps(nodes, ensure_ascii=False), json.dumps(edges, ensure_ascii=False), dsl, now))
        
        conn.commit()
        return True, version
    except Exception as e:
        log.error("保存工作流失败: %s", e)
        return False, 0
    finally:
        conn.close()


def _get_version(workflow_id: str, version: int = None) -> Optional[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        if version:
            row = conn.execute("SELECT * FROM workflow_versions WHERE workflow_id=? AND version=?", (workflow_id, version)).fetchone()
        else:
            row = conn.execute("SELECT * FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC LIMIT 1", (workflow_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _list_versions(workflow_id: str) -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute("SELECT id, version, status, created_at FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC", (workflow_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _publish_workflow(workflow_id: str) -> dict:
    from core import storage
    conn = storage._get_conn()
    try:
        # 将最新草稿标记为已发布
        conn.execute("""
            UPDATE workflow_versions SET status='published'
            WHERE workflow_id=? AND version=(SELECT MAX(version) FROM workflow_versions WHERE workflow_id=?)
        """, (workflow_id, workflow_id))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def _register_webhook(workflow_id: str, endpoint: str, method: str = "POST") -> dict:
    from core import storage
    import uuid
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    try:
        webhook_id = uuid.uuid4().hex[:12]
        conn.execute("""
            INSERT OR REPLACE INTO workflow_webhooks (id, workflow_id, endpoint, method, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (webhook_id, workflow_id, endpoint, method, now))
        conn.commit()
        return {"webhook_id": webhook_id, "endpoint": endpoint}
    finally:
        conn.close()


# ── 自动化管理 ──

def _list_automations() -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute("SELECT * FROM automations ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _create_automation(name: str, description: str, workflow_id: str,
                       trigger_type: str, config: dict) -> dict:
    from core import storage
    import uuid
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    aid = uuid.uuid4().hex[:12]
    try:
        conn.execute("""
            INSERT INTO automations (id, name, description, workflow_id, trigger_type, config, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (aid, name, description, workflow_id, trigger_type, json.dumps(config, ensure_ascii=False), now, now))
        conn.commit()
        return {"id": aid, "success": True}
    finally:
        conn.close()


def _update_automation(aid: str, **kwargs) -> dict:
    from core import storage
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    fields = []
    vals = []
    for k, v in kwargs.items():
        if k in ("name", "description", "workflow_id", "trigger_type", "status"):
            fields.append(f"{k}=?")
            vals.append(v)
        elif k == "config":
            fields.append("config=?")
            vals.append(json.dumps(v, ensure_ascii=False))
    if fields:
        fields.append("updated_at=?")
        vals.append(now)
        vals.append(aid)
        conn.execute(f"UPDATE automations SET {', '.join(fields)} WHERE id=?", tuple(vals))
        conn.commit()
    return {"success": True}


def _delete_automation(aid: str) -> dict:
    from core import storage
    conn = storage._get_conn()
    try:
        conn.execute("DELETE FROM automations WHERE id=?", (aid,))
        conn.execute("DELETE FROM automation_runs WHERE automation_id=?", (aid,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def _get_automation_runs(aid: str, limit: int = 20) -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM automation_runs WHERE automation_id=? ORDER BY created_at DESC LIMIT ?",
            (aid, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _record_automation_run(aid: str, wid: str, status: str, trigger: str,
                           input_data: str, output: str):
    from core import storage
    import uuid
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    rid = uuid.uuid4().hex[:12]
    try:
        conn.execute("""
            INSERT INTO automation_runs (id, automation_id, workflow_id, status, trigger, input, output, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (rid, aid, wid, status, trigger, input_data, output, now, now if status in ("success","failed") else None))
        conn.commit()
    finally:
        conn.close()


# ── 自动化调度器（简版Cron）──

_scheduler_task = None

def start_automation_scheduler(loop=None):
    """启动自动化定时调度器（每60秒检查一次）"""
    global _scheduler_task
    import asyncio
    
    async def _check():
        while True:
            try:
                automations = _list_automations()
                for a in automations:
                    if a["status"] != "active":
                        continue
                    if a["trigger_type"] == "schedule":
                        # 简易调度：每分钟检查是否需要触发
                        config = json.loads(a.get("config", "{}"))
                        # 简单地按 cron 格式执行
                        pass
            except Exception as e:
                log.warning("[调度器] 检查失败: %s", e)
            await asyncio.sleep(60)
    
    if loop:
        _scheduler_task = asyncio.ensure_future(_check(), loop=loop)
    else:
        _scheduler_task = asyncio.ensure_future(_check())


# ── 模板管理 ──

# 预置模板
BUILTIN_TEMPLATES = [
    {
        "name": "文本摘要",
        "description": "对输入文本进行AI摘要",
        "category": "LLM",
        "tags": "摘要,LLM,文本处理",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 200}, "data": {"label": "LLM摘要", "type": "llm", "config": {"prompt": "请对以下内容进行简要摘要：\n\n{{s1.output}}", "model": "qwen3-32b"}}},
            {"id": "e1", "type": "end", "position": {"x": 510, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "l1"}, {"id": "x2", "source": "l1", "target": "e1"}],
    },
    {
        "name": "搜索+问答",
        "description": "先搜索网络再回答问题",
        "category": "搜索",
        "tags": "搜索,问答,工具",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "t1", "type": "tool", "position": {"x": 280, "y": 160}, "data": {"label": "搜索", "type": "tool", "config": {"tool_name": "search_web", "tool_args": {"query": "{s1.output}"}}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 300}, "data": {"label": "回答", "type": "llm", "config": {"prompt": "根据以下搜索结果回答问题：\n\n搜索结果：{{t1.result}}\n问题：{{s1.output}}", "model": "qwen3-32b"}}},
            {"id": "e1", "type": "end", "position": {"x": 510, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "t1"}, {"id": "x2", "source": "t1", "target": "e1"}, {"id": "x3", "source": "s1", "target": "l1"}, {"id": "x4", "source": "l1", "target": "e1"}],
    },
    {
        "name": "分类处理",
        "description": "根据LLM分类结果走不同处理路径",
        "category": "流程",
        "tags": "分类,条件,分支",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "q1", "type": "question-classifier", "position": {"x": 280, "y": 200}, "data": {"label": "分类", "type": "question-classifier", "config": {"query": "{s1.output}", "categories": [{"name": "技术", "description": "技术问题"}, {"name": "生活", "description": "日常生活"}]}}},
            {"id": "l1", "type": "llm", "position": {"x": 510, "y": 120}, "data": {"label": "技术回答", "type": "llm", "config": {"prompt": "用专业角度回答技术问题：{s1.output}"}}},
            {"id": "l2", "type": "llm", "position": {"x": 510, "y": 320}, "data": {"label": "日常回答", "type": "llm", "config": {"prompt": "用轻松语气回答：{s1.output}"}}},
            {"id": "e1", "type": "end", "position": {"x": 740, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [
            {"id": "x1", "source": "s1", "target": "q1"},
            {"id": "x2", "source": "q1", "target": "l1", "sourceHandle": "技术"},
            {"id": "x3", "source": "q1", "target": "l2", "sourceHandle": "生活"},
            {"id": "x4", "source": "l1", "target": "e1"},
            {"id": "x5", "source": "l2", "target": "e1"},
        ],
    },
    {
        "name": "数据提取",
        "description": "从文本中提取结构化信息并格式化输出",
        "category": "数据处理",
        "tags": "提取,JSON,模板",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "p1", "type": "parameter-extractor", "position": {"x": 280, "y": 200}, "data": {"label": "提取参数", "type": "parameter-extractor", "config": {"query": "{s1.output}", "parameters": [{"name": "date", "type": "string", "description": "日期"}, {"name": "amount", "type": "number", "description": "金额"}, {"name": "category", "type": "string", "description": "类别"}]}}},
            {"id": "t1", "type": "template-transform", "position": {"x": 510, "y": 200}, "data": {"label": "格式化", "type": "template-transform", "config": {"template": "日期: {{p1.parameters.date}}\n金额: {{p1.parameters.amount}}\n类别: {{p1.parameters.category}}"}}},
            {"id": "e1", "type": "end", "position": {"x": 740, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "p1"}, {"id": "x2", "source": "p1", "target": "t1"}, {"id": "x3", "source": "t1", "target": "e1"}],
    },
    {
        "name": "智能客服",
        "description": "基于 LLM 的智能客服机器人，支持多轮对话和问题分类",
        "category": "LLM",
        "tags": "客服,对话,LLM",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "q1", "type": "question-classifier", "position": {"x": 280, "y": 200}, "data": {"label": "问题分类", "type": "question-classifier", "config": {"query": "{s1.output}", "categories": [{"name": "售后", "description": "售后问题"}, {"name": "售前", "description": "售前咨询"}, {"name": "其他", "description": "其他"}]}}},
            {"id": "l1", "type": "llm", "position": {"x": 510, "y": 120}, "data": {"label": "售后回复", "type": "llm", "config": {"prompt": "作为售后客服，回答用户问题：{s1.output}"}}},
            {"id": "l2", "type": "llm", "position": {"x": 510, "y": 300}, "data": {"label": "售前回复", "type": "llm", "config": {"prompt": "作为售前顾问，回答用户咨询：{s1.output}"}}},
            {"id": "e1", "type": "end", "position": {"x": 740, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [
            {"id": "x1", "source": "s1", "target": "q1"},
            {"id": "x2", "source": "q1", "target": "l1", "sourceHandle": "售后"},
            {"id": "x3", "source": "q1", "target": "l2", "sourceHandle": "售前"},
            {"id": "x4", "source": "l1", "target": "e1"},
            {"id": "x5", "source": "l2", "target": "e1"},
        ],
    },
    {
        "name": "内容翻译",
        "description": "多语言翻译工作流，支持文本翻译和语言检测",
        "category": "LLM",
        "tags": "翻译,LLM,多语言",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 200}, "data": {"label": "翻译", "type": "llm", "config": {"prompt": "将以下内容翻译为目标语言：\n原文：{{s1.output}}\n翻译：", "model": "qwen3-32b"}}},
            {"id": "e1", "type": "end", "position": {"x": 510, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "l1"}, {"id": "x2", "source": "l1", "target": "e1"}],
    },
    {
        "name": "文档问答",
        "description": "上传文档后基于 RAG 进行智能问答",
        "category": "知识库",
        "tags": "文档,RAG,问答",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "k1", "type": "knowledge", "position": {"x": 280, "y": 200}, "data": {"label": "检索知识", "type": "knowledge", "config": {"query": "{s1.output}", "top_k": 3}}},
            {"id": "l1", "type": "llm", "position": {"x": 510, "y": 200}, "data": {"label": "回答", "type": "llm", "config": {"prompt": "基于以下资料回答问题：\n\n资料：{{k1.result}}\n问题：{{s1.output}}"}}},
            {"id": "e1", "type": "end", "position": {"x": 740, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "k1"}, {"id": "x2", "source": "k1", "target": "l1"}, {"id": "x3", "source": "l1", "target": "e1"}],
    },
    {
        "name": "SEO 优化",
        "description": "自动生成 SEO 友好的标题、描述和关键词",
        "category": "内容创作",
        "tags": "SEO,内容,创作",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 120}, "data": {"label": "生成标题", "type": "llm", "config": {"prompt": "为以下内容生成5个SEO优化的标题：\n{{s1.output}}"}}},
            {"id": "l2", "type": "llm", "position": {"x": 280, "y": 300}, "data": {"label": "生成描述", "type": "llm", "config": {"prompt": "为以下内容生成SEO描述和关键词：\n{{s1.output}}"}}},
            {"id": "e1", "type": "end", "position": {"x": 510, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "l1"}, {"id": "x2", "source": "s1", "target": "l2"}, {"id": "x3", "source": "l1", "target": "e1"}, {"id": "x4", "source": "l2", "target": "e1"}],
    },
    {
        "name": "内容审核",
        "description": "对输入内容进行安全审核和敏感信息检测",
        "category": "安全",
        "tags": "审核,安全,合规",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 200}, "data": {"label": "内容审核", "type": "llm", "config": {"prompt": "请审核以下内容，判断是否包含：1.敏感信息 2.违法违规 3.垃圾广告。请逐项判断并给出结论。\n\n内容：{{s1.output}}"}}},
            {"id": "c1", "type": "condition", "position": {"x": 510, "y": 200}, "data": {"label": "判断结果", "type": "condition", "config": {"expression": "input.get('result', '').find('通过') >= 0"}}},
            {"id": "e1", "type": "end", "position": {"x": 740, "y": 120}, "data": {"label": "通过", "type": "end", "config": {}}},
            {"id": "e2", "type": "end", "position": {"x": 740, "y": 320}, "data": {"label": "不通过", "type": "end", "config": {}}},
        ],
        "edges": [
            {"id": "x1", "source": "s1", "target": "l1"},
            {"id": "x2", "source": "l1", "target": "c1"},
            {"id": "x3", "source": "c1", "target": "e1", "sourceHandle": "true"},
            {"id": "x4", "source": "c1", "target": "e2", "sourceHandle": "false"},
        ],
    },
    {
        "name": "AI 写作",
        "description": "长文本写作辅助，支持续写、改写、润色等多种模式",
        "category": "内容创作",
        "tags": "写作,内容,创作",
        "nodes": [
            {"id": "s1", "type": "start", "position": {"x": 50, "y": 200}, "data": {"label": "开始", "type": "start", "config": {}}},
            {"id": "l1", "type": "llm", "position": {"x": 280, "y": 200}, "data": {"label": "写作", "type": "llm", "config": {"prompt": "请根据以下要求进行写作：\n模式：{{s1.output}}\n请输出完整的文章。", "model": "qwen3-32b"}}},
            {"id": "e1", "type": "end", "position": {"x": 510, "y": 200}, "data": {"label": "结束", "type": "end", "config": {}}},
        ],
        "edges": [{"id": "x1", "source": "s1", "target": "l1"}, {"id": "x2", "source": "l1", "target": "e1"}],
    },
]


def _init_templates():
    """初始化预置模板到数据库"""
    from core import storage
    conn = storage._get_conn()
    try:
        now = datetime.now().isoformat()
        for i, tpl in enumerate(BUILTIN_TEMPLATES):
            tid = f"tpl_{i}"
            nodes_json = json.dumps(tpl["nodes"], ensure_ascii=False)
            edges_json = json.dumps(tpl["edges"], ensure_ascii=False)
            dsl = export_to_dsl(tpl["nodes"], tpl["edges"], tpl["name"], tpl["description"])
            conn.execute("""
                INSERT OR REPLACE INTO workflow_templates (id, name, description, category, nodes, edges, dsl, tags, author, usage_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Naixi', 0, ?)
            """, (tid, tpl["name"], tpl["description"], tpl["category"], nodes_json, edges_json, dsl, tpl.get("tags", ""), now))
        conn.commit()
    finally:
        conn.close()


def _list_templates(category: str = "") -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        if category:
            rows = conn.execute("SELECT * FROM workflow_templates WHERE category=? ORDER BY usage_count DESC, created_at DESC", (category,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM workflow_templates ORDER BY usage_count DESC, created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _use_template(tid: str) -> Optional[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        conn.execute("UPDATE workflow_templates SET usage_count = usage_count + 1 WHERE id=?", (tid,))
        row = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (tid,)).fetchone()
        conn.commit()
        if row:
            tpl = dict(row)
            tpl["nodes"] = json.loads(tpl.get("nodes", "[]"))
            tpl["edges"] = json.loads(tpl.get("edges", "[]"))
            return tpl
        return None
    finally:
        conn.close()


def _get_template_categories() -> list[str]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT category FROM workflow_templates ORDER BY category").fetchall()
        return [r["category"] for r in rows]
    finally:
        conn.close()



def _delete_workflow(wid: str):
    from core import storage
    conn = storage._get_conn()
    try:
        conn.execute("DELETE FROM workflows WHERE id=?", (wid,))
        conn.execute("DELETE FROM workflow_runs WHERE workflow_id=?", (wid,))
        conn.commit()
    finally:
        conn.close()


def _get_runs(wid: str, limit: int = 10) -> list[dict]:
    from core import storage
    conn = storage._get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?",
            (wid, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _save_run(run_id: str, workflow_id: str, status: str, trigger: str,
              input_data: str, output: str, node_results: list, variables: list):
    from core import storage
    conn = storage._get_conn()
    now = datetime.now().isoformat()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO workflow_runs
            (id, workflow_id, status, trigger, input, output, node_results, variables, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, workflow_id, status, trigger, input_data, output,
              json.dumps(node_results, ensure_ascii=False),
              json.dumps(variables, ensure_ascii=False),
              now if status == "running" else None,
              now if status in ("success", "failed") else None))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════
# 第六部分：API 处理函数
# ══════════════════════════════════════════════

def init_workflow_tables():
    _init_db()
    _init_templates()


async def api_list_workflows() -> list[dict]:
    wfs = _get_all_workflows()
    simplified = []
    for w in wfs:
        nodes = json.loads(w.get("nodes", "[]"))
        simplified.append({
            "id": w["id"],
            "name": w.get("name", "未命名"),
            "description": w.get("description", ""),
            "node_count": len(nodes),
            "updated_at": w.get("updated_at", ""),
        })
    return simplified


async def api_get_workflow(wid: str) -> Optional[dict]:
    wf = _get_workflow(wid)
    if wf:
        wf["nodes"] = json.loads(wf.get("nodes", "[]"))
        wf["edges"] = json.loads(wf.get("edges", "[]"))
    return wf


async def api_save_workflow(wid: str, name: str, description: str,
                             nodes: list, edges: list, dsl: str = "") -> dict:
    if not dsl:
        dsl = export_to_dsl(nodes, edges, name, description)
    ok, version = _save_workflow(wid, name, description, nodes, edges, dsl)
    return {"success": ok, "id": wid, "version": version, "dsl": dsl}


async def api_publish_workflow(wid: str) -> dict:
    return _publish_workflow(wid)


async def api_list_versions(wid: str) -> list[dict]:
    return _list_versions(wid)


async def api_register_webhook(wid: str, endpoint: str, method: str = "POST") -> dict:
    return _register_webhook(wid, endpoint, method)


async def api_submit_human_input(pending_key: str, value: str) -> dict:
    return {"success": True, "pending_key": pending_key, "value": value}


async def api_list_templates(category: str = "") -> list[dict]:
    return _list_templates(category)


async def api_use_template(tid: str) -> Optional[dict]:
    return _use_template(tid)


async def api_template_categories() -> list[str]:
    return _get_template_categories()


# 在线模板搜索缓存
_online_template_cache: dict = {"data": [], "time": 0.0, "ttl": 3600}  # 1 小时缓存

async def api_search_online_templates(request) -> list[dict]:
    """从网络搜索工作流模板（带 5 分钟缓存）"""
    query = request.query.get("q", "").strip().lower()
    import time

    # 缓存命中（无关键词时直接用缓存）
    now = time.time()
    if not query and _online_template_cache["data"] and (now - _online_template_cache["time"]) < _online_template_cache["ttl"]:
        return _online_template_cache["data"]

    templates = []

    import aiohttp
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "NaixiBot/1.0"}

    async def _fetch_dir(session, full_name, path=""):
        """递归获取仓库目录中的 DSL 文件"""
        url = f"https://api.github.com/repos/{full_name}/contents/{path}" if path else \
              f"https://api.github.com/repos/{full_name}/contents"
        try:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return []
                items = await resp.json()
                if not isinstance(items, list):
                    return []
                results = []
                for item in items:
                    name = item.get("name", "")
                    if item.get("type") == "dir":
                        sub_path = f"{path}/{name}" if path else name
                        if sub_path.count("/") < 3:  # 限制递归深度
                            results.extend(await _fetch_dir(session, full_name, sub_path))
                    elif name.endswith((".json", ".yaml", ".yml", ".dsl")):
                        results.append({
                            "name": name,
                            "path": f"{path}/{name}" if path else name,
                            "url": item.get("download_url", ""),
                        })
                return results
        except:
            return []

    async with aiohttp.ClientSession(headers=headers) as session:
        # 先并发搜索已知的模板仓库
        known_repos = [
            ("aircrushin/awesome-dify-workflow", 35),
            ("svcvit/Awesome-Dify-Workflow", 10656),
            ("Paulzhang2023/Dify-DSL-collection", 28),
            ("yzmw123/dify-workflow-dsl-skill", 35),
            ("shamspias/awesome-dify-agents", 3),
        ]

        known_repos_list = [r[0] for r in known_repos]

        # 并发获取所有已知仓库的文件列表
        repo_files = await asyncio.gather(*[
            _fetch_dir(session, repo_name) for repo_name in known_repos_list
        ], return_exceptions=True)

        for (repo_name, stars), files in zip(known_repos, repo_files):
            if isinstance(files, Exception) or not files:
                continue
            for f in files:
                label = f["name"].rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
                if query and query not in label.lower() and query not in f["name"].lower():
                    continue
                templates.append({
                    "id": f"{repo_name}/{f['path']}",
                    "name": label,
                    "description": f"来自 {repo_name} 模板集",
                    "category": "GitHub 模板",
                    "source": "github_file",
                    "url": f["url"],
                    "usage_count": stars,
                })

        # 再搜索更多仓库（如果已知仓库不够）
        if not templates or query:
            try:
                search_url = (
                    "https://api.github.com/search/repositories"
                    "?q=dify+DSL+workflow&sort=stars&per_page=20"
                )
                async with session.get(search_url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for repo in data.get("items", []):
                            full_name = repo.get("full_name", "")
                            # 跳过已处理的已知仓库
                            if full_name in known_repos_list:
                                continue
                            name = repo.get("name", "")
                            desc = repo.get("description", "") or ""
                            stars = repo.get("stargazers_count", 0)

                            if query and query not in name.lower() and query not in desc.lower():
                                continue

                            files = await _fetch_dir(session, full_name)
                            if files:
                                for f in files:
                                    label = f["name"].rsplit(".", 1)[0].replace("_", " ").replace("-", " ").title()
                                    if query and query not in label.lower():
                                        continue
                                    templates.append({
                                        "id": f"{full_name}/{f['path']}",
                                        "name": label,
                                        "description": f"{desc[:80] or name} ({stars} stars)",
                                        "category": "GitHub 模板",
                                        "source": "github_file",
                                        "url": f["url"],
                                        "usage_count": stars,
                                    })
                            else:
                                templates.append({
                                    "id": full_name,
                                    "name": name.replace("-", " ").replace("_", " ").title(),
                                    "description": f"{desc[:120] or 'Dify 相关工作流'} ({stars} stars)",
                                    "category": "GitHub 仓库",
                                    "source": "github_repo",
                                    "url": repo.get("html_url", ""),
                                    "usage_count": stars,
                                })
            except:
                pass

    # 更新缓存
    if not query:
        _online_template_cache["data"] = templates
        _online_template_cache["time"] = now

    return templates


# ── 自动化 API ──

async def api_list_automations() -> list[dict]:
    return _list_automations()


async def api_create_automation(name: str, description: str, workflow_id: str,
                                 trigger_type: str, config: dict) -> dict:
    return _create_automation(name, description, workflow_id, trigger_type, config)


async def api_update_automation(aid: str, **kwargs) -> dict:
    return _update_automation(aid, **kwargs)


async def api_delete_automation(aid: str) -> dict:
    return _delete_automation(aid)


async def api_run_automation(aid: str, input_data: dict = None) -> dict:
    """手动触发自动化"""
    automations = _list_automations()
    a = next((a for a in automations if a["id"] == aid), None)
    if not a:
        return {"status": "error", "error": "自动化不存在"}
    
    wid = a["workflow_id"]
    wf = _get_workflow(wid)
    if not wf:
        return {"status": "error", "error": "关联工作流不存在"}
    
    nodes = json.loads(wf.get("nodes", "[]"))
    edges = json.loads(wf.get("edges", "[]"))
    
    _record_automation_run(aid, wid, "running", "manual",
                          json.dumps(input_data or {}, ensure_ascii=False), "")
    
    layers = LayerStack()
    layers.add(ExecutionLimitsLayer())
    layers.add(ObservabilityLayer())
    
    engine = GraphEngine(nodes, edges, input_data or {}, layers=layers)
    result = await engine.run()
    
    output_str = json.dumps(result.get("final_output", {}), ensure_ascii=False)[:500]
    _record_automation_run(aid, wid, result["status"], "manual",
                          json.dumps(input_data or {}, ensure_ascii=False), output_str)
    
    _update_automation(aid, last_run=datetime.now().isoformat(), last_result=result["status"])
    
    return result


async def api_automation_runs(aid: str, limit: int = 20) -> list[dict]:
    return _get_automation_runs(aid, limit)


async def api_delete_workflow(wid: str) -> dict:
    _delete_workflow(wid)
    return {"success": True}


async def api_run_workflow(wid: str, input_data: dict = None) -> dict:
    wf = _get_workflow(wid)
    if not wf:
        return {"status": "error", "error": "工作流不存在"}
    
    nodes = json.loads(wf.get("nodes", "[]"))
    edges = json.loads(wf.get("edges", "[]"))
    
    run_id = uuid.uuid4().hex[:12]
    _save_run(run_id, wid, "running", "manual",
              json.dumps(input_data or {}, ensure_ascii=False), "", [], [])
    
    try:
        layers = LayerStack()
        layers.add(ExecutionLimitsLayer(max_steps=200, max_time=300))
        layers.add(ObservabilityLayer())
        
        engine = GraphEngine(nodes, edges, input_data or {}, layers=layers)
        result = await engine.run()
        
        output_str = json.dumps(result.get("final_output", {}), ensure_ascii=False)[:2000]
        _save_run(run_id, wid, result["status"], "manual",
                  json.dumps(input_data or {}, ensure_ascii=False),
                  output_str, result.get("node_results", []),
                  result.get("variables", []))
        
        result["run_id"] = run_id
        
        # 添加 Layer 统计信息
        for layer in layers._layers:
            if isinstance(layer, ObservabilityLayer):
                result["timings"] = layer.node_timings
        
        return result
    except Exception as e:
        log.error("[工作流] 执行异常: %s", e)
        _save_run(run_id, wid, "failed", "manual",
                  json.dumps(input_data or {}, ensure_ascii=False),
                  str(e), [], [])
        return {"status": "failed", "error": str(e), "run_id": run_id}


async def api_get_runs(wid: str, limit: int = 10) -> list[dict]:
    return _get_runs(wid, limit)


async def api_get_node_types() -> dict:
    return dict(NODE_TYPE_INFO)


async def api_export_dsl(wid: str) -> dict:
    wf = _get_workflow(wid)
    if not wf:
        return {"error": "工作流不存在"}
    dsl = wf.get("dsl", "")
    if not dsl:
        nodes = json.loads(wf.get("nodes", "[]"))
        edges = json.loads(wf.get("edges", "[]"))
        dsl = export_to_dsl(nodes, edges, wf.get("name", ""), wf.get("description", ""))
    return {"dsl": dsl}


async def api_import_dsl(dsl_str: str) -> dict:
    try:
        data = import_from_dsl(dsl_str)
        return data
    except Exception as e:
        return {"error": f"DSL 解析失败: {e}"}
