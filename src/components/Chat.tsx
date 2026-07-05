import { useState, useEffect, useRef } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { sendChatStream } from "@/lib/stream";
import ContentRenderer, { type ContentBlock } from "@/components/ContentRenderer";
import DetailPanel from "@/components/DetailPanel";
import ProviderSettings from "@/components/ProviderSettings";
import PromptPanel from "@/components/PromptPanel";
import {
  Search, Send, MessageCircle, User, Bot, Trash2, Plus, Copy, Check, X,
  ChevronLeft, RotateCcw, Layers, Sparkles, ImageIcon, Video, Music, Code, Globe, Settings, FileText, Edit3, Zap, Cpu,
} from "lucide-react";

/* ─── 类型 ─── */
interface ConvItem { key: string; last_role: string; last_msg: string; last_time: number; }
interface MsgItem { id: number; role: string; content: string; content_blocks?: ContentBlock[] | null; time: number; }
interface ProviderModel { key: string; label: string; provider_id: number; }

const MODELS = [{ key: "auto", label: "自动路由（默认）" }];

/* ─── 工具函数 ─── */
function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
function convName(key: string, msgs?: MsgItem[], customName?: string) {
  if (customName) return customName;
  if (msgs && msgs.length > 0) {
    const first = msgs.find(m => m.role === "user");
    if (first) {
      const txt = first.content.replace(/^\[[^\]]+\]\s*:\s*/, "").slice(0, 20);
      return txt + (txt.length >= 20 ? "..." : "");
    }
  }
  const parts = key.split(":");
  if (parts.length < 2) return key;
  const id = parts[1];
  if (parts[0] === "group") return `群聊 ${id.slice(-4)}`;
  if (parts[0] === "user") return `私聊 ${id.slice(-4)}`;
  return "新对话";
}

/* ═══════════════════════════════════════════
   快捷操作按钮（输入框上方）
   ═══════════════════════════════════════════ */
const QUICK_ACTIONS = [
  { icon: ImageIcon, label: "画图", color: "text-pink-500", bg: "bg-pink-50", template: "画一张" },
  { icon: Video, label: "视频", color: "text-sakura-500", bg: "bg-sakura-50", template: "生成一段视频：" },
  { icon: Music, label: "语音", color: "text-blue-500", bg: "bg-blue-50", template: "用语音说：" },
  { icon: Code, label: "代码", color: "text-green-500", bg: "bg-green-50", template: "写一段代码：" },
  { icon: Globe, label: "搜索", color: "text-amber-500", bg: "bg-amber-50", template: "搜索一下：" },
];

/* ═══════════════════════════════════════════
   对话列表（左侧面板）
   ═══════════════════════════════════════════ */
function ConvList({
  convs, activeKey, onSelect, onNew, search, onSearchChange, loading, customNames,
}: {
  convs: ConvItem[]; activeKey: string | null; onSelect: (k: string) => void; onNew: () => void;
  search: string; onSearchChange: (s: string) => void; loading: boolean;
  customNames: Record<string, string>;
}) {
  const filtered = convs.filter(c => (customNames[c.key] || convName(c.key)).includes(search) || c.last_msg.includes(search));
  return (
    <div className="w-64 min-w-[16rem] border-r border-sakura-100 bg-white flex flex-col">
      {/* 搜索 + 新对话 */}
      <div className="p-3 border-b border-sakura-100 space-y-2">
        <button onClick={onNew} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg bg-gradient-to-br from-sakura-400 to-sakura-200 text-white hover:shadow-md transition-shadow">
          <Plus size={13} />
          <span>新对话</span>
        </button>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sakura-300" />
          <input className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-sakura-100 bg-sakura-50 text-sakura-600 placeholder:text-sakura-300 focus:outline-none focus:ring-1 focus:ring-sakura-300" placeholder="搜索对话..." value={search} onChange={e => onSearchChange(e.target.value)} />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-sakura-300"><MessageCircle size={16} className="animate-pulse" /></div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center py-12 text-sakura-300 text-xs gap-1.5">
            <MessageCircle size={20} className="text-sakura-200" />
            <span>{search ? "没有匹配的对话" : "暂无对话记录"}</span>
          </div>
        ) : filtered.map((c) => (
          <button key={c.key} onClick={() => onSelect(c.key)}
            className={`w-full text-left px-3 py-2.5 border-b border-sakura-50 transition-colors hover:bg-sakura-50 ${activeKey === c.key ? "bg-sakura-100" : ""}`}>
            <div className="flex items-start gap-2">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${c.last_role === "assistant" ? "bg-sakura-100 text-sakura-500" : "bg-pink-100 text-pink-500"}`}>
                {c.last_role === "assistant" ? <Bot size={14} /> : <User size={14} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-medium text-sakura-600 truncate">{customNames[c.key] || convName(c.key)}</span>
                  <span className="text-[10px] text-sakura-300 shrink-0">{fmtTime(c.last_time)}</span>
                </div>
                <p className="text-[11px] text-sakura-400 truncate mt-0.5">{c.last_msg}</p>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   消息气泡（内容块版）
   ═══════════════════════════════════════════ */
function MsgBubble({ msg, onEdit, onRegenerate }: { msg: MsgItem; onEdit?: (id: number, text: string) => void; onRegenerate?: (id: number) => void }) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const isUser = msg.role === "user";
  let displayName = isUser ? "你" : "奶昔";
  let cleanContent = msg.content;

  // 提取用户昵称
  if (isUser && msg.content.startsWith("[")) {
    const end = msg.content.indexOf("]: ");
    if (end > 0) {
      displayName = msg.content.slice(1, msg.content.indexOf("("));
      cleanContent = msg.content.slice(end + 3);
    }
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(cleanContent).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const startEdit = () => {
    setEditText(cleanContent);
    setEditing(true);
  };

  const handleEditSave = () => {
    if (editText.trim() && onEdit) onEdit(msg.id, editText.trim());
    setEditing(false);
  };

  return (
    <div className={`flex gap-2 group ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${isUser ? "bg-pink-100 text-pink-500" : "bg-sakura-100 text-sakura-500"}`}>
        {isUser ? <User size={12} /> : <Bot size={12} />}
      </div>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className="flex items-center gap-1 mb-0.5">
          <span className={`text-[10px] ${isUser ? "text-right" : ""} text-sakura-400`}>{displayName}</span>
          {/* 操作按钮：hover 显示 */}
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={handleCopy} className="p-0.5 hover:text-sakura-500 text-sakura-300" title="复制">
              {copied ? <Check size={10} /> : <Copy size={10} />}
            </button>
            {isUser && (
              <button onClick={startEdit} className="p-0.5 hover:text-sakura-500 text-sakura-300" title="编辑">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
              </button>
            )}
            {!isUser && onRegenerate && (
              <button onClick={() => onRegenerate(msg.id)} className="p-0.5 hover:text-sakura-500 text-sakura-300" title="重新生成">
                <RotateCcw size={10} />
              </button>
            )}
          </div>
        </div>
        {editing ? (
          <div className="flex flex-col gap-1">
            <textarea className="w-full px-3 py-2 rounded-xl border border-sakura-100 bg-white text-xs text-sakura-600 resize-none min-h-[60px]"
              value={editText} onChange={e => setEditText(e.target.value)} rows={3} />
            <div className="flex gap-1 justify-end">
              <button onClick={() => setEditing(false)} className="px-2 py-0.5 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleEditSave} className="px-2 py-0.5 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-200 text-white">保存</button>
            </div>
          </div>
        ) : (
          <div className={`rounded-xl px-3 py-2 text-xs leading-relaxed ${
            isUser
              ? "bg-gradient-to-br from-sakura-400 to-sakura-200 text-white rounded-tr-sm"
              : "bg-white border border-blue-100 text-sakura-600 rounded-tl-sm"
          }`}>
            {msg.content_blocks && msg.content_blocks.length > 0 ? (
              <ContentRenderer blocks={msg.content_blocks} />
            ) : (
              <span className="whitespace-pre-wrap">{cleanContent}</span>
            )}
          </div>
        )}
        <span className="text-[9px] text-sakura-300 mt-0.5">{fmtTime(msg.time)}</span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   Agent 活动面板
   ═══════════════════════════════════════════ */
function AgentStatus({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div className="px-4 py-2 border-b border-sakura-100 bg-gradient-to-r from-teal-50/50 to-green-50/50">
      <div className="flex items-center gap-2 text-[11px] text-teal-600">
        <Cpu size={13} className="text-teal-500 animate-pulse" />
        <span>Agent 正在思考并调用工具...</span>
        <span className="flex gap-1 ml-auto">
          <span className="w-1 h-1 bg-teal-400 rounded-full animate-bounce" style={{animationDelay: "0ms"}} />
          <span className="w-1 h-1 bg-teal-400 rounded-full animate-bounce" style={{animationDelay: "150ms"}} />
          <span className="w-1 h-1 bg-teal-400 rounded-full animate-bounce" style={{animationDelay: "300ms"}} />
        </span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   输入栏（含快捷操作）
   ═══════════════════════════════════════════ */
function ChatInput({ onSend }: { onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const insertTemplate = (tpl: string) => {
    setText(prev => (prev ? prev + "\n" : "") + tpl);
    if (inputRef.current) {
      inputRef.current.focus();
      inputRef.current.style.height = "auto";
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + "px";
    }
  };

  const handleSend = () => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  };
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };
  return (
    <div className={`border-t border-sakura-100 bg-white ${dragOver ? "ring-2 ring-sakura-300" : ""}`}
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault();
        setDragOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
          insertTemplate(`[附件: ${files[0].name}]`);
        }
      }}>
      {/* 快捷操作 */}
      <div className="flex items-center gap-1.5 px-4 pt-2 pb-1">
        {QUICK_ACTIONS.map((a, i) => (
          <button key={i} onClick={() => insertTemplate(a.template)}
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] ${a.color} ${a.bg} hover:opacity-80 transition-opacity`}>
            <a.icon size={11} />
            <span>{a.label}</span>
          </button>
        ))}
        <span className="text-[9px] text-sakura-300 ml-auto">Shift+Enter 换行</span>
      </div>
      {/* 输入框 */}
      <div className="flex items-end gap-2 px-4 pb-3">
        <textarea
          ref={inputRef}
          className="flex-1 bg-sakura-50 rounded-xl px-3 py-2 text-xs text-sakura-600 placeholder:text-sakura-300 resize-none outline-none ring-1 ring-sakura-100 focus:ring-sakura-300 min-h-[36px] max-h-[120px]"
          placeholder="给奶昔发消息..."
          rows={1}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            if (inputRef.current) {
              inputRef.current.style.height = "auto";
              inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + "px";
            }
          }}
          onKeyDown={handleKeyDown}
        />
        <button onClick={handleSend} disabled={!text.trim()}
          className="w-9 h-9 rounded-xl bg-gradient-to-br from-sakura-400 to-sakura-200 flex items-center justify-center shrink-0 disabled:opacity-40 hover:shadow-md transition-shadow">
          <Send size={14} className="text-white" />
        </button>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   对话主页面
   ═══════════════════════════════════════════ */
export default function ChatPage() {
  const [convs, setConvs] = useState<ConvItem[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<MsgItem[]>([]);
  const [search, setSearch] = useState("");
  const [convLoading, setConvLoading] = useState(true);
  const [msgLoading, setMsgLoading] = useState(false);
  const [modelKey, setModelKey] = useState(MODELS[0].key);
  const [agentActive, setAgentActive] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
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
  const msgEndRef = useRef<HTMLDivElement>(null);

  // 加载对话列表
  useEffect(() => {
    setConvLoading(true);
    apiGet<{ conversations: ConvItem[]; total: number }>("/api/conversations")
      .then(d => { setConvs(d.conversations); setConvLoading(false); })
      .catch(() => setConvLoading(false));
  }, []);

  // 加载可用模型列表
  useEffect(() => {
    apiGet<{ models: ProviderModel[] }>("/api/providers")
      .then(d => {
        if (d.models?.length) {
          setAvailableModels([{ key: "auto", label: "自动路由（默认）" }, ...d.models]);
        }
      })
      .catch(() => {});
  }, []);

  // 加载自定义场景（prompts 中非预设场景）
  useEffect(() => {
    apiGet<{ prompts: { scene: string; file: string; desc: string }[] }>("/api/prompts")
      .then(d => {
        const presets = ["owner", "group", "stranger"];
        const custom = (d.prompts || []).filter(p => !presets.includes(p.scene));
        setCustomScenes(custom.map(p => ({ file: p.file, desc: p.desc })));
      })
      .catch(() => {});
  }, []);

  // 持久化自定义名称
  useEffect(() => {
    localStorage.setItem("naixi_custom_names", JSON.stringify(customNames));
  }, [customNames]);

  // 选中对话时加载消息
  useEffect(() => {
    if (!activeKey) return;
    setMsgLoading(true);
    apiGet<{ key: string; messages: MsgItem[]; total: number }>(`/api/conversation/${encodeURIComponent(activeKey)}`)
      .then(d => { setMsgs(d.messages); setMsgLoading(false); })
      .catch(() => setMsgLoading(false));
  }, [activeKey]);

  // 自动滚到底部
  useEffect(() => { msgEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const handleNew = () => {
    setActiveKey(null);
    setMsgs([]);
    setIsNewChat(true);
  };

  const isImageRequest = (text: string) => {
    return /^(画[一张]?[：:]?|画一张[ ]?|生成图片[：:]?|生成一张)/i.test(text.trim());
  };

  const extractImagePrompt = (text: string) => {
    return text.replace(/^(画[一张]?[：:]?|画一张[ ]?|生成图片[：:]?|生成一张)/i, "").trim();
  };

  const extractPrefix = (text: string, prefix: string) => {
    return text.replace(prefix, "").trim();
  };

  const handleGenerateImage = async (text: string) => {
    const prompt = extractImagePrompt(text);
    const userMsg: MsgItem = {
      id: Date.now(),
      role: "user",
      content: text,
      time: Math.floor(Date.now() / 1000),
    };
    setMsgs(prev => [...prev, userMsg]);
    if (!prompt) {
      // 没有提取到提示词，走普通聊天
      await handleNormalChat(text);
      return;
    }
    setAgentActive(true);
    setIsNewChat(false);
    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = {
      id: aiId,
      role: "assistant",
      content: "正在生成图片，请稍候...",
      content_blocks: [{ type: "status", state: "loading", text: "正在生成图片..." }],
      time: Math.floor(Date.now() / 1000),
    };
    setMsgs(prev => [...prev, aiMsg]);

    try {
      const res = await apiPost<{ ok: boolean; url?: string; error?: string }>("/api/generate_image", { prompt });
      if (res.ok && res.url) {
        setMsgs(prev => prev.map(m => {
          if (m.id !== aiId) return m;
          return {
            ...m,
            content: "图片已生成",
            content_blocks: [{ type: "image", url: res.url! }, { type: "text", text: "图片已生成，点击查看原图。" }],
          };
        }));
      } else {
        setMsgs(prev => prev.map(m => {
          if (m.id !== aiId) return m;
          return { ...m, content: `生成失败: ${res.error || "未知错误"}`, content_blocks: [{ type: "status", state: "error", text: res.error || "生成失败" }] };
        }));
      }
    } catch (e) {
      const err = String(e);
      setMsgs(prev => prev.map(m => {
        if (m.id !== aiId) return m;
        return { ...m, content: `生成失败: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] };
      }));
    }
    setAgentActive(false);
    if (activeKey) {
      apiGet<{ conversations: ConvItem[] }>("/api/conversations")
        .then(d => setConvs(d.conversations)).catch(() => {});
    }
  };

  const handleGenerateVideo = async (text: string) => {
    const prompt = extractPrefix(text, "生成一段视频：");
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    if (!prompt) { await handleNormalChat(text); return; }
    setAgentActive(true); setIsNewChat(false);
    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "正在生成视频，请稍候...", content_blocks: [{ type: "status", state: "loading", text: "正在生成视频（约1-2分钟）..." }], time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, aiMsg]);
    try {
      const res = await apiPost<{ ok: boolean; url?: string; error?: string }>("/api/generate_video", { prompt });
      if (res.ok && res.url) {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: "视频已生成", content_blocks: [{ type: "video", url: res.url! }, { type: "text", text: "视频已生成" }] }));
      } else {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${res.error || "未知错误"}`, content_blocks: [{ type: "status", state: "error", text: res.error || "生成失败" }] }));
      }
    } catch (e) {
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${String(e)}`, content_blocks: [{ type: "status", state: "error", text: String(e) }] }));
    }
    setAgentActive(false);
  };

  const handleGenerateVoice = async (text: string) => {
    const content = extractPrefix(text, "用语音说：");
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    if (!content) { await handleNormalChat(text); return; }
    setAgentActive(true); setIsNewChat(false);
    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "正在合成语音...", content_blocks: [{ type: "status", state: "loading", text: "正在合成语音..." }], time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, aiMsg]);
    try {
      const res = await apiPost<{ ok: boolean; audio?: string; format?: string; error?: string }>("/api/generate_voice", { text: content, voice: "longfeifei_v3" });
      if (res.ok && res.audio) {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : {
          ...m, content: "语音已合成",
          content_blocks: [
            { type: "audio", url: `data:audio/${res.format || "wav"};base64,${res.audio}` },
            { type: "text", text: content },
          ]
        }));
      } else {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `合成失败: ${res.error || "未知错误"}`, content_blocks: [{ type: "status", state: "error", text: res.error || "合成失败" }] }));
      }
    } catch (e) {
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `合成失败: ${String(e)}`, content_blocks: [{ type: "status", state: "error", text: String(e) }] }));
    }
    setAgentActive(false);
  };

  const handleGenerateCode = async (text: string) => {
    const prompt = extractPrefix(text, "写一段代码：");
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    if (!prompt) { await handleNormalChat(text); return; }
    setAgentActive(true); setIsNewChat(false);
    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "正在生成代码...", content_blocks: [{ type: "status", state: "loading", text: "正在生成代码..." }], time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, aiMsg]);
    try {
      const res = await apiPost<{ ok: boolean; code?: string; model?: string; error?: string }>("/api/generate_code", { prompt });
      if (res.ok && res.code) {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : {
          ...m, content: res.code || "代码已生成",
          content_blocks: [{ type: "code", text: res.code, language: "" }, { type: "text", text: `由 ${res.model || "AI"} 生成` }]
        }));
      } else {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${res.error || "未知错误"}`, content_blocks: [{ type: "status", state: "error", text: res.error || "生成失败" }] }));
      }
    } catch (e) {
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${String(e)}`, content_blocks: [{ type: "status", state: "error", text: String(e) }] }));
    }
    setAgentActive(false);
  };

  const handleSearch = async (text: string) => {
    const q = extractPrefix(text, "搜索一下：");
    const userMsg: MsgItem = { id: Date.now(), role: "user", content: text, time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, userMsg]);
    if (!q) { await handleNormalChat(text); return; }
    setAgentActive(true); setIsNewChat(false);
    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = { id: aiId, role: "assistant", content: "正在搜索...", content_blocks: [{ type: "status", state: "loading", text: "正在搜索..." }], time: Math.floor(Date.now() / 1000) };
    setMsgs(prev => [...prev, aiMsg]);
    try {
      const res = await apiPost<{ ok: boolean; results?: Array<{title:string;url:string;content:string}>; total?: number; error?: string }>("/api/search", { q });
      if (res.ok && res.results) {
        const items = res.results.slice(0, 8).map((r, i) =>
          `${i+1}. [${r.title}](${r.url})\n${(r.content || "").slice(0, 120)}...`
        ).join("\n\n");
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : {
          ...m, content: `找到 ${res.total || res.results.length} 条结果：\n\n${items}`,
          content_blocks: [{ type: "text", text: `找到 ${res.total || res.results.length} 条结果：\n\n${items}` }]
        }));
      } else {
        setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `搜索失败: ${res.error || "未知错误"}`, content_blocks: [{ type: "status", state: "error", text: res.error || "搜索失败" }] }));
      }
    } catch (e) {
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `搜索失败: ${String(e)}`, content_blocks: [{ type: "status", state: "error", text: String(e) }] }));
    }
    setAgentActive(false);
  };

  const handleNormalChat = async (text: string) => {
    const userMsg: MsgItem = {
      id: Date.now(),
      role: "user",
      content: text,
      time: Math.floor(Date.now() / 1000),
    };
    setMsgs(prev => [...prev, userMsg]);
    setAgentActive(true);
    setIsNewChat(false);

    const aiId = Date.now() + 1;
    const aiMsg: MsgItem = {
      id: aiId,
      role: "assistant",
      content: "",
      content_blocks: [{ type: "status", state: "loading", text: "思考中..." }],
      time: Math.floor(Date.now() / 1000),
    };
    setMsgs(prev => [...prev, aiMsg]);

    const selectedModel = availableModels.find(m => m.key === modelKey);

    await sendChatStream(agentMode ? "/api/agent/stream" : "/api/chat/stream", {
      text,
      key: activeKey || `chat:${Date.now().toString(36)}`,
      model: modelKey,
      provider_id: selectedModel?.provider_id || 0,
      scene,
    }, {
      onUpdate: (blocks, generating, usage) => {
        setMsgs(prev => prev.map(m => {
          if (m.id !== aiId) return m;
          return { ...m, content_blocks: blocks, content: blocks.find(b => b.type === "text")?.text || "" };
        }));
        if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
      },
      onDone: (usage) => {
        setAgentActive(false);
        if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
        apiGet<{ conversations: ConvItem[] }>("/api/conversations")
          .then(d => setConvs(d.conversations)).catch(() => {});
      },
      onError: (err) => {
        setMsgs(prev => prev.map(m => {
          if (m.id !== aiId) return m;
          return { ...m, content: `出错了: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] };
        }));
        setAgentActive(false);
      },
    });
  };

  const handleSend = async (text: string) => {
    const t = text.trim();
    if (t.startsWith("生成一段视频：")) {
      await handleGenerateVideo(t);
    } else if (t.startsWith("用语音说：")) {
      await handleGenerateVoice(t);
    } else if (t.startsWith("写一段代码：")) {
      await handleGenerateCode(t);
    } else if (t.startsWith("搜索一下：")) {
      await handleSearch(t);
    } else if (isImageRequest(t)) {
      await handleGenerateImage(t);
    } else {
      await handleNormalChat(t);
    }
  };

  const handleDelete = async (key: string) => {
    try {
      await apiPost("/api/conversation/delete", { key });
      setConvs(prev => prev.filter(c => c.key !== key));
      if (activeKey === key) { setActiveKey(null); setMsgs([]); }
    } catch {}
  };

  return (
    <div className="flex h-full bg-sakura-50 rounded-xl overflow-hidden border border-sakura-100">
      {/* 对话列表 */}
      <ConvList convs={convs} activeKey={activeKey} onSelect={setActiveKey} onNew={handleNew}
        search={search} onSearchChange={setSearch} loading={convLoading} customNames={customNames} />

      {/* 消息区 */}
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
              {/* 第一行：标题 + 面板按钮 */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <button className="lg:hidden p-1 hover:bg-sakura-50 rounded shrink-0" onClick={() => setActiveKey(null)}>
                    <ChevronLeft size={14} className="text-sakura-400" />
                  </button>
                  {renaming && activeKey ? (
                    <div className="flex items-center gap-1">
                      <input className="w-36 px-2 py-0.5 rounded border border-sakura-100 text-xs text-sakura-600"
                        value={renameText} onChange={e => setRenameText(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") { setCustomNames(p => ({ ...p, [activeKey]: renameText })); setRenaming(false); } }}
                        autoFocus />
                      <button onClick={() => { setCustomNames(p => ({ ...p, [activeKey]: renameText })); setRenaming(false); }}
                        className="p-0.5 text-green-500"><Check size={12} /></button>
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
                  {/* Token 用量 */}
                  <div className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-sakura-50 text-sakura-400" title={realTokens ? `输入 ${realTokens.input} · 输出 ${realTokens.output}` : "未获取到用量数据"}>
                    <Sparkles size={10} />
                    <span>{realTokens ? `${(realTokens.input! + realTokens.output!) > 1000 ? `${((realTokens.input! + realTokens.output!) / 1000).toFixed(1)}k` : realTokens.input! + realTokens.output!} tokens` : "-"}</span>
                  </div>
                  <button onClick={() => setShowSettings(!showSettings)} className={`p-1.5 rounded transition-colors ${showSettings ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                    <Settings size={12} />
                  </button>
                  <button onClick={() => setShowPrompt(!showPrompt)} className={`p-1.5 rounded transition-colors ${showPrompt ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                    <FileText size={12} />
                  </button>
                  {activeKey && (
                    <button onClick={() => setShowDetail(!showDetail)} className={`p-1.5 rounded transition-colors ${showDetail ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                      <Sparkles size={12} />
                    </button>
                  )}
                  {activeKey && (
                    <button onClick={() => handleDelete(activeKey)} className="p-1.5 hover:bg-red-50 rounded text-sakura-300 hover:text-red-500 transition-colors">
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>

              {/* 第二行：模型切换 + 场景切换 */}
              <div className="flex items-center gap-2 flex-wrap">
                {/* 模型切换 */}
                <div className="relative group">
                  <button className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-sakura-50 text-sakura-500 hover:bg-sakura-100 transition-colors">
                    <Layers size={10} />
                    <span className="max-w-[8rem] truncate">{availableModels.find(m => m.key === modelKey)?.label || modelKey}</span>
                  </button>
                  <div className="absolute left-0 top-full mt-1 w-52 bg-white border border-sakura-100 rounded-lg shadow-lg hidden group-hover:block z-10 max-h-60 overflow-y-auto">
                    {availableModels.map(m => (
                      <button key={m.key} onClick={() => setModelKey(m.key)}
                        className={`w-full text-left px-3 py-1.5 text-[11px] hover:bg-sakura-50 ${modelKey === m.key ? "text-sakura-600 font-medium bg-sakura-50" : "text-sakura-400"}`}>
                        {m.label}
                      </button>
                    ))}
                  </div>
                </div>
                {/* 场景切换 */}
                <div className="flex items-center gap-0.5 flex-wrap">
                  {[
                    { key: "owner", label: "日常助手", icon: Bot },
                    { key: "group", label: "创作模式", icon: Edit3 },
                    { key: "stranger", label: "快捷问答", icon: Zap },
                    ...customScenes.map(s => ({ key: s.file, label: s.desc, icon: FileText })),
                  ].map(({ key, label, icon: SIcon }) => (
                    <button
                      key={key}
                      onClick={() => setScene(key)}
                      className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors ${
                        scene === key
                          ? "bg-gradient-to-r from-sakura-100 to-sakura-200 text-sakura-600 font-medium"
                          : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"
                      }`}
                      title={label}
                    >
                      <SIcon size={9} />
                      <span className="max-w-[4rem] truncate">{label}</span>
                      {scene === key && <span className="w-1.5 h-1.5 rounded-full bg-sakura-500" />}
                    </button>
                  ))}
                </div>
                {/* Agent 模式切换 */}
                <button onClick={() => setAgentMode(!agentMode)}
                  className={`flex items-center gap-1 px-1.5 py-1 rounded text-[10px] transition-colors ${
                    agentMode
                      ? "bg-gradient-to-r from-teal-100 to-green-100 text-teal-600 font-medium"
                      : "text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50"
                  }`}
                  title={agentMode ? "当前为 Agent 模式（LLM 可调用工具）" : "点击切换 Agent 模式"}
                >
                  <Cpu size={9} />
                  <span className="max-w-[4rem] truncate">Agent</span>
                  {agentMode && <span className="w-1.5 h-1.5 rounded-full bg-teal-500" />}
                </button>
              </div>
            </div>

            {/* Agent 活动面板 */}
            <AgentStatus active={agentActive} />

            {/* 消息列表 */}
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {msgLoading ? (
                <div className="flex items-center justify-center py-12"><Bot size={18} className="text-sakura-300 animate-bounce" /></div>
              ) : msgs.length === 0 ? (
                <div className="flex flex-col items-center py-12 text-sakura-300 text-xs gap-1">
                  <MessageCircle size={20} className="text-sakura-200" />
                  <span>开始你的第一条消息</span>
                </div>
              ) : msgs.map((m) => (<MsgBubble key={m.id} msg={m}
                onEdit={(id, text) => {
                  setMsgs(prev => prev.map(msg => msg.id === id ? { ...msg, content: text } : msg));
                }}
                onRegenerate={(id) => {
                  // 找到要重新生成的消息，重新发送
                  const idx = msgs.findIndex(m => m.id === id);
                  if (idx > 0) {
                    const userMsg = msgs[idx - 1];
                    if (userMsg?.role === "user") handleSend(userMsg.content);
                  }
                }}
              />))}
              <div ref={msgEndRef} />
            </div>

            {/* 输入栏 */}
            <ChatInput onSend={handleSend} />
          </>
        )}
      </div>

      {/* 右侧详情面板 */}
      {showDetail && activeKey && (
        <DetailPanel
          activeKey={activeKey}
          messageCount={msgs.length}
          tokenEstimate={realTokens ? (realTokens.input! + realTokens.output!) : 0}
          modelKey={modelKey}
          onClose={() => setShowDetail(false)}
        />
      )}

      {/* 提示词面板 */}
      {showPrompt && (
        <div className="w-60 min-w-[15rem] border-l border-sakura-100 bg-white flex flex-col">
          <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
            <span className="text-xs font-semibold text-sakura-500">提示词</span>
            <button onClick={() => setShowPrompt(false)} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
              <X size={13} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <PromptPanel activeScene={scene} onSceneChange={setScene} />
          </div>
        </div>
      )}

      {/* 供应商设置面板 */}
      {showSettings && (
        <div className="w-72 min-w-[18rem] border-l border-sakura-100 bg-white overflow-y-auto">
          <div className="sticky top-0 bg-white border-b border-sakura-100 px-3 py-2 flex items-center justify-between z-10">
            <span className="text-xs font-semibold text-sakura-500">模型供应商</span>
            <button onClick={() => setShowSettings(false)} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
              <X size={13} />
            </button>
          </div>
          <div className="p-3">
            <ProviderSettings />
          </div>
        </div>
      )}
    </div>
  );
}
