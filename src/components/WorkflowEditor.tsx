import { useState, useCallback, useRef, useEffect } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  useReactFlow,
  addEdge,
  type Connection,
  type Node,
  type Edge,
  type NodeTypes,
  type OnNodesChange,
  type OnEdgesChange,
  Panel,
  Handle,
  type NodeProps,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { apiGet, apiPost } from "@/lib/api";
import {
  Play, Save, Trash2, Plus, X, ChevronRight, ChevronDown, RefreshCw, Variable,
  Bot, Code, Globe, BookOpen, GitBranch, Wrench,
  Square, PlayCircle, FileText, List, Filter, Equal,
  Combine, MessageSquare, RotateCcw, File, FileType, Clock,
} from "lucide-react";

// 节点图标映射
const NODE_ICONS: Record<string, React.ReactNode> = {
  start: <PlayCircle size={16} />,
  end: <Square size={16} />,
  llm: <Bot size={16} />,
  tool: <Wrench size={16} />,
  code: <Code size={16} />,
  condition: <GitBranch size={16} />,
  http: <Globe size={16} />,
  knowledge: <BookOpen size={16} />,
  iteration: <RotateCcw size={16} />,
  "template-transform": <FileType size={16} />,
  "parameter-extractor": <List size={16} />,
  "question-classifier": <GitBranch size={16} />,
  "document-extractor": <File size={16} />,
  assigner: <Equal size={16} />,
  "variable-aggregator": <Combine size={16} />,
  "list-operator": <Filter size={16} />,
  answer: <MessageSquare size={16} />,
  loop: <RotateCcw size={16} />,
};

const NODE_COLORS: Record<string, string> = {
  start: "border-emerald-400 bg-emerald-50",
  end: "border-gray-400 bg-gray-50",
  llm: "border-indigo-400 bg-indigo-50",
  tool: "border-amber-400 bg-amber-50",
  code: "border-blue-400 bg-blue-50",
  condition: "border-red-400 bg-red-50",
  http: "border-violet-400 bg-violet-50",
  knowledge: "border-teal-400 bg-teal-50",
  iteration: "border-pink-400 bg-pink-50",
  "template-transform": "border-orange-400 bg-orange-50",
  "parameter-extractor": "border-violet-400 bg-violet-50",
  "question-classifier": "border-pink-400 bg-pink-50",
  "document-extractor": "border-teal-400 bg-teal-50",
  assigner: "border-cyan-400 bg-cyan-50",
  "variable-aggregator": "border-sakura-400 bg-sakura-50",
  "list-operator": "border-sky-400 bg-sky-50",
  answer: "border-green-400 bg-green-50",
  loop: "border-rose-400 bg-rose-50",
};

// ── 自定义节点组件 ──

function BaseNode({ data, selected }: NodeProps) {
  const ntype = (data as any).type || "llm";
  const colorClass = (NODE_COLORS as any)[ntype] || "border-gray-300 bg-gray-50";
  const icon = (NODE_ICONS as any)[ntype] || <Wrench size={16} />;
  const label = (data as any).label || ntype;
  const hasInput = ntype !== "start";
  const hasOutput = ntype !== "end";
  const isCondition = ntype === "condition";
  const status = (data as any)?.status || "";

  const statusDot = status === "running" ? (
    <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-amber-400 border-2 border-white animate-ping" />
  ) : status === "success" ? (
    <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-emerald-400 border-2 border-white" />
  ) : status === "error" ? (
    <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-red-400 border-2 border-white" />
  ) : null;

  const statusBorder = status === "running" ? "border-amber-400" :
    status === "success" ? "border-emerald-400" :
    status === "error" ? "border-red-400" : "";

  return (
    <div className={`relative px-3 py-2 rounded-xl border-2 min-w-[160px] shadow-sm ${colorClass} ${selected ? "ring-2 ring-sakura-400" : ""} ${statusBorder}`}>
      {statusDot}
      {hasInput && <Handle type="target" position={Position.Left} className="!w-3 !h-3 !bg-sakura-300 !border-2 !border-white" />}
      <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
        <span className="text-gray-500">{icon}</span>
        <span>{label}</span>
      </div>
      {data && (data as any).config && (
        <div className="mt-1 text-[10px] text-gray-400 truncate max-w-[140px]">
          {Object.entries((data as any).config || {}).slice(0, 2).map(([k, v]) => (
            <div key={k} className="truncate">{k}: {String(v).slice(0, 20)}</div>
          ))}
        </div>
      )}
      {isCondition ? (
        <>
          <Handle type="source" position={Position.Bottom} id="true" className="!w-2 !h-2 !bg-emerald-400 !border-2 !border-white !left-[30%]" />
          <Handle type="source" position={Position.Bottom} id="false" className="!w-2 !h-2 !bg-red-400 !border-2 !border-white !left-[70%]" />
        </>
      ) : hasOutput ? (
        <Handle type="source" position={Position.Right} className="!w-3 !h-3 !bg-sakura-300 !border-2 !border-white" />
      ) : null}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  base: BaseNode,
};

// ── 默认节点 ──

const DEFAULT_NODES: Node[] = [
  {
    id: "start_1",
    type: "base",
    position: { x: 50, y: 250 },
    data: { label: "开始", type: "start", config: {} },
  },
  {
    id: "end_1",
    type: "base",
    position: { x: 650, y: 250 },
    data: { label: "结束", type: "end", config: {} },
  },
];

// ── 节点面板 ──

const PALETTE_ITEMS = [
  { type: "llm", label: "LLM", icon: <Bot size={14} />, color: "border-indigo-400 bg-indigo-50" },
  { type: "agent", label: "智能体", icon: <Bot size={14} />, color: "border-rose-400 bg-rose-50" },
  { type: "tool", label: "工具", icon: <Wrench size={14} />, color: "border-amber-400 bg-amber-50" },
  { type: "code", label: "代码", icon: <Code size={14} />, color: "border-blue-400 bg-blue-50" },
  { type: "condition", label: "条件分支", icon: <GitBranch size={14} />, color: "border-red-400 bg-red-50" },
  { type: "http", label: "HTTP请求", icon: <Globe size={14} />, color: "border-violet-400 bg-violet-50" },
  { type: "knowledge", label: "知识库", icon: <BookOpen size={14} />, color: "border-teal-400 bg-teal-50" },
  { type: "template-transform", label: "模板转换", icon: <FileType size={14} />, color: "border-orange-400 bg-orange-50" },
  { type: "parameter-extractor", label: "参数提取", icon: <List size={14} />, color: "border-violet-400 bg-violet-50" },
  { type: "question-classifier", label: "问题分类", icon: <GitBranch size={14} />, color: "border-pink-400 bg-pink-50" },
  { type: "document-extractor", label: "文档提取", icon: <File size={14} />, color: "border-teal-400 bg-teal-50" },
  { type: "assigner", label: "变量赋值", icon: <Equal size={14} />, color: "border-cyan-400 bg-cyan-50" },
  { type: "list-operator", label: "列表操作", icon: <Filter size={14} />, color: "border-sky-400 bg-sky-50" },
  { type: "iteration", label: "迭代", icon: <RotateCcw size={14} />, color: "border-pink-400 bg-pink-50" },
  { type: "loop", label: "条件循环", icon: <RotateCcw size={14} />, color: "border-rose-400 bg-rose-50" },
  { type: "answer", label: "中间输出", icon: <MessageSquare size={14} />, color: "border-green-400 bg-green-50" },
  { type: "human-input", label: "人工输入", icon: <FileText size={14} />, color: "border-sky-400 bg-sky-50" },
  { type: "variable-aggregator", label: "变量聚合", icon: <Combine size={14} />, color: "border-sakura-400 bg-sakura-50" },
];

function getDefaultConfig(type: string): Record<string, any> {
  switch (type) {
    case "llm": return { prompt: "{input}", model: "qwen3-32b", temperature: 0.7, max_tokens: 4096, system_prompt: "" };
    case "tool": return { tool_name: "", tool_args: {} };
    case "code": return { code: "result = input_data", language: "python" };
    case "condition": return { expression: "True" };
    case "http": return { url: "https://api.example.com", method: "GET", headers: {}, body: "" };
    case "knowledge": return { query: "{input}", top_k: 3 };
    case "iteration": return { items: "[]", mode: "sequential" };
    case "template-transform": return { template: "{{ input }}", variables: {} };
    case "parameter-extractor": return { query: "{input}", parameters: [{ name: "field1", type: "string", description: "" }] };
    case "question-classifier": return { query: "{input}", categories: [{ name: "A", description: "" }, { name: "B", description: "" }] };
    case "document-extractor": return { file_path: "" };
    case "assigner": return { assignments: [{ variable: "output", expression: "input" }] };
    case "variable-aggregator": return { merge_strategy: "overwrite" };
    case "list-operator": return { operation: "filter", expression: "True" };
    case "answer": return { output: "{input}" };
    case "loop": return { condition: "iteration < 10", max_iterations: 10 };
    default: return {};
  }
}

// ── 主组件 ──

export default function WorkflowEditor({ workflowId: initialId }: { workflowId?: string }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(DEFAULT_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [workflowName, setWorkflowName] = useState("新建工作流");
  const [workflowDesc, setWorkflowDesc] = useState("");
  const [workflowId, setWorkflowId] = useState(initialId || "");
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<any>(null);
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [showList, setShowList] = useState(false);
  const [inputData, setInputData] = useState("{}");
  const [showTemplates, setShowTemplates] = useState(false);
  const [templateList, setTemplateList] = useState<any[]>([]);
  const [templateCategories, setTemplateCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [showOnline, setShowOnline] = useState(false);
  const [onlineTemplates, setOnlineTemplates] = useState<any[]>([]);
  const [onlineQuery, setOnlineQuery] = useState("");
  const [onlineSearched, setOnlineSearched] = useState(false);
  const [onlineError, setOnlineError] = useState("");
  const [loadingOnline, setLoadingOnline] = useState(false);
  const [nodeStatuses, setNodeStatuses] = useState<Record<string, string>>({});
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [showVarPanel, setShowVarPanel] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [showRunsPanel, setShowRunsPanel] = useState(false);
  const [runsData, setRunsData] = useState<any[]>([]);
  const [publishResult, setPublishResult] = useState<any>(null);
  const [showWorkflowList, setShowWorkflowList] = useState(false);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // 同步节点执行状态到节点数据（用于节点渲染动画）
  useEffect(() => {
    setNodes(nds => nds.map(n => {
      const st = nodeStatuses[n.id] || "";
      if ((n.data as any)?.status !== st) {
        return { ...n, data: { ...n.data, status: st } };
      }
      return n;
    }));
  }, [nodeStatuses, setNodes]);

  // 加载工作流列表
  useEffect(() => {
    apiGet<any>("/api/workflows").then(d => {
      if (d?.workflows) setWorkflows(d.workflows);
    }).catch(() => {});
    // 加载模板
    apiGet<any>("/api/workflow/templates").then(d => {
      if (d?.templates) setTemplateList(d.templates);
    }).catch(() => {});
    apiGet<any>("/api/workflow/templates/categories").then(d => {
      if (d?.categories) setTemplateCategories(d.categories);
    }).catch(() => {});
  }, []);

  // 加载指定工作流
  useEffect(() => {
    if (initialId) {
      apiGet<any>(`/api/workflows/${initialId}`).then(d => {
        if (d) {
          setWorkflowId(d.id);
          setWorkflowName(d.name);
          setWorkflowDesc(d.description || "");
          try {
            const loadedNodes = typeof d.nodes === "string" ? JSON.parse(d.nodes) : d.nodes;
            const loadedEdges = typeof d.edges === "string" ? JSON.parse(d.edges) : d.edges;
            if (loadedNodes?.length) setNodes(loadedNodes.map((n: any) => ({ ...n, type: "base" })));
            if (loadedEdges?.length) setEdges(loadedEdges);
          } catch {}
        }
      }).catch(() => {});
    }
  }, [initialId]);

  const onConnect = useCallback(
    (params: Connection) => setEdges(eds => addEdge(params, eds)),
    [setEdges]
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  // 保存工作流
  const handleSave = useCallback(async () => {
    const id = workflowId || `wf_${Date.now()}`;
    const payload = {
      id,
      name: workflowName,
      description: workflowDesc,
      nodes: nodes.map(n => ({
        ...n,
        data: {
          ...n.data,
          config: (n.data as any)?.config || getDefaultConfig((n.data as any)?.type || "llm"),
        },
      })),
      edges,
    };
    try {
      const r: any = await apiPost("/api/workflows/save", payload);
      if (r?.success) {
        setWorkflowId(id);
        alert("工作流已保存");
      }
    } catch (e: any) {
      alert("保存失败: " + (e?.message || "未知错误"));
    }
  }, [workflowId, workflowName, workflowDesc, nodes, edges]);

  // 执行工作流
  const handleRun = useCallback(async () => {
    if (!workflowId) {
      await handleSave();
    }
    setRunning(true);
    setRunResult(null);
    try {
      let input = {};
      try { input = JSON.parse(inputData); } catch {}
      const r: any = await apiPost("/api/workflows/run", { id: workflowId, input });
      setRunResult(r);
      if (r?.node_results) {
        const st: Record<string, string> = {};
        r.node_results.forEach((nr: any) => { st[nr.id] = nr.status; });
        setNodeStatuses(st);
      }
    } catch (e: any) {
      setRunResult({ status: "error", error: String(e?.message || e) });
    }
    setRunning(false);
  }, [workflowId, handleSave, inputData]);

  // 使用模板
  const handleUseTemplate = useCallback(async (tid: string) => {
    try {
      const r: any = await apiPost("/api/workflow/templates/use", { id: tid });
      if (r?.nodes) {
        setNodes(r.nodes.map((n: any, i: number) => ({
          ...n,
          type: "base",
          position: n?.position?.x != null ? n.position : { x: 80 + (i % 3) * 200, y: 80 + Math.floor(i / 3) * 120 },
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })));
        setEdges(r.edges || []);
        setWorkflowName(r.name || "来自模板");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setShowTemplates(false);
        setRunResult(null);
      }
    } catch {}
  }, [setNodes, setEdges]);

  // 加载工作流
  const loadWorkflow = useCallback(async (id: string) => {
    try {
      const d = await apiGet<any>(`/api/workflows/${id}`);
      if (!d) {
        alert("未找到该工作流");
        return;
      }
      setWorkflowId(d.id || "");
      setWorkflowName(d.name || "未命名");
      setWorkflowDesc(d.description || "");
      setRunResult(null);
      setNodeStatuses({});
      setSelectedNode(null);

      let parsedNodes: any[] = [];
      let parsedEdges: any[] = [];
      try {
        const rawNodes = typeof d.nodes === "string" ? JSON.parse(d.nodes) : d.nodes;
        const rawEdges = typeof d.edges === "string" ? JSON.parse(d.edges) : d.edges;
        if (Array.isArray(rawNodes)) parsedNodes = rawNodes;
        if (Array.isArray(rawEdges)) parsedEdges = rawEdges;
      } catch (e) {
        console.warn("解析工作流节点数据出错", e);
      }

      if (parsedNodes.length > 0) {
        setNodes(parsedNodes.map((n: any, i: number) => ({
          ...n,
          type: "base",
          position: n?.position?.x != null ? n.position : { x: 80 + (i % 3) * 200, y: 80 + Math.floor(i / 3) * 120 },
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })));
      } else {
        setNodes(DEFAULT_NODES.map(n => ({ ...n })));
      }
      setEdges(parsedEdges);
    } catch (e: any) {
      console.error("加载工作流失败", e);
      alert("加载工作流失败: " + (e?.message || "未知错误"));
    }
  }, [setNodes, setEdges]);

  // 新建工作流
  const handleNew = useCallback(() => {
    setWorkflowId("");
    setWorkflowName("新建工作流");
    setWorkflowDesc("");
    setNodes((DEFAULT_NODES as Node[]).map(n => ({ ...n })));
    setEdges([]);
    setSelectedNode(null);
    setRunResult(null);
    setNodeStatuses({});
  }, [setNodes, setEdges]);

  // 删除工作流
  const handleDelete = useCallback(async () => {
    if (!workflowId) return;
    if (!confirm(`确认删除工作流「${workflowName}」？`)) return;
    try {
      const r: any = await apiPost("/api/workflows/delete", { id: workflowId });
      if (r?.success) {
        handleNew();
        apiGet<any>("/api/workflows").then(d => {
          if (d?.workflows) setWorkflows(d.workflows);
        }).catch(() => {});
      }
    } catch (e: any) {
      alert("删除失败: " + (e?.message || "未知错误"));
    }
  }, [workflowId, workflowName, handleNew, setWorkflows]);

  // 刷新工作流列表
  const handleRefresh = useCallback(() => {
    apiGet<any>("/api/workflows").then(d => {
      if (d?.workflows) setWorkflows(d.workflows);
    }).catch(() => {});
  }, [setWorkflows]);

  // 选择工作流
  const handleSelectWorkflow = useCallback(async (id: string) => {
    setShowWorkflowList(false);
    await loadWorkflow(id);
  }, [loadWorkflow]);

  // 发布工作流为 API
  const handlePublish = useCallback(async () => {
    if (!workflowId) { alert("请先保存工作流"); return; }
    try {
      const r: any = await apiPost("/api/workflows/publish", { id: workflowId });
      setPublishResult(r);
      if (r?.success) {
        alert("工作流已发布\n可通过 API 端点调用");
      }
    } catch (e: any) {
      alert("发布失败: " + (e?.message || "未知错误"));
    }
  }, [workflowId]);

  // 加载运行日志
  const loadRuns = useCallback(async () => {
    if (!workflowId) { setRunsData([]); return; }
    try {
      const r = await apiGet<any>(`/api/workflows/${workflowId}/runs?limit=20`);
      if (r?.runs) setRunsData(r.runs);
    } catch {}
  }, [workflowId]);

  // 打开运行日志面板时自动加载
  const handleToggleRuns = useCallback(() => {
    const next = !showRunsPanel;
    setShowRunsPanel(next);
    if (next && workflowId) loadRuns();
  }, [showRunsPanel, workflowId, loadRuns]);

  // 导入 DSL
  const handleImportDSL = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const r: any = await apiPost("/api/workflows/import", { dsl: text });
      if (r?.nodes) {
        setNodes(r.nodes.map((n: any) => ({
          ...n,
          type: "base",
          position: n.position || { x: 100, y: 200 },
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })));
        setEdges(r.edges || []);
        setWorkflowName(r.name || "导入的工作流");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setRunResult(null);
        setNodeStatuses({});
        alert("导入成功");
      } else if (r?.error) {
        alert("导入失败: " + r.error);
      }
    } catch (e: any) {
      alert("导入失败: " + (e?.message || "文件格式错误"));
    }
    e.target.value = "";
  }, [setNodes, setEdges]);

  // 搜索在线模板（按按钮/回车触发，直接读 input ref 避免闭包陈旧值）
  const handleSearchOnline = useCallback(async () => {
    const q = (searchInputRef.current?.value || "").trim();
    setOnlineQuery(q);
    setOnlineError("");
    if (!q) { setOnlineTemplates([]); setOnlineSearched(false); return; }
    setLoadingOnline(true);
    setOnlineSearched(true);
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 25000);
      const res = await fetch(`${window.location.origin === 'http://localhost:1420' ? '' : 'http://127.0.0.1:9845'}/api/workflow/templates/online?q=${encodeURIComponent(q)}`, {
        signal: controller.signal,
        mode: "cors",
      });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const r = await res.json();
      setOnlineTemplates(Array.isArray(r) ? r : []);
      if (!Array.isArray(r) || r.length === 0) setOnlineError("服务器返回空结果");
    } catch (e: any) {
      console.error("在线模板搜索失败", e);
      setOnlineTemplates([]);
      if (e.name === "AbortError") setOnlineError("请求超时（超过25秒）");
      else if (e.message?.includes("Failed to fetch") || e.message?.includes("NetworkError"))
        setOnlineError("无法连接到后端服务（127.0.0.1:9845）");
      else setOnlineError(`搜索失败: ${e.message || "未知错误"}`);
    }
    setLoadingOnline(false);
  }, []);

  // 从在线地址导入模板
  const handleUseOnlineTemplate = useCallback(async (tpl: any) => {
    if (tpl.source === "github_repo") {
      window.open(tpl.url, "_blank");
      return;
    }
    // github_file: 下载 DSL 并导入
    try {
      const resp = await fetch(tpl.url);
      const text = await resp.text();
      const r: any = await apiPost("/api/workflows/import", { dsl: text });
      if (r?.nodes) {
        setNodes(r.nodes.map((n: any) => ({
          ...n, type: "base",
          position: n.position || { x: 100, y: 200 },
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })));
        setEdges(r.edges || []);
        setWorkflowName(r.name || "在线模板");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setRunResult(null);
        setNodeStatuses({});
        setShowTemplates(false);
        alert("模板导入成功");
      } else if (r?.error) {
        alert("导入失败: " + r.error);
      }
    } catch (e: any) {
      alert("下载模板失败: " + (e?.message || "网络错误"));
    }
  }, [setNodes, setEdges]);

  // 导出 DSL
  const handleExport = useCallback(async () => {
    if (!workflowId) { alert("请先保存工作流"); return; }
    try {
      const r = await apiGet<any>(`/api/workflows/${workflowId}/export`);
      if (r?.dsl) {
        const blob = new Blob([r.dsl], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${workflowName.replace(/[\\/:*?"<>|]/g, "_")}.dsl.json`;
        a.click();
        URL.revokeObjectURL(url);
      } else if (r?.error) {
        alert("导出失败: " + r.error);
      }
    } catch (e: any) {
      alert("导出失败: " + (e?.message || "未知错误"));
    }
  }, [workflowId, workflowName]);

  // 从画板拖拽添加节点
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/reactflow");
      if (!type) return;

      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;

      const position = {
        x: event.clientX - bounds.left - 80,
        y: event.clientY - bounds.top - 20,
      };

      const newNode: Node = {
        id: `${type}_${Date.now()}`,
        type: "base",
        position,
        data: {
          label: PALETTE_ITEMS.find(p => p.type === type)?.label || type,
          type,
          config: getDefaultConfig(type),
        },
      };

      setNodes(nds => [...nds, newNode]);
    },
    [setNodes]
  );

  // 更新选中节点的配置
  const updateNodeConfig = useCallback(
    (key: string, value: any) => {
      if (!selectedNode) return;
      setNodes(nds =>
        nds.map(n =>
          n.id === selectedNode.id
            ? { ...n, data: { ...n.data, config: { ...(n.data as any)?.config, [key]: value } } }
            : n
        )
      );
      setSelectedNode(prev =>
        prev ? { ...prev, data: { ...prev.data, config: { ...(prev.data as any)?.config, [key]: value } } } : null
      );
    },
    [selectedNode, setNodes]
  );

  const updateNodeLabel = useCallback(
    (value: string) => {
      if (!selectedNode) return;
      setNodes(nds =>
        nds.map(n =>
          n.id === selectedNode.id ? { ...n, data: { ...n.data, label: value } } : n
        )
      );
      setSelectedNode(prev =>
        prev ? { ...prev, data: { ...prev.data, label: value } } : null
      );
    },
    [selectedNode, setNodes]
  );

  // 删除选中节点
  const deleteSelectedNode = useCallback(() => {
    if (!selectedNode) return;
    setNodes(nds => nds.filter(n => n.id !== selectedNode.id));
    setEdges(eds => eds.filter((e: any) => e.source !== selectedNode.id && e.target !== selectedNode.id));
    setSelectedNode(null);
  }, [selectedNode, setNodes, setEdges]);

  const startDrag = useCallback(
    (event: React.DragEvent, type: string) => {
      event.dataTransfer.setData("application/reactflow", type);
      event.dataTransfer.effectAllowed = "move";
    },
    []
  );

  // 自动适配视图：处理 display:none → block 切换后视图偏移的问题
  function FitOnShow() {
    const { fitView } = useReactFlow();
    const fitted = useRef(false);

    useEffect(() => {
      fitted.current = false;

      const tryFit = () => {
        const el = document.querySelector('.react-flow');
        const parent = el?.parentElement;
        if (parent && parent.clientWidth > 0 && parent.clientHeight > 0) {
          fitView({ duration: 300 });
          fitted.current = true;
          return true;
        }
        return false;
      };

      // 首次尝试（如果已经可见）
      if (tryFit()) return;

      // 通过 ResizeObserver 等待容器出现实际尺寸
      const el = document.querySelector('.react-flow');
      const parent = el?.parentElement;
      if (!parent) return;

      const observer = new ResizeObserver(() => {
        if (!fitted.current && parent.clientWidth > 0) tryFit();
      });
      observer.observe(parent);

      return () => observer.disconnect();
    }, [fitView]);

    return null;
  }

  return (
    <div className="flex h-full">
      {/* 左侧节点面板 */}
      <div className="w-48 bg-gray-50 border-r border-gray-200 p-3 flex flex-col h-full">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 shrink-0">节点</div>
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex flex-col gap-1 pr-1">
            {PALETTE_ITEMS.map(item => (
              <div
                key={item.type}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-grab active:cursor-grabbing text-xs ${item.color} hover:shadow-sm transition-shadow`}
                draggable
                onDragStart={(e) => startDrag(e, item.type)}
              >
                {item.icon}
                <span>{item.label}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="pt-3 border-t border-gray-200 mt-2 shrink-0">
          <div className="text-xs font-semibold text-gray-500 mb-1">操作</div>
          <button onClick={handleSave} className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs bg-sakura-100 text-sakura-700 hover:bg-sakura-200 transition-colors">
            <Save size={14} /> 保存
          </button>
          <button onClick={handleRun} disabled={running} className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs bg-emerald-100 text-emerald-700 hover:bg-emerald-200 disabled:opacity-50 mt-1 transition-colors">
            <Play size={14} /> {running ? "执行中..." : "执行"}
          </button>
        </div>
      </div>

      {/* 主编辑器区域 */}
      <div className="flex-1 flex flex-col">
        {/* 顶部栏 */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 bg-white">
          {/* 工作流名称 + 切换下拉 */}
          <div className="relative flex items-center">
            <input
              value={workflowName}
              onChange={e => setWorkflowName(e.target.value)}
              className="text-sm font-medium border-none outline-none bg-transparent w-[140px]"
              placeholder="工作流名称"
            />
            <button
              onClick={() => setShowWorkflowList(!showWorkflowList)}
              className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
              title="切换工作流"
            >
              <ChevronDown size={14} />
            </button>
            {showWorkflowList && (
              <div className="absolute top-full left-0 mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-50 min-w-[180px] max-h-[280px] overflow-y-auto">
                <div className="px-3 py-2 text-[10px] text-gray-400 uppercase tracking-wider border-b border-gray-100">工作流列表</div>
                {workflows.length === 0 && (
                  <div className="px-3 py-4 text-xs text-center text-gray-400">暂无保存的工作流</div>
                )}
                {workflows.map((w: any) => (
                  <div
                    key={w.id}
                    onClick={() => handleSelectWorkflow(w.id)}
                    className={`flex items-center justify-between px-3 py-2 text-xs cursor-pointer hover:bg-gray-50 ${
                      w.id === workflowId ? 'bg-sakura-50 text-sakura-600 font-medium' : 'text-gray-700'
                    }`}
                  >
                    <span className="truncate flex-1">{w.name}</span>
                    {w.id === workflowId && <span className="text-[10px] text-sakura-400 ml-1">当前</span>}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 操作按钮组 */}
          <button onClick={handleSave} className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200" title="保存工作流">
            <Save size={12} /> 保存
          </button>
          <button onClick={handleNew} className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 hover:bg-gray-100" title="新建工作流">
            <Plus size={12} /> 新建
          </button>
          <button onClick={handleRefresh} className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 hover:bg-gray-100" title="刷新列表">
            <RefreshCw size={12} /> 刷新
          </button>
          {workflowId ? (
            <button onClick={handleDelete} className="flex items-center gap-1 px-2 py-1 rounded text-xs text-red-400 hover:bg-red-50" title="删除工作流">
              <Trash2 size={12} /> 删除
            </button>
          ) : (
            <button className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-300 cursor-not-allowed" title="请先保存工作流">
              <Trash2 size={12} /> 删除
            </button>
          )}

          <div className="w-px h-5 bg-gray-200 mx-1" />

          <input
            value={workflowDesc}
            onChange={e => setWorkflowDesc(e.target.value)}
            className="text-xs text-gray-400 border-none outline-none bg-transparent flex-1 min-w-0"
            placeholder="描述（可选）"
          />

          <button onClick={() => setShowTemplates(true)} className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200">
            <BookOpen size={12} /> 模板市场
          </button>
          <button onClick={() => setShowDebugPanel(!showDebugPanel)} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${showDebugPanel ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`}>
            <Code size={12} /> 调试
          </button>
          <button onClick={() => setShowVarPanel(!showVarPanel)} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${showVarPanel ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`}>
            <Variable size={12} /> 变量
          </button>
          <button onClick={() => setShowPublishDialog(true)} className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-100 text-emerald-600 hover:bg-emerald-200">
            <Globe size={12} /> 发布
          </button>
          <button onClick={handleToggleRuns} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${showRunsPanel ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`}>
            <Clock size={12} /> 日志
          </button>
          <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-indigo-100 text-indigo-600 hover:bg-indigo-200">
            <FileType size={12} /> 导入
          </button>
          <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={handleImportDSL} />
        </div>

        {/* 画布 */}
        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onDrop={onDrop}
            onDragOver={onDragOver}
            nodeTypes={nodeTypes}
            fitView
            deleteKeyCode="Delete"
            className="bg-white"
          >
            <Controls />
            <MiniMap
              nodeStrokeColor="#e879a1"
              nodeColor="#fce4ec"
              maskColor="rgba(0,0,0,0.05)"
              className="rounded-lg border border-gray-200"
            />
            <Background color="#f0f0f0" gap={20} size={1} />
            <Panel position="top-right" className="flex gap-2">
              <div className="flex items-center gap-2 bg-white/90 backdrop-blur px-3 py-2 rounded-lg shadow-sm border border-gray-200 text-xs text-gray-500">
                <span className="font-medium">{nodes.length}</span> 节点
                <span className="text-gray-300">|</span>
                <span className="font-medium">{edges.length}</span> 连线
              </div>
            </Panel>
            <FitOnShow />
          </ReactFlow>
        </div>

        {/* 底部分隔线 */}
        {(runResult) && (
          <div className="border-t border-gray-200 bg-gray-50 p-3 max-h-40 overflow-y-auto">
            <div className="text-xs font-semibold text-gray-500 mb-2">执行结果</div>
            {runResult.status === "error" ? (
              <div className="text-xs text-red-500">错误: {runResult.error || "未知错误"}</div>
            ) : (
              <div className="space-y-1">
                <div className="text-xs text-emerald-600">状态: {runResult.status}</div>
                {runResult.node_results?.map((nr: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className={`w-2 h-2 rounded-full ${nr.status === "success" ? "bg-emerald-400" : nr.status === "error" ? "bg-red-400" : "bg-gray-300"}`} />
                    <span className="text-gray-600 font-medium">{nr.label}</span>
                    <span className="text-gray-400 truncate max-w-[300px]">{nr.output?.slice(0, 60)}</span>
                  </div>
                ))}
                <div className="text-xs text-gray-500 mt-1">
                  最终输出: {JSON.stringify(runResult.final_output).slice(0, 200)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 右侧配置面板 */}
      {selectedNode && (
        <div className="w-64 bg-white border-l border-gray-200 p-4 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-semibold text-gray-700">节点配置</span>
            <button onClick={deleteSelectedNode} className="text-red-400 hover:text-red-500">
              <Trash2 size={14} />
            </button>
          </div>

          <div className="space-y-3 text-xs">
            <div>
              <label className="block text-gray-500 mb-1">名称</label>
              <input
                value={(selectedNode.data as any)?.label || ""}
                onChange={e => updateNodeLabel(e.target.value)}
                className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
              />
            </div>

            {selectedNode.data?.type === "llm" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">提示词</label>
                  <textarea
                    value={(selectedNode.data as any)?.config?.prompt || ""}
                    onChange={e => updateNodeConfig("prompt", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 h-20 resize-none"
                    placeholder='使用 {input} 引用输入'
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">系统提示词</label>
                  <textarea
                    value={(selectedNode.data as any)?.config?.system_prompt || ""}
                    onChange={e => updateNodeConfig("system_prompt", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 h-16 resize-none"
                    placeholder="设定 AI 的角色和行为"
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">模型</label>
                  <input
                    value={(selectedNode.data as any)?.config?.model || "qwen3-32b"}
                    onChange={e => updateNodeConfig("model", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="block text-gray-500 mb-1">温度</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="2"
                      value={(selectedNode.data as any)?.config?.temperature ?? 0.7}
                      onChange={e => updateNodeConfig("temperature", parseFloat(e.target.value) || 0.7)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="block text-gray-500 mb-1">最大 Token</label>
                    <input
                      type="number"
                      step="1"
                      min="1"
                      max="32768"
                      value={(selectedNode.data as any)?.config?.max_tokens ?? 4096}
                      onChange={e => updateNodeConfig("max_tokens", parseInt(e.target.value) || 4096)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="block text-gray-500 mb-1">Top-P</label>
                    <input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={(selectedNode.data as any)?.config?.top_p ?? 0.9}
                      onChange={e => updateNodeConfig("top_p", parseFloat(e.target.value) || 0.9)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    />
                  </div>
                </div>
              </>
            )}

            {selectedNode.data?.type === "code" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">语言</label>
                  <select
                    value={(selectedNode.data as any)?.config?.language || "python"}
                    onChange={e => updateNodeConfig("language", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  >
                    <option value="python">Python</option>
                    <option value="javascript">JavaScript</option>
                    <option value="typescript">TypeScript</option>
                    <option value="go">Go</option>
                    <option value="bash">Bash</option>
                  </select>
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">代码</label>
                  <textarea
                    value={(selectedNode.data as any)?.config?.code || ""}
                    onChange={e => updateNodeConfig("code", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-24 resize-none"
                    placeholder='result = input_data.get("input", "") + " 处理完成"'
                  />
                </div>
              </>
            )}

            {selectedNode.data?.type === "condition" && (
              <div>
                <label className="block text-gray-500 mb-1">条件表达式</label>
                <input
                  value={(selectedNode.data as any)?.config?.expression || ""}
                  onChange={e => updateNodeConfig("expression", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300"
                  placeholder='input.get("value", 0) > 10'
                />
              </div>
            )}

            {selectedNode.data?.type === "http" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">URL</label>
                  <input
                    value={(selectedNode.data as any)?.config?.url || ""}
                    onChange={e => updateNodeConfig("url", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    placeholder="https://api.example.com"
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">方法</label>
                  <select
                    value={(selectedNode.data as any)?.config?.method || "GET"}
                    onChange={e => updateNodeConfig("method", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  >
                    <option>GET</option>
                    <option>POST</option>
                    <option>PUT</option>
                    <option>DELETE</option>
                  </select>
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">请求体 (JSON)</label>
                  <textarea
                    value={(selectedNode.data as any)?.config?.body || ""}
                    onChange={e => updateNodeConfig("body", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                    placeholder='{"key": "value"}'
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">请求头 (JSON)</label>
                  <textarea
                    value={JSON.stringify((selectedNode.data as any)?.config?.headers || {}, null, 2)}
                    onChange={e => { try { updateNodeConfig("headers", JSON.parse(e.target.value)); } catch {} }}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-16 resize-none"
                    placeholder='{"Authorization": "Bearer xxx"}'
                  />
                </div>
              </>
            )}

            {selectedNode.data?.type === "tool" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">工具名称</label>
                  <input
                    value={(selectedNode.data as any)?.config?.tool_name || ""}
                    onChange={e => updateNodeConfig("tool_name", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    placeholder="search_web"
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">参数 (JSON)</label>
                  <textarea
                    value={JSON.stringify((selectedNode.data as any)?.config?.tool_args || {}, null, 2)}
                    onChange={e => { try { updateNodeConfig("tool_args", JSON.parse(e.target.value)); } catch {} }}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                    placeholder='{"query": "{input}"}'
                  />
                </div>
              </>
            )}

            {selectedNode.data?.type === "knowledge" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">查询模板</label>
                  <input
                    value={(selectedNode.data as any)?.config?.query || ""}
                    onChange={e => updateNodeConfig("query", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                    placeholder='{input}'
                  />
                </div>
                <div>
                  <label className="block text-gray-500 mb-1">返回条数 (Top-K)</label>
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={(selectedNode.data as any)?.config?.top_k ?? 3}
                    onChange={e => updateNodeConfig("top_k", parseInt(e.target.value) || 3)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  />
                </div>
              </>
            )}

            {selectedNode.data?.type === "template-transform" && (
              <div>
                <label className="block text-gray-500 mb-1">Jinja2 模板</label>
                <textarea
                  value={(selectedNode.data as any)?.config?.template || ""}
                  onChange={e => updateNodeConfig("template", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                  placeholder='使用 {{ variable }} 语法引用变量'
                />
              </div>
            )}

            {selectedNode.data?.type === "parameter-extractor" && (
              <div>
                <label className="block text-gray-500 mb-1">查询文本</label>
                <input
                  value={(selectedNode.data as any)?.config?.query || ""}
                  onChange={e => updateNodeConfig("query", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  placeholder='{input}'
                />
                <label className="block text-gray-500 mb-1 mt-2">提取字段 (JSON)</label>
                <textarea
                  value={JSON.stringify((selectedNode.data as any)?.config?.parameters || [], null, 2)}
                  onChange={e => { try { updateNodeConfig("parameters", JSON.parse(e.target.value)); } catch {} }}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                  placeholder='[{"name":"field","type":"string","description":""}]'
                />
              </div>
            )}

            {selectedNode.data?.type === "question-classifier" && (
              <div>
                <label className="block text-gray-500 mb-1">查询文本</label>
                <input
                  value={(selectedNode.data as any)?.config?.query || ""}
                  onChange={e => updateNodeConfig("query", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  placeholder='{input}'
                />
                <label className="block text-gray-500 mb-1 mt-2">分类列表 (JSON)</label>
                <textarea
                  value={JSON.stringify((selectedNode.data as any)?.config?.categories || [], null, 2)}
                  onChange={e => { try { updateNodeConfig("categories", JSON.parse(e.target.value)); } catch {} }}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                  placeholder='[{"name":"类别A","description":""},{"name":"类别B","description":""}]'
                />
              </div>
            )}

            {selectedNode.data?.type === "document-extractor" && (
              <div>
                <label className="block text-gray-500 mb-1">文件路径</label>
                <input
                  value={(selectedNode.data as any)?.config?.file_path || ""}
                  onChange={e => updateNodeConfig("file_path", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  placeholder="D:/path/to/document.pdf"
                />
              </div>
            )}

            {selectedNode.data?.type === "assigner" && (
              <div>
                <label className="block text-gray-500 mb-1">赋值表达式 (JSON)</label>
                <textarea
                  value={JSON.stringify((selectedNode.data as any)?.config?.assignments || [], null, 2)}
                  onChange={e => { try { updateNodeConfig("assignments", JSON.parse(e.target.value)); } catch {} }}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-20 resize-none"
                  placeholder='[{"variable":"out","expression":"input.get(\"value\",0)*2"}]'
                />
              </div>
            )}

            {selectedNode.data?.type === "variable-aggregator" && (
              <div>
                <label className="block text-gray-500 mb-1">合并策略</label>
                <select
                  value={(selectedNode.data as any)?.config?.merge_strategy || "overwrite"}
                  onChange={e => updateNodeConfig("merge_strategy", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                >
                  <option value="overwrite">覆盖</option>
                  <option value="keep_existing">保留原值</option>
                </select>
              </div>
            )}

            {selectedNode.data?.type === "list-operator" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">操作</label>
                  <select
                    value={(selectedNode.data as any)?.config?.operation || "filter"}
                    onChange={e => updateNodeConfig("operation", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  >
                    <option value="filter">过滤 (filter)</option>
                    <option value="map">映射 (map)</option>
                    <option value="sort">排序 (sort)</option>
                    <option value="first">取第一个</option>
                    <option value="count">计数</option>
                  </select>
                </div>
                <div className="mt-2">
                  <label className="block text-gray-500 mb-1">表达式</label>
                  <input
                    value={(selectedNode.data as any)?.config?.expression || ""}
                    onChange={e => updateNodeConfig("expression", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300"
                    placeholder='item.get("value", 0) > 10'
                  />
                </div>
              </>
            )}

            {selectedNode.data?.type === "answer" && (
              <div>
                <label className="block text-gray-500 mb-1">输出模板</label>
                <textarea
                  value={(selectedNode.data as any)?.config?.output || ""}
                  onChange={e => updateNodeConfig("output", e.target.value)}
                  className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 h-20 resize-none"
                  placeholder='使用 {{ variable }} 语法'
                />
              </div>
            )}

            {selectedNode.data?.type === "iteration" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">数组 (JSON)</label>
                  <input
                    value={(selectedNode.data as any)?.config?.items || "[]"}
                    onChange={e => updateNodeConfig("items", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300"
                    placeholder='["A","B","C"]'
                  />
                </div>
                <div className="mt-2">
                  <label className="block text-gray-500 mb-1">模式</label>
                  <select
                    value={(selectedNode.data as any)?.config?.mode || "sequential"}
                    onChange={e => updateNodeConfig("mode", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  >
                    <option value="sequential">顺序</option>
                    <option value="parallel">并行</option>
                  </select>
                </div>
              </>
            )}

            {selectedNode.data?.type === "loop" && (
              <>
                <div>
                  <label className="block text-gray-500 mb-1">条件表达式</label>
                  <input
                    value={(selectedNode.data as any)?.config?.condition || ""}
                    onChange={e => updateNodeConfig("condition", e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300"
                    placeholder='iteration < 10'
                  />
                </div>
                <div className="mt-2">
                  <label className="block text-gray-500 mb-1">最大迭代次数</label>
                  <input
                    type="number"
                    value={(selectedNode.data as any)?.config?.max_iterations || 10}
                    onChange={e => updateNodeConfig("max_iterations", parseInt(e.target.value) || 10)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300"
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* 调试面板 */}
      {showDebugPanel && (
        <div className="w-64 bg-gray-50 border-l border-gray-200 p-3 overflow-y-auto">
          <div className="text-xs font-semibold text-gray-500 mb-2">调试面板</div>
          <div className="text-xs text-gray-500 mb-2">输入数据 (JSON)</div>
          <textarea
            value={inputData}
            onChange={e => setInputData(e.target.value)}
            className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 h-16 resize-none mb-2"
          />
          <div className="text-xs text-gray-500 mb-1">节点状态</div>
          <div className="space-y-1">
            {nodes.map(n => (
              <div key={n.id} className="flex items-center gap-2 text-[10px]">
                <span className={`w-2 h-2 rounded-full ${nodeStatuses[n.id] === "success" ? "bg-emerald-400" : nodeStatuses[n.id] === "error" ? "bg-red-400" : nodeStatuses[n.id] === "running" ? "bg-amber-400" : "bg-gray-300"}`} />
                <span className="text-gray-600 truncate flex-1">{(n.data as any)?.label || n.id}</span>
                <span className="text-gray-400">{nodeStatuses[n.id] || "pending"}</span>
              </div>
            ))}
          </div>
          {runResult?.variables && (
            <>
              <div className="text-xs text-gray-500 mt-3 mb-1">变量快照</div>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {runResult.variables.map((v: any, i: number) => (
                  <div key={i} className="text-[10px] text-gray-600 truncate">{v.path}: {v.type}</div>
                ))}
              </div>
            </>
          )}
          {runResult?.timings && (
            <>
              <div className="text-xs text-gray-500 mt-3 mb-1">节点耗时 (ms)</div>
              <div className="space-y-1">
                {runResult.timings.map((t: any, i: number) => (
                  <div key={i} className="flex items-center gap-1 text-[10px]">
                    <span className="text-gray-600 truncate flex-1">{t.node_id}</span>
                    <span className={t.elapsed_ms > 1000 ? "text-red-400" : "text-gray-400"}>{t.elapsed_ms}ms</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* 变量面板 */}
      {showVarPanel && (
        <div className="w-64 bg-gray-50 border-l border-gray-200 p-3 overflow-y-auto">
          <div className="text-xs font-semibold text-gray-500 mb-3">变量参考</div>
          {(() => {
            const getNodeVars = (n: any) => {
              const type = (n.data as any)?.type || "llm";
              const label = (n.data as any)?.label || n.id;
              const outputs: { key: string; desc: string }[] = [];
              switch (type) {
                case "start": outputs.push({ key: `{{${n.id}.output}}`, desc: "初始输入" }); break;
                case "llm": outputs.push({ key: `{{${n.id}.text}}`, desc: "生成文本" }); break;
                case "code": outputs.push({ key: `{{${n.id}.result}}`, desc: "执行结果" }); break;
                case "http": outputs.push({ key: `{{${n.id}.body}}`, desc: "响应体" }); break;
                case "condition":
                  outputs.push({ key: `{{${n.id}.result}}`, desc: "条件结果" });
                  outputs.push({ key: `{{${n.id}.branch}}`, desc: "分支 (true/false)" });
                  break;
                case "knowledge": outputs.push({ key: `{{${n.id}.result}}`, desc: "检索结果" }); break;
                case "tool": outputs.push({ key: `{{${n.id}.result}}`, desc: "工具输出" }); break;
                case "template-transform": outputs.push({ key: `{{${n.id}.output}}`, desc: "转换结果" }); break;
                case "parameter-extractor": outputs.push({ key: `{{${n.id}.params}}`, desc: "提取参数" }); break;
                case "question-classifier": outputs.push({ key: `{{${n.id}.category}}`, desc: "分类结果" }); break;
                case "document-extractor": outputs.push({ key: `{{${n.id}.content}}`, desc: "文档内容" }); break;
                case "assigner": outputs.push({ key: `{{${n.id}.output}}`, desc: "赋值结果" }); break;
                case "variable-aggregator": outputs.push({ key: `{{${n.id}.output}}`, desc: "聚合结果" }); break;
                case "list-operator": outputs.push({ key: `{{${n.id}.output}}`, desc: "列表结果" }); break;
                case "iteration": outputs.push({ key: `{{${n.id}.output}}`, desc: "迭代输出" }); break;
                case "loop": outputs.push({ key: `{{${n.id}.output}}`, desc: "循环输出" }); break;
                case "answer": outputs.push({ key: `{{${n.id}.output}}`, desc: "输出内容" }); break;
                default: outputs.push({ key: `{{${n.id}.output}}`, desc: "节点输出" });
              }
              return outputs;
            };
            return (
              <div className="space-y-2">
                {nodes.length === 0 && <div className="text-xs text-gray-400 text-center py-4">暂无节点</div>}
                {nodes.map((n: any) => {
                  const vars = getNodeVars(n);
                  return (
                    <div key={n.id} className="bg-white rounded-lg border border-gray-200 p-2">
                      <div className="flex items-center gap-1 text-[10px] text-gray-500 mb-1">
                        {(NODE_ICONS as any)[(n.data as any)?.type] || <Wrench size={10} />}
                        <span className="font-medium truncate">{(n.data as any)?.label || n.id}</span>
                        <span className="text-gray-300 ml-auto text-[9px]">{n.id}</span>
                      </div>
                      <div className="space-y-0.5">
                        {vars.map((v: any) => (
                          <button
                            key={v.key}
                            onClick={() => navigator.clipboard.writeText(v.key).catch(() => {})}
                            className="flex items-center gap-1 w-full text-left px-2 py-1 rounded text-[10px] font-mono text-sakura-600 bg-sakura-50 hover:bg-sakura-100 transition-colors"
                            title="点击复制"
                          >
                            <span className="truncate flex-1">{v.key}</span>
                            <span className="text-gray-400 shrink-0">({v.desc})</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>
      )}

      {/* 运行日志面板 */}
      {showRunsPanel && (
        <div className="w-64 bg-gray-50 border-l border-gray-200 p-3 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-gray-500">运行日志</span>
            <button onClick={loadRuns} className="text-gray-400 hover:text-gray-600" title="刷新">
              <RefreshCw size={12} />
            </button>
          </div>
          {runsData.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-6">暂无运行记录</div>
          ) : (
            <div className="space-y-2">
              {runsData.map((run: any) => (
                <div key={run.id} className="bg-white rounded-lg border border-gray-200 p-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                      run.status === "success" ? "bg-emerald-100 text-emerald-600" :
                      run.status === "error" ? "bg-red-100 text-red-600" :
                      run.status === "running" ? "bg-amber-100 text-amber-600" :
                      "bg-gray-100 text-gray-500"
                    }`}>
                      {run.status === "success" ? "成功" : run.status === "error" ? "失败" :
                       run.status === "running" ? "运行中" : run.status || "未知"}
                    </span>
                    <span className="text-[9px] text-gray-400">{run.trigger || "手动"}</span>
                  </div>
                  <div className="text-[9px] text-gray-400 truncate">
                    {run.started_at?.slice(0, 19)?.replace("T", " ") || ""}
                  </div>
                  {(run.node_results?.length > 0) && (
                    <div className="mt-1 text-[9px] text-gray-400">
                      {run.node_results.length} 个节点
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 发布对话框 */}
      {showPublishDialog && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => { setShowPublishDialog(false); setPublishResult(null); }}>
          <div className="bg-white rounded-xl shadow-xl w-[420px] p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold text-gray-700">发布工作流</span>
              <button onClick={() => { setShowPublishDialog(false); setPublishResult(null); }} className="text-gray-400 hover:text-gray-600">
                <X size={16} />
              </button>
            </div>

            {!workflowId ? (
              <div className="text-xs text-gray-400 text-center py-6">请先保存工作流后再发布</div>
            ) : (
              <div className="space-y-3">
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">工作流</div>
                  <div className="text-sm font-medium text-gray-700">{workflowName}</div>
                </div>

                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">API 端点</div>
                  <div className="flex items-center gap-2">
                    <input
                      readOnly
                      value={`POST /api/webhook/${workflowId}`}
                      className="flex-1 text-xs font-mono bg-white px-2 py-1.5 border border-gray-200 rounded-md outline-none"
                    />
                    <button
                      onClick={() => navigator.clipboard.writeText(`/api/webhook/${workflowId}`).catch(() => {})}
                      className="shrink-0 px-3 py-1.5 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200"
                    >
                      复制
                    </button>
                  </div>
                </div>

                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-xs text-gray-500 mb-1">导出 DSL</div>
                  <button
                    onClick={handleExport}
                    className="w-full px-3 py-2 rounded-lg text-xs font-medium bg-indigo-100 text-indigo-600 hover:bg-indigo-200 transition-colors"
                  >
                    <FileType size={12} className="inline mr-1" />导出为 DSL 文件
                  </button>
                </div>

                <button
                  onClick={handlePublish}
                  className="w-full px-4 py-2 rounded-lg text-xs font-medium bg-emerald-500 text-white hover:bg-emerald-600 transition-colors"
                >
                  {publishResult?.success ? "✅ 已发布" : "确认发布"}
                </button>

                {publishResult?.error && (
                  <div className="text-xs text-red-500 bg-red-50 p-2 rounded">{publishResult.error}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 模板市场弹窗 */}
      {showTemplates && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowTemplates(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[600px] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <span className="text-sm font-semibold text-gray-700">工作流模板市场</span>
              <button onClick={() => setShowTemplates(false)} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
            </div>

            {/* 本地 / 在线 切换 */}
            <div className="flex border-b border-gray-100">
              <button
                onClick={() => setShowOnline(false)}
                className={`flex-1 py-3 text-xs font-medium text-center ${!showOnline ? 'text-sakura-600 border-b-2 border-sakura-300' : 'text-gray-400 hover:text-gray-600'}`}
              >
                <BookOpen size={12} className="inline mr-1" />本地模板
              </button>
              <button
                onClick={() => setShowOnline(true)}
                className={`flex-1 py-3 text-xs font-medium text-center ${showOnline ? 'text-sakura-600 border-b-2 border-sakura-300' : 'text-gray-400 hover:text-gray-600'}`}
              >
                <Globe size={12} className="inline mr-1" />在线搜索
              </button>
            </div>

            {!showOnline ? (
              <>
                <div className="px-5 py-3 flex gap-2 flex-wrap border-b border-gray-100">
                  <button onClick={() => setSelectedCategory("")}
                    className={`px-3 py-1 rounded-full text-xs ${!selectedCategory ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}>全部</button>
                  {templateCategories.map(cat => (
                    <button key={cat} onClick={() => setSelectedCategory(cat)}
                      className={`px-3 py-1 rounded-full text-xs ${selectedCategory === cat ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}>{cat}</button>
                  ))}
                </div>
                <div className="p-5 space-y-3">
                  {templateList.filter(t => !selectedCategory || t.category === selectedCategory).map(tpl => (
                    <div key={tpl.id} className="border border-gray-200 rounded-lg p-4 hover:border-sakura-300 hover:shadow-sm transition-all cursor-pointer"
                         onClick={() => handleUseTemplate(tpl.id)}>
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-sm font-medium text-gray-700">{tpl.name}</span>
                          <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{tpl.category}</span>
                        </div>
                        <span className="text-xs text-gray-400">{tpl.usage_count || 0} 次使用</span>
                      </div>
                      <p className="text-xs text-gray-400 mt-1">{tpl.description}</p>
                    </div>
                  ))}
                  {templateList.length === 0 && (
                    <div className="text-center py-8 text-xs text-gray-400">暂无本地模板</div>
                  )}
                </div>
              </>
            ) : (
              <div className="p-5">
                <div className="flex items-center gap-2 mb-4">
                  <input
                    ref={searchInputRef}
                    value={onlineQuery}
                    onChange={e => setOnlineQuery(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleSearchOnline()}
                    placeholder="输入关键词搜索..."
                    className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300"
                  />
                  <button
                    onClick={handleSearchOnline}
                    disabled={loadingOnline}
                    className="shrink-0 px-4 py-2 rounded-lg text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 disabled:opacity-50 transition-colors"
                  >
                    {loadingOnline ? "搜索中..." : "搜索"}
                  </button>
                </div>

                {onlineTemplates.length > 0 ? (
                  <div className="space-y-3">
                    {onlineTemplates.map((tpl: any) => (
                      <div key={tpl.id} className="border border-gray-200 rounded-lg p-4 hover:border-sakura-300 hover:shadow-sm transition-all">
                        <div className="flex items-center justify-between mb-1">
                          <div>
                            <span className="text-sm font-medium text-gray-700">{tpl.name}</span>
                            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-500">{tpl.category}</span>
                          </div>
                          {tpl.usage_count > 0 && (
                            <span className="text-[10px] text-gray-400">{tpl.usage_count} stars</span>
                          )}
                        </div>
                        <p className="text-xs text-gray-400 mb-2">{tpl.description}</p>
                        <button
                          onClick={() => handleUseOnlineTemplate(tpl)}
                          className="px-3 py-1.5 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors"
                        >
                          {tpl.source === "github_repo" ? "打开仓库" : "导入使用"}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : onlineSearched && !loadingOnline ? (
                  <div className="text-center py-4 text-xs text-gray-400">
                    {onlineError ? (
                      <div className="text-red-400">
                        <p>{onlineError}</p>
                        <p className="mt-2 text-gray-400">请确认后端已启动并刷新重试</p>
                      </div>
                    ) : (
                      "未找到相关模板，试试其他关键词"
                    )}
                  </div>
                ) : (
                  <div className="text-center py-8 text-xs text-gray-400">
                    <Globe size={24} className="mx-auto mb-2 text-gray-300" />
                    输入关键词后点击「搜索」
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
