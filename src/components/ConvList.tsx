import { useState } from "react";
import { Search, Plus, MessageCircle, X, Tag, Folder, Clock } from "lucide-react";
import type { ConvItem, MsgItem } from "@/components/ChatTypes";
import { fmtTime, convName } from "@/components/ChatTypes";
import { resolveAvatarUrl, getAvatarUrl, AVATAR_KEYS } from "@/lib/avatar";

const GROUPS_KEY = "naixi_groups";
const TAGS_KEY = "naixi_tags";

function loadList(key: string): Record<string, string[]> {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}

export default function ConvList({
  convs, activeKey, onSelect, onNew, search, onSearchChange, loading, customNames, onDeleteConv,
}: {
  convs: ConvItem[]; activeKey: string | null; onSelect: (k: string) => void; onNew: () => void;
  search: string; onSearchChange: (s: string) => void; loading: boolean;
  customNames: Record<string, string>; onDeleteConv?: (key: string) => void;
}) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const [groups, setGroups] = useState<Record<string, string[]>>(() => loadList(GROUPS_KEY));
  const [tags, setTags] = useState<Record<string, string[]>>(() => loadList(TAGS_KEY));
  const [filterTag, setFilterTag] = useState("");
  const [filterGroup, setFilterGroup] = useState("");
  const [showTagModal, setShowTagModal] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [groupInput, setGroupInput] = useState("");

  const saveGroups = (g: Record<string, string[]>) => { setGroups(g); localStorage.setItem(GROUPS_KEY, JSON.stringify(g)); };
  const saveTags = (t: Record<string, string[]>) => { setTags(t); localStorage.setItem(TAGS_KEY, JSON.stringify(t)); };

  const allGroups = [...new Set(Object.values(groups).flat())];
  const allTags = [...new Set(Object.values(tags).flat())];

  let filtered = convs.filter(c => (customNames[c.key] || convName(c.key)).includes(search) || c.last_msg.includes(search));
  if (filterGroup) filtered = filtered.filter(c => (groups[c.key] || []).includes(filterGroup));
  if (filterTag) filtered = filtered.filter(c => (tags[c.key] || []).includes(filterTag));
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
        {/* 分组/标签过滤器 */}
        {(filterGroup || filterTag || allGroups.length > 0 || allTags.length > 0) && (
          <div className="flex flex-wrap gap-1">
            {filterGroup && <button onClick={() => setFilterGroup("")} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] bg-sakura-100 text-sakura-500"><Folder size={9} /> {filterGroup} <X size={8} /></button>}
            {filterTag && <button onClick={() => setFilterTag("")} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] bg-amber-100 text-amber-600"><Tag size={9} /> {filterTag} <X size={8} /></button>}
            {/* 未筛选时显示所有可用分组/标签供点击筛选 */}
            {!filterGroup && !filterTag && allGroups.slice(0, 5).map(g => (
              <button key={g} onClick={() => setFilterGroup(g)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] bg-sakura-50 text-sakura-400 hover:bg-sakura-100"><Folder size={9} />{g}</button>
            ))}
            {!filterGroup && !filterTag && allTags.slice(0, 8).map(t => (
              <button key={t} onClick={() => setFilterTag(t)} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] bg-amber-50 text-amber-500 hover:bg-amber-100"><Tag size={9} />{t}</button>
            ))}
          </div>
        )}
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
          <div key={c.key} className="group relative"
            onMouseEnter={() => setHoveredKey(c.key)}
            onMouseLeave={() => setHoveredKey(null)}>
            <button onClick={() => onSelect(c.key)}
              className={`w-full text-left px-3 py-2.5 border-b border-sakura-50 transition-colors hover:bg-sakura-50 ${activeKey === c.key ? "bg-sakura-100" : ""}`}
              title={`${customNames[c.key] || convName(c.key)} — ${c.last_msg}`}>
              <div className="flex items-start gap-2">
                {c.key.startsWith("auto:") ? (
                  <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 bg-indigo-100 text-indigo-400">
                    <Clock size={14} />
                  </div>
                ) : (
                <div className="w-8 h-8 rounded-full overflow-hidden shrink-0 bg-sakura-50">
                  <img
                    src={c.last_role === "assistant"
                      ? resolveAvatarUrl(AVATAR_KEYS.BOT_AVATAR, "奶昔")
                      : resolveAvatarUrl(AVATAR_KEYS.USER_AVATAR, "用户")}
                    alt=""
                    className="w-full h-full object-cover"
                    onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                </div>
                )}
                <div className="flex-1 min-w-0 pr-4">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-medium text-sakura-600 truncate">{customNames[c.key] || convName(c.key)}</span>
                    <span className="text-[10px] text-sakura-300 shrink-0">{fmtTime(c.last_time)}</span>
                  </div>
                  <p className="text-[11px] text-sakura-400 truncate mt-0.5">{c.last_msg}</p>
                </div>
              </div>
            </button>
            {onDeleteConv && (
              <div className={`absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5 transition-all duration-150 ${hoveredKey === c.key ? "opacity-100" : "opacity-0"}`}>
                <button onClick={(e) => { e.stopPropagation(); setShowTagModal(c.key); }}
                  className="p-1 rounded-full bg-white border border-sakura-100 text-sakura-300 hover:text-amber-500 shadow-sm" title="标签">
                  <Tag size={9} />
                </button>
                <button onClick={(e) => { e.stopPropagation(); onDeleteConv(c.key); }}
                  className="p-1 rounded-full bg-white border border-sakura-100 text-sakura-300 hover:text-red-500 hover:border-red-200 shadow-sm" title="删除">
                  <X size={9} />
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 标签/分组管理弹窗 */}
      {showTagModal && (
        <div className="fixed inset-0 z-[200] bg-black/30 flex items-center justify-center" onClick={() => setShowTagModal(null)}>
          <div className="bg-white rounded-xl shadow-xl border border-sakura-100 p-4 w-64 mx-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-semibold text-sakura-600">管理标签</span>
              <button onClick={() => setShowTagModal(null)} className="p-0.5 hover:bg-sakura-50 rounded"><X size={12} /></button>
            </div>
            {/* 现有标签 */}
            <div className="flex flex-wrap gap-1 mb-2">
              {(tags[showTagModal] || []).map(t => (
                <span key={t} className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-amber-100 text-amber-600">
                  {t}
                  <button onClick={() => {
                    const next = { ...tags };
                    next[showTagModal] = (next[showTagModal] || []).filter(x => x !== t);
                    saveTags(next);
                  }}><X size={8} /></button>
                </span>
              ))}
            </div>
            {/* 添加标签 */}
            <div className="flex items-center gap-1">
              <input value={tagInput} onChange={e => setTagInput(e.target.value)}
                className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 outline-none"
                placeholder="新标签" onKeyDown={e => {
                  if (e.key === "Enter" && tagInput.trim()) {
                    const next = { ...tags };
                    next[showTagModal] = [...(next[showTagModal] || []), tagInput.trim()];
                    saveTags(next);
                    setTagInput("");
                  }
                }} />
              <button onClick={() => {
                if (tagInput.trim()) {
                  const next = { ...tags };
                  next[showTagModal] = [...(next[showTagModal] || []), tagInput.trim()];
                  saveTags(next);
                  setTagInput("");
                }
              }} className="px-2 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">添加</button>
            </div>
            {/* 分组 */}
            <div className="mt-3 pt-3 border-t border-sakura-100">
              <p className="text-[10px] text-sakura-400 mb-1">分组</p>
              <div className="flex flex-wrap gap-1 mb-1.5">
                {allGroups.map(g => (
                  <button key={g} onClick={() => {
                    const next = { ...groups };
                    const cur = next[showTagModal] || [];
                    if (cur.includes(g)) { next[showTagModal] = cur.filter(x => x !== g); }
                    else { next[showTagModal] = [...cur, g]; }
                    saveGroups(next);
                  }}
                    className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${(groups[showTagModal] || []).includes(g) ? "bg-sakura-200 text-sakura-600" : "bg-sakura-50 text-sakura-400 hover:bg-sakura-100"}`}>
                    <Folder size={9} className="inline mr-0.5" />{g}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1">
                <input value={groupInput} onChange={e => setGroupInput(e.target.value)}
                  className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 outline-none"
                  placeholder="新分组" onKeyDown={e => {
                    if (e.key === "Enter" && groupInput.trim()) {
                      const next = { ...groups };
                      next[showTagModal] = [...(next[showTagModal] || []), groupInput.trim()];
                      saveGroups(next);
                      setGroupInput("");
                    }
                  }} />
                <button onClick={() => {
                  const next = { ...groups };
                  next[showTagModal] = [...(next[showTagModal] || []), groupInput.trim()];
                  saveGroups(next);
                  setGroupInput("");
                }} className="px-2 py-1 rounded text-[10px] bg-gradient-to-br from-purple-400 to-purple-500 text-white">添加</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
