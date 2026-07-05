import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { Plus, Trash2, Check, X, Loader2, Settings, ChevronDown, ChevronUp } from "lucide-react";

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

interface Provider { id: number; name: string; type: string; api_url: string; has_key: boolean; models: string[]; }

export default function ProviderSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Form fields
  const [formType, setFormType] = useState("openai");
  const [formName, setFormName] = useState("");
  const [formHost, setFormHost] = useState("https://api.openai.com/v1");
  const [formKey, setFormKey] = useState("");
  const [formModels, setFormModels] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const load = () => {
    apiGet<{ providers: Provider[] }>("/api/providers")
      .then(d => { setProviders(d.providers); setLoading(false); })
      .catch(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const openForm = () => {
    setFormType("openai"); setFormName(""); setFormHost("https://api.openai.com/v1");
    setFormKey(""); setFormModels(""); setTestResult(null); setShowForm(true);
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
      const res = await apiPost<{ ok: boolean; models?: string[]; error?: string }>("/api/providers/test", {
        api_url: formHost, api_key: formKey,
      });
      setTestResult({ ok: res.ok, msg: res.ok ? `连接成功` : `失败: ${res.error}` });
    } catch { setTestResult({ ok: false, msg: "请求失败" }); }
    setTesting(false);
  };

  const handleSave = async () => {
    const modelsArr = formModels.split("\n").map(s => s.trim()).filter(Boolean);
    if (!formName || !formHost) return;
    await apiPost("/api/providers", {
      type: formType, name: formName, api_url: formHost,
      api_key: formKey, models: modelsArr.length > 0 ? modelsArr : [formName + " Default"],
    });
    setShowForm(false); load();
  };

  const handleDelete = async (id: number) => {
    await apiPost("/api/providers/delete", { id }); load();
  };

  if (loading) return <div className="flex items-center justify-center py-12"><Loader2 size={16} className="text-sakura-300 animate-spin" /></div>;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-semibold text-sakura-500">模型供应商</p>
          <p className="text-[11px] text-sakura-300">{providers.length} 个供应商</p>
        </div>
        <button onClick={openForm}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors">
          <Plus size={12} /> 添加
        </button>
      </div>

      {/* Provider List */}
      <div className="space-y-1">
        {providers.length === 0 ? (
          <div className="text-center py-10 text-sakura-300 text-xs">还没有供应商，点击上方添加</div>
        ) : providers.map(p => (
          <div key={p.id} className="flex items-center justify-between px-3 py-2.5 bg-white border border-sakura-100 rounded-lg text-xs">
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="w-6 h-6 rounded flex items-center justify-center text-[9px] font-bold bg-sakura-100 text-sakura-500 shrink-0">
                {p.name.slice(0, 2).toUpperCase()}
              </span>
              <div className="min-w-0">
                <p className="text-sakura-600 font-medium truncate">{p.name}</p>
                <p className="text-[10px] text-sakura-400">{p.models.length} 模型 · {p.has_key ? "有 Key" : "无 Key"}</p>
              </div>
            </div>
            <button onClick={() => handleDelete(p.id)} className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500 shrink-0">
              <Trash2 size={11} />
            </button>
          </div>
        ))}
      </div>

      {/* Add Form */}
      {showForm && (
        <div className="mt-3 bg-white border border-sakura-100 rounded-xl p-4 space-y-3 text-xs">
          <p className="text-xs font-semibold text-sakura-500">添加供应商</p>

          <select value={formType} onChange={e => selectType(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 text-xs">
            {PROVIDER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>

          <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300"
            placeholder="显示名称" value={formName} onChange={e => setFormName(e.target.value)} />

          <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px]"
            placeholder="API 地址（如 https://api.openai.com/v1）" value={formHost} onChange={e => setFormHost(e.target.value)} />

          <input className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px]"
            placeholder="API Key（Ollama 不需要）" value={formKey} onChange={e => setFormKey(e.target.value)} />

          <div>
            <p className="text-[10px] text-sakura-400 mb-1">模型名（每行一个）</p>
            <textarea className="w-full px-3 py-2 rounded-lg border border-sakura-100 bg-white text-sakura-600 placeholder:text-sakura-300 font-mono text-[10px] min-h-[60px] resize-none"
              placeholder="gpt-4&#10;gpt-3.5-turbo&#10;gpt-4-vision-preview" value={formModels} onChange={e => setFormModels(e.target.value)} rows={3} />
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
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 rounded-lg text-[11px] text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
            <button onClick={handleSave} disabled={!formName || !formHost}
              className="px-4 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40 transition-shadow">
              保存
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
