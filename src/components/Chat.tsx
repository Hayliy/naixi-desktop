import { useState, useEffect, useRef } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { sendChatStream } from "@/lib/stream";
import ContentRenderer, { type ContentBlock } from "@/components/ContentRenderer";
import DetailPanel from "@/components/DetailPanel";
import ProviderSettings from "@/components/ProviderSettings";
import PromptPanel from "@/components/PromptPanel";
import ErrorBoundary from "@/components/ErrorBoundary";
import { useAppConfig } from "@/contexts/AppContext";
import {
  Search, Send, MessageCircle, User, Bot, Trash2, Plus, Copy, Check, X,
  ChevronLeft, RotateCcw, Layers, Sparkles, ImageIcon, Video, Music, Code, Globe, Settings, FileText, Edit3, Zap, Cpu,
} from "lucide-react";

/* ─── 类型 ─── */
interface ConvItem { key: string; last_role: string; last_msg: string; last_time: number; }
interface MsgItem { id: number; role: string; content: string; content_blocks?: ContentBlock[] | null; time: number; }
interface ProviderModel { key: string; label: string; provider_id: number; }

const MODELS: ProviderModel[] = [{ key: "auto", label: "自动路由（默认）", provider_id: 0 }];

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

/* ─── 能力输入弹窗（大输入框） ─── */
function CapabilityInput({ action, config, onSend, onClose }: {
  action: typeof QUICK_ACTIONS[number];
  config: any;
  onSend: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(action.template);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 每种能力需要的供应商类型
  const NEEDS_PROVIDER: Record<string, { type: string; label: string; example: string }> = {
    "画一张": { type: "image", label: "画图模型", example: "阿里百炼 Wanx / OpenAI DALL-E" },
    "生成一段视频：": { type: "video", label: "视频模型", example: "智谱 CogVideoX" },
    "用语音说：": { type: "audio", label: "语音模型", example: "OpenAI TTS / 百炼 CosyVoice" },
  };

  const need = NEEDS_PROVIDER[action.template];
  const hasProvider = need ? Object.values(config?.api_providers || {}).some((v: any) => v.type === need.type) : true;

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.setSelectionRange(action.template.length, action.template.length);
  }, []);

  const handleSend = () => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-sakura-100">
          <div className="flex items-center gap-2">
            <action.icon size={16} className="text-sakura-500" />
            <span className="text-sm font-semibold text-sakura-600">{action.label}</span>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-sakura-50 rounded text-sakura-300">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
          </button>
        </div>

        {/* 供应商缺失提示 */}
        {need && !hasProvider && (
          <div className="mx-5 mt-4 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200">
            <p className="text-[12px] font-medium text-amber-800">未配置 {need.label}</p>
            <p className="text-[11px] text-amber-600 mt-1">
              发送后将由聊天 LLM 处理，效果取决于模型能力。
              如需专用 {need.label}，请添加类型为「{need.type}」的供应商（例如：{need.example}）。
            </p>
          </div>
        )}

        <div className="flex-1 p-5">
          <textarea ref={inputRef}
            className="w-full h-[250px] px-4 py-3 rounded-xl border border-sakura-100 text-sm text-sakura-600 resize-none outline-none focus:ring-1 focus:ring-sakura-300 leading-relaxed"
            value={text} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); handleSend(); } }} />
        </div>
        <div className="px-5 py-3 border-t border-sakura-100 flex items-center justify-between">
          <span className="text-[11px] text-sakura-400">Ctrl+Enter 发送</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-lg text-xs text-sakura-400 hover:bg-sakura-50 transition-colors">取消</button>
            <button onClick={handleSend} disabled={!text.trim()}
              className="px-5 py-2 rounded-lg text-xs bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-40 hover:shadow-md transition-shadow">
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

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
function ChatInput({ onSend, streaming, onStop, onCapabilityClick }: { onSend: (text: string) => void; streaming: boolean; onStop: () => void; onCapabilityClick?: (a: typeof QUICK_ACTIONS[number]) => void }) {
  const [text, setText] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [listening, setListening] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);

  // 语音输入
  const [listeningText, setListeningText] = useState("");
  const startListening = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("当前浏览器不支持语音输入，请使用 Chrome 或 Edge");
      return;
    }
    try {
      const rec = new SpeechRecognition();
      rec.lang = "zh-CN";
      rec.continuous = false;
      rec.interimResults = true;
      rec.onresult = (e: any) => {
        let finalText = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) {
            finalText += e.results[i][0].transcript;
          }
        }
        if (finalText) {
          setText(prev => (prev ? prev + finalText : finalText));
          setListeningText("");
        } else {
          // 显示中间结果提示
          setListeningText(e.results[e.results.length - 1][0].transcript);
        }
      };
      rec.onerror = (ev: any) => {
        console.error("语音识别错误:", ev.error);
        setListening(false);
        setListeningText("");
        if (ev.error === "not-allowed") alert("请允许麦克风权限");
      };
      rec.onend = () => { setListening(false); setListeningText(""); };
      rec.start();
      recognitionRef.current = rec;
      setListening(true);
      setListeningText("请说话...");
    } catch (err) {
      console.error("语音识别启动失败:", err);
      setListening(false);
    }
  };

  const stopListening = () => {
    if (recognitionRef.current) {
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    setListening(false);
  };

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

  const sendRef = useRef(handleSend);
  sendRef.current = handleSend;
  // 原生事件监听：用 ref 避免闭包过期问题
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        sendRef.current();
      }
    };
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, []); // 空依赖：只绑定一次，通过 ref 拿最新 handleSend
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
          <button key={i} onClick={() => onCapabilityClick?.(a)}
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] ${a.color} ${a.bg} hover:opacity-80 transition-opacity`}>
            <a.icon size={11} />
            <span>{a.label}</span>
          </button>
        ))}
        {listening && listeningText && (
          <span className="text-[10px] text-red-400 animate-pulse ml-2">{listeningText}</span>
        )}
        <span className="text-[9px] text-sakura-300 ml-auto">Enter 换行 · Ctrl+Enter 发送</span>
      </div>
      {/* 输入框 */}
      <div className="flex items-end gap-2 px-4 pb-3">
        <textarea
          ref={inputRef}
          className="flex-1 bg-sakura-50 rounded-xl px-3 py-2 text-xs text-sakura-600 placeholder:text-sakura-300 resize-none outline-none ring-1 ring-sakura-100 focus:ring-sakura-300 min-h-[36px] max-h-[120px]"
          placeholder="给奶昔发消息..."
          rows={1}
          value={text}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
          onChange={(e) => {
            setText(e.target.value);
            if (inputRef.current) {
              inputRef.current.style.height = "auto";
              inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + "px";
            }
          }}
        />
        {/* 语音输入按钮 */}
        <button onClick={listening ? stopListening : startListening}
          className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all ${
            listening
              ? "bg-red-500 text-white shadow-lg shadow-red-200 animate-pulse"
              : "bg-sakura-50 text-sakura-400 hover:text-sakura-500 hover:bg-sakura-100"
          }`}
          title={listening ? "停止录音" : "语音输入"}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            <line x1="12" y1="19" x2="12" y2="22"/>
          </svg>
        </button>
        {streaming ? (
          <button onClick={onStop}
            className="w-9 h-9 rounded-xl bg-red-500 flex items-center justify-center shrink-0 hover:bg-red-600 transition-colors shadow-sm"
            title="停止生成">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="white"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
          </button>
        ) : (
          <button onClick={handleSend} disabled={!text.trim()}
            className="w-9 h-9 rounded-xl bg-gradient-to-br from-sakura-400 to-sakura-200 flex items-center justify-center shrink-0 disabled:opacity-40 hover:shadow-md transition-shadow">
            <Send size={14} className="text-white" />
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── 模型下拉选择器 ─── */
function ModelSelector({ availableModels, modelKey, onModelChange }: {
  availableModels: ProviderModel[];
  modelKey: string;
  onModelChange: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const current = availableModels.find(m => m.key === modelKey);

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-sakura-50 text-sakura-500 hover:bg-sakura-100 transition-colors">
        <Layers size={10} />
        <span className="max-w-[8rem] truncate">{current?.label || modelKey}</span>
        <svg className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-56 bg-white border border-sakura-100 rounded-lg shadow-lg z-50 max-h-64 overflow-y-auto">
          {availableModels.map(m => (
            <button key={m.key}
              onClick={() => { onModelChange(m.key); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-[11px] flex items-center gap-2 transition-colors hover:bg-sakura-50 ${
                m.key === modelKey ? "text-sakura-600 bg-sakura-50 font-medium" : "text-sakura-500"
              }`}>
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${m.key === modelKey ? "bg-sakura-500" : "bg-sakura-200"}`} />
              <span className="truncate">{m.label}</span>
              {m.key === modelKey && (
                <svg className="w-3 h-3 ml-auto shrink-0 text-sakura-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6 9 17l-5-5"/></svg>
              )}
            </button>
          ))}
        </div>
      )}
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
  const [modelKey, setModelKey] = useState(() => {
    try { return localStorage.getItem("naixi_model_key") || MODELS[0].key; } catch { return MODELS[0].key; }
  });
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
  const [capabilityAction, setCapabilityAction] = useState<typeof QUICK_ACTIONS[number] | null>(null);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [streaming, setStreaming] = useState(false);

  const stopStreaming = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setAgentActive(false);
    setStreaming(false);
  };

  // 加载对话列表
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
    for (const [pid, pcfg] of Object.entries(config.api_providers)) {
      idx++;
      if (pcfg.model) {
        models.push({ key: pcfg.model, label: `${pcfg.model}`, provider_id: idx });
      }
    }
    if (models.length > 0) {
      setAvailableModels([{ key: "auto", label: "自动路由（默认）", provider_id: 0 }, ...models]);
      // 如果当前模型不在列表中，用第一个实际模型
      const savedKey = localStorage.getItem("naixi_model_key");
      if (savedKey && models.find(m => m.key === savedKey)) {
        // 已经正确保存了
      } else if (models[0]) {
        setModelKey(models[0].key);
        try { localStorage.setItem("naixi_model_key", models[0].key); } catch {}
      }
    }
  }, [config, loaded]);

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
      // 桌面端无专用 API 时回退到普通聊天
      if (err.includes("404")) {
        setAgentActive(false);
        setMsgs(prev => prev.filter(m => m.id !== aiId));
        await handleNormalChat(text);
        return;
      }
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
      const err = String(e);
      if (err.includes("404")) { setAgentActive(false); setMsgs(prev => prev.filter(m => m.id !== aiId)); await handleNormalChat(text); return; }
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] }));
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
      const err = String(e);
      if (err.includes("404")) { setAgentActive(false); setMsgs(prev => prev.filter(m => m.id !== aiId)); await handleNormalChat(text); return; }
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `合成失败: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] }));
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
      const err = String(e);
      if (err.includes("404")) { setAgentActive(false); setMsgs(prev => prev.filter(m => m.id !== aiId)); await handleNormalChat(text); return; }
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `生成失败: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] }));
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
      const err = String(e);
      if (err.includes("404")) { setAgentActive(false); setMsgs(prev => prev.filter(m => m.id !== aiId)); await handleNormalChat(text); return; }
      setMsgs(prev => prev.map(m => m.id !== aiId ? m : { ...m, content: `搜索失败: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] }));
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
    setStreaming(true);
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

    const controller = new AbortController();
    abortRef.current = controller;

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
        setStreaming(false);
        abortRef.current = null;
        if (usage) setRealTokens({ input: usage.input || 0, output: usage.output || 0 });
        apiGet<{ conversations: ConvItem[] }>("/api/conversations")
          .then(d => setConvs(d.conversations)).catch(() => {});
      },
      onError: (err) => {
        // 如果是主动取消，不显示错误
        if (err.includes("abort") || err.includes("AbortError")) {
          setAgentActive(false);
          setStreaming(false);
          abortRef.current = null;
          setMsgs(prev => prev.filter(m => m.id !== aiId));
          return;
        }
        setMsgs(prev => prev.map(m => {
          if (m.id !== aiId) return m;
          return { ...m, content: `出错了: ${err}`, content_blocks: [{ type: "status", state: "error", text: err }] };
        }));
        setAgentActive(false);
        setStreaming(false);
        abortRef.current = null;
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
      // 代码直接走聊天 LLM，不需要专用 API
      await handleNormalChat(t);
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
                  <button onClick={() => setShowSettings(!showSettings)} title="模型设置" className={`p-1.5 rounded transition-colors ${showSettings ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
                    <Settings size={12} />
                  </button>
                  <button onClick={() => setShowPrompt(!showPrompt)} title="提示词" className={`p-1.5 rounded transition-colors ${showPrompt ? "bg-sakura-100 text-sakura-500" : "text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50"}`}>
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
                {/* 模型切换（直接下拉选择） */}
                <ModelSelector availableModels={availableModels} modelKey={modelKey} onModelChange={(key) => {
                  setModelKey(key);
                  try { localStorage.setItem("naixi_model_key", key); } catch {}
                }} />
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
            <ChatInput onSend={handleSend} streaming={streaming} onStop={stopStreaming}
              onCapabilityClick={(a) => setCapabilityAction(a)} />
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
            <ErrorBoundary name="提示词面板">
              <PromptPanel activeScene={scene} onSceneChange={setScene} />
            </ErrorBoundary>
          </div>
        </div>
      )}

      {/* 能力输入弹窗 */}
      {capabilityAction && (
        <CapabilityInput action={capabilityAction} config={config}
          onSend={(text) => { setCapabilityAction(null); handleSend(text); }}
          onClose={() => setCapabilityAction(null)} />
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
            <ErrorBoundary name="供应商设置">
              <ProviderSettings />
            </ErrorBoundary>
          </div>
        </div>
      )}
    </div>
  );
}
