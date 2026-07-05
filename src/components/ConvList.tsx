import { useState } from "react";
import { Search, Plus, MessageCircle, Bot, User } from "lucide-react";
import type { ConvItem, MsgItem } from "@/components/ChatTypes";
import { fmtTime, convName } from "@/components/ChatTypes";

export default function ConvList({
  convs, activeKey, onSelect, onNew, search, onSearchChange, loading, customNames,
}: {
  convs: ConvItem[]; activeKey: string | null; onSelect: (k: string) => void; onNew: () => void;
  search: string; onSearchChange: (s: string) => void; loading: boolean;
  customNames: Record<string, string>;
}) {
  const filtered = convs.filter(c => (customNames[c.key] || convName(c.key)).includes(search) || c.last_msg.includes(search));
  return (
    <div className="w-64 min-w-[16rem] border-r border-sakura-100 bg-white flex flex-col">
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
