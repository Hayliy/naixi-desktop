/* ═══════════════════════════════════════════════════════
   聊天主页面 — 只做状态管理和布局编排
   组件拆分：ChatTypes / CapabilityInput / ConvList / MsgBubble / AgentStatus / ChatInput / ModelSelector
   ═══════════════════════════════════════════════════════ */
import { useState, useEffect, useRef } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { applyTheme, getTheme } from "@/lib/theme";
import { useToast } from "@/components/Toast";
import { sendChatStream } from "@/lib/stream";
import ContentRenderer, { type ContentBlock } from "@/components/ContentRenderer";
import DetailPanel from "@/components/DetailPanel";
import ProviderSettings from "@/components/ProviderSettings";
import AutomationPanel from "@/components/AutomationPanel";
import ConnectionPanel from "@/components/ConnectionPanel";
import PreferencesPanel from "@/components/PreferencesPanel";
import ResourcePanel from "@/components/ResourcePanel";
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
import TeamPanel from "@/components/TeamPanel";
import type { TeamMember } from "@/components/TeamPanel";
import KnowledgePanel from "@/components/KnowledgePanel";
import type { ConvItem, MsgItem, ProviderModel } from "@/components/ChatTypes";
import { convName, QUICK_ACTIONS } from "@/components/ChatTypes";
import {
  Bot, Trash2, Check, X, ChevronLeft, Sparkles, Settings, FileText, Cpu, MessageCircle,
  CheckCircle2, Shield, Volume2, Library, User, Palette, Search, Download, Star, Reply, Users, BookOpen, Zap, Clock,
} from "lucide-react";
import { loadAvatarCache } from "@/lib/avatar";

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
  type SideTab = "settings" | "resource" | "prompt" | "detail" | "task" | "knowledge" | "team" | "preferences" | "connection" | "automation" | null;
  const [sideTab, setSideTab] = useState<SideTab>(null);

  // 初始化头像缓存
  useEffect(() => { loadAvatarCache(); }, []);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [teamName, setTeamName] = useState("");
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
  const [fullTrust, setFullTrust] = useState(false);
  const [currentExpert, setCurrentExpert] = useState<{ name: string; prompt: string } | null>(() => {
    try { const r = localStorage.getItem("naixi_expert"); return r ? JSON.parse(r) : null; } catch { return null; }
  });
  const [msgSearch, setMsgSearch] = useState("");
  const [showStarredOnly, setShowStarredOnly] = useState(false);
  const [starredMsgs, setStarredMsgs] = useState<number[]>([]);
  const [replyToId, setReplyToId] = useState<number | null>(null);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const shortcutsRef = useRef<{ key: string; desc: string }[]>([]);
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
    // 初始化主题
    const { theme: t, hue: h } = getTheme();
    applyTheme(t, h);
    // 加载会话列表
    setConvLoading(true);
    apiGet<{ conversations: ConvItem[]; total: number }>("/api/conversations")
      .then(d => { setConvs(d.conversations); setConvLoading(false); })
      .catch(() => setConvLoading(false));
  }, []);

  // 定时刷新会话列表（自动更新自动化产生的对话）
  useEffect(() => {
    const t = setInterval(() => {
      apiGet<{ conversations: ConvItem[] }>("/api/conversations")
        .then(d => setConvs(d.conversations))
        .catch(() => {});
    }, 30000);
    return () => clearInterval(t);
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
      else { setModelKey("auto"); localStorage.setItem("naixi_model_key", "auto"); }
    } else {
      // 无可用供应商时，强制回到「自动路由」，避免残留旧模型名（如 qwen3.5-flash）被显示
      setAvailableModels(MODELS);
      if (localStorage.getItem("naixi_model_key") !== "auto") {
        setModelKey("auto");
        localStorage.setItem("naixi_model_key", "auto");
      }
    }
  }, [config, loaded]);

  // 加载自定义场景
  useEffect(() => {
    apiGet<{ prompts: { scene: string; file: string; desc: string }[] }>("/api/prompts")
      .then(d => { const p = ["owner", "group", "stranger"]; setCustomScenes((d.prompts || []).filter(x => !p.includes(x.scene)).map(x => ({ file: x.file, desc: x.desc }))); })
      .catch(() => {});
    apiGet<{ full_trust: boolean }>("/api/config/trust")
      .then(d => setFullTrust(d.full_trust))
      .catch(() => {});
  }, []);

  useEffect(() => { localStorage.setItem("naixi_custom_names", JSON.stringify(customNames)); }, [customNames]);

  // 加载收藏消息
  useEffect(() => {
    if (activeKey) {
      try { setStarredMsgs(JSON.parse(localStorage.getItem(`naixi_starred_${activeKey}`) || "[]")); } catch { setStarredMsgs([]); }
    }
  }, [activeKey]);

  // 快捷键处理：Ctrl+, 开设置 + 自定义快捷键
  useEffect(() => {
    const raw = localStorage.getItem("naixi_shortcuts");
    try { shortcutsRef.current = JSON.parse(raw ?? "[]") || []; } catch { shortcutsRef.current = []; }

    const handler = (e: KeyboardEvent) => {
      // Ctrl+, 开/关设置面板
      if (e.key === "," && e.ctrlKey && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        setSideTab(t => t === "settings" ? null : "settings");
        return;
      }
      // 自定义快捷键：不在输入框内时才匹配
      if ((e.target as HTMLElement)?.closest("input,textarea,[contenteditable]")) return;
      // 跳过 Tab（浏览器原生焦点跳转，不参与快捷键匹配）
      if (e.key === "Tab") return;
      for (const s of shortcutsRef.current) {
        const parts = s.key.toLowerCase().split("+");
        const key = parts.pop() || "";
        if (e.key.toLowerCase() !== key) continue;
        if (parts.includes("ctrl") !== e.ctrlKey) continue;
        if (parts.includes("shift") !== e.shiftKey) continue;
        if (parts.includes("alt") !== e.altKey) continue;
        if (s.desc === "清空对话") {
          e.preventDefault();
          handleNew();
          return;
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (!activeKey) return;
    setMsgLoading(true);
    apiGet<{ key: string; messages: MsgItem[]; total: number }>(`/api/conversation/${encodeURIComponent(activeKey)}`)
      .then(d => { setMsgs(d.messages); setMsgLoading(false); })
      .catch(() => setMsgLoading(false));
  }, [activeKey]);

  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  // auto 对话实时轮询新消息
  useEffect(() => {
    if (!activeKey || !activeKey.startsWith("auto:")) return;
    const t = setInterval(async () => {
      try {
        const res = await apiGet<{ messages: MsgItem[]; total: number }>(
          `/api/conversation/${encodeURIComponent(activeKey)}?limit=50`
        );
        if (res) {
          setMsgs(prev => {
            if (prev.length === res.messages.length) return prev; // 没新消息，不触发重渲染
            return res.messages;
          });
        }
      } catch {}
    }, 1000);
    return () => clearInterval(t);
  }, [activeKey]);

  // ── 消息处理 ──
  const handleNormalChat = async (text: string) => {
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    setAgentActive(true); setStreaming(true); setIsNewChat(false);

    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "", content_blocks: [{ type: "status", state: "loading", text: "思考中..." }], time: Math.floor(Date.now() / 1000), expert_name: currentExpert?.name || undefined } as any;
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

  const handleTeamChat = async (text: string) => {
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    setAgentActive(true); setStreaming(true); setIsNewChat(false);

    const convKey = activeKey || `chat:${Date.now().toString(36)}`;
    const selectedModel = availableModels.find(m => m.key === modelKey);

    let accumulated = `用户需求: ${text}`;

    for (let i = 0; i < team.length; i++) {
      const member = team[i];
      const aiId = Date.now() + i + 1;
      const fullPrompt = `【角色: ${member.name}】\n${member.prompt}\n\n${accumulated}\n\n请以${member.name}的身份完成你的任务。`;

      const aiMsg: MsgItem = {
        id: aiId, role: "assistant",
        content: "",
        content_blocks: [{ type: "status", state: "loading", text: `${member.name} 正在工作...` }],
        time: Math.floor(Date.now() / 1000),
        expert_name: member.name,
      } as any;
      setMsgs(prev => [...prev, aiMsg]);
      // 在下一 tick 获取最新 msgs
      await new Promise(r => setTimeout(r, 50));

      const controller = new AbortController();
      abortRef.current = controller;

      let output = "";
      await sendChatStream("/api/chat/stream", {
        text: fullPrompt, key: convKey, model: modelKey,
        provider_id: selectedModel?.provider_id || 0, scene,
      }, {
        onUpdate: (blocks) => {
          output = blocks.find(b => b.type === "text")?.text || "";
          setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content_blocks: blocks, content: output }));
        },
        onDone: (usage) => {
          if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
        },
        onError: (err) => {
          if (err.includes("abort") || err.includes("AbortError")) return;
          output = `出错了: ${err}`;
          setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: output, content_blocks: [{ type: "status", state: "error", text: err }] }));
        },
      });

      accumulated += `\n\n【${member.name} 的输出】\n${output || "(无输出)"}`;
    }

    setAgentActive(false); setStreaming(false); abortRef.current = null;
    try {
      const res = await apiGet<{ conversations: ConvItem[] }>("/api/conversations");
      setConvs(res.conversations);
    } catch {}
  };

  const handleExport = () => {
    if (msgs.length === 0) return;
    const lines = msgs.map((m: MsgItem) => `[${m.role === "user" ? "我" : "AI"} ${new Date(m.time).toLocaleString()}]\n${m.content}`);
    const text = lines.join("\n\n---\n\n");
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `对话_${activeKey || "export"}.txt`;
    a.click(); URL.revokeObjectURL(url);
  };

  const handleSend = async (text: string) => {
    const t = text.trim();

    // 团队模式：逐轮调用
    if (team.length > 0) {
      await handleTeamChat(t);
      return;
    }

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
        search={search} onSearchChange={setSearch} loading={convLoading} customNames={customNames}
        onDeleteConv={handleDelete} />

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
                  <button onClick={() => setSideTab(t => t === "settings" ? null : "settings")} title="模型设置" className={`p-1.5 rounded transition-colors ${sideTab === "settings" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Settings size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "connection" ? null : "connection")} title="外部连接" className={`p-1.5 rounded transition-colors ${sideTab === "connection" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Zap size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "preferences" ? null : "preferences")} title="外观与偏好" className={`p-1.5 rounded transition-colors ${sideTab === "preferences" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Palette size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "automation" ? null : "automation")} title="自动化" className={`p-1.5 rounded transition-colors ${sideTab === "automation" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Clock size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "prompt" ? null : "prompt")} title="提示词" className={`p-1.5 rounded transition-colors ${sideTab === "prompt" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><FileText size={12} /></button>
                  {activeKey && <button onClick={() => setSideTab(t => t === "detail" ? null : "detail")} title="会话详情" className={`p-1.5 rounded transition-colors ${sideTab === "detail" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Sparkles size={12} /></button>}
                  <button onClick={() => setSideTab(t => t === "task" ? null : "task")} className={`p-1.5 rounded transition-colors ${sideTab === "task" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`} title="任务进度"><CheckCircle2 size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "team" ? null : "team")} title="专家" className={`p-1.5 rounded transition-colors ${sideTab === "team" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><Users size={12} /></button>
                  <button onClick={() => setSideTab(t => t === "knowledge" ? null : "knowledge")} title="知识库" className={`p-1.5 rounded transition-colors ${sideTab === "knowledge" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}><BookOpen size={12} /></button>
                  <button onClick={async () => {
                    const next = !fullTrust;
                    try { await apiPost("/api/config/trust", { full_trust: next }); setFullTrust(next); } catch {}
                  }} title={fullTrust ? "完全信任模式（点击关闭）" : "完全信任模式（高危工具自动允许）"}
                    className={`p-1.5 rounded transition-colors ${fullTrust ? "text-red-500 bg-red-50" : "text-sakura-300 hover:text-red-400 hover:bg-red-50"}`}>
                    <Shield size={12} />
                  </button>
                  <TtsToggle />
                  <ThemeToggle />
                  <button onClick={() => setSideTab(t => t === "resource" ? null : "resource")} title="资源库"
                    className={`p-1.5 rounded transition-colors ${sideTab === "resource" ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                    <Library size={12} />
                  </button>
                  {activeKey && <button onClick={() => handleDelete(activeKey)} title="删除会话" className="p-1.5 hover:bg-red-50 rounded text-sakura-300 hover:text-red-500 transition-colors"><Trash2 size={12} /></button>}
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
                {currentExpert && (
                  <button onClick={() => { setCurrentExpert(null); localStorage.removeItem("naixi_expert"); }}
                    className="flex items-center gap-1 px-1.5 py-1 rounded text-[10px] bg-gradient-to-r from-purple-100 to-pink-100 text-purple-600 font-medium">
                    <User size={9} /><span className="max-w-[80px] truncate">{currentExpert.name}</span>
                    <X size={9} className="ml-0.5" />
                  </button>
                )}
                {team.length > 0 && (
                  <button onClick={() => { setTeam([]); setTeamName(""); }}
                    className="flex items-center gap-1 px-1.5 py-1 rounded text-[10px] bg-gradient-to-r from-amber-100 to-orange-100 text-amber-600 font-medium">
                    <Users size={9} /><span className="max-w-[100px] truncate">{teamName || `团队 (${team.length}人)`}</span>
                    <X size={9} className="ml-0.5" />
                  </button>
                )}
                {fullTrust && <span className="text-[10px] text-red-400 flex items-center gap-0.5"><Shield size={9} />完全信任</span>}
              </div>
            </div>

            <AgentStatus active={agentActive} />

            {/* 消息搜索 + 导出 + 收藏筛选 */}
            {msgs.length > 0 && (
              <div className="flex items-center gap-1.5 px-4 pt-2">
                <div className="flex-1 flex items-center gap-1 px-2 py-1 rounded-lg bg-sakura-50 border border-sakura-100">
                  <Search size={10} className="text-sakura-300 shrink-0" />
                  <input value={msgSearch} onChange={e => setMsgSearch(e.target.value)}
                    className="flex-1 bg-transparent text-[10px] text-sakura-600 outline-none placeholder:text-sakura-300"
                    placeholder="搜索消息..." />
                </div>
                <button onClick={() => setShowStarredOnly(!showStarredOnly)} title={showStarredOnly ? "显示全部" : "仅显示收藏"}
                  className={`p-1 rounded transition-colors ${showStarredOnly ? "text-amber-500 bg-amber-50" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                  <Star size={11} />
                </button>
                <button onClick={handleExport} title="导出对话"
                  className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50 transition-colors">
                  <Download size={11} />
                </button>
              </div>
            )}

            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {msgLoading ? (
                <div className="flex items-center justify-center py-12"><Bot size={18} className="text-sakura-300 animate-bounce" /></div>
              ) : msgs.length === 0 ? (
                <div className="flex flex-col items-center py-12 text-sakura-300 text-xs gap-1">
                  <MessageCircle size={20} className="text-sakura-200" />
                  <span>开始你的第一条消息</span>
                </div>
              ) : msgs.filter(m => {
                if (msgSearch && !m.content.toLowerCase().includes(msgSearch.toLowerCase())) return false;
                if (showStarredOnly && !starredMsgs.includes(m.id)) return false;
                return true;
              }).map((m) => (<MsgBubble key={m.id} msg={m}
                expertName={(m as any).expert_name || undefined}
                onEdit={(id, text) => setMsgs(prev => prev.map(msg => msg.id === id ? { ...msg, content: text } : msg))}
                onRegenerate={(id) => { const idx = msgs.findIndex(x => x.id === id); if (idx > 0 && msgs[idx - 1]?.role === "user") handleSend(msgs[idx - 1].content); }}
                onDelete={async (id) => {
                  if (!activeKey) return;
                  setMsgs(prev => prev.filter(m => m.id !== id));
                  try { await apiPost("/api/conversation/message/delete", { key: activeKey, msg_id: id }); } catch {}
                }}
                onStar={(id) => {
                  const cur = starredMsgs;
                  const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id];
                  setStarredMsgs(next);
                  localStorage.setItem(`naixi_starred_${activeKey}`, JSON.stringify(next));
                }}
                starred={starredMsgs.includes(m.id)}
                onReply={(id) => setReplyToId(id)}
              />))}
              <div ref={msgEndRef} />
            </div>

          {/* 回复引用栏 */}
          {replyToId && (
            <div className="flex items-center gap-2 px-4 py-1.5 bg-amber-50 border-t border-amber-100 text-[10px] text-amber-600">
              <Reply size={10} />
              <span className="flex-1 truncate">回复: {msgs.find(m => m.id === replyToId)?.content.slice(0, 80)}</span>
              <button onClick={() => setReplyToId(null)} className="p-0.5 hover:bg-amber-100 rounded"><X size={10} /></button>
            </div>
          )}

            <ChatInput onSend={(text) => {
              if (replyToId) text = `> ${msgs.find(m => m.id === replyToId)?.content.slice(0, 80) || ""}\n\n${text}`;
              setReplyToId(null);
              handleSend(text);
            }} streaming={streaming} onStop={stopStreaming}
              onCapabilityClick={(a) => setCapabilityAction(a)} />
          </>
        )}
      </div>

      {/* ─── 统一侧边栏（VSCode 风格：左侧内容 + 右侧图标条） ─── */}
      {sideTab && (
        <div className="flex border-l border-sakura-100 bg-white">
          {/* 内容区 */}
          <div className="w-80 min-w-[20rem] flex flex-col">
            {sideTab === "detail" && activeKey && <DetailPanel activeKey={activeKey} messageCount={msgs.length} tokenEstimate={realTokens ? (realTokens.input! + realTokens.output!) : 0} modelKey={modelKey} onClose={() => setSideTab(null)} />}
            {sideTab === "resource" && (
              <ResourcePanel onClose={() => setSideTab(null)} onApply={(text, label, type) => {
                if (type === "experts") {
                  setCurrentExpert({ name: label, prompt: text });
                  localStorage.setItem("naixi_expert", JSON.stringify({ name: label, prompt: text }));
                  handleSend(label + " 请以该身份回复");
                } else if (type === "skills") {
                  handleSend("执行 Skill「" + label + "」: " + text);
                } else {
                  handleSend("请根据以下提示词回复: " + text);
                }
                setSideTab(null);
              }} />
            )}
            {sideTab === "prompt" && (
              <div className="flex-1 overflow-y-auto"><ErrorBoundary name="提示词面板"><PromptPanel activeScene={scene} onSceneChange={setScene} onClose={() => setSideTab(null)} /></ErrorBoundary></div>
            )}
            {sideTab === "task" && <TaskPanel onClose={() => setSideTab(null)} />}
            {sideTab === "knowledge" && <KnowledgePanel onClose={() => setSideTab(null)} />}
            {sideTab === "team" && (
              <TeamPanel onClose={() => setSideTab(null)} onApplyTeam={(members, name) => {
                setTeam(members);
                setTeamName(name);
                setSideTab(null);
              }} />
            )}
            {sideTab === "connection" && <ConnectionPanel onClose={() => setSideTab(null)} />}
            {sideTab === "automation" && <AutomationPanel onClose={() => setSideTab(null)} onNavigate={async (key: string, msgs?: any[]) => { 
              await apiGet<{ conversations: ConvItem[] }>("/api/conversations").then(d => setConvs(d.conversations)).catch(() => {}); 
              if (msgs) setMsgs(msgs);
              setActiveKey(key); setSideTab(null); 
            }} />}
            {sideTab === "preferences" && <PreferencesPanel onClose={() => setSideTab(null)} />}
            {sideTab === "settings" && (
              <div className="flex-1 overflow-y-auto"><ErrorBoundary name="供应商设置"><ProviderSettings onClose={() => setSideTab(null)} /></ErrorBoundary></div>
            )}
          </div>
          {/* 右侧图标条 */}
          <div className="w-9 flex flex-col items-center pt-2 gap-1 border-l border-sakura-100 bg-sakura-50 shrink-0">
            {([
              ["settings", "模型供应商", Settings],
              ["connection", "外部连接", Zap],
              ["automation", "自动化", Clock],
              ["preferences", "外观与偏好", Palette],
              ["resource", "资源库", Library],
              ["prompt", "提示词", FileText],
              ["detail", "会话详情", Sparkles],
              ["task", "任务进度", CheckCircle2],
              ["knowledge", "知识库", BookOpen],
              ["team", "专家", Users],
            ] as [SideTab, string, any][]).filter(([k]) => k !== "detail" || activeKey).map(([k, label, Icon]) => (
              <button key={k} onClick={() => setSideTab(t => t === k ? null : k)}
                title={label}
                className={`w-7 h-7 flex items-center justify-center rounded-lg transition-colors ${
                  sideTab === k ? "bg-sakura-200 text-sakura-600" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-100"
                }`}>
                <Icon size={14} />
              </button>
            ))}
            <div className="flex-1" />
            <button onClick={() => setSideTab(null)} title="关闭侧边栏" className="w-7 h-7 flex items-center justify-center rounded-lg text-sakura-300 hover:text-red-400 mb-2 hover:bg-red-50">
              <X size={12} />
            </button>
          </div>
        </div>
      )}

      {capabilityAction && <CapabilityInput action={capabilityAction} config={config}
        onSend={(text) => { setCapabilityAction(null); handleSend(text); }}
        onClose={() => setCapabilityAction(null)} />}

      {permissionReq && <PermissionDialog
        reqId={permissionReq.id} name={permissionReq.name} args={permissionReq.args}
        onClose={() => setPermissionReq(null)} />}

    </div>
  );
}

/* ─── TTS 模式切换按钮 ─── */
function TtsToggle() {
  const [mode, setMode] = useState<"browser" | "api">("browser");
  const { notify } = useToast();

  useEffect(() => {
    apiGet<{ mode: string }>("/api/config/tts")
      .then(d => setMode(d.mode as "browser" | "api"))
      .catch(() => {});
  }, []);

  const toggle = async () => {
    const next = mode === "browser" ? "api" : "browser";
    try {
      await apiPost("/api/config/tts", { mode: next });
      setMode(next);
      notify(next === "api" ? "已切换为 AI 语音朗读（需配置语音供应商）" : "已切换为浏览器合成朗读", "info");
    } catch {}
  };

  return (
    <button onClick={toggle}
      title={mode === "api" ? "AI 语音朗读（点击切换为浏览器合成）" : "浏览器合成朗读（点击切换为 AI 语音）"}
      className={`p-1.5 rounded transition-colors ${mode === "api" ? "text-purple-500 bg-purple-50" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
      <Volume2 size={12} />
    </button>
  );
}

/* ─── 主题切换按钮 ─── */
function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    (localStorage.getItem("naixi_theme") as "light" | "dark") || "light"
  );

  const toggle = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    applyTheme(next, getTheme().hue);
  };

  return (
    <button onClick={toggle}
      title={theme === "dark" ? "切换为浅色模式" : "切换为暗色模式"}
      className={`p-1.5 rounded transition-colors ${theme === "dark" ? "text-purple-500 bg-purple-50" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
      <Palette size={12} />
    </button>
  );
}
