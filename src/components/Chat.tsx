/* ═══════════════════════════════════════════════════════
   聊天主页面 — 只做状态管理和布局编排
   组件拆分：ChatTypes / CapabilityInput / ConvList / MsgBubble / AgentStatus / ChatInput / ModelSelector
   ═══════════════════════════════════════════════════════ */
import { useState, useEffect, useRef } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { sendChatStream } from "@/lib/stream";
import ContentRenderer, { type ContentBlock } from "@/components/ContentRenderer";
import DetailPanel from "@/components/DetailPanel";
import ProviderSettings from "@/components/ProviderSettings";
import PromptPanel from "@/components/PromptPanel";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useAppConfig } from "@/contexts/AppContext";
import CapabilityInput from "@/components/CapabilityInput";
import ConvList from "@/components/ConvList";
import MsgBubble from "@/components/MsgBubble";
import AgentStatus from "@/components/AgentStatus";
import ChatInput from "@/components/ChatInput";
import ModelSelector from "@/components/ModelSelector";
import PermissionDialog from "@/components/PermissionDialog";
import TaskPanel from "@/components/TaskPanel";
import type { ConvItem, MsgItem, ProviderModel } from "@/components/ChatTypes";
import { convName, QUICK_ACTIONS } from "@/components/ChatTypes";
import {
  Bot, Trash2, Check, X, ChevronLeft, Sparkles, Settings, FileText, Cpu, MessageCircle,
  CheckCircle2,
} from "lucide-react";

const MODELS: ProviderModel[] = [{ key: "auto", label: "自动路由（默认）", provider_id: 0 }];

function isImageRequest(text: string) {
  const kw = ["画一张", "画个", "画一下", "帮我画", "生成图片", "生成图", "画图", "image", "图片"];
  return kw.some(k => text.includes(k));
}

/* ═══════════════════════════════════════════
   主页面组件
   ═══════════════════════════════════════════ */
export default function ChatPage() {
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<MsgItem[]>([]);
  const [search, setSearch] = useState("");
  const [convLoading, setConvLoading] = useState(true);
  const [msgLoading, setMsgLoading] = useState(false);
  const [modelKey, setModelKey] = useState(() => {
    try { return localStorage.getItem("naixi_model_key") || MODELS[0].key; } catch { return MODELS[0].key; }
  });
  const [agentActive, setAgentActive] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [showTask, setShowTask] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [scene, setScene] = useState("owner");
  const [customScenes, setCustomScenes] = useState<{ file: string; desc: string }[]>([]);
  const [isNewChat, setIsNewChat] = useState(false);
  const [realTokens, setRealTokens] = useState<{ input?: number; output?: number } | null>(null);
  const [customNames, setCustomNames] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem("naixi_custom_names") || "{}"); } catch { return {}; }
  });
  const [renaming, setRenaming] = useState(false);
  const [renameText, setRenameText] = useState("");
  const [availableModels, setAvailableModels] = useState<ProviderModel[]>(MODELS);
  const [agentMode, setAgentMode] = useState(false);
  const [capabilityAction, setCapabilityAction] = useState<typeof QUICK_ACTIONS[number] | null>(null);
  const [permissionReq, setPermissionReq] = useState<{ id: string; name: string; args: Record<string, unknown> } | null>(null);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [streaming, setStreaming] = useState(false);

  const stopStreaming = async () => {
    // 先取消后端 Agent 循环
    try {
      const k = activeKey || "";
      if (k) await apiPost("/api/chat/cancel", { key: k });
      else await apiPost("/api/chat/cancel", { key: "all" });
    } catch {}
    // 再中断前端 SSE 流
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setAgentActive(false); setStreaming(false);
  };

  // ── 初始化加载 ──
  useEffect(() => {
    setConvLoading(true);
    apiGet<{ conversations: ConvItem[]; total: number }>("/api/conversations")
      .then(d => { setConvs(d.conversations); setConvLoading(false); })
      .catch(() => setConvLoading(false));
  }, []);

  // 从全局配置加载可用模型
  const { config, loaded } = useAppConfig();
  useEffect(() => {
    if (!loaded) return;
    const models: ProviderModel[] = [];
    let idx = 0;
    for (const [, pcfg] of Object.entries(config.api_providers)) {
      idx++;
      if (pcfg.model) models.push({ key: pcfg.model, label: pcfg.model, provider_id: idx });
    }
    if (models.length > 0) {
      setAvailableModels([{ key: "auto", label: "自动路由（默认）", provider_id: 0 }, ...models]);
      const savedKey = localStorage.getItem("naixi_model_key");
      if (savedKey && models.find(m => m.key === savedKey)) { /* keep */ }
      else if (models[0]) { setModelKey(models[0].key); localStorage.setItem("naixi_model_key", models[0].key); }
    }
  }, [config, loaded]);

  // 加载自定义场景
  useEffect(() => {
    apiGet<{ prompts: { scene: string; file: string; desc: string }[] }>("/api/prompts")
      .then(d => { const p = ["owner", "group", "stranger"]; setCustomScenes((d.prompts || []).filter(x => !p.includes(x.scene)).map(x => ({ file: x.file, desc: x.desc }))); })
      .catch(() => {});
  }, []);

  useEffect(() => { localStorage.setItem("naixi_custom_names", JSON.stringify(customNames)); }, [customNames]);

  useEffect(() => {
    if (!activeKey) return;
    setMsgLoading(true);
    apiGet<{ key: string; messages: MsgItem[]; total: number }>(`/api/conversation/${encodeURIComponent(activeKey)}`)
      .then(d => { setMsgs(d.messages); setMsgLoading(false); })
      .catch(() => setMsgLoading(false));
  }, [activeKey]);

  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  // ── 消息处理 ──
  const handleNormalChat = async (text: string) => {
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    setAgentActive(true); setStreaming(true); setIsNewChat(false);

    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "", content_blocks: [{ type: "status", state: "loading", text: "思考中..." }], time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, aiMsg]);

    const selectedModel = availableModels.find(m => m.key === modelKey);
    const controller = new AbortController();
    abortRef.current = controller;

    await sendChatStream(agentMode ? "/api/agent/stream" : "/api/chat/stream", {
      text, key: activeKey || `chat:${Date.now().toString(36)}`, model: modelKey,
      provider_id: selectedModel?.provider_id || 0, scene,
    }, {
      onUpdate: (blocks, generating, usage) => {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content_blocks: blocks, content: blocks.find(b => b.type === "text")?.text || "" }));
        if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
      },
      onDone: (usage) => {
        setAgentActive(false); setStreaming(false); abortRef.current = null;
        if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
        // 清理无内容的消息
        setMsgs(prev => prev.filter(m => m.content || (m.content_blocks || []).length > 0));
        apiGet<{ conversations: ConvItem[] }>("/api/conversations").then(d => setConvs(d.conversations)).catch(() => {});
      },
      onError: (err) => {
        if (err.includes("abort") || err.includes("AbortError")) {
          setAgentActive(false); setStreaming(false); abortRef.current = null;
          setMsgs(prev => prev.filter(m => m.id !== aiId));
          return;
        }
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `出错了: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] }));
        setAgentActive(false); setStreaming(false); abortRef.current = null;
      },
      onPermissionRequest: (reqId, name, args) => {
        setPermissionReq({ id: reqId, name, args });
      },
    });
  };

  const handleSend = async (text: string) => {
    const t = text.trim();
    if (t.startsWith("生成一段视频：")) {
      await handleNormalChat(t.replace("生成一段视频：", "请生成视频："));
    } else if (t.startsWith("用语音说：")) {
      await handleNormalChat(t.replace("用语音说：", "请用语音说："));
    } else if (t.startsWith("写一段代码：")) {
      await handleNormalChat(t);
    } else if (t.startsWith("搜索一下：")) {
      await handleNormalChat(t);
    } else if (isImageRequest(t)) {
      await handleNormalChat(t);
    } else {
      await handleNormalChat(t);
    }
  };

  const handleDelete = async (key: string) => {
    try { await apiPost("/api/conversation/delete", { key }); setConvs(prev => prev.filter(c => c.key !== key)); if (activeKey === key) { setActiveKey(null); setMsgs([]); } } catch {}
  };

  const handleNew = () => { stopStreaming(); setActiveKey(null); setMsgs([]); setIsNewChat(true); };
  const handleConvSelect = (key: string | null) => { stopStreaming(); setActiveKey(key); };

  return (
    <div className="flex h-full bg-sakura-50 rounded-xl overflow-hidden border border-sakura-100">
      <ConvList convs={convs} activeKey={activeKey} onSelect={handleConvSelect} onNew={handleNew}
        search={search} onSearchChange={setSearch} loading={convLoading} customNames={customNames} />

      <div className="flex-1 flex flex-col bg-white min-w-0">
        {!activeKey && msgs.length === 0 && !isNewChat ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-sakura-300">
            <MessageCircle size={36} className="text-sakura-200" />
            <p className="text-xs">选择一个对话或点「新对话」开始</p>
          </div>
        ) : (
          <>
            {/* 对话头部 */}
            <div className="flex flex-col gap-2 px-4 py-2 border-b border-sakura-100 bg-white shrink-0">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <button className="lg:hidden p-1 hover:bg-sakura-50 rounded shrink-0" onClick={() => setActiveKey(null)}>
                    <ChevronLeft size={14} className="text-sakura-400" />
                  </button>
                  {renaming && activeKey ? (
                    <div className="flex items-center gap-1">
                      <input className="w-36 px-2 py-0.5 rounded border border-sakura-100 text-xs text-sakura-600"
                        value={renameText} onChange={e => setRenameText(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") { setCustomNames(p => ({ ...p, [activeKey]: renameText })); setRenaming(false); } }} autoFocus />
                      <button onClick={() => { setCustomNames(p => ({ ...p, [activeKey]: renameText })); setRenaming(false); }} className="p-0.5 text-green-500"><Check size={12} /></button>
                      <button onClick={() => setRenaming(false)} className="p-0.5 text-sakura-300"><X size={12} /></button>
                    </div>
                  ) : (
                    <button onClick={() => { if (activeKey) { setRenameText(customNames[activeKey] || convName(activeKey, msgs)); setRenaming(true); } }}
                      className="text-xs font-semibold text-sakura-600 hover:text-sakura-800 transition-colors truncate">
                      {activeKey ? convName(activeKey, msgs, customNames[activeKey]) : "新对话"}
                    </button>
                  )}
                  {activeKey && <span className="text-[10px] text-sakura-300 truncate">{activeKey}</span>}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <div className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-sakura-50 text-sakura-400" title={realTokens ? `输入 ${realTokens.input} · 输出 ${realTokens.output}` : "未获取到用量数据"}>
                    <Sparkles size={10} />
                    <span>{realTokens ? `${(realTokens.input! + realTokens.output!) > 1000 ? `${((realTokens.input! + realTokens.output!) / 1000).toFixed(1)}k` : realTokens.input! + realTokens.output!} tokens` : "-"}</span>
                  </div>
                  <button onClick={() => setShowSettings(!showSettings)} title="模型设置" className={`p-1.5 rounded transition-colors ${showSettings ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Settings size={12} /></button>
                  <button onClick={() => setShowPrompt(!showPrompt)} title="提示词" className={`p-1.5 rounded transition-colors ${showPrompt ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><FileText size={12} /></button>
                  {activeKey && <button onClick={() => setShowDetail(!showDetail)} className={`p-1.5 rounded transition-colors ${showDetail ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Sparkles size={12} /></button>}
                  <button onClick={() => setShowTask(!showTask)} className={`p-1.5 rounded transition-colors ${showTask ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`} title="任务进度"><CheckCircle2 size={12} /></button>
                  {activeKey && <button onClick={() => handleDelete(activeKey)} className="p-1.5 hover:bg-red-50 rounded text-sakura-300 hover:text-red-500 transition-colors"><Trash2 size={12} /></button>}
                </div>
              </div>

              {/* 第二行：模型 + 场景 + Agent */}
              <div className="flex items-center gap-2 flex-wrap">
                <ModelSelector availableModels={availableModels} modelKey={modelKey} onModelChange={(key) => { setModelKey(key); try { localStorage.setItem("naixi_model_key", key); } catch {} }} />
                <div className="flex items-center gap-0.5 flex-wrap">
                  {[{ key: "owner", label: "日常助手", icon: Bot }, { key: "group", label: "创作模式", icon: FileText }, { key: "stranger", label: "快捷问答", icon: FileText }].map(({ key, label, icon: SIcon }) => (
                    <button key={key} onClick={() => setScene(key)}
                      className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors ${scene === key ? "bg-gradient-to-r from-sakura-100 to-sakura-200 text-sakura-600 font-medium" : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                      <SIcon size={9} /><span className="max-w-[4rem] truncate">{label}</span>
                      {scene === key && <span className="w-1.5 h-1.5 rounded-full bg-sakura-500" />}
                    </button>
                  ))}
                  {customScenes.map(s => (
                    <button key={s.file} onClick={() => setScene(s.file)}
                      className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors ${scene === s.file ? "bg-gradient-to-r from-sakura-100 to-sakura-200 text-sakura-600 font-medium" : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                      <FileText size={9} /><span className="max-w-[4rem] truncate">{s.desc}</span>
                      {scene === s.file && <span className="w-1.5 h-1.5 rounded-full bg-sakura-500" />}
                    </button>
                  ))}
                </div>
                <button onClick={() => setAgentMode(!agentMode)}
                  className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors ${agentMode ? "bg-gradient-to-r from-teal-100 to-green-100 text-teal-600 font-medium" : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                  <Cpu size={9} /><span>Agent</span>
                  {agentMode && <span className="w-1.5 h-1.5 rounded-full bg-teal-500" />}
                </button>
              </div>
            </div>

            <AgentStatus active={agentActive} />

            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {msgLoading ? (
                <div className="flex items-center justify-center py-12"><Bot size={18} className="text-sakura-300 animate-bounce" /></div>
              ) : msgs.length === 0 ? (
                <div className="flex flex-col items-center py-12 text-sakura-300 text-xs gap-1">
                  <MessageCircle size={20} className="text-sakura-200" />
                  <span>开始你的第一条消息</span>
                </div>
              ) : msgs.map((m) => (<MsgBubble key={m.id} msg={m}
                onEdit={(id, text) => setMsgs(prev => prev.map(msg => msg.id === id ? { ...msg, content: text } : msg))}
                onRegenerate={(id) => { const idx = msgs.findIndex(x => x.id === id); if (idx > 0 && msgs[idx - 1]?.role === "user") handleSend(msgs[idx - 1].content); }}
              />))}
              <div ref={msgEndRef} />
            </div>

            <ChatInput onSend={handleSend} streaming={streaming} onStop={stopStreaming}
              onCapabilityClick={(a) => setCapabilityAction(a)} />
          </>
        )}
      </div>

      {showDetail && activeKey && <DetailPanel activeKey={activeKey} messageCount={msgs.length} tokenEstimate={realTokens ? (realTokens.input! + realTokens.output!) : 0} modelKey={modelKey} onClose={() => setShowDetail(false)} />}

      {showPrompt && (
        <div className="w-60 min-w-[15rem] border-l border-sakura-100 bg-white flex flex-col">
          <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
            <span className="text-xs font-semibold text-sakura-500">提示词</span>
            <button onClick={() => setShowPrompt(false)} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
          </div>
          <div className="flex-1 overflow-y-auto"><ErrorBoundary name="提示词面板"><PromptPanel activeScene={scene} onSceneChange={setScene} /></ErrorBoundary></div>
        </div>
      )}

      {capabilityAction && <CapabilityInput action={capabilityAction} config={config}
        onSend={(text) => { setCapabilityAction(null); handleSend(text); }}
        onClose={() => setCapabilityAction(null)} />}

      {permissionReq && <PermissionDialog
        reqId={permissionReq.id} name={permissionReq.name} args={permissionReq.args}
        onClose={() => setPermissionReq(null)} />}

      {showTask && <TaskPanel onClose={() => setShowTask(false)} />}

      {showSettings && (
        <div className="w-72 min-w-[18rem] border-l border-sakura-100 bg-white overflow-y-auto">
          <div className="sticky top-0 bg-white border-b border-sakura-100 px-3 py-2 flex items-center justify-between z-10">
            <span className="text-xs font-semibold text-sakura-500">模型供应商</span>
            <button onClick={() => setShowSettings(false)} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
          </div>
          <div className="p-3"><ErrorBoundary name="供应商设置"><ProviderSettings /></ErrorBoundary></div>
        </div>
      )}
    </div>
  );
}
