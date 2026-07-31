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

  // 加载 TTS 配置；WebView2 环境下浏览器 speechSynthesis 常不可用，自动降级到语音模型
  useEffect(() => {
    apiGet<{ mode: string }>("/api/config/tts")
      .then(d => {
        const browserOk = typeof window !== "undefined" && !!window.speechSynthesis;
        setTtsMode((browserOk ? d.mode : "api") as "browser" | "api");
      })
      .catch(() => {});
  }, []);

  // 语音模型 API：后端合成音频，按 format 选正确 MIME 播放（修 wav 被当 mp3 解码的静默失败）
  const playByApi = async (text: string) => {
    try {
      const { apiPost } = await import("@/lib/api");
      const res = await apiPost<{ ok: boolean; audio?: string; format?: string; error?: string }>(
        "/api/generate_voice", { text: text.slice(0, 500) }
      );
      if (res.ok && res.audio) {
        const mime = res.format === "wav" ? "audio/wav" : (res.format === "mp3" ? "audio/mpeg" : "audio/mpeg");
        const audio = new Audio(`data:${mime};base64,${res.audio}`);
        audio.onended = () => setSpeaking(false);
        audio.onerror = () => { console.error("[语音] 播放失败（解码/格式错误）"); setSpeaking(false); };
        audio.play().catch(e => { console.error("[语音] 播放被浏览器拒绝:", e); setSpeaking(false); });
        setAudioEl(audio);
        setSpeaking(true);
        return;
      }
      console.error("[语音] 语音模型返回失败:", res.error);
    } catch (e) {
      console.error("[语音] 请求语音模型失败:", e);
    }
    setSpeaking(false);
  };

  // 浏览器 TTS：WebView2 下 speechSynthesis 常无声/报错，自动降级到语音模型
  const playByBrowser = (text: string) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      playByApi(text);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1.0;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => { setSpeaking(false); playByApi(text); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    setSpeaking(true);
  };

  const copyText = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const toggleSpeak = async () => {
    if (speaking) {
      if (ttsMode === "browser") {
        if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel();
      } else if (audioEl) {
        audioEl.pause();
        audioEl.currentTime = 0;
      }
      setSpeaking(false);
      return;
    }
    const text = msg.content;
    if (!text) return;
    if (ttsMode === "browser") playByBrowser(text);
    else playByApi(text);
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
          <AvatarImage src={resolveAvatarUrl(AVATAR_KEYS.USER_AVATAR, "用户")} alt="用户" />
        ) : expertName ? (
          <AvatarImage src={getAvatarUrl(expertName)} alt={expertName} />
        ) : (
          <AvatarImage src={resolveAvatarUrl(AVATAR_KEYS.BOT_AVATAR, "奶昔")} alt="奶昔" />
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

/* 带文字回退的头像组件，监听头像缓存加载完成后自动刷新 */
function AvatarImage({ src: initialSrc, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const handler = () => { setFailed(false); setVersion(v => v + 1); };
    window.addEventListener("avatar-cache-loaded", handler);
    return () => window.removeEventListener("avatar-cache-loaded", handler);
  }, []);
  // 每次缓存更新时重新解析 URL（_avatarMap 可能已变化）
  const src = version === 0 ? initialSrc : getAvatarUrl(alt);
  if (!src || failed) {
    return <span className="text-[9px] font-medium">{alt[0] || "?"}</span>;
  }
  return <img key={version} src={src} alt={alt} className="w-full h-full object-cover"
    onError={() => setFailed(true)} />;
}
