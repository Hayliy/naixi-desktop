import { useState, useEffect } from "react";
import { Plus, Trash2, Check, X, Loader2, Pencil, Save, Eye, EyeOff } from "lucide-react";
import { useAppConfig } from "@/contexts/AppContext";
import { apiPost } from "@/lib/api";

const PROVIDER_TYPES = [
  // ─── 国际 ───
  { value: "openai", label: "OpenAI (GPT-5 / o-series)", host: "https://api.openai.com/v1" },
  { value: "anthropic", label: "Anthropic (Claude Opus/Sonnet/Haiku)", host: "https://api.anthropic.com/v1" },
  { value: "gemini", label: "Google Gemini (Gemma/Gemini)", host: "https://generativelanguage.googleapis.com/v1beta" },
  { value: "deepseek", label: "DeepSeek (V4/R1/Coder)", host: "https://api.deepseek.com/v1" },
  { value: "xai", label: "xAI Grok (Grok-3)", host: "https://api.x.ai/v1" },
  { value: "mistral", label: "Mistral AI (Large/Small/Codestral)", host: "https://api.mistral.ai/v1" },
  { value: "cohere", label: "Cohere (Command R+)", host: "https://api.cohere.ai/v1" },
  { value: "ai21", label: "AI21 Labs (Jurassic-2)", host: "https://api.ai21.com/studio/v1" },
  { value: "stability", label: "Stability AI (Stable Diffusion)", host: "https://api.stability.ai/v1" },
  { value: "perplexity", label: "Perplexity (Sonar)", host: "https://api.perplexity.ai" },
  { value: "replicate", label: "Replicate (开源模型)", host: "https://api.replicate.com/v1" },
  { value: "openrouter", label: "OpenRouter (模型聚合)", host: "https://openrouter.ai/api/v1" },
  // ─── 国内云厂商 ───
  { value: "bailian", label: "阿里百炼 (通义千问 Qwen3)", host: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { value: "volcengine", label: "火山引擎 (豆包 Doubao)", host: "https://ark.cn-beijing.volces.com/api/v3" },
  { value: "hunyuan", label: "腾讯混元 (Hunyuan)", host: "https://api.hunyuan.cloud.tencent.com/v1" },
  { value: "baidu", label: "百度千帆 (文心一言 ERNIE)", host: "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop" },
  { value: "huawei", label: "华为云 (盘古 Pangu)", host: "https://pangu.cn-north-4.myhuaweicloud.com/v1" },
  // ─── 国内第三方模型 ───
  { value: "zhipu", label: "智谱 GLM (GLM-5/4V/CogView)", host: "https://open.bigmodel.cn/api/paas/v4" },
  { value: "moonshot", label: "月之暗面 Kimi (超长上下文)", host: "https://api.moonshot.cn/v1" },
  { value: "minimax", label: "MiniMax (ABAB/语音)", host: "https://api.minimax.chat/v1" },
  { value: "iflytek", label: "科大讯飞星火 (Spark)", host: "https://spark-api.xf-yun.com/v3.5/chat" },
  { value: "baichuan", label: "百川智能 (Baichuan)", host: "https://api.baichuan-ai.com/v1" },
  { value: "lingyi", label: "零一万物 Yi (Yi-6B/34B)", host: "https://api.lingyiwanwu.com/v1" },
  { value: "ling", label: "百灵 Ling (Ling-2.6)", host: "https://api.ant-ling.com/v1" },
  // ─── 本地 ───
  { value: "ollama", label: "Ollama 本地模型", host: "http://127.0.0.1:11434/v1" },
  { value: "custom", label: "自定义 (兼容 OpenAI 格式)", host: "" },
];

const CAPABILITY_TYPES = [
  { value: "chat", label: "对话", desc: "大语言模型，文本对话、代码生成" },
  { value: "vision", label: "视觉", desc: "图片理解、OCR、视频理解" },
  { value: "image", label: "画图", desc: "图片生成" },
  { value: "video", label: "视频", desc: "视频生成" },
  { value: "audio", label: "语音", desc: "语音合成、语音识别" },
  { value: "embedding", label: "向量", desc: "文本向量化、RAG 知识库" },
];

interface Provider { id: number; name: string; type: string; api_url: string; has_key: boolean; models: string[]; }
interface EditableProvider {
  id: number;
  key: string;
  type: string;
  api_url: string;
  api_key: string;
  model: string;
}

export default function ProviderSettings({ onClose }: { onClose?: () => void }) {
  // 有 onClose = 作为 Chat 右侧滑出面板（保留 header/侧栏）；无 onClose = 嵌入设置页（行式，无 header）
  const embedded = !onClose;
  const { config, loaded, refreshConfig } = useAppConfig();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  // ── 从 config 构建 provider 列表 ──
  useEffect(() => {
    if (!loaded) return;
    const list: Provider[] = [];
    let idx = 0;
    for (const [pid, pcfg] of Object.entries(config.api_providers)) {
      idx++;
      list.push({
        id: idx,
        name: pid,
        type: pid,
        api_url: pcfg.api_url,
        has_key: !!pcfg.api_key,
        models: pcfg.model ? [pcfg.model] : [],
      });
    }
    setProviders(list);
    setLoading(false);
  }, [config, loaded]);

  // ── 读取完整 config 中某个 provider 的可编辑字段 ──
  const getEditingProvider = (id: number): EditableProvider | null => {
    const p = providers.find(x => x.id === id);
    if (!p) return null;
    const raw = config.api_providers[p.name] || {};
    return {
      id: p.id,
      key: p.name,
      type: raw.type || "chat",
      api_url: raw.api_url || "",
      api_key: raw.api_key || "",
      model: raw.model || "",
    };
  };

  // ── 保存单个 provider 的修改 ──
  const saveProviderEdit = async (ep: EditableProvider) => {
    const updated = { ...config };
    if (!updated.api_providers) updated.api_providers = {};
    if (ep.model) {
      updated.api_providers[ep.key] = { type: ep.type, api_url: ep.api_url, api_key: ep.api_key, model: ep.model };
    } else {
      delete updated.api_providers[ep.key];
    }
    await apiPost("/api/desktop/config", updated);
    await refreshConfig();
    setEditingId(null);
  };

  // ── 删除 provider ──
  const handleDelete = async (name: string) => {
    const updated = { ...config };
    if (updated.api_providers) {
      delete updated.api_providers[name];
    }
    await apiPost("/api/desktop/config", updated);
    await refreshConfig();
  };

  // ── 新增 provider ──
  const handleAddSave = async () => {
    if (!formName || !formHost) return;
    const updated = { ...config };
    if (!updated.api_providers) updated.api_providers = {};
    const modelName = formModels.trim() || formName;
    updated.api_providers[formName] = { type: formCapability, api_url: formHost, api_key: formKey, model: modelName };
    await apiPost("/api/desktop/config", updated);
    await refreshConfig();
    setShowForm(false);
    resetForm();
  };

  // ── 表单状态 ──
  const [formType, setFormType] = useState("openai");
  const [formName, setFormName] = useState("");
  const [formHost, setFormHost] = useState("https://api.openai.com/v1");
  const [formKey, setFormKey] = useState("");
  const [showFormKey, setShowFormKey] = useState(false);
  const [formModels, setFormModels] = useState("");
  const [formCapability, setFormCapability] = useState("chat");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const resetForm = () => {
    setFormType("openai"); setFormName(""); setFormHost("https://api.openai.com/v1");
    setFormKey(""); setFormModels(""); setFormCapability("chat"); setTestResult(null);
  };

  const openForm = () => {
    resetForm();
    setShowForm(true);
  };

  const selectType = (val: string) => {
    setFormType(val);
    const t = PROVIDER_TYPES.find(p => p.value === val);
    if (t) { setFormHost(t.host); if (val !== "custom") setFormName(t.label.split(" ")[0]); }
    setTestResult(null);
  };

  const handleTest = async () => {
    if (!formHost) return;
    setTesting(true); setTestResult(null);
    try {
      const res = await apiPost<{ ok: boolean; models?: string[]; error?: string }>("/api/desktop/test-connection", {
        api_url: formHost, api_key: formKey,
      });
      setTestResult({ ok: res.ok, msg: res.ok ? `连接成功` : `失败: ${res.error}` });
    } catch { setTestResult({ ok: false, msg: "请求失败" }); }
    setTesting(false);
  };

  if (fatalError) return (
    <div className="py-6 text-center">
      <p className="text-xs text-red-500 font-medium mb-1">组件初始化异常</p>
      <p className="text-[10px] text-gray-400 mb-3 font-mono break-all">{fatalError}</p>
      <button onClick={() => { setFatalError(null); setLoading(true); }}
        className="px-3 py-1.5 rounded text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200">重试</button>
    </div>
  );

  if (loading) return <div className="flex items-center justify-center py-12"><Loader2 size={16} className="text-sakura-300 animate-spin" /></div>;

  return (
    <div className={embedded ? "w-full" : "flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full"}>
      {/* 面板模式才显示标题栏与关闭按钮；嵌入设置页时由外层 Section 提供标题 */}
      {!embedded && (
        <div className="bg-white flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
          <span className="text-xs font-semibold text-sakura-500">模型供应商</span>
          <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
        </div>
      )}

      {/* Provider 列表 */}
      <div className={embedded ? "w-full" : "flex-1 overflow-y-auto space-y-1 overflow-x-hidden pr-0.5"}>
        {/* 添加按钮 */}
        {!showForm && (
          <button onClick={openForm}
            className={embedded
              ? "flex items-center justify-center gap-1.5 w-full py-2.5 mt-1 rounded-lg text-sm text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors"
              : "flex items-center gap-1 w-full px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors"}>
            <Plus size={embedded ? 14 : 10} /> 添加供应商
          </button>
        )}

        {/* 新增表单 — 在列表上方 */}
        {showForm && (
          <div className={embedded
            ? "bg-sakura-50/50 border border-sakura-200/60 rounded-lg p-4 space-y-2.5 text-xs mt-1"
            : "bg-white border border-sakura-200 rounded-xl p-3 space-y-2.5 text-xs"}>
            <p className="text-xs font-semibold text-sakura-500">添加供应商</p>
            <select value={formType} onChange={e => selectType(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]">
              {PROVIDER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">服务类型</p>
              <div className="flex flex-wrap gap-1">
                {CAPABILITY_TYPES.map(ct => (
                  <button key={ct.value} type="button" onClick={() => { setFormCapability(ct.value); setTestResult(null); }}
                    className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${
                      formCapability === ct.value
                        ? "bg-sakura-100 border-sakura-300 text-sakura-600 font-medium"
                        : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"
                    }`}>
                    {ct.label}
                  </button>
                ))}
              </div>
            </div>
            <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]"
              placeholder="显示名称" value={formName} onChange={e => setFormName(e.target.value)} />
            <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[10px] font-mono"
              placeholder="API 地址" value={formHost} onChange={e => setFormHost(e.target.value)} />
            <div className="relative">
              <input type={showFormKey ? "text" : "password"}
                className="w-full px-2.5 py-1.5 pr-9 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[10px] font-mono"
                placeholder="API Key" value={formKey} onChange={e => setFormKey(e.target.value)} />
              <button type="button" onClick={() => setShowFormKey(!showFormKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-sakura-300 hover:text-sakura-500">
                {showFormKey ? <EyeOff size={12} /> : <Eye size={12} />}
              </button>
            </div>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">模型名</p>
              <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[10px] font-mono"
                placeholder="gpt-4 / qwen-plus" value={formModels} onChange={e => setFormModels(e.target.value)} />
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleTest} disabled={testing || !formHost}
                className="px-2.5 py-1 rounded-lg text-[10px] bg-sakura-100 text-sakura-500 hover:bg-sakura-200 disabled:opacity-50">
                {testing ? <Loader2 size={10} className="animate-spin" /> : "测试"}
              </button>
              {testResult && (
                <span className={`text-[10px] ${testResult.ok ? "text-green-600" : "text-red-500"}`}>
                  {testResult.ok ? <Check size={10} className="inline" /> : <X size={10} className="inline" />}
                  {testResult.msg}
                </span>
              )}
            </div>
            <div className="flex justify-end gap-1.5 pt-1 border-t border-sakura-100">
              <button onClick={() => { setShowForm(false); resetForm(); }}
                className="px-2.5 py-1 rounded-lg text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleAddSave} disabled={!formName || !formHost}
                className="flex items-center gap-1 px-3 py-1 rounded-lg text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40">
                <Check size={10} /> 保存
              </button>
            </div>
          </div>
        )}

        {providers.length === 0 && !showForm ? (
          <div className="text-center py-10 text-sakura-300 text-xs">还没有供应商，点击上方添加</div>
        ) : providers.map(p => (
          editingId === p.id ? (
            /* ═══ 编辑模式 ═══ */
            <EditProviderCard
              key={p.id}
              provider={getEditingProvider(p.id)!}
              onSave={saveProviderEdit}
              onCancel={() => setEditingId(null)}
              embedded={embedded}
            />
          ) : (
            /* ═══ 展示模式 ═══ */
            <div key={p.id} className={embedded ? "text-xs border-t border-sakura-200/50" : "bg-white border border-sakura-100 rounded-lg text-xs"}>
              <div className={embedded ? "flex items-center justify-between py-3" : "flex items-center justify-between px-3 py-2.5"}>
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <span className="w-6 h-6 rounded flex items-center justify-center text-[9px] font-bold bg-sakura-100 text-sakura-500 shrink-0">
                    {(p.name || "??").slice(0, 2).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sakura-600 font-medium truncate">{p.name}</p>
                    {/* 能力类型标签 */}
                    <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
                      <span className="inline-block px-1.5 py-0.5 rounded text-[9px] bg-sakura-200 text-sakura-600 font-medium">
                        {p.type || "chat"}
                      </span>
                      {p.models.length > 0 ? p.models.map((m, i) => (
                        <span key={i} className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-sakura-50 text-sakura-500 font-mono">
                          {m}
                        </span>
                      )) : (
                        <span className="text-[10px] text-sakura-300">无模型</span>
                      )}
                      <span className={`text-[10px] ${p.has_key ? "text-green-500" : "text-sakura-300"}`}>
                        · {p.has_key ? "有 Key" : "无 Key"}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0 ml-2">
                  <button onClick={() => setEditingId(p.id)}
                    className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500 transition-colors"
                    title="编辑">
                    <Pencil size={11} />
                  </button>
                  <button onClick={() => handleDelete(p.name)}
                    className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors"
                    title="删除">
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            </div>
          )
        ))}
      </div>
    </div>
  );
}

/* ═══ 内联编辑卡片 ═══ */
function EditProviderCard({ provider, onSave, onCancel, embedded }: {
  provider: EditableProvider;
  onSave: (ep: EditableProvider) => Promise<void>;
  onCancel: () => void;
  embedded?: boolean;
}) {
  const [key, setKey] = useState(provider.key);
  const [type, setType] = useState(provider.type || "chat");
  const [apiUrl, setApiUrl] = useState(provider.api_url);
  const [apiKey, setApiKey] = useState(provider.api_key);
  const [model, setModel] = useState(provider.model);
  const [showEditKey, setShowEditKey] = useState(false);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({ id: provider.id, key, type, api_url: apiUrl, api_key: apiKey, model });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={embedded
      ? "bg-sakura-50/50 border border-sakura-200/60 rounded-lg p-4 space-y-2.5 text-xs mt-1"
      : "bg-white border border-sakura-200 rounded-lg p-3 space-y-2.5 text-xs"}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-sakura-500">编辑供应商</p>
        <span className="text-[10px] text-sakura-300">ID: {provider.id}</span>
      </div>

      <div className="space-y-2">
        <div>
          <p className="text-[10px] text-sakura-400 mb-0.5">名称</p>
          <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]"
            value={key} onChange={e => setKey(e.target.value)} />
        </div>
        <div>
          <p className="text-[10px] text-sakura-400 mb-0.5">服务类型</p>
          <div className="flex flex-wrap gap-1">
            {CAPABILITY_TYPES.map(ct => (
              <button key={ct.value} type="button"
                onClick={() => setType(ct.value)}
                className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                  type === ct.value
                    ? "bg-sakura-100 border-sakura-300 text-sakura-600 font-medium"
                    : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"
                }`}
              >
                {ct.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[10px] text-sakura-400 mb-0.5">API 地址</p>
          <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[11px] font-mono"
            value={apiUrl} onChange={e => setApiUrl(e.target.value)} />
        </div>
        <div>
          <p className="text-[10px] text-sakura-400 mb-0.5">API Key</p>
          <div className="relative">
            <input type={showEditKey ? "text" : "password"}
              className="w-full px-2.5 py-1.5 pr-9 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[11px] font-mono"
              value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="留空不改变" />
            <button type="button" onClick={() => setShowEditKey(!showEditKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-sakura-300 hover:text-sakura-500 transition-colors">
              {showEditKey ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          </div>
        </div>
        <div>
          <p className="text-[10px] text-sakura-400 mb-0.5">模型名</p>
          <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-white text-sakura-600 text-[11px] font-mono"
            value={model} onChange={e => setModel(e.target.value)}
            placeholder="gpt-4 / qwen-plus / glm-4-flash" />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1 border-t border-sakura-100">
        <button onClick={onCancel}
          className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
        <button onClick={handleSave} disabled={saving || !key || !apiUrl}
          className="flex items-center gap-1 px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40 transition-shadow">
          {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
          保存
        </button>
      </div>
    </div>
  );
}
