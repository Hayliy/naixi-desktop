import { useState, useEffect, useRef } from "react";
import { Send, Square, Mic, MicOff, ImageIcon, Video, Music, Code, Globe } from "lucide-react";
import { loadShortcuts, comboMatches, onShortcutsChanged, type ShortcutItem } from "@/lib/shortcuts";

export default function ChatInput({ onSend, streaming, onStop, onCapabilityClick, lastUserMsg }: {
  onSend: (text: string) => void; streaming: boolean; onStop: () => void;
  onCapabilityClick?: (a: any) => void; lastUserMsg?: string;
}) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [sc, setSc] = useState<ShortcutItem[]>(() => loadShortcuts());
  const scRef = useRef(sc);
  const lastUserRef = useRef(lastUserMsg);
  lastUserRef.current = lastUserMsg;
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

  // 快捷键配置：改键即刻生效（设置面板保存后广播 naixi-shortcuts-changed）
  useEffect(() => onShortcutsChanged(() => {
    const n = loadShortcuts();
    scRef.current = n;
    setSc(n);
  }), []);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const caret = (pos: number) => requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = pos;
      autoResize(el);
    });

    const handler = (e: KeyboardEvent) => {
      const get = (desc: string) => scRef.current.find(s => s.desc === desc)?.key || "";
      // 发送消息（默认 Ctrl+Enter）
      const ks = get("发送消息");
      if (ks && comboMatches(e, ks)) { e.preventDefault(); sendRef.current(); return; }
      // 上一条消息（默认 ↑）：光标在输入开头时回填上一条用户消息
      const kp = get("上一条消息");
      if (kp && comboMatches(e, kp)) {
        if (el.selectionStart === 0 && el.selectionEnd === 0 && lastUserRef.current) {
          e.preventDefault();
          const v = lastUserRef.current;
          setText(v);
          caret(v.length);
        }
        return; // 未命中回填条件时保留 ↑ 的原生光标移动
      }
      // 换行（默认 Enter，textarea 原生行为）：键位被改成非 Enter 时手动插入换行；
      // 此时普通 Enter 不再是换行键，需阻止原生换行，避免两个键都能换行。
      const kn = get("换行");
      if (kn && kn !== "Enter") {
        if (comboMatches(e, kn)) {
          e.preventDefault();
          const s0 = el.selectionStart ?? 0, e0 = el.selectionEnd ?? 0;
          setText(prev => prev.slice(0, s0) + "\n" + prev.slice(e0));
          caret(s0 + 1);
          return;
        }
        if (e.key === "Enter") { e.preventDefault(); return; }
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

  const k = (desc: string) => sc.find(s => s.desc === desc)?.key || "";

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
        {/* 按当前配置动态显示（改键后随之更新），不再写死「Enter 换行 · Ctrl+Enter 发送」 */}
        <span className="text-[9px] text-sakura-300">
          {k("换行") || "Enter"} 换行 · {k("发送消息") || "Ctrl+Enter"} 发送 · {k("上一条消息") || "↑"} 上一条
        </span>
      </div>
    </div>
  );
}
