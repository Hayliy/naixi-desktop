import { Layers, Check } from "lucide-react";

export default function ModelSelector({ availableModels, modelKey, onModelChange }: {
  availableModels: { key: string; label: string; provider_id: number }[];
  modelKey: string;
  onModelChange: (key: string) => void;
}) {
  const selected = availableModels.find(m => m.key === modelKey);
  return (
    <div className="relative group">
      <button className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-sakura-50 text-sakura-500 hover:bg-sakura-100 transition-colors">
        <Layers size={10} />
        <span className="max-w-[8rem] truncate">{selected?.label || modelKey}</span>
      </button>
      <div className="absolute top-full left-0 mt-1 z-30 hidden group-hover:block min-w-[12rem] bg-white border border-sakura-100 rounded-xl shadow-lg py-1 max-h-[20rem] overflow-y-auto">
        {availableModels.map(m => (
          <button key={m.key} onClick={() => onModelChange(m.key)}
            className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition-colors ${m.key === modelKey ? "bg-sakura-100 text-sakura-600 font-medium" : "text-sakura-500 hover:bg-sakura-50"}`}>
            {m.key === modelKey && <Check size={10} className="text-sakura-400 shrink-0" />}
            <span>{m.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
