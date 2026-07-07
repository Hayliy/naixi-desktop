import { useState, useEffect } from "react";
import { Plus, Trash2, Check, X, Loader2, Settings, ChevronDown, ChevronUp, Pencil, Save, Eye, EyeOff, Zap, Folder, Tag, Image } from "lucide-react";
import { useAppConfig } from "@/contexts/AppContext";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";
import ThemeSettings from "@/components/ThemeSettings";
import { prefillAvatars, getAvatarTotal, refreshAvatarCache } from "@/lib/avatar";

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

export default function ProviderSettings() {
  const { config, loaded, refreshConfig } = useAppConfig();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [avatarCount, setAvatarCount] = useState(() => getAvatarTotal());
  const [avatarGenerating, setAvatarGenerating] = useState(false);

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
    <div>
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100">
        <span className="text-xs font-semibold text-sakura-500">模型供应商</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-sakura-300">{providers.length} 个</span>
          <button onClick={openForm}
            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors">
            <Plus size={10} /> 添加
          </button>
        </div>
      </div>

      {/* Provider 列表 - 固定高度，超出滚动 */}
      <div className="space-y-1 max-h-[320px] overflow-y-auto overflow-x-hidden pr-0.5">
        {providers.length === 0 ? (
          <div className="text-center py-10 text-sakura-300 text-xs">还没有供应商，点击上方添加</div>
        ) : providers.map(p => (
            <div key={p.id}>
              <div className="bg-white border border-sakura-100 rounded-lg text-xs">
                <div className="flex items-center justify-between px-3 py-2.5">
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <span className="w-6 h-6 rounded flex items-center justify-center text-[9px] font-bold bg-sakura-100 text-sakura-500 shrink-0">
                      {(p.name || "??").slice(0, 2).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sakura-600 font-medium truncate">{p.name}</p>
                      <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
                        <span className="inline-block px-1.5 py-0.5 rounded text-[9px] bg-sakura-200 text-sakura-600 font-medium">
                          {p.type || "chat"}
                        </span>
                        {p.models.length > 0 ? p.models.map((m, i) => (
                          <span key={i} className="inline-block px-1.5 py-0.5 rounded text-[10px] bg-sakura-50 text-sakura-500 font-mono">{m}</span>
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
                      className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500 transition-colors" title="编辑">
                      <Pencil size={11} />
                    </button>
                    <button onClick={() => handleDelete(p.name)}
                      className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors" title="删除">
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              </div>
              {editingId === p.id && (
                <EditProviderCard
                  provider={getEditingProvider(p.id)!}
                  onSave={saveProviderEdit}
                  onCancel={() => setEditingId(null)}
                />
              )}
            </div>
          ))
        }
      </div>

      {/* 头像与昵称设置 */}
      <div className="mt-4 border-t border-sakura-100 pt-3">
        <button onClick={() => setAvatarOpen(!avatarOpen)}
          className="flex items-center gap-1.5 text-xs font-semibold text-sakura-500 hover:text-sakura-600 transition-colors mb-2">
          {avatarOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          头像与昵称
        </button>
        {avatarOpen && (
          <div className="space-y-3 pt-2 text-xs">
            <AvatarRow label="我的头像" storageKey="naixi_user_avatar" previewKey="用户" />
            <AvatarRow label="我的昵称" storageKey="naixi_user_name" isName />
            <AvatarRow label="奶昔头像" storageKey="naixi_bot_avatar" previewKey="奶昔" />
            <AvatarRow label="奶昔昵称" storageKey="naixi_bot_name" isName />
            {/* AI 头像预生成 */}
            <div className="pt-1 border-t border-sakura-100">
              {avatarGenerating ? (
                <div className="space-y-1.5">
                  <p className="text-[10px] text-sakura-400">AI 头像生成中（每张约 5-15 秒）...</p>
                  <div className="flex items-center gap-2">
                    <Loader2 size={11} className="animate-spin text-sakura-400 shrink-0" />
                    <span className="text-[10px] text-sakura-500 font-medium">{avatarCount} 个已生成</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-sakura-100 overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-sakura-300 to-sakura-500 transition-all"
                      style={{ width: `${Math.min(100, (avatarCount / 50) * 100)}%` }} />
                  </div>
                </div>
              ) : (
                <button
                  onClick={async () => {
                    setAvatarGenerating(true);
                    setAvatarCount(0);
                    const ok = await prefillAvatars(50);
                    if (ok) {
                      // 轮询进度
                      const poll = setInterval(async () => {
                        try {
                          const res = await apiGet<{running: boolean; completed: number; total: number}>("/api/avatar/gen-status");
                          if (res.completed !== undefined) setAvatarCount(res.completed);
                          if (!res.running && res.completed >= res.total) {
                            clearInterval(poll);
                            await refreshAvatarCache();
                            setAvatarCount(getAvatarTotal());
                            setAvatarGenerating(false);
                          }
                        } catch {}
                      }, 3000);
                    } else {
                      setAvatarGenerating(false);
                      notify("请先在「模型供应商」中添加画图模型（如阿里百炼 Wanx2.1）", "warning");
                    }
                  }}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white hover:shadow-md transition-shadow"
                >
                  <Image size={11} />
                  批量生成 50 个头像
                </button>
              )}
              <p className="text-[9px] text-sakura-300 mt-1">使用 Wanx 2.1 生成二次元风格头像，生成后所有图标自动替换</p>
            </div>
          </div>
        )}
      </div>

      {/* MCP 服务器管理 */}
      <MCPSection />
      {/* 主题设置 */}
      <div className="mt-4 border-t border-sakura-100 pt-3">
        <button onClick={() => setThemeOpen(!themeOpen)}
          className="flex items-center gap-1.5 text-xs font-semibold text-sakura-500 hover:text-sakura-600 transition-colors mb-2">
          {themeOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          主题与快捷键
        </button>
        {themeOpen && (
          <div className="space-y-3 pt-2">
            <ThemeSettings />
            <ShortcutsSettings />
          </div>
        )}
      </div>

      {/* 新增表单 */}
      {showForm && (
        <div className="mt-3 bg-white border border-sakura-100 rounded-xl p-4 space-y-3 text-xs">
          <p className="text-xs font-semibold text-sakura-500">添加供应商</p>

          {/* 能力类型 */}
          <select value={formType} onChange={e => selectType(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-xs">
            {PROVIDER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>

          {/* 服务类型 */}
          <div>
            <p className="text-[10px] text-sakura-400 mb-1">服务类型</p>
            <div className="flex flex-wrap gap-1.5">
              {CAPABILITY_TYPES.map(ct => (
                <button key={ct.value} type="button"
                  onClick={() => {
                    setFormCapability(ct.value);
                    setTestResult(null);
                  }}
                  className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                    formCapability === ct.value
                      ? "bg-sakura-100 border-sakura-300 text-sakura-600 font-medium"
                      : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"
                  }`}
                  title={ct.desc}
                >
                  {ct.label}
                </button>
              ))}
            </div>
          </div>

          <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300"
            placeholder="显示名称" value={formName} onChange={e => setFormName(e.target.value)} />

          <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px]"
            placeholder="API 地址（如 https://api.openai.com/v1）" value={formHost} onChange={e => setFormHost(e.target.value)} />

          <div className="relative">
            <input type={showFormKey ? "text" : "password"}
              className="w-full px-3 py-2 pr-9 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px]"
              placeholder="API Key（Ollama 不需要）" value={formKey} onChange={e => setFormKey(e.target.value)} />
            <button type="button" onClick={() => setShowFormKey(!showFormKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-sakura-300 hover:text-sakura-500 transition-colors">
              {showFormKey ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          </div>

          <div>
            <p className="text-[10px] text-sakura-400 mb-1">模型名（留空自动使用名称）</p>
            <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px]"
              placeholder="gpt-4 / qwen-plus / glm-4-flash" value={formModels} onChange={e => setFormModels(e.target.value)} />
          </div>

          <div className="flex items-center gap-2">
            <button onClick={handleTest} disabled={testing || !formHost}
              className="px-3 py-1.5 rounded-lg text-[11px] bg-sakura-100 text-sakura-500 hover:bg-sakura-200 disabled:opacity-50 transition-colors">
              {testing ? <Loader2 size={11} className="animate-spin" /> : "测试"}
            </button>
            {testResult && (
              <span className={`text-[10px] ${testResult.ok ? "text-green-600" : "text-red-500"}`}>
                {testResult.ok ? <Check size={10} className="inline" /> : <X size={10} className="inline" />}
                {testResult.msg}
              </span>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-1 border-t border-sakura-100">
            <button onClick={() => { setShowForm(false); resetForm(); }}
              className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
            <button onClick={handleAddSave} disabled={!formName || !formHost}
              className="px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40 transition-shadow">
              保存
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══ 内联编辑卡片 ═══ */
function EditProviderCard({ provider, onSave, onCancel }: {
  provider: EditableProvider;
  onSave: (ep: EditableProvider) => Promise<void>;
  onCancel: () => void;
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
    <div className="bg-white border border-sakura-200 rounded-lg p-3 space-y-2.5 text-xs">
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

/* ─── MCP 服务器管理 ─── */

function MCPSection() {
  const { notify } = useToast();
  const [servers, setServers] = useState<Record<string, { command: string; args: string[]; env: Record<string, string> }>>({});
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [collapsed, setCollapsed] = useState(true);

  const loadServers = async () => {
    try {
      const res = await apiGet<{ servers: any }>("/api/mcp/servers");
      setServers(res.servers || {});
    } catch {}
    setLoading(false);
  };

  useEffect(() => { loadServers(); }, []);

  const handleAdd = async () => {
    if (!name.trim() || !command.trim()) return;
    const updated = { ...servers };
    if (editingKey && editingKey !== name.trim()) {
      delete updated[editingKey];
    }
    updated[name.trim()] = {
      command: command.trim(),
      args: args.split(" ").filter(Boolean),
      env: {},
    };
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setServers(updated);
      setShowForm(false);
      setEditingKey(null);
      setName(""); setCommand(""); setArgs("");
    } catch {}
  };

  const handleEdit = (key: string) => {
    const srv = servers[key];
    if (!srv) return;
    setEditingKey(key);
    setName(key);
    setCommand(srv.command);
    setArgs(srv.args?.join(" ") || "");
    setShowForm(true);
  };

  const handleDelete = async (key: string) => {
    const updated = { ...servers };
    delete updated[key];
    try {
      await apiPost("/api/mcp/servers", { servers: updated });
      setServers(updated);
    } catch {}
  };

  const handleConnect = async () => {
    try {
      const res = await apiPost<{ ok: boolean; tool_count: number }>("/api/mcp/connect");
      if (res.ok) notify(`MCP 连接成功，当前共 ${res.tool_count} 个工具`, "success");
    } catch {}
  };

  const handleTestSingle = async (key: string) => {
    try {
      const res = await apiPost<{ ok: boolean; error?: string; tools?: string[] }>("/api/mcp/test", { name: key });
      if (res.ok) {
        notify(`✅ ${key} 连接成功！工具: ${(res.tools || []).join(", ")}`, "success");
      } else {
        notify(`❌ ${key} 连接失败: ${res.error || "未知错误"}`, "error");
      }
    } catch (e) {
      notify(`❌ ${key} 测试异常: ${String(e)}`, "error");
    }
  };

  if (loading) return null;

  return (
    <div className="mt-4 border-t border-sakura-100 pt-3">
      <button onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1.5 text-xs font-semibold text-sakura-500 hover:text-sakura-600 transition-colors mb-2">
        {collapsed ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
        MCP 服务器
        <span className="text-[10px] text-sakura-300 font-normal">({Object.keys(servers).length})</span>
      </button>

      {!collapsed && (
        <div className="space-y-1.5">
          {Object.keys(servers).length > 0 && (
            <button onClick={handleConnect}
              className="w-full px-3 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-teal-400 to-teal-500 text-white hover:shadow-md transition-shadow mb-1">
              连接 MCP 服务器
            </button>
          )}

          {!editingKey && (
            showForm ? (
              <div className="bg-white border border-sakura-100 rounded-lg px-2.5 py-2 space-y-2 text-xs">
                <p className="text-[11px] font-semibold text-sakura-500">添加 MCP 服务器</p>
                <div>
                  <p className="text-[10px] text-sakura-400 mb-0.5">名称</p>
                  <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]"
                    value={name} onChange={e => setName(e.target.value)} placeholder="例如: fetch" />
                </div>
                <div>
                  <p className="text-[10px] text-sakura-400 mb-0.5">启动命令</p>
                  <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                    value={command} onChange={e => setCommand(e.target.value)} placeholder="例如: uvx" />
                </div>
                <div>
                  <p className="text-[10px] text-sakura-400 mb-0.5">参数（空格分隔）</p>
                  <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                    value={args} onChange={e => setArgs(e.target.value)} placeholder="例如: mcp-server-fetch" />
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button onClick={() => { setShowForm(false); setName(""); setCommand(""); setArgs(""); }}
                    className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
                  <button onClick={handleAdd} disabled={!name.trim() || !command.trim()}
                    className="flex items-center gap-1 px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40">
                    <Plus size={11} /> 添加
                  </button>
                </div>
              </div>
            ) : (
              <button onClick={() => setShowForm(true)}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 transition-colors w-full">
                <Plus size={11} /> 添加 MCP 服务器
              </button>
            )
          )}

          <div className="max-h-[300px] overflow-y-auto space-y-1.5 pr-0.5">
          {Object.entries(servers).map(([key, srv]) => (
            <div key={key}>
              <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-sakura-50 border border-sakura-100">
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-medium text-sakura-600 truncate">{key}</p>
                  <p className="text-[10px] text-sakura-400 truncate font-mono">{srv.command} {srv.args?.join(" ")}</p>
                </div>
                <button onClick={() => handleTestSingle(key)}
                  className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500 transition-colors shrink-0" title="测试连接">
                  <Zap size={11} />
                </button>
                <button onClick={() => handleEdit(key)}
                  className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500 transition-colors shrink-0" title="编辑">
                  <Pencil size={11} />
                </button>
                <button onClick={() => handleDelete(key)}
                  className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 transition-colors shrink-0">
                  <Trash2 size={11} />
                </button>
              </div>
              {editingKey === key && (
                <div className="bg-white border border-sakura-100 rounded-lg px-2.5 py-2 space-y-2 text-xs mt-1">
                  <p className="text-[11px] font-semibold text-sakura-500">编辑 MCP 服务器</p>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">名称</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px]"
                      value={name} onChange={e => setName(e.target.value)} placeholder="例如: fetch" />
                  </div>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">启动命令</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                      value={command} onChange={e => setCommand(e.target.value)} placeholder="例如: uvx" />
                  </div>
                  <div>
                    <p className="text-[10px] text-sakura-400 mb-0.5">参数（空格分隔）</p>
                    <input className="w-full px-2.5 py-1.5 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-[11px] font-mono"
                      value={args} onChange={e => setArgs(e.target.value)} placeholder="例如: mcp-server-fetch" />
                  </div>
                  <div className="flex justify-end gap-2 pt-1">
                    <button onClick={() => { setShowForm(false); setEditingKey(null); setName(""); setCommand(""); setArgs(""); }}
                      className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
                    <button onClick={handleAdd} disabled={!name.trim() || !command.trim()}
                      className="flex items-center gap-1 px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40">
                      <Check size={11} /> 保存
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── 头像与昵称设置项 ─── */
function AvatarRow({ label, storageKey, isName, previewKey }: { label: string; storageKey: string; isName?: boolean; previewKey?: string }) {
  const [val, setVal] = useState(() => localStorage.getItem(storageKey) || "");
  const save = (v: string) => { setVal(v); localStorage.setItem(storageKey, v); };
  const clear = () => { setVal(""); localStorage.removeItem(storageKey); };

  return (
    <div className="flex items-center gap-2">
      {!isName && (
        <div className="w-7 h-7 rounded-full overflow-hidden bg-sakura-100 shrink-0">
          {val ? (
            <img src={val} alt={label} className="w-full h-full object-cover" onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-[8px] text-sakura-400">{previewKey?.[0] || "?"}</div>
          )}
        </div>
      )}
      <input value={val} onChange={e => save(e.target.value)}
        className={`flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 ${isName ? "" : "font-mono"}`}
        placeholder={isName ? "留空使用默认" : "头像图片 URL（留空自动 DiceBear）"} />
      {val && (
        <button onClick={clear} className="p-0.5 text-sakura-300 hover:text-red-500 shrink-0"><X size={10} /></button>
      )}
    </div>
  );
}

/* ─── 快捷键设置 ─── */
const DEFAULT_SHORTCUTS: { key: string; desc: string }[] = [
  { key: "Ctrl+Enter", desc: "发送消息" },
  { key: "Enter", desc: "换行" },
  { key: "Ctrl+,", desc: "打开/关闭设置面板" },
  { key: "Escape", desc: "取消/关闭当前弹窗" },
  { key: "Ctrl+L", desc: "清空对话" },
  { key: "↑ (输入框)", desc: "上一条消息" },
];

function ShortcutsSettings() {
  const [s, setS] = useState<{ key: string; desc: string }[]>(() => {
    try { return JSON.parse(localStorage.getItem("naixi_shortcuts") || "null") || DEFAULT_SHORTCUTS; } catch { return DEFAULT_SHORTCUTS; }
  });
  const [ei, setEi] = useState<number | null>(null);
  const [ek, setEk] = useState("");
  const [ed, setEd] = useState("");
  const save = (v: typeof s) => { setS(v); localStorage.setItem("naixi_shortcuts", JSON.stringify(v)); };

  return (
    <div className="space-y-2 text-xs">
      <p className="text-[10px] text-sakura-400 mb-1">快捷键列表（按 Ctrl+, 打开设置面板）</p>
      <div className="space-y-1">
        {s.map((item, i) => ei === i ? (
          <div key={i} className="flex items-center gap-1">
            <input value={ek} onChange={e => setEk(e.target.value)} className="flex-1 px-1.5 py-0.5 rounded border border-sakura-100 bg-sakura-50 text-[10px] font-mono text-sakura-600 w-20" placeholder="快捷键" />
            <input value={ed} onChange={e => setEd(e.target.value)} className="flex-1 px-1.5 py-0.5 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600" placeholder="说明" />
            <button onClick={() => { if (ek.trim() && ed.trim()) { const n = [...s]; n[i] = { key: ek.trim(), desc: ed.trim() }; save(n); setEi(null); } }} className="p-0.5 text-sakura-400 hover:text-sakura-600"><Check size={10} /></button>
          </div>
        ) : (
          <div key={i} className="flex items-center justify-between group">
            <span className="flex items-center gap-1.5">
              <code className="px-1 py-0.5 rounded bg-sakura-50 text-[10px] font-mono text-sakura-500">{item.key}</code>
              <span className="text-[10px] text-sakura-400">{item.desc}</span>
            </span>
            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button onClick={() => { setEi(i); setEk(item.key); setEd(item.desc); }} className="p-0.5 text-sakura-300 hover:text-sakura-500"><Pencil size={9} /></button>
              <button onClick={() => save(s.filter((_, j) => j !== i))} className="p-0.5 text-sakura-300 hover:text-red-500"><X size={9} /></button>
            </div>
          </div>
        ))}
      </div>
      <button onClick={() => save([...s, { key: "新快捷键", desc: "说明" }])}
        className="flex items-center gap-1 text-[10px] text-sakura-400 hover:text-sakura-500">
        <Plus size={10} /> 添加快捷键
      </button>
      <button onClick={() => save(DEFAULT_SHORTCUTS)}
        className="w-full mt-1 px-2.5 py-1 rounded-lg text-[10px] border border-sakura-100 text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 transition-colors">
        恢复默认
      </button>
      <p className="text-[9px] text-sakura-300 mt-1">部分快捷键（如 Ctrl+L 清空对话）需要页面刷新后生效。</p>
    </div>
  );
}