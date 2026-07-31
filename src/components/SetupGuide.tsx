import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { useAppConfig } from "@/contexts/AppContext";

/* ─── 预设的 API 提供商 ─── */
const API_PROVIDERS = [
  {
    id: "bailian",
    name: "阿里百炼",
    desc: "通义千问系列，注册送 100 万 Token",
    url: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    keyUrl: "https://bailian.console.aliyun.com/#/api-key",
    modelHint: "qwen3.7-max",
  },
  {
    id: "zhipu",
    name: "智谱 AI",
    desc: "GLM 系列，免费版有并发限制",
    url: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    keyUrl: "https://open.bigmodel.cn/usercenter/apikeys",
    modelHint: "glm-4-flash",
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    desc: "DeepSeek 系列，性价比高",
    url: "https://api.deepseek.com/v1/chat/completions",
    keyUrl: "https://platform.deepseek.com/api_keys",
    modelHint: "deepseek-chat",
  },
  {
    id: "agnes",
    name: "Agnes AI",
    desc: "无限期免费，1M 上下文，30 RPM",
    url: "https://apihub.agnes-ai.com/v1/chat/completions",
    keyUrl: "https://platform.agnes-ai.com/",
    modelHint: "agnes-2.0-flash",
  },
  {
    id: "openai",
    name: "OpenAI",
    desc: "GPT 系列，需海外支付方式",
    url: "https://api.openai.com/v1/chat/completions",
    keyUrl: "https://platform.openai.com/api-keys",
    modelHint: "gpt-5.5",
  },
  {
    id: "anthropic",
    name: "Anthropic",
    desc: "Claude 系列，需海外支付方式",
    url: "https://api.anthropic.com/v1/messages",
    keyUrl: "https://console.anthropic.com/settings/keys",
    modelHint: "claude-sonnet-4-20250514",
  },
  {
    id: "gemini",
    name: "Google Gemini",
    desc: "Gemini 系列，有免费额度",
    url: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    keyUrl: "https://aistudio.google.com/apikey",
    modelHint: "gemini-2.0-flash",
  },
  {
    id: "moonshot",
    name: "月之暗面",
    desc: "Kimi 系列，国内直连",
    url: "https://api.moonshot.cn/v1/chat/completions",
    keyUrl: "https://platform.moonshot.cn/console/api-keys",
    modelHint: "kimi-k2.7-code",
  },
  {
    id: "custom",
    name: "自定义",
    desc: "任意兼容 OpenAI 格式的 API",
    url: "",
    keyUrl: "",
    models: [],
  },
];

export default function SetupGuide({ onClose, standalone }: { onClose: () => void; standalone?: boolean }) {
  const { refreshConfig } = useAppConfig();
  const [step, setStep] = useState(0);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("http://localhost:9845/api/webhook/my-workflow");
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [fetchedModels, setFetchedModels] = useState<{ id: string; owned_by: string }[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [settingsTab, setSettingsTab] = useState("api");
  const [prompts, setPrompts] = useState<Record<string, { label: string; prompt: string }>>({});
  const [promptDirty, setPromptDirty] = useState(false);
  const [promptSaved, setPromptSaved] = useState(false);

  useEffect(() => {
    apiGet("/api/desktop/platforms").then((d: any) => {
      if (d?.platforms) setPlatforms(d.platforms);
    }).catch((err) => console.error("[SetupGuide] 平台列表加载失败:", err));
    // 加载提示词
    apiGet("/api/desktop/prompts").then((d: any) => {
      if (d?.prompts) setPrompts(d.prompts);
    }).catch((err) => console.error("[SetupGuide] 提示词加载失败:", err));
  }, []);

  const provider = API_PROVIDERS.find(p => p.id === selectedProvider);

  const handleTest = async () => {
    if (!(apiKey || "").trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiPost("/api/desktop/test-connection", {
        provider: selectedProvider,
        api_key: apiKey,
        api_url: apiUrl || provider?.url || "",
      });
      setTestResult(r as any);
    } catch {
      setTestResult({ ok: false, error: "请求失败，请检查后端是否运行" });
    }
    setTesting(false);
  };

  const handleSave = async () => {
    const config: any = {
      api_providers: {
        [selectedProvider]: {
          api_key: apiKey,
          api_url: apiUrl || provider?.url || "",
          model: modelName || provider?.modelHint || "default",
        },
      },
      platform_configs: {},
    };

    // 合并已有配置（保留其他 provider）
    try {
      const existing = await apiGet<any>("/api/desktop/config");
      if (existing?.api_providers) {
        config.api_providers = { ...existing.api_providers, ...config.api_providers };
      }
      if (existing?.platform_configs) {
        config.platform_configs = existing.platform_configs;
      }
    } catch {}

    try {
      await apiPost("/api/desktop/config", config);
      refreshConfig();
      setSaved(true);
      if (!standalone) setTimeout(() => setStep(1), 600);
    } catch {}
  };

  // 从 API 拉取可用模型列表
  const handleFetchModels = async () => {
    const key = (apiKey || "").trim();
    const url = (apiUrl || provider?.url || "").trim();
    if (!key || !url) return;
    setLoadingModels(true);
    setFetchedModels([]);
    try {
      const r = await apiPost<any>("/api/desktop/models", { api_url: url, api_key: key });
      if (r?.models?.length) {
        setFetchedModels(r.models);
      } else {
        setFetchedModels([{ id: r?.error || "API 未返回模型列表", owned_by: "error" }]);
      }
    } catch {
      setFetchedModels([{ id: "请求失败，请检查 API 地址", owned_by: "error" }]);
    }
    setLoadingModels(false);
  };

  const handleFinish = () => {
    onClose();
  };

  if (standalone) {
    return (
      <div className="space-y-6">
        {/* 全页面模式：标签页切换 */}
        <div className="flex items-center gap-1 border-b border-sakura-100 pb-3">
          {[
            { key: "api", label: "API 配置" },
            { key: "platforms", label: "平台连接" },
            { key: "prompts", label: "提示词" },
          ].map(tab => (
            <button key={tab.key} onClick={() => setSettingsTab(tab.key)}
              className={`px-4 py-2 rounded-lg text-xs transition-colors ${
                settingsTab === tab.key
                  ? "bg-sakura-100 text-sakura-600 font-medium"
                  : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"
              }`}
            >{tab.label}</button>
          ))}
        </div>

        {settingsTab === "api" && (
          <SetupSteps
            step={step} setStep={setStep}
            selectedProvider={selectedProvider}             setSelectedProvider={setSelectedProvider}
            modelName={modelName} setModelName={setModelName}
            apiKey={apiKey} setApiKey={setApiKey}
            apiUrl={apiUrl} setApiUrl={setApiUrl}
            saved={saved}
            testing={testing} testResult={testResult} setTestResult={setTestResult}
            handleTest={handleTest} handleSave={handleSave}
            handleFetchModels={handleFetchModels}
            fetchedModels={fetchedModels} setFetchedModels={setFetchedModels}
            loadingModels={loadingModels}
            standalone={standalone}
            webhookUrl={webhookUrl}
            platforms={platforms}
            provider={provider}
            onFinish={handleFinish}
          />
        )}

        {settingsTab === "platforms" && (
          <div className="space-y-4">
            <p className="text-sm font-medium text-sakura-600">连接到消息平台</p>
            <p className="text-xs text-sakura-400">将工作流发布为 API，在目标平台上配置 webhook 回调</p>
            <div className="bg-sakura-50 border border-sakura-200 rounded-xl px-4 py-3">
              <p className="text-[11px] text-sakura-500 mb-1">你的 webhook 地址</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 px-3 py-2 bg-white border border-sakura-200 rounded-lg text-xs font-mono text-sakura-700 truncate">{webhookUrl}</code>
                <button onClick={() => navigator.clipboard.writeText(webhookUrl)}
                  className="px-3 py-2 bg-sakura-100 text-sakura-600 rounded-lg text-xs hover:bg-sakura-200 shrink-0">复制</button>
              </div>
            </div>
            <div className="space-y-2 max-h-[60vh] overflow-y-auto">
              {platforms.map((p: any) => (
                <details key={p.id} className="border border-gray-200 rounded-xl overflow-hidden">
                  <summary className="px-4 py-3 text-xs font-medium text-gray-700 cursor-pointer hover:bg-gray-50 flex items-center gap-2">
                    <span className="text-sakura-500">▸</span>
                    <span>{p.name}</span>
                    <span className="text-gray-400 ml-1">({p.platform})</span>
                  </summary>
                  <div className="px-4 py-3 border-t border-gray-100 bg-gray-50/50">
                    <p className="text-xs text-gray-500 mb-3">{p.description}</p>
                    <ol className="space-y-2">
                      {p.steps.map((s: string, i: number) => (
                        <li key={i} className="text-xs text-gray-600 flex gap-2">
                          <span className="text-sakura-400 font-medium shrink-0">{i + 1}.</span>
                          <span>{s}</span>
                        </li>
                      ))}
                    </ol>
                    {p.links && p.links.length > 0 && (
                      <div className="mt-3 flex gap-2">
                        {p.links.map((link: any, i: number) => (
                          <a key={i} href={link.url} target="_blank" rel="noopener noreferrer"
                            className="text-xs text-sakura-500 underline hover:text-sakura-600">{link.label} →</a>
                        ))}
                      </div>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}

        {settingsTab === "prompts" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-sakura-600">场景提示词</p>
                <p className="text-xs text-sakura-400 mt-0.5">自定义各个对话场景的系统提示词</p>
              </div>
              {promptDirty && (
                <button onClick={async () => {
                  try {
                    await apiPost("/api/desktop/prompts", { prompts });
                    setPromptSaved(true);
                    setPromptDirty(false);
                    setTimeout(() => setPromptSaved(false), 2000);
                  } catch {}
                }}
                  className="px-4 py-2 bg-sakura-500 text-white rounded-lg text-xs hover:bg-sakura-600 transition-colors">
                  {promptSaved ? "已保存 ✓" : "保存全部"}
                </button>
              )}
            </div>
            {Object.entries(prompts).map(([key, p]: [string, any]) => (
              <div key={key} className="border border-gray-200 rounded-xl overflow-hidden">
                <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-700">{p.label}</span>
                  <button onClick={async () => {
                    try {
                      const r = await apiPost<any>("/api/desktop/prompts/reset", { scene: key });
                      if (r?.prompt) {
                        setPrompts(prev => ({ ...prev, [key]: r.prompt }));
                        setPromptDirty(true);
                      }
                    } catch {}
                  }}
                    className="text-[10px] text-sakura-400 hover:text-sakura-500 underline">恢复默认</button>
                </div>
                <textarea
                  value={p.prompt}
                  onChange={e => {
                    setPrompts(prev => ({ ...prev, [key]: { ...prev[key], prompt: e.target.value } }));
                    setPromptDirty(true);
                    setPromptSaved(false);
                  }}
                  className="w-full h-[160px] px-4 py-3 text-xs font-mono leading-relaxed outline-none resize-none border-0 focus:ring-0"
                  placeholder="输入提示词..."
                />
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  /* ─── 弹窗模式（首次启动，非阻塞：引导存在但不拦住整个应用） ─── */
  return (
    <div className="fixed inset-0 z-50 pointer-events-none flex items-end justify-end p-6">
      <div className="pointer-events-auto bg-white rounded-2xl shadow-2xl w-[640px] max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-5 border-b border-sakura-100 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-sakura-600">欢迎使用奶昔</h2>
            <p className="text-xs text-sakura-400 mt-1">先配好 API Key 和消息平台，三步上手</p>
          </div>
          <div className="flex items-center gap-2">
            {/* 步骤指示器 */}
            <div className="flex items-center gap-1.5 mr-3">
              {[0, 1, 2].map(i => (
                <div key={i} className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                  step === i ? "bg-sakura-500 text-white" :
                  step > i ? "bg-green-100 text-green-600" :
                  "bg-sakura-100 text-sakura-400"
                }`}>{step > i ? "✓" : i + 1}</div>
              ))}
            </div>
            {/* 稍后配置：明确可跳过的关闭入口 */}
            <button onClick={onClose} className="text-xs text-sakura-500 hover:text-sakura-600 px-2.5 py-1 rounded-lg hover:bg-sakura-50 transition-colors whitespace-nowrap">
              稍后配置
            </button>
            {/* 关闭按钮 */}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition-colors" title="关闭">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>
        <div className="px-6 py-5">
          <SetupSteps
            step={step} setStep={setStep}
            selectedProvider={selectedProvider}             setSelectedProvider={setSelectedProvider}
            modelName={modelName} setModelName={setModelName}
            apiKey={apiKey} setApiKey={setApiKey}
            apiUrl={apiUrl} setApiUrl={setApiUrl}
            saved={saved}
            testing={testing} testResult={testResult} setTestResult={setTestResult}
            handleTest={handleTest} handleSave={handleSave}
            handleFetchModels={handleFetchModels}
            fetchedModels={fetchedModels} setFetchedModels={setFetchedModels}
            loadingModels={loadingModels}
            standalone={standalone}
            webhookUrl={webhookUrl}
            platforms={platforms}
            provider={provider}
            onFinish={handleFinish}
          />
        </div>
      </div>
    </div>
  );
}

/* ─── 三步引导内容 ─── */
function SetupSteps({
  step, setStep,
  selectedProvider, setSelectedProvider,
  modelName, setModelName,
  apiKey, setApiKey,
  apiUrl, setApiUrl,
  saved,
  testing, testResult, setTestResult,
  handleTest, handleSave,
  handleFetchModels,
  fetchedModels, setFetchedModels,
  loadingModels,
  standalone,
  webhookUrl,
  platforms, provider, onFinish,
}: any) {

  const copy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  if (step === 0) {
    return (
      <div className="space-y-5">
        <p className="text-sm font-medium text-sakura-600">第一步：配置 API Key</p>
        <p className="text-xs text-sakura-400">选择模型提供商，填入 API Key，工作流中的 LLM 节点才能正常使用</p>

        {/* 提供商选择 */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {API_PROVIDERS.map(p => (
            <button key={p.id} onClick={() => { setSelectedProvider(p.id); setApiUrl(p.url); setModelName(p.modelHint || ""); setTestResult(null); }}
              className={`border rounded-xl px-3 py-3 text-left transition-all ${
                selectedProvider === p.id
                  ? "border-sakura-400 bg-sakura-50 ring-1 ring-sakura-300"
                  : "border-gray-200 hover:border-sakura-200 hover:bg-sakura-50/50"
              }`}
            >
              <p className="text-xs font-medium text-gray-700">{p.name}</p>
              <p className="text-[10px] text-gray-400 mt-0.5 leading-relaxed">{p.desc}</p>
            </button>
          ))}
        </div>

        {selectedProvider && provider && (
          <div className="space-y-3">
            {provider.keyUrl && (
              <a href={provider.keyUrl} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-sakura-500 hover:text-sakura-600 underline">
                去 {provider.name} 获取 API Key →
              </a>
            )}
            <div>
              <label className="block text-xs text-gray-500 mb-1">API Key</label>
              <input value={apiKey} onChange={e => setApiKey(e.target.value)}
                type="password" placeholder="sk-..." autoComplete="off"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300 font-mono" />
            </div>
            {selectedProvider === "custom" && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">API 地址</label>
                <input value={apiUrl} onChange={e => setApiUrl(e.target.value)}
                  placeholder="https://api.example.com/v1/chat/completions"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300" />
              </div>
            )}
            <div>
              <label className="block text-xs text-gray-500 mb-1">模型名称</label>
              <div className="flex gap-2">
                <input value={modelName} onChange={e => setModelName(e.target.value)}
                  placeholder={provider?.modelHint ? '例如: ' + provider.modelHint : "输入模型名称"}
                  className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-xs outline-none focus:border-sakura-300 font-mono" />
                <button onClick={handleFetchModels} disabled={!(apiKey || "").trim() || loadingModels || selectedProvider === "custom"}
                  title="从 API 获取最新模型列表"
                  className="shrink-0 px-2.5 py-2 rounded-lg text-xs bg-lavender-100 text-lavender-600 hover:bg-lavender-200 disabled:opacity-40 transition-colors">
                  {loadingModels ? "..." : "刷新"}
                </button>
              </div>
              {fetchedModels.length > 0 && (
                <div className="mt-2 p-2 border border-lavender-100 rounded-lg bg-lavender-50/50 max-h-[180px] overflow-y-auto">
                  <div className="text-[10px] text-lavender-400 mb-1">API 返回的可用模型（点击选用）</div>
                  <div className="flex flex-wrap gap-1.5">
                    {fetchedModels.map((m, i) => (
                      <button key={i} onClick={() => setModelName(m.id)}
                        className={`text-[10px] px-2 py-1 rounded-full border transition-colors ${modelName === m.id ? "bg-lavender-100 border-lavender-300 text-lavender-600" : "bg-white border-gray-200 text-gray-600 hover:border-lavender-200"}`}>
                        {m.owned_by === "error" ? "⚠ " : ""}{m.id}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={handleTest} disabled={!(apiKey || "").trim() || testing}
                className="px-4 py-2 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200 disabled:opacity-50 transition-colors">
                {testing ? "测试中..." : "测试连接"}
              </button>
              {testResult && (
                <span className={`text-xs ${testResult.ok ? "text-green-600" : "text-red-500"}`}>
                  {testResult.ok ? "✓ 连接成功" : `✗ ${testResult.error}`}
                </span>
              )}
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-sakura-100">
              <button onClick={handleSave} disabled={!(apiKey || "").trim()}
                className="px-5 py-2 bg-sakura-500 text-white rounded-lg text-xs hover:bg-sakura-600 disabled:opacity-50 transition-colors">
                {saved ? "已保存 ✓" : (standalone ? "保存" : "保存并下一步")}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (step === 1) {
    return (
      <div className="space-y-5">
        <p className="text-sm font-medium text-sakura-600">第二步：连接到消息平台</p>
        <p className="text-xs text-sakura-400">将工作流发布为 API，然后在你需要的平台上配置回调地址</p>

        {/* webhook URL */}
        <div className="bg-sakura-50 border border-sakura-200 rounded-xl px-4 py-3">
          <p className="text-[11px] text-sakura-500 mb-1">你的 webhook 地址（工作流触发入口）</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-white border border-sakura-200 rounded-lg text-xs font-mono text-sakura-700 truncate">
              {webhookUrl}
            </code>
            <button onClick={() => copy(webhookUrl)}
              className="px-3 py-2 bg-sakura-100 text-sakura-600 rounded-lg text-xs hover:bg-sakura-200 shrink-0">
              复制
            </button>
          </div>
        </div>

        <p className="text-xs font-medium text-sakura-500 mt-4 mb-2">支持的平台</p>
        <div className="space-y-2 max-h-[320px] overflow-y-auto">
          {platforms.map((p: any) => (
            <details key={p.id} className="border border-gray-200 rounded-xl overflow-hidden">
              <summary className="px-4 py-3 text-xs font-medium text-gray-700 cursor-pointer hover:bg-gray-50 flex items-center gap-2">
                <span className="text-sakura-500">▸</span>
                <span>{p.name}</span>
                <span className="text-gray-400 ml-1">({p.platform})</span>
              </summary>
              <div className="px-4 py-3 border-t border-gray-100 bg-gray-50/50">
                <p className="text-xs text-gray-500 mb-3">{p.description}</p>
                <ol className="space-y-2">
                  {p.steps.map((s: string, i: number) => (
                    <li key={i} className="text-xs text-gray-600 flex gap-2">
                      <span className="text-sakura-400 font-medium shrink-0">{i + 1}.</span>
                      <span>{s}</span>
                    </li>
                  ))}
                </ol>
                {p.links && p.links.length > 0 && (
                  <div className="mt-3 flex gap-2">
                    {p.links.map((link: any, i: number) => (
                      <a key={i} href={link.url} target="_blank" rel="noopener noreferrer"
                        className="text-xs text-sakura-500 underline hover:text-sakura-600">
                        {link.label} →
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </details>
          ))}
        </div>

        <div className="flex justify-between pt-2 border-t border-sakura-100">
          <button onClick={() => setStep(0)} className="px-4 py-2 text-xs text-gray-500 hover:text-gray-700">上一步</button>
          <button onClick={() => setStep(2)} className="px-5 py-2 bg-sakura-500 text-white rounded-lg text-xs hover:bg-sakura-600 transition-colors">完成设置</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 text-center py-4">
      <div className="w-16 h-16 mx-auto bg-green-100 rounded-full flex items-center justify-center">
        <span className="text-3xl">✓</span>
      </div>
      <p className="text-base font-bold text-sakura-600">设置完成</p>
      <p className="text-xs text-sakura-400">现在你可以开始创建工作流了</p>
      <p className="text-xs text-sakura-400">之后可以在「设置」页面重新配置</p>
      <button onClick={onFinish}
        className="px-8 py-2.5 bg-sakura-500 text-white rounded-lg text-sm hover:bg-sakura-600 transition-colors mt-4">
        开始使用
      </button>
    </div>
  );
}
