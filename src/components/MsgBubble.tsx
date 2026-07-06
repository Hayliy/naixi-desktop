import { useState, useEffect } from "react";
import { Bot, User, Copy, Check, RotateCcw, Edit3, X, Volume2, VolumeX } from "lucide-react";
import ContentRenderer from "@/components/ContentRenderer";
import type { MsgItem } from "@/components/ChatTypes";
import { fmtTime } from "@/components/ChatTypes";
import { apiGet } from "@/lib/api";

export default function MsgBubble({ msg, onEdit, onRegenerate, onDelete }: {
  msg: MsgItem; onEdit?: (id: number, text: string) => void; onRegenerate?: (id: number) => void; onDelete?: (id: number) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsMode, setTtsMode] = useState<"browser" | "api">("browser");
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null);

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
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${isUser ? "bg-pink-100 text-pink-500" : "bg-sakura-100 text-sakura-500"}`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>
      <div className={`max-w-[75%] min-w-0 ${isUser ? "items-end" : "items-start"} flex flex-col relative`}>
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
          ) : msg.content_blocks && msg.content_blocks.length > 0 ? (
            <ContentRenderer blocks={msg.content_blocks} />
          ) : (
            <span className="whitespace-pre-wrap">{displayContent}</span>
          )}
        </div>
        <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[10px] text-sakura-300">{fmtTime(msg.time)}</span>
          {/* 朗读按钮：所有消息都可用 */}
          {displayContent && (
            <button onClick={toggleSpeak} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title={speaking ? "停止朗读" : "朗读"}>
              {speaking ? <VolumeX size={10} /> : <Volume2 size={10} />}
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
          {isUser && onEdit && (
            <button onClick={() => onEdit(msg.id, msg.content)} className="p-0.5 rounded hover:bg-sakura-50 text-sakura-300 hover:text-sakura-500" title="编辑">
              <Edit3 size={10} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
