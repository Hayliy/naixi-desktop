import { useState, useEffect, useRef } from "react";
import { Send, Square, Mic, MicOff, ImageIcon, Video, Music, Code, Globe } from "lucide-react";

export default function ChatInput({ onSend, streaming, onStop, onCapabilityClick }: {
  onSend: (text: string) => void; streaming: boolean; onStop: () => void; onCapabilityClick?: (a: any) => void;
}) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);

  const handleSend = () => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const sendRef = useRef(handleSend);
  sendRef.current = handleSend;

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        sendRef.current();
      }
    };
    el.addEventListener("keydown", handler);
    return () => el.removeEventListener("keydown", handler);
  }, []);

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
        let transcript = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          if (e.results[i].isFinal) transcript += e.results[i][0].transcript;
        }
        if (transcript) setText(prev => (prev ? prev + transcript : transcript));
      };
      rec.onerror = () => setListening(false);
      rec.onend = () => setListening(false);
      rec.start();
      recognitionRef.current = rec;
      setListening(true);
    } catch { setListening(false); }
  };

  const stopListening = () => {
    try { recognitionRef.current?.stop(); } catch {}
    setListening(false);
  };

  const QUICK_ACTIONS = [
    { icon: ImageIcon, label: "画图", color: "text-pink-500", bg: "bg-pink-50", template: "画一张" },
    { icon: Video, label: "视频", color: "text-sakura-500", bg: "bg-sakura-50", template: "生成一段视频：" },
    { icon: Music, label: "语音", color: "text-blue-500", bg: "bg-blue-50", template: "用语音说：" },
    { icon: Code, label: "代码", color: "text-green-500", bg: "bg-green-50", template: "写一段代码：" },
    { icon: Globe, label: "搜索", color: "text-amber-500", bg: "bg-amber-50", template: "搜索一下：" },
  ];

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  };

  return (
    <div className="p-3 border-t border-sakura-100 bg-white/80 backdrop-blur-sm">
      <div className="flex items-center gap-1 mb-2 px-0.5">
        {QUICK_ACTIONS.map((a, i) => (
          <button key={i} onClick={() => onCapabilityClick?.(a)}
            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] ${a.color} ${a.bg} hover:opacity-80 transition-opacity`}>
            <a.icon size={11} />
            <span>{a.label}</span>
          </button>
        ))}
      </div>

      <div className="flex items-end gap-2">
        <textarea ref={inputRef}
          className="flex-1 max-h-[150px] px-3 py-2 rounded-xl border border-sakura-100 text-xs text-sakura-600 bg-sakura-50/50 resize-none outline-none focus:ring-1 focus:ring-sakura-300 placeholder:text-sakura-300 leading-relaxed"
          placeholder="输入消息..."
          value={text} onChange={e => { setText(e.target.value); autoResize(e.target); }}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !(e.ctrlKey || e.metaKey)) { /* Enter换行 */ } }}
          rows={1} />

        {listening ? (
          <button onClick={stopListening}
            className="w-9 h-9 rounded-xl bg-red-500 flex items-center justify-center shrink-0 animate-pulse">
            <MicOff size={14} className="text-white" />
          </button>
        ) : (
          <button onClick={startListening}
            className="w-9 h-9 rounded-xl bg-sakura-50 border border-sakura-100 flex items-center justify-center shrink-0 hover:bg-sakura-100 transition-colors">
            <Mic size={14} className="text-sakura-400" />
          </button>
        )}

        {streaming ? (
          <button onClick={onStop}
            className="w-9 h-9 rounded-xl bg-red-500 flex items-center justify-center shrink-0 hover:bg-red-600 transition-colors">
            <Square size={12} className="text-white" />
          </button>
        ) : (
          <button onClick={handleSend} disabled={!text.trim()}
            className="w-9 h-9 rounded-xl bg-gradient-to-br from-sakura-400 to-sakura-200 flex items-center justify-center shrink-0 disabled:opacity-40 hover:shadow-md transition-shadow">
            <Send size={14} className="text-white" />
          </button>
        )}
      </div>
      <div className="flex items-center justify-between mt-1 px-1">
        <span className="text-[9px] text-sakura-300">Enter 换行 · Ctrl+Enter 发送</span>
      </div>
    </div>
  );
}
