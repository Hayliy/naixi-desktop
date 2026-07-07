import { useState, useEffect } from "react";
import { Bot, User, Copy, Check, RotateCcw, Edit3, X, Volume2, VolumeX, Star, Reply } from "lucide-react";
import ContentRenderer from "@/components/ContentRenderer";
import type { MsgItem } from "@/components/ChatTypes";
import { fmtTime } from "@/components/ChatTypes";
import { apiGet } from "@/lib/api";

import { getAvatarUrl, resolveAvatarUrl, resolveDisplayName, AVATAR_KEYS } from "@/lib/avatar";

export default function MsgBubble({ msg, onEdit, onRegenerate, onDelete, onStar, onReply, starred, expertName }: {
  msg: MsgItem; onEdit?: (id: number, text: string) => void; onRegenerate?: (id: number) => void; onDelete?: (id: number) => void;
  onStar?: (id: number) => void; onReply?: (id: number) => void; starred?: boolean; expertName?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsMode, setTtsMode] = useState<"browser" | "api">("browser");
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");

  // 加载 TTS 配置
  useEffect(() => {
    apiGet<{ mode: string }>("/api/config/tts")
      .then(d => setTtsMode(d.mode as "browser" | "api"))
      .catch(() => {});
  }, []);

  const copyText = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const toggleSpeak = async () => {
    if (speaking) {
      if (ttsMode === "browser") window.speechSynthesis.cancel();
      else if (audioEl) { audioEl.pause(); audioEl.currentTime = 0; }
      setSpeaking(false);
      return;
    }
    const text = msg.content;
    if (!text) return;

    if (ttsMode === "browser") {
      // 浏览器 TTS
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "zh-CN";
      utterance.rate = 1.0;
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
      setSpeaking(true);
    } else {
      // AI 语音（走后端 generate_voice）
      try {
        const { apiPost } = await import("@/lib/api");
        const res = await apiPost<{ ok: boolean; audio?: string; error?: string }>("/api/generate_voice", { text: text.slice(0, 500) });
        if (res.ok && res.audio) {
          const audio = new Audio("data:audio/mp3;base64," + res.audio);
          audio.onended = () => setSpeaking(false);
          audio.onerror = () => setSpeaking(false);
          audio.play();
          setAudioEl(audio);
          setSpeaking(true);
        } else {
          // fallback: use browser TTS
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = "zh-CN";
          utterance.onend = () => setSpeaking(false);
          utterance.onerror = () => setSpeaking(false);
          window.speechSynthesis.speak(utterance);
          setSpeaking(true);
        }
      } catch {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "zh-CN";
        utterance.onend = () => setSpeaking(false);
        utterance.onerror = () => setSpeaking(false);
        window.speechSynthesis.speak(utterance);
        setSpeaking(true);
      }
    }
  };

  const isUser = msg.role === "user";
  const hasContentBlocks = (msg.content_blocks || []).length > 0;
  const displayContent = msg.content || "";
  // 没内容也没卡片 → 等待加载中，渲染最小骨架
  const isEmpty = !displayContent && !hasContentBlocks;

  return (
    <div className={`flex items-start gap-2 px-3 py-3 group ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 overflow-hidden ${isUser ? "bg-pink-100 text-pink-500" : "bg-sakura-100 text-sakura-500"}`}>
        {isUser ? (
          <img src={resolveAvatarUrl(AVATAR_KEYS.USER_AVATAR, "用户")} alt="用户"
            className="w-full h-full object-cover" onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
        ) : expertName ? (
          <img src={getAvatarUrl(expertName)} alt={expertName} className="w-full h-full object-cover" />
        ) : (
          <img src={resolveAvatarUrl(AVATAR_KEYS.BOT_AVATAR, "奶昔")} alt="奶昔"
            className="w-full h-full object-cover" onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
        )}
      </div>
      <div className={`max-w-[75%] min-w-0 ${isUser ? "items-end" : "items-start"} flex flex-col relative`}>
        {/* 专家团队模式：显示名称 */}
        {expertName && !isUser && (
          <span className="text-[9px] text-sakura-400 mb-0.5 ml-1">{expertName}</span>
        )}
        {/* 快捷删除按钮：悬浮在气泡右上角，hover 时显示 */}
        {onDelete && (
          <button onClick={() => onDelete(msg.id)}
            title="删除此消息"
            className="absolute -top-1.5 -right-1.5 p-0.5 rounded-full bg-white border border-sakura-100 text-sakura-300 hover:text-red-500 hover:border-red-200 opacity-0 group-hover:opacity-100 transition-opacity z-10 shadow-sm">
            <X size={10} />
          </button>
        )}
        <div className={`rounded-2xl px-4 py-2.5 text-xs leading-relaxed break-words ${
          isUser ? "bg-pink-500 text-white rounded-tr-md" : "bg-sakura-50 text-sakura-700 rounded-tl-md border border-sakura-100"
        }`}>
          {isEmpty && !isUser ? (
            <span className="text-sakura-300 italic">等待响应...</span>
          ) : editing ? (
            <textarea value={editText} onChange={e => setEditText(e.target.value)}
              className="w-full bg-white text-sakura-700 text-xs rounded border border-sakura-200 p-2 resize-none outline-none"
              rows={4} autoFocus />
          ) : msg.content_blocks && msg.content_blocks.length > 0 ? (
            <ContentRenderer blocks={msg.content_blocks} />
          ) : (
            <span className="whitespace-pre-wrap">{displayContent}</span>
          )}
        </div>
        <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[10px] text-sakura-300">{fmtTime(msg.time)}</span>
          {/* 朗读 */}
          {displayContent && (
            <button onClick={toggleSpeak} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title={speaking ? "停止朗读" : "朗读"}>
              {speaking ? <VolumeX size={10} /> : <Volume2 size={10} />}
            </button>
          )}
          {/* 引用回复 */}
          {onReply && (
            <button onClick={() => onReply(msg.id)} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title="回复">
              <Reply size={10} />
            </button>
          )}
          {/* 收藏 */}
          {onStar && (
            <button onClick={() => onStar(msg.id)} className="p-0.5 rounded hover:bg-amber-50 text-sakura-300 hover:text-amber-500" title={starred ? "取消收藏" : "收藏"}>
              <Star size={10} className={starred ? "fill-amber-400 text-amber-400" : ""} />
            </button>
          )}
          {!isUser && (
            <>
              <button onClick={copyText} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title="复制">
                {copied ? <Check size={10} /> : <Copy size={10} />}
              </button>
              {onRegenerate && (
                <button onClick={() => onRegenerate(msg.id)} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title="重新生成">
                  <RotateCcw size={10} />
                </button>
              )}
            </>
          )}
          {isUser && onEdit && !editing && (
            <button onClick={() => { setEditText(msg.content); setEditing(true); }} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title="编辑">
              <Edit3 size={10} />
            </button>
          )}
          {editing && (
            <>
              <button onClick={() => { setEditing(false); }} className="p-0.5 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500" title="取消">
                <X size={10} />
              </button>
              <button onClick={() => { onEdit?.(msg.id, editText); setEditing(false); }} className="p-0.5 rounded hover:bg-green-50 text-green-500" title="保存">
                <Check size={10} />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
