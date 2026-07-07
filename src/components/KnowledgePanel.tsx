import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { BookOpen, Plus, Search, X, Trash2, Edit3, Globe, Check } from "lucide-react";
import { useToast } from "@/components/Toast";

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
  const { notify } = useToast();
  const [data, setData] = useState<KbData | null>(null);
  const [allCats, setAllCats] = useState<{ name: string; count: number }[]>([]);
  const [search, setSearch] = useState("");
  const [filterCat, setFilterCat] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [fTitle, setFTitle] = useState("");
  const [fContent, setFContent] = useState("");
  const [fCat, setFCat] = useState("默认");
  const [importUrl, setImportUrl] = useState("");
  const [importCat, setImportCat] = useState("网页导入");
  const [loading, setLoading] = useState(false);

  const closeForm = () => { setShowForm(false); setEditId(null); setShowImport(false); setFTitle(""); setFContent(""); setFCat("默认"); };

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

  const handleSave = async () => {
    if (!fTitle.trim()) { notify("标题不能为空", "warning"); return; }
    setLoading(true);
    try {
      if (editId) {
        await apiPost("/api/knowledge/update", { id: editId, title: fTitle, content: fContent, category: fCat || "默认" });
        notify("已保存", "success");
      } else {
        await apiPost("/api/knowledge/add", { title: fTitle, content: fContent, category: fCat || "默认" });
        notify("已添加", "success");
      }
      closeForm();
      await load();
    } catch { notify("保存失败", "error"); }
    setLoading(false);
  };

  const handleEdit = (item: KnowledgeItem) => {
    setEditId(item.id);
    setFTitle(item.title);
    setFContent(item.content);
    setFCat(item.category);
    setShowForm(true);
    setShowImport(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiPost("/api/knowledge/delete", { id });
      notify("已删除", "success");
      await load();
    } catch { notify("删除失败", "error"); }
  };

  const handleImportUrl = async () => {
    if (!importUrl.trim()) return;
    setLoading(true);
    try {
      await apiPost("/api/knowledge/import-url", { url: importUrl, category: importCat || "网页导入" });
      notify("导入成功", "success");
      setImportUrl(""); setShowImport(false);
      await load();
    } catch { notify("导入失败", "error"); }
    setLoading(false);
  };

  const items = data?.items ?? [];

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500 flex items-center gap-1">
          <BookOpen size={13} /> 知识库
          <span className="text-sakura-300 font-normal">({data?.total ?? 0})</span>
        </span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300">
          <X size={13} />
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
        <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-sakura-50 border border-sakura-100">
          <Search size={11} className="text-sakura-300 shrink-0" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="搜索知识库..." className="flex-1 bg-transparent text-[11px] text-sakura-600 outline-none placeholder:text-sakura-300" />
        </div>
      </div>

      {/* 分类过滤 */}
      {allCats.length > 0 && (
        <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
          <div className="flex flex-wrap gap-1">
            <button onClick={() => setFilterCat("")}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${!filterCat ? 'bg-sakura-200 text-sakura-600' : 'text-sakura-400 hover:bg-sakura-50'}`}>
              全部
            </button>
            {allCats.map((c, i) => (
              <button key={i} onClick={() => setFilterCat(c.name)}
                className={`px-2 py-0.5 rounded text-[10px] transition-colors ${filterCat === c.name ? 'bg-sakura-200 text-sakura-600' : 'text-sakura-400 hover:bg-sakura-50'}`}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 列表（含操作按钮和表单卡片） */}
      <div className="flex-1 overflow-y-auto min-h-0 px-3 py-3 space-y-3">
        {/* 添加/导入按钮 */}
        {!showForm && !showImport && items.length > 0 && (
          <button onClick={() => { closeForm(); setShowForm(true); }}
            className="flex items-center gap-1 w-full px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
            <Plus size={10} /> 添加条目
          </button>
        )}

        {/* 编辑表单卡片 */}
        {showForm && (
          <div className="bg-white border border-sakura-200 rounded-lg p-2.5 space-y-1.5 text-xs">
            <p className="text-[10px] font-semibold text-sakura-500">{editId ? "编辑条目" : "新建条目"}</p>
            <input value={fTitle} onChange={e => setFTitle(e.target.value)}
              placeholder="标题" className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] outline-none" />
            <textarea value={fContent} onChange={e => setFContent(e.target.value)}
              placeholder="内容" rows={3} className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] resize-none outline-none" />
            <div className="flex items-center gap-1">
              <button onClick={closeForm}
                className="px-3 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleSave} disabled={loading}
                className="flex items-center gap-1 px-3 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-50">
                <Check size={10} /> {editId ? "保存" : "添加"}
              </button>
            </div>
          </div>
        )}

        {/* 导入卡片 */}
        {showImport && (
          <div className="bg-white border border-sakura-200 rounded-lg p-2.5 space-y-1.5 text-xs">
            <p className="text-[10px] font-semibold text-sakura-500">从网页导入</p>
            <input value={importUrl} onChange={e => setImportUrl(e.target.value)}
              placeholder="https://..." className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] outline-none" />
            <div className="flex items-center gap-1">
              <button onClick={() => setShowImport(false)}
                className="px-3 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleImportUrl} disabled={loading}
                className="flex items-center gap-1 px-3 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-50">
                <Globe size={10} /> 导入
              </button>
            </div>
          </div>
        )}

        {/* 空状态或条目列表 */}
        {items.length === 0 && !showForm && !showImport ? (
          <div className="flex flex-col items-center justify-center py-12 text-sakura-300 space-y-2">
            <p className="text-[10px]">{search ? "未找到匹配的知识" : "知识库为空"}</p>
            {!search && (
              <div className="flex gap-1.5">
                <button onClick={() => { closeForm(); setShowForm(true); }}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
                  <Plus size={10} /> 添加条目
                </button>
                <button onClick={() => { setShowImport(true); }}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
                  <Globe size={10} /> 网页导入
                </button>
              </div>
            )}
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
