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
import { useToast } from "@/components/Toast";
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
  const { notify } = useToast();
  const { fitView } = useReactFlow();

  /** 自动布局：按拓扑层次排列节点 */
  const autoLayout = useCallback((nodes: Node[], edges: Edge[]) => {
    if (!nodes.length) return nodes;
    // 1. 找源节点（无入边）
    const hasIncoming = new Set(edges.map(e => e.target));
    const sources = nodes.filter(n => !hasIncoming.has(n.id));
    // 2. BFS 分配层级
    const levelMap: Record<string, number> = {};
    const queue: { id: string; level: number }[] = sources.map(n => ({ id: n.id, level: 0 }));
    for (const q of queue) levelMap[q.id] = q.level;
    while (queue.length > 0) {
      const cur = queue.shift()!;
      const outEdges = edges.filter(e => e.source === cur.id);
      for (const e of outEdges) {
        if (!(e.target in levelMap) || levelMap[e.target] < cur.level + 1) {
          levelMap[e.target] = cur.level + 1;
          queue.push({ id: e.target, level: cur.level + 1 });
        }
      }
    }
    // 3. 为无层级节点分配
    for (const n of nodes) {
      if (!(n.id in levelMap)) levelMap[n.id] = 0;
    }
    // 4. 按层级分组，计算位置
    const byLevel: Record<number, Node[]> = {};
    for (const n of nodes) {
      const lvl = levelMap[n.id] || 0;
      if (!byLevel[lvl]) byLevel[lvl] = [];
      byLevel[lvl].push(n);
    }
    const levelKeys = Object.keys(byLevel).map(Number).sort((a, b) => a - b);
    const H_SPACING = 250;
    const V_SPACING = 120;
    const TOP = 80;
    const LEFT = 80;
    return nodes.map(n => {
      const lvl = levelMap[n.id] || 0;
      const siblings = byLevel[lvl] || [];
      const idx = siblings.indexOf(n);
      const total = siblings.length;
      const x = LEFT + lvl * H_SPACING;
      const y = TOP + idx * V_SPACING - ((total - 1) * V_SPACING) / 2;
      return { ...n, position: { x, y } };
    });
  }, []);

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
  const [rightTab, setRightTab] = useState<"config" | "vars" | "debug" | "runs" | null>(null);
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
    }).catch(e => console.warn("加载工作流列表失败", e));
    // 加载模板
    apiGet<any>("/api/workflow/templates").then(d => {
      if (d?.templates) setTemplateList(d.templates);
    }).catch(e => console.warn("加载模板失败", e));
    apiGet<any>("/api/workflow/templates/categories").then(d => {
      if (d?.categories) setTemplateCategories(d.categories);
    }).catch(e => console.warn("加载模板分类失败", e));
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
            if (loadedNodes?.length) {
              const laidOut = autoLayout(loadedNodes.map((n: any) => ({
                ...n, type: "base",
                data: n.data || { label: n.id || "节点", type: "llm", config: {} },
              })), loadedEdges || []);
              setNodes(laidOut);
            }
            if (loadedEdges?.length) setEdges(loadedEdges);
            setTimeout(() => fitView({ duration: 300 }), 150);
          } catch (e) { console.warn("解析工作流数据出错", e); }
        }
      }).catch(e => console.warn("加载工作流失败", e));
    }
  }, [initialId, autoLayout, fitView]);

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
        notify("工作流已保存", "success");
      }
    } catch (e: any) {
      notify("保存失败: " + (e?.message || "未知错误"), "error");
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
        const laidOut = autoLayout(r.nodes.map((n: any) => ({
          ...n,
          type: "base",
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })), r.edges || []);
        setNodes(laidOut);
        setEdges(r.edges || []);
        setTimeout(() => fitView({ duration: 300 }), 100);
        setWorkflowName(r.name || "来自模板");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setShowTemplates(false);
        setRunResult(null);
      }
    } catch {}
  }, [setNodes, setEdges, autoLayout, fitView]);

  // 加载工作流
  const loadWorkflow = useCallback(async (id: string) => {
    try {
      const d = await apiGet<any>(`/api/workflows/${id}`);
      if (!d) {
        notify("未找到该工作流", "warning");
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
        const laidOut = autoLayout(parsedNodes.map((n: any) => ({
          ...n,
          type: "base",
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })), parsedEdges);
        setNodes(laidOut);
        setTimeout(() => fitView({ duration: 300 }), 100);
      } else {
        setNodes(DEFAULT_NODES.map(n => ({ ...n })));
      }
      setEdges(parsedEdges);
    } catch (e: any) {
      console.error("加载工作流失败", e);
      notify("加载工作流失败: " + (e?.message || "未知错误"), "error");
    }
  }, [setNodes, setEdges, autoLayout, fitView]);

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
  }, [setNodes, setEdges, autoLayout, fitView]);

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
        }).catch(e => console.warn("加载工作流列表失败", e));
      }
    } catch (e: any) {
      notify("删除失败: " + (e?.message || "未知错误"), "error");
    }
  }, [workflowId, workflowName, handleNew, setWorkflows]);

  // 刷新工作流列表
  const handleRefresh = useCallback(() => {
    apiGet<any>("/api/workflows").then(d => {
      if (d?.workflows) setWorkflows(d.workflows);
    }).catch(e => console.warn("刷新工作流列表失败", e));
  }, [setWorkflows]);

  // 选择工作流
  const handleSelectWorkflow = useCallback(async (id: string) => {
    setShowWorkflowList(false);
    await loadWorkflow(id);
  }, [loadWorkflow]);

  // 发布工作流为 API
  const handlePublish = useCallback(async () => {
    if (!workflowId) { notify("请先保存工作流", "warning"); return; }
    try {
      const r: any = await apiPost("/api/workflows/publish", { id: workflowId });
      setPublishResult(r);
      if (r?.success) {
        notify("工作流已发布，可通过 API 端点调用", "success");
      }
    } catch (e: any) {
      notify("发布失败: " + (e?.message || "未知错误"), "error");
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
        const laidOut = autoLayout(r.nodes.map((n: any) => ({
          ...n,
          type: "base",
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })), r.edges || []);
        setNodes(laidOut);
        setEdges(r.edges || []);
        setTimeout(() => fitView({ duration: 300 }), 100);
        setWorkflowName(r.name || "导入的工作流");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setRunResult(null);
        setNodeStatuses({});
        notify("导入成功", "success");
      } else if (r?.error) {
        notify("导入失败: " + r.error, "error");
      }
    } catch (e: any) {
      notify("导入失败: " + (e?.message || "文件格式错误"), "error");
    }
    e.target.value = "";
  }, [setNodes, setEdges, autoLayout, fitView]);

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
        const laidOut = autoLayout(r.nodes.map((n: any) => ({
          ...n, type: "base",
          data: n.data || { label: n.id || "节点", type: "llm", config: {} },
        })), r.edges || []);
        setNodes(laidOut);
        setEdges(r.edges || []);
        setTimeout(() => fitView({ duration: 300 }), 100);
        setWorkflowName(r.name || "在线模板");
        setWorkflowDesc(r.description || "");
        setWorkflowId(`wf_${Date.now()}`);
        setRunResult(null);
        setNodeStatuses({});
        setShowTemplates(false);
        notify("模板导入成功", "success");
      } else if (r?.error) {
        notify("导入失败: " + r.error, "error");
      }
    } catch (e: any) {
      notify("下载模板失败: " + (e?.message || "网络错误"), "error");
    }
  }, [setNodes, setEdges, autoLayout, fitView]);

  // 导出 DSL
  const handleExport = useCallback(async () => {
    if (!workflowId) { notify("请先保存工作流", "warning"); return; }
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
        notify("导出失败: " + r.error, "error");
      }
    } catch (e: any) {
      notify("导出失败: " + (e?.message || "未知错误"), "error");
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
          <button onClick={() => setRightTab(rightTab === "debug" ? null : "debug")} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${rightTab === "debug" ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`} title="调试面板">
            <Code size={12} /> 调试
          </button>
          <button onClick={() => setRightTab(rightTab === "vars" ? null : "vars")} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${rightTab === "vars" ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`} title="变量参考">
            <Variable size={12} /> 变量
          </button>
          <button onClick={() => setShowPublishDialog(true)} className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-100 text-emerald-600 hover:bg-emerald-200">
            <Globe size={12} /> 发布
          </button>
          <button onClick={() => { setRightTab(rightTab === "runs" ? null : "runs"); if (rightTab !== "runs" && workflowId) loadRuns(); }} className={`flex items-center gap-1 px-2 py-1 rounded text-xs ${rightTab === "runs" ? 'bg-sakura-100 text-sakura-600' : 'bg-gray-100 text-gray-500'} hover:bg-gray-200`} title="运行日志">
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

      {/* 右侧统一面板 */}
      {$rightTab && (
        <div className="w-64 bg-white border-l border-gray-200 flex flex-col shrink-0">
          {/* 标签栏 */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 shrink-0">
            <div className="flex items-center gap-1">
              {([
                ["config", "配置", Wrench],
                ["vars", "变量", Variable],
                ["debug", "调试", Code],
                ["runs", "日志", Clock],
              ] as const).filter(([k]) => k !== "config" || selectedNode).map(([k, label, Icon]) => (
                <button key={k} onClick={() => {
                  setRightTab(k);
                  if (k === "runs" && workflowId) loadRuns();
                }}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] ${
                    rightTab === k ? "bg-sakura-100 text-sakura-600" : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                  }`}>
                  <Icon size={11} />
                  {label}
                </button>
              ))}
            </div>
            <button onClick={() => setRightTab(null)} className="p-0.5 text-gray-300 hover:text-red-400 transition-colors" title="关闭面板">
              <X size={13} />
            </button>
          </div>

          {/* 内容区 */}
          <div className="flex-1 overflow-y-auto p-3 text-xs">

            {/* 节点配置 */}
            {rightTab === "config" && selectedNode && (
              <div className="space-y-3">
                <div>
                  <label className="block text-gray-500 mb-1">名称</label>
                  <input value={(selectedNode.data as any)?.label || ""} onChange={e => updateNodeLabel(e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300" />
                </div>
                {selectedNode.data?.type === "llm" && (
                  <>
                    <div><label className="block text-gray-500 mb-1">系统提示词</label>
                      <textarea rows={4} value={(selectedNode.data as any)?.config?.system_prompt || ""} onChange={e => updateNodeConfig("system_prompt", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" /></div>
                    <div><label className="block text-gray-500 mb-1">模型</label>
                      <input value={(selectedNode.data as any)?.config?.model || ""} onChange={e => updateNodeConfig("model", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300" placeholder="留空使用默认" /></div>
                    <div><label className="block text-gray-500 mb-1">温度</label>
                      <input type="number" step="0.1" min="0" max="2" value={(selectedNode.data as any)?.config?.temperature ?? ""}
                        onChange={e => updateNodeConfig("temperature", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300" /></div>
                  </>
                )}
                {selectedNode.data?.type === "code" && (
                  <div><label className="block text-gray-500 mb-1">代码</label>
                    <textarea rows={6} value={(selectedNode.data as any)?.config?.code || ""} onChange={e => updateNodeConfig("code", e.target.value)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" /></div>
                )}
                {selectedNode.data?.type === "condition" && (
                  <div><label className="block text-gray-500 mb-1">条件表达式</label>
                    <textarea rows={3} value={(selectedNode.data as any)?.config?.condition || ""} onChange={e => updateNodeConfig("condition", e.target.value)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" placeholder="例如: {{result.score > 0.5}}" /></div>
                )}
                {selectedNode.data?.type === "http" && (
                  <>
                    <div><label className="block text-gray-500 mb-1">URL</label>
                      <input value={(selectedNode.data as any)?.config?.url || ""} onChange={e => updateNodeConfig("url", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300" /></div>
                    <div><label className="block text-gray-500 mb-1">方法</label>
                      <select value={(selectedNode.data as any)?.config?.method || "GET"} onChange={e => updateNodeConfig("method", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300">
                        <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option></select></div>
                    <div><label className="block text-gray-500 mb-1">Headers (JSON)</label>
                      <textarea rows={3} value={JSON.stringify((selectedNode.data as any)?.config?.headers || {}, null, 2)}
                        onChange={e => { try { updateNodeConfig("headers", JSON.parse(e.target.value)); } catch {} }}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" /></div>
                    <div><label className="block text-gray-500 mb-1">Body</label>
                      <textarea rows={3} value={(selectedNode.data as any)?.config?.body || ""} onChange={e => updateNodeConfig("body", e.target.value)}
                        className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" /></div>
                  </>
                )}
                {selectedNode.data?.type === "knowledge" && (
                  <div><label className="block text-gray-500 mb-1">知识库查询</label>
                    <textarea rows={3} value={(selectedNode.data as any)?.config?.query || ""} onChange={e => updateNodeConfig("query", e.target.value)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300 resize-none font-mono" placeholder="搜索关键词或 {{变量}}" /></div>
                )}
                {selectedNode.data?.type === "tool" && (
                  <div><label className="block text-gray-500 mb-1">工具名称</label>
                    <input value={(selectedNode.data as any)?.config?.tool_name || ""} onChange={e => updateNodeConfig("tool_name", e.target.value)}
                      className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs outline-none focus:border-sakura-300" placeholder="例如: web_search" /></div>
                )}
                <div className="pt-2 border-t border-gray-100">
                  <button onClick={deleteSelectedNode} className="flex items-center gap-1 px-3 py-1.5 rounded text-xs bg-red-50 text-red-500 hover:bg-red-100">
                    <Trash2 size={11} /> 删除节点
                  </button>
                </div>
              </div>
            )}

            {/* 调试 */}
            {rightTab === "debug" && (
              <>
                <div className="mb-3">
                  <p className="text-gray-500 mb-1">输入数据 (JSON)</p>
                  <textarea value={inputData} onChange={e => setInputData(e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-200 rounded-md text-xs font-mono outline-none focus:border-sakura-300 resize-none" rows={8} />
                </div>
                <button onClick={handleRun} disabled={running}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 disabled:opacity-50">
                  {running ? <RefreshCw size={11} className="animate-spin" /> : <Play size={11} />}
                  {running ? "运行中..." : "运行"}
                </button>
                {runResult && (
                  <div className="mt-3 space-y-2">
                    <p className="text-green-600 text-[10px] font-medium">运行完成</p>
                    <div className="text-gray-400 text-[10px]">耗时: {runResult.timing?.total || "?"}ms</div>
                    {(runResult.nodes_snapshot || runResult.node_results || []).map((ns: any, i: number) => (
                      <div key={i} className="p-2 rounded border border-gray-100 bg-gray-50">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-gray-600 font-medium text-xs">{ns.id || ns.name || 节点 }</span>
                          <span className={	ext-[10px] }>
                            {ns.status === "success" ? "✓" : ns.status === "error" ? "✗" : ns.status || "?"}
                          </span>
                        </div>
                        <div className="text-gray-400 text-[10px] break-all font-mono">
                          {ns.output ? JSON.stringify(ns.output).slice(0, 200) : ns.error || "无输出"}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {/* 变量 */}
            {rightTab === "vars" && (
              <div className="space-y-1">
                <p className="text-gray-500 mb-2">可用变量（点击复制）</p>
                {[
                  { key: "{{input}}", desc: "工作流输入" },
                  { key: "{{result.节点ID}}", desc: "指定节点的输出", example: "{{result.llm_1}}" },
                  { key: "{{env.变量名}}", desc: "环境变量" },
                  { key: "{{now}}", desc: "当前时间" },
                ].map(v => (
                  <div key={v.key} onClick={() => navigator.clipboard.writeText(v.key).catch(() => {})}
                    className="p-2 rounded border border-gray-100 hover:border-sakura-200 hover:bg-sakura-50 cursor-pointer transition-colors">
                    <code className="text-[10px] font-mono text-sakura-600 bg-sakura-50 px-1 py-0.5 rounded">{v.key}</code>
                    <p className="text-[10px] text-gray-400 mt-0.5">{v.desc}</p>
                    {v.example && <p className="text-[9px] text-gray-300 font-mono">{v.example}</p>}
                  </div>
                ))}
              </div>
            )}

            {/* 日志 */}
            {rightTab === "runs" && (
              <>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-gray-500 text-[10px]">最近运行记录</span>
                  <button onClick={() => { if (workflowId) loadRuns(); }} className="text-gray-400 hover:text-sakura-500" title="刷新">
                    <RefreshCw size={11} />
                  </button>
                </div>
                {runsData.length === 0 ? (
                  <p className="text-gray-300 text-[10px] text-center py-4">暂无运行记录</p>
                ) : (
                  <div className="space-y-1">
                    {runsData.map((r: any, i: number) => (
                      <div key={r.id || i} className="p-2 rounded border border-gray-100 hover:border-sakura-200 cursor-pointer transition-colors">
                        <div className="flex items-center justify-between">
                          <span className="text-gray-600 text-[10px] font-medium">{r.status || "unknown"}</span>
                          <span className="text-gray-300 text-[9px]">{r.started_at ? new Date(r.started_at).toLocaleString() : ""}</span>
                        </div>
                        {r.error && <p className="text-red-400 text-[9px] mt-0.5 truncate">{r.error}</p>}
                        <p className="text-gray-400 text-[9px] mt-0.5 truncate">{r.final_output ? JSON.stringify(r.final_output).slice(0, 80) : ""}</p>
                        <div className="text-gray-300 text-[9px] mt-0.5">耗时: {r.timing?.total || "?"}ms</div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

          </div>
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
