import { useState } from "react";
import { Bot, User, Copy, Check, RotateCcw, Edit3 } from "lucide-react";
import ContentRenderer from "@/components/ContentRenderer";
import type { MsgItem } from "@/components/ChatTypes";
import { fmtTime } from "@/components/ChatTypes";

export default function MsgBubble({ msg, onEdit, onRegenerate }: {
  msg: MsgItem; onEdit?: (id: number, text: string) => void; onRegenerate?: (id: number) => void;
}) {
  const [copied, setCopied] = useState(false);

  const copyText = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const isUser = msg.role === "user";
  const hasContentBlocks = (msg.content_blocks || []).length > 0;
  // 无内容且无内容块时，返回 null 不渲染
  if (!msg.content && !hasContentBlocks && !isUser) return null;

  return (
    <div className={`flex items-start gap-2 px-3 py-3 group ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${isUser ? "bg-pink-100 text-pink-500" : "bg-sakura-100 text-sakura-500"}`}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>
      <div className={`max-w-[75%] min-w-0 ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div className={`rounded-2xl px-4 py-2.5 text-xs leading-relaxed break-words ${
          isUser ? "bg-pink-500 text-white rounded-tr-md" : "bg-sakura-50 text-sakura-700 rounded-tl-md border border-sakura-100"
        }`}>
          {msg.content_blocks && msg.content_blocks.length > 0 ? (
            <ContentRenderer blocks={msg.content_blocks} />
          ) : (
            <span className="whitespace-pre-wrap">{msg.content}</span>
          )}
        </div>
        <div className="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[10px] text-sakura-300">{fmtTime(msg.time)}</span>
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
