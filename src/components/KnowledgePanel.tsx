import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { BookOpen, Plus, Search, X, Trash2, ChevronDown } from "lucide-react";

interface KnowledgeItem {
  id: string;
  title: string;
  content: string;
  category: string;
  created_at: string;
}

interface KbData {
  items: KnowledgeItem[];
  categories: { name: string; count: number }[];
  total: number;
}

export default function KnowledgePanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<KbData | null>(null);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newCat, setNewCat] = useState("默认");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const url = `/api/knowledge/list${filterCat ? `?category=${encodeURIComponent(filterCat)}` : ""}`;
      const r = await apiGet<KbData>(url);
      if (r) setData(r);
    } catch {}
  }, [filterCat]);

  useEffect(() => { load(); }, [load]);

  const handleSearch = async () => {
    if (!search.trim()) { load(); return; }
    try {
      const r = await apiPost<KbData>("/api/knowledge/search", { query: search });
      if (r) setData({ items: r.items || [], categories: data?.categories || [], total: r.total || 0 });
    } catch {}
  };

  const handleAdd = async () => {
    if (!newTitle.trim()) return;
    setLoading(true);
    try {
      await apiPost("/api/knowledge/add", { title: newTitle, content: newContent, category: newCat || "默认" });
      setNewTitle(""); setNewContent(""); setShowAdd(false);
      await load();
    } catch {}
    setLoading(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiPost("/api/knowledge/delete", { id });
      await load();
    } catch {}
  };

  const items = data?.items ?? [];
  const cats = data?.categories ?? [];

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100">
        <span className="text-xs font-semibold text-sakura-600 flex items-center gap-1">
          <BookOpen size={13} /> 知识库
          <span className="text-sakura-300 font-normal">({data?.total ?? 0})</span>
        </span>
        <button onClick={() => setShowAdd(!showAdd)} className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
          <Plus size={13} />
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 py-2 border-b border-sakura-50">
        <div className="flex gap-1">
          <input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="搜索知识库..." className="flex-1 text-[10px] px-2 py-1 border border-sakura-100 rounded-md outline-none focus:border-sakura-300" />
          <button onClick={handleSearch} className="px-2 py-1 rounded text-[10px] bg-sakura-100 text-sakura-500 hover:bg-sakura-200">
            <Search size={11} />
          </button>
        </div>
      </div>

      {/* 分类过滤 */}
      {cats.length > 0 && (
        <div className="px-3 py-1.5 border-b border-sakura-50 flex gap-1 flex-wrap">
          <button onClick={() => setFilterCat("")}
            className={`text-[9px] px-1.5 py-0.5 rounded ${!filterCat ? 'bg-sakura-200 text-sakura-600' : 'bg-sakura-50 text-sakura-400 hover:bg-sakura-100'}`}>
            全部
          </button>
          {cats.map((c, i) => (
            <button key={i} onClick={() => setFilterCat(c.name)}
              className={`text-[9px] px-1.5 py-0.5 rounded ${filterCat === c.name ? 'bg-sakura-200 text-sakura-600' : 'bg-sakura-50 text-sakura-400 hover:bg-sakura-100'}`}>
              {c.name} ({c.count})
            </button>
          ))}
        </div>
      )}

      {/* 添加表单 */}
      {showAdd && (
        <div className="px-3 py-2 border-b border-sakura-50 space-y-1.5">
          <input value={newTitle} onChange={e => setNewTitle(e.target.value)}
            placeholder="标题" className="w-full text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
          <textarea value={newContent} onChange={e => setNewContent(e.target.value)}
            placeholder="内容" rows={3} className="w-full text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300 resize-none" />
          <div className="flex gap-1">
            <input value={newCat} onChange={e => setNewCat(e.target.value)}
              placeholder="分类" className="flex-1 text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
            <button onClick={handleAdd} disabled={loading}
              className="px-3 py-1 text-[10px] rounded bg-sakura-200 text-sakura-600 hover:bg-sakura-300 disabled:opacity-50">
              添加
            </button>
          </div>
        </div>
      )}

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-[10px] text-sakura-300">
            {search ? "未找到匹配的知识" : "知识库为空，点击 + 添加"}
          </div>
        ) : items.map(item => (
          <div key={item.id} className="px-3 py-2 border-b border-sakura-50 hover:bg-sakura-50/30 group">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-medium text-sakura-700 truncate">{item.title}</span>
                  <span className="text-[8px] px-1 py-0.5 rounded bg-sakura-50 text-sakura-400 shrink-0">{item.category}</span>
                </div>
                {item.content && (
                  <p className="text-[9px] text-sakura-400 mt-0.5 line-clamp-2">{item.content}</p>
                )}
              </div>
              <button onClick={() => handleDelete(item.id)}
                className="shrink-0 p-0.5 rounded text-sakura-200 hover:text-red-400 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity">
                <Trash2 size={11} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
