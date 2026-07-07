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
  const [allCats, setAllCats] = useState<{ name: string; count: number }[]>([]);
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

  const load = useCallback(async (keepCats = false) => {
    try {
      const url = `/api/knowledge/list${filterCat ? `?category=${encodeURIComponent(filterCat)}` : ""}`;
      const r = await apiGet<KbData>(url);
      if (r) {
        if (!keepCats && r.categories && !filterCat) setAllCats(r.categories);
        setData(r);
      }
    } catch {}
  }, [filterCat]);

  useEffect(() => { load(); }, [load]);

  const handleSearch = async () => {
    if (!search.trim()) { load(); return; }
    try {
      const r = await apiPost<KbData>("/api/knowledge/search", { query: search });
      if (r) setData({ items: r.items || [], categories: allCats, total: r.total || 0 });
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
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500 flex items-center gap-1">
          <BookOpen size={13} /> 知识库
          <span className="text-sakura-300 font-normal">({data?.total ?? 0})</span>
        </span>
        <div className="flex items-center gap-0.5">
          <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
            <X size={13} />
          </button>
        </div>
      </div>

      {/* 搜索 */}
      <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
        <div className="flex items-center gap-1">
          <input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="搜索知识库..." className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 placeholder:text-sakura-300 outline-none focus:border-sakura-300" />
          <button onClick={handleSearch} className="p-1.5 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
            <Search size={12} />
          </button>
        </div>
      </div>

      {/* 分类过滤 */}
      {allCats.length > 0 && (
        <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
          <div className="flex flex-wrap gap-1">
            <button onClick={() => setFilterCat("")}
              className={`text-[10px] px-2 py-0.5 rounded ${!filterCat ? 'bg-sakura-100 text-sakura-600' : 'text-sakura-400 hover:text-sakura-500'}`}>
              全部
            </button>
            {allCats.map((c, i) => (
              <button key={i} onClick={() => setFilterCat(c.name)}
                className={`text-[10px] px-2 py-0.5 rounded ${filterCat === c.name ? 'bg-sakura-100 text-sakura-600' : 'text-sakura-400 hover:text-sakura-500'}`}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 网页导入 */}
      {showImport && (
        <div className="px-3 py-2 border-b border-sakura-100 shrink-0 bg-sakura-50/50 space-y-1.5">
          <div className="text-[10px] text-sakura-500 font-medium">从网页导入</div>
          <input value={importUrl} onChange={e => setImportUrl(e.target.value)}
            placeholder="https://..." className="w-full px-2 py-1 rounded border border-sakura-100 bg-white text-[10px] text-sakura-600 placeholder:text-sakura-300 outline-none focus:border-sakura-300" />
          <div className="flex items-center gap-1">
            <input value={importCat} onChange={e => setImportCat(e.target.value)}
              placeholder="分类" className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-white text-[10px] text-sakura-600 placeholder:text-sakura-300 outline-none focus:border-sakura-300" />
            <button onClick={handleImportUrl} disabled={loading}
              className="px-2.5 py-1 rounded-lg text-[10px] bg-sakura-100 text-sakura-600 hover:bg-sakura-200 disabled:opacity-50">
              <Globe size={10} className="inline mr-0.5" />导入
            </button>
          </div>
        </div>
      )}

      {/* 添加/编辑表单 */}
      {showAdd && (
        <div className="px-3 py-2 border-b border-sakura-100 shrink-0 bg-sakura-50/50 space-y-1.5">
          <div className="text-[10px] text-sakura-500 font-medium">{editId ? "编辑条目" : "新建条目"}</div>
          <input value={newTitle} onChange={e => setNewTitle(e.target.value)}
            placeholder="标题" className="w-full px-2 py-1 rounded border border-sakura-100 bg-white text-[10px] text-sakura-600 placeholder:text-sakura-300 outline-none focus:border-sakura-300" />
          <textarea value={newContent} onChange={e => setNewContent(e.target.value)}
            placeholder="内容" rows={3} className="w-full px-2 py-1 rounded border border-sakura-100 bg-white text-[10px] text-sakura-600 placeholder:text-sakura-300 resize-none outline-none focus:border-sakura-300" />
          <div className="flex items-center gap-1">
            <input value={newCat} onChange={e => setNewCat(e.target.value)}
              placeholder="分类" className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-white text-[10px] text-sakura-600 placeholder:text-sakura-300 outline-none focus:border-sakura-300" />
            <button onClick={handleSave} disabled={loading}
              className="px-2.5 py-1 rounded-lg text-[10px] bg-sakura-100 text-sakura-600 hover:bg-sakura-200 disabled:opacity-50">
              <Check size={10} className="inline mr-0.5" />{editId ? "更新" : "添加"}
            </button>
          </div>
        </div>
      )}

      {/* 操作按钮（参考 ResourcePanel 的虚线添加按钮） */}
      <div className="px-3 py-1.5 border-b border-sakura-100 shrink-0 space-y-1.5">
        {!showAdd && !showImport && (
          <div className="flex gap-1.5">
            <button onClick={() => { setShowAdd(true); setShowImport(false); setEditId(null); setNewTitle(""); setNewContent(""); }}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
              <Plus size={10} /> 添加条目
            </button>
            <button onClick={() => { setShowImport(true); setShowAdd(false); }}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
              <Globe size={10} /> 网页导入
            </button>
          </div>
        )}
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto min-h-0 px-3 py-3 space-y-2 text-xs">
        {items.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-sakura-300">
            {search ? "未找到匹配的知识" : "知识库为空，点击上方按钮添加"}
          </div>
        ) : items.map(item => (
          <div key={item.id} className="bg-sakura-50 rounded-lg p-3 border border-sakura-100 group">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1 space-y-0.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] font-medium text-sakura-600 truncate max-w-[10rem]">{item.title}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-white text-sakura-400 border border-sakura-100 shrink-0">{item.category}</span>
                  {item.source_url && <span title={item.source_url}><Globe size={9} className="text-sakura-300 shrink-0" /></span>}
                </div>
                {item.content && (
                  <p className="text-[10px] text-sakura-400 leading-relaxed line-clamp-2">{item.content}</p>
                )}
              </div>
              <div className="flex items-center gap-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => handleEdit(item)}
                  className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-white/50">
                  <Edit3 size={11} />
                </button>
                <button onClick={() => handleDelete(item.id)}
                  className="p-1 rounded text-sakura-300 hover:text-red-400 hover:bg-red-50">
                  <Trash2 size={11} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
