import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { BookOpen, Plus, Search, X, Trash2, Edit3, Globe, Check, FileText } from "lucide-react";

interface KnowledgeItem {
  id: string;
  title: string;
  content: string;
  category: string;
  source_url?: string;
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
  const [editId, setEditId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newCat, setNewCat] = useState("默认");
  const [importUrl, setImportUrl] = useState("");
  const [importCat, setImportCat] = useState("网页导入");
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

  const resetAddForm = () => {
    setNewTitle(""); setNewContent(""); setNewCat("默认"); setEditId(null); setShowAdd(false);
  };

  const handleSave = async () => {
    if (!newTitle.trim()) return;
    setLoading(true);
    try {
      if (editId) {
        await apiPost("/api/knowledge/update", { id: editId, title: newTitle, content: newContent, category: newCat || "默认" });
      } else {
        await apiPost("/api/knowledge/add", { title: newTitle, content: newContent, category: newCat || "默认" });
      }
      resetAddForm();
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

  const handleEdit = (item: KnowledgeItem) => {
    setEditId(item.id);
    setNewTitle(item.title);
    setNewContent(item.content);
    setNewCat(item.category);
    setShowAdd(true);
    setShowImport(false);
  };

  const handleImportUrl = async () => {
    if (!importUrl.trim()) return;
    setLoading(true);
    try {
      await apiPost("/api/knowledge/import-url", { url: importUrl, category: importCat || "网页导入" });
      setImportUrl(""); setShowImport(false);
      await load();
    } catch (e: any) { alert("导入失败: " + (e?.message || "未知错误")); }
    setLoading(false);
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
        <div className="flex items-center gap-0.5">
          <button onClick={() => { setShowImport(!showImport); setShowAdd(false); }} title="从网页导入"
            className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
            <Globe size={12} />
          </button>
          <button onClick={() => { setShowAdd(!showAdd); setShowImport(false); setEditId(null); setNewTitle(""); setNewContent(""); }}
            className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
            <Plus size={13} />
          </button>
        </div>
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

      {/* 网页导入 */}
      {showImport && (
        <div className="px-3 py-2 border-b border-sakura-50 space-y-1.5 bg-blue-50/30">
          <div className="text-[9px] text-sakura-500 font-medium">从网页导入</div>
          <input value={importUrl} onChange={e => setImportUrl(e.target.value)}
            placeholder="https://..." className="w-full text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
          <div className="flex gap-1">
            <input value={importCat} onChange={e => setImportCat(e.target.value)}
              placeholder="分类" className="flex-1 text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
            <button onClick={handleImportUrl} disabled={loading}
              className="px-3 py-1 text-[10px] rounded bg-blue-100 text-blue-600 hover:bg-blue-200 disabled:opacity-50">
              <Globe size={10} className="inline mr-0.5" />导入
            </button>
          </div>
        </div>
      )}

      {/* 添加/编辑表单 */}
      {showAdd && (
        <div className="px-3 py-2 border-b border-sakura-50 space-y-1.5">
          <div className="text-[9px] text-sakura-500 font-medium">{editId ? "编辑条目" : "新建条目"}</div>
          <input value={newTitle} onChange={e => setNewTitle(e.target.value)}
            placeholder="标题" className="w-full text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
          <textarea value={newContent} onChange={e => setNewContent(e.target.value)}
            placeholder="内容" rows={3} className="w-full text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300 resize-none" />
          <div className="flex gap-1">
            <input value={newCat} onChange={e => setNewCat(e.target.value)}
              placeholder="分类" className="flex-1 text-[10px] px-2 py-1 border border-sakura-100 rounded outline-none focus:border-sakura-300" />
            <button onClick={handleSave} disabled={loading}
              className="px-3 py-1 text-[10px] rounded bg-sakura-200 text-sakura-600 hover:bg-sakura-300 disabled:opacity-50">
              <Check size={10} className="inline mr-0.5" />{editId ? "更新" : "添加"}
            </button>
          </div>
        </div>
      )}

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-[10px] text-sakura-300">
            {search ? "未找到匹配的知识" : "知识库为空，点 + 添加"}
          </div>
        ) : items.map(item => (
          <div key={item.id} className="px-3 py-2 border-b border-sakura-50 hover:bg-sakura-50/30 group">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-medium text-sakura-700 truncate">{item.title}</span>
                  <span className="text-[8px] px-1 py-0.5 rounded bg-sakura-50 text-sakura-400 shrink-0">{item.category}</span>
                  {item.source_url && <span title={item.source_url}><Globe size={8} className="text-sakura-300 shrink-0" /></span>}
                </div>
                {item.content && (
                  <p className="text-[9px] text-sakura-400 mt-0.5 line-clamp-2">{item.content}</p>
                )}
              </div>
              <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => handleEdit(item)}
                  className="p-0.5 rounded text-sakura-200 hover:text-sakura-500 hover:bg-sakura-50">
                  <Edit3 size={10} />
                </button>
                <button onClick={() => handleDelete(item.id)}
                  className="p-0.5 rounded text-sakura-200 hover:text-red-400 hover:bg-red-50">
                  <Trash2 size={10} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
