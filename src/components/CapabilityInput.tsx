import { useState, useEffect, useRef } from "react";
import { QUICK_ACTIONS } from "@/components/ChatTypes";

export default function CapabilityInput({ action, config, onSend, onClose }: {
  action: typeof QUICK_ACTIONS[number];
  config: any;
  onSend: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(action.template);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
