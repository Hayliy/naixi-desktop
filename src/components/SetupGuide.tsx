import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";

/* ─── 预设的 API 提供商 ─── */
const API_PROVIDERS = [
  {
    id: "bailian",
    name: "阿里百炼",
    desc: "通义千问系列模型，注册即送 100 万 Token",
    url: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    keyUrl: "https://bailian.console.aliyun.com/#/api-key",
    models: ["qwen-plus", "qwen-turbo", "qwen3-32b"],
  },
  {
    id: "zhipu",
    name: "智谱 AI",
    desc: "GLM 系列模型，免费版有并发限制",
    url: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    keyUrl: "https://open.bigmodel.cn/usercenter/apikeys",
    models: ["glm-4.7-flash", "glm-4-flash"],
  },
  {
    id: "agnes",
    name: "Agnes AI",
    desc: "无限期免费，1M 上下文，30 RPM 限速",
    url: "https://apihub.agnes-ai.com/v1/chat/completions",
    keyUrl: "https://platform.agnes-ai.com/",
    models: ["agnes-2.0-flash"],
  },
  {
    id: "openai",
    name: "OpenAI",
    desc: "GPT 系列模型，需海外支付方式",
    url: "https://api.openai.com/v1/chat/completions",
    keyUrl: "https://platform.openai.com/api-keys",
    models: ["gpt-4o", "gpt-4o-mini", "gpt-4.1"],
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
  const [step, setStep] = useState(0);
  const [selectedProvider, setSelectedProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState("");
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("http://localhost:9845/api/webhook/my-workflow");
  const [platforms, setPlatforms] = useState<any[]>([]);

  useEffect(() => {
    apiGet("/api/desktop/platforms").then((d: any) => {
      if (d?.platforms) setPlatforms(d.platforms);
    }).catch(() => {});
  }, []);

  const provider = API_PROVIDERS.find(p => p.id === selectedProvider);

  const handleTest = async () => {
    if (!apiKey.trim()) return;
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
        [selectedProvider]: { api_key: apiKey, api_url: apiUrl || provider?.url || "" },
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
      setSaved(true);
      setTimeout(() => setStep(1), 600);
    } catch {}
  };

  const handleFinish = () => {
    onClose();
  };

  if (standalone) {
    return (
      <div className="space-y-6">
        {/* 全页面模式下的完整设置 */}
        <SetupSteps
          step={step} setStep={setStep}
          selectedProvider={selectedProvider} setSelectedProvider={setSelectedProvider}
          apiKey={apiKey} setApiKey={setApiKey}
          apiUrl={apiUrl} setApiUrl={setApiUrl}
          saved={saved}
          testing={testing} testResult={testResult}
          handleTest={handleTest} handleSave={handleSave}
          webhookUrl={webhookUrl}
          platforms={platforms}
          provider={provider}
          onFinish={handleFinish}
        />
      </div>
    );
  }

  /* ─── 弹窗模式（首次启动） ─── */
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-[640px] max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
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
            {/* 关闭按钮 */}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition-colors" title="关闭">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        </div>
        <div className="px-6 py-5">
          <SetupSteps
            step={step} setStep={setStep}
            selectedProvider={selectedProvider} setSelectedProvider={setSelectedProvider}
            apiKey={apiKey} setApiKey={setApiKey}
            apiUrl={apiUrl} setApiUrl={setApiUrl}
            saved={saved}
            testing={testing} testResult={testResult}
            handleTest={handleTest} handleSave={handleSave}
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
  apiKey, setApiKey,
  apiUrl, setApiUrl,
  saved,
  testing, testResult,
  handleTest, handleSave,
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
            <button key={p.id} onClick={() => { setSelectedProvider(p.id); setApiUrl(p.url); setTestResult(null); }}
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
            <div className="flex items-center gap-2">
              <button onClick={handleTest} disabled={!apiKey.trim() || testing}
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
              <button onClick={handleSave} disabled={!apiKey.trim()}
                className="px-5 py-2 bg-sakura-500 text-white rounded-lg text-xs hover:bg-sakura-600 disabled:opacity-50 transition-colors">
                {saved ? "已保存 ✓" : "保存并下一步"}
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
