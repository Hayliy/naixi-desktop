import { useState } from "react";
import { Copy, Check, ChevronDown, ChevronRight, Loader2, File, Play, Music, Image as ImageIcon, Wrench } from "lucide-react";

/* ─── 内容块类型 ─── */
export interface ContentBlock {
  type: "text" | "code" | "image" | "video" | "audio" | "file" | "tool_use" | "tool_result" | "reasoning" | "status";
  text?: string;
  language?: string;
  url?: string;
  base64?: string;
  mime_type?: string;
  name?: string;
  args?: Record<string, unknown>;
  id?: string;
  tool_call_id?: string;
  content?: string;
  icon?: string;
  state?: "loading" | "done" | "error";
  size?: number;
}

/* ─── text (支持简易 Markdown) ─── */
function TextBlock({ text }: { text: string }) {
  if (!text) return null;
  const lines = text.split("\n");
  return (
    <div className="text-xs leading-relaxed whitespace-pre-wrap [&_strong]:font-semibold [&_strong]:text-sakura-700 [&_em]:italic [&_code]:bg-sakura-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[11px] [&_code]:font-mono [&_a]:text-lavender-600 [&_a]:underline [&_a:hover]:text-lavender-800 [&_hr]:border-sakura-100 [&_hr]:my-2 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_blockquote]:border-l-2 [&_blockquote]:border-lavender-300 [&_blockquote]:pl-3 [&_blockquote]:text-sakura-400 [&_blockquote]:italic [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-sakura-600 [&_h2]:text-xs [&_h2]:font-semibold [&_h2]:text-sakura-500 [&_h3]:text-xs [&_h3]:font-medium [&_h3]:text-sakura-500 [&_p]:my-1">
      {lines.map((line, i) => {
        // 标题
        if (line.startsWith("### ")) return <h3 key={i}>{renderInline(line.slice(4))}</h3>;
        if (line.startsWith("## ")) return <h2 key={i}>{renderInline(line.slice(3))}</h2>;
        if (line.startsWith("# ")) return <h1 key={i}>{renderInline(line.slice(2))}</h1>;
        // 分割线
        if (/^[-*]{3,}$/.test(line.trim())) return <hr key={i} />;
        // 引用
        if (line.startsWith("> ")) return <blockquote key={i}>{renderInline(line.slice(2))}</blockquote>;
        // 无序列表
        if (/^[-*]\s/.test(line)) return <li key={i} className="list-disc ml-4">{renderInline(line.replace(/^[-*]\s/, ""))}</li>;
        // 有序列表
        if (/^\d+\.\s/.test(line)) return <li key={i} className="list-decimal ml-4">{renderInline(line.replace(/^\d+\.\s/, ""))}</li>;
        // 空行
        if (!line.trim()) return <br key={i} />;
        // 普通段落
        return <p key={i} className="my-0.5">{renderInline(line)}</p>;
      })}
    </div>
  );
}

/** 行内渲染：**加粗**、*斜体*、`代码`、[链接](url) */
function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let idx = 0;
  while (remaining.length > 0) {
    // 链接 [text](url)
    const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/);
    if (linkMatch) {
      parts.push(<a key={idx++} href={linkMatch[2]} target="_blank" rel="noopener noreferrer">{linkMatch[1]}</a>);
      remaining = remaining.slice(linkMatch[0].length);
      continue;
    }
    // 行内代码 `code`
    const codeMatch = remaining.match(/^`([^`]+)`/);
    if (codeMatch) {
      parts.push(<code key={idx++}>{codeMatch[1]}</code>);
      remaining = remaining.slice(codeMatch[0].length);
      continue;
    }
    // 加粗 **text**
    const boldMatch = remaining.match(/^\*\*([^*]+)\*\*/);
    if (boldMatch) {
      parts.push(<strong key={idx++}>{boldMatch[1]}</strong>);
      remaining = remaining.slice(boldMatch[0].length);
      continue;
    }
    // 斜体 *text*
    const italicMatch = remaining.match(/^\*([^*]+)\*/);
    if (italicMatch) {
      parts.push(<em key={idx++}>{italicMatch[1]}</em>);
      remaining = remaining.slice(italicMatch[0].length);
      continue;
    }
    // 普通字符
    parts.push(remaining[0]);
    remaining = remaining.slice(1);
  }
  return <>{parts}</>;
}

/* ─── code ─── */
function CodeBlock({ text, language }: { text: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <div className="my-1 rounded-lg overflow-hidden border border-sakura-100">
      <div className="flex items-center justify-between px-3 py-1.5 bg-sakura-50 text-[10px] text-sakura-400">
        <span>{language || "code"}</span>
        <button onClick={handleCopy} className="flex items-center gap-1 hover:text-sakura-600 transition-colors">
          {copied ? <Check size={11} /> : <Copy size={11} />}
          <span>{copied ? "已复制" : "复制"}</span>
        </button>
      </div>
      <pre className="p-3 text-xs font-mono leading-relaxed overflow-x-auto bg-[#1a1a2e] text-sakura-50 m-0">
        <code>{text}</code>
      </pre>
    </div>
  );
}

/* ─── image ─── */
function ImageBlock({ url, base64, mime_type }: { url?: string; base64?: string; mime_type?: string }) {
  const src = url || (base64 ? `data:${mime_type || "image/png"};base64,${base64}` : "");
  if (!src) return null;
  return (
    <div className="my-1 rounded-lg overflow-hidden border border-sakura-100">
      <img src={src} alt="chat image" className="max-w-full max-h-80 object-contain" loading="lazy" />
    </div>
  );
}

/* ─── file ─── */
function FileBlock({ name, size }: { name?: string; size?: number }) {
  return (
    <div className="my-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-sakura-100 bg-sakura-50 text-xs">
      <File size={14} className="text-sakura-400 shrink-0" />
      <span className="text-sakura-600 truncate flex-1">{name || "文件"}</span>
      {size ? <span className="text-sakura-300 text-[10px]">{(size / 1024).toFixed(1)} KB</span> : null}
    </div>
  );
}

/* ─── audio ─── */
function AudioBlock({ url, base64, mime_type }: { url?: string; base64?: string; mime_type?: string }) {
  const src = url || (base64 ? `data:${mime_type || "audio/mp3"};base64,${base64}` : "");
  if (!src) return null;
  return (
    <div className="my-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-sakura-100 bg-sakura-50">
      <Music size={14} className="text-sakura-400 shrink-0" />
      <audio src={src} controls className="h-8 flex-1" />
    </div>
  );
}

/* ─── video ─── */
function VideoBlock({ url, base64, mime_type }: { url?: string; base64?: string; mime_type?: string }) {
  const src = url || (base64 ? `data:${mime_type || "video/mp4"};base64,${base64}` : "");
  if (!src) return null;
  return (
    <div className="my-1 rounded-lg overflow-hidden border border-sakura-100">
      <video src={src} controls className="max-w-full max-h-80" />
    </div>
  );
}

/* ─── reasoning ─── */
function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="my-1">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1 text-[10px] text-sakura-400 hover:text-sakura-500 transition-colors">
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <span>{open ? "收起思考过程" : "展开思考过程"}</span>
      </button>
      {open && (
        <div className="mt-1 px-3 py-2 rounded-lg bg-sakura-50 border border-sakura-100 text-[11px] text-sakura-400 italic whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  );
}

/* ─── tool_use ─── */
function ToolUseBlock({ name, args, state }: { name: string; args?: Record<string, unknown>; state?: "loading" | "done" | "error" }) {
  const isRunning = state === "loading" || !state;
  const isError = state === "error";
  
  // 工具分类图标
  const toolIcon = (() => {
    if (name.includes("file") || name.includes("read") || name.includes("write") || name.includes("edit") || name.includes("delete") || name.includes("copy") || name.includes("move")) return <File size={11} />;
    if (name.includes("search") || name.includes("web") || name.includes("fetch")) return <File size={11} />;
    if (name.includes("image") || name.includes("video") || name.includes("voice") || name.includes("code")) return <File size={11} />;
    if (name.includes("plan") || name.includes("task")) return <File size={11} />;
    if (name.includes("run") || name.includes("execute") || name.includes("powershell")) return <File size={11} />;
    return <Wrench size={11} />;
  })();

  const bgColor = isError ? "border-red-100 bg-red-50" : isRunning ? "border-lavender-100 bg-lavender-50" : "border-green-100 bg-green-50";
  const textColor = isError ? "text-red-600" : isRunning ? "text-lavender-600" : "text-green-700";

  return (
    <div className={`my-1 rounded-lg border overflow-hidden ${bgColor}`}>
      <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] ${textColor}">
        {isRunning ? <Loader2 size={11} className="animate-spin" /> : isError ? <span className="w-[11px] h-[11px] flex items-center justify-center text-[10px] font-bold bg-red-100 rounded-full">!</span> : <Check size={11} />}
        <span className="font-medium">{name}</span>
        {args && Object.keys(args).length > 0 && (
          <span className="text-sakura-400 ml-auto text-[10px] truncate max-w-[200px]">
            {JSON.stringify(args).slice(0, 80)}{JSON.stringify(args).length > 80 ? "..." : ""}
          </span>
        )}
      </div>
      {isError && (
        <div className="px-3 py-1.5 text-[10px] text-red-500 bg-red-50 border-t border-red-100 font-mono">
          工具执行失败，LLM 将尝试其他方案
        </div>
      )}
    </div>
  );
}

/* ─── tool_result ─── */
function ToolResultBlock({ content }: { content?: string }) {
  if (!content) return null;
  const isError = content.startsWith("【工具报错】");
  return (
    <div className={`my-1 px-3 py-1.5 rounded-lg border overflow-hidden ${isError ? "border-red-100 bg-red-50" : "border-green-100 bg-green-50"}`}>
      <div className="flex items-center gap-1 mb-0.5">
        {isError ? (
          <span className="w-[11px] h-[11px] flex items-center justify-center text-[10px] font-bold text-red-500">!</span>
        ) : (
          <Check size={11} className="text-green-600" />
        )}
        <span className={`text-[11px] font-medium ${isError ? "text-red-600" : "text-green-700"}`}>
          {isError ? "工具出错" : "工具返回"}
        </span>
      </div>
      <pre className={`text-[10px] mt-0.5 whitespace-pre-wrap font-mono overflow-x-auto ${isError ? "text-red-500" : "text-green-600"}`}>
        {content.slice(0, 300)}{content.length > 300 ? "\n...(内容过长已截断)" : ""}
      </pre>
    </div>
  );
}

/* ─── status ─── */
function StatusBlock({ text, state }: { text?: string; state?: "loading" | "done" | "error" }) {
  const colorMap = { loading: "text-blue-500", done: "text-green-500", error: "text-red-500" };
  const iconMap = { loading: <Loader2 size={11} className="animate-spin" />, done: <Check size={11} />, error: <span className="w-[11px] h-[11px] flex items-center justify-center text-[10px] font-bold">!</span> };
  return (
    <div className={`my-1 flex items-center gap-1.5 text-[11px] ${colorMap[state || "loading"] || "text-sakura-400"}`}>
      {iconMap[state || "loading"]}
      <span>{text || "处理中..."}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════
   ContentRenderer — 遍历内容块逐个渲染
   ═══════════════════════════════════════════ */
export default function ContentRenderer({ blocks }: { blocks: ContentBlock[] }) {
  if (!blocks || blocks.length === 0) return null;
  return (
    <>
      {blocks.map((block, i) => {
        switch (block.type) {
          case "text": return <TextBlock key={i} text={block.text || ""} />;
          case "code": return <CodeBlock key={i} text={block.text || ""} language={block.language} />;
          case "image": return <ImageBlock key={i} url={block.url} base64={block.base64} mime_type={block.mime_type} />;
          case "video": return <VideoBlock key={i} url={block.url} base64={block.base64} mime_type={block.mime_type} />;
          case "audio": return <AudioBlock key={i} url={block.url} base64={block.base64} mime_type={block.mime_type} />;
          case "file": return <FileBlock key={i} name={block.name} size={block.size} />;
          case "reasoning": return <ReasoningBlock key={i} text={block.text || ""} />;
          case "tool_use": return <ToolUseBlock key={i} name={block.name || ""} args={block.args} state={block.state} />;
          case "tool_result": return <ToolResultBlock key={i} content={block.content} />;
          case "status": return <StatusBlock key={i} text={block.text} state={block.state} />;
          default: return <TextBlock key={i} text={JSON.stringify(block)} />;
        }
      })}
    </>
  );
}
