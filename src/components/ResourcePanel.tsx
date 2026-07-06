import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { X, Search, ChevronDown, ChevronUp, Sparkles, User, Cpu, Play, Plus, Trash2, Pencil, Check } from "lucide-react";
import { useToast } from "@/components/Toast";
import { getAvatarUrl } from "@/lib/avatar";

type TabType = "prompts" | "experts" | "skills";
const TAB_LABELS: Record<TabType, string> = { prompts: "提示词", experts: "专家团队", skills: "Skill 技能" };
const TAB_META_KEY: Record<TabType, string> = { prompts: "custom_prompts", experts: "custom_experts", skills: "custom_skills" };
const ALL_CATS = ["全部", "通用", "开发", "代码开发", "写作文案", "数据分析", "设计创意", "翻译语言", "教育学习", "商业运营", "法律合规"];

interface AnyItem { act?: string; name?: string; prompt: string; description?: string; category: string; _custom?: boolean }

export default function ResourcePanel({ onClose, onApply }: {
  onClose: () => void;
  onApply: (text: string, label: string, type: TabType) => void;
}) {
  const { notify } = useToast();
  const [tab, setTab] = useState<TabType>("prompts");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<AnyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("全部");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editIdx, setEditIdx] = useState(-1);  // -1 = 新增, >=0 = 编辑第几个自定义

  // 表单字段
  const [fName, setFName] = useState("");
  const [fPrompt, setFPrompt] = useState("");
  const [fDesc, setFDesc] = useState("");
  const [fCat, setFCat] = useState("通用");

  const ghEndpoint = tab === "prompts" ? "/api/github/prompts" : tab === "experts" ? "/api/github/experts" : "/api/github/skills";
  const metaKey = TAB_META_KEY[tab];

  // 分类按钮
  const tabCats = tab === "skills" ? ["全部", "通用", "开发"] : tab === "prompts" ? ["全部", "通用", "开发"] : ["全部", ...ALL_CATS.slice(3)];

  const loadItems = () => {
    setLoading(true);
    const cat = category === "全部" ? "" : tab === "experts" ? category : category === "通用" ? "" : category;
    const params = new URLSearchParams();
    if (cat) params.set("category", cat);
    if (search) params.set("search", search);
    apiGet<{ prompts?: AnyItem[]; experts?: AnyItem[]; skills?: AnyItem[] }>(`${ghEndpoint}?${params}`)
      .then(d => {
        const merged = (tab === "prompts" ? d.prompts : tab === "experts" ? d.experts : d.skills) || [];
        setItems(merged);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadItems(); }, [tab, search, category]);

  // 添加/编辑提交
  const handleSave = async () => {
    if (!fName.trim() || !fPrompt.trim()) { notify("名称和内容不能为空", "warning"); return; }
    const item: AnyItem = {
      [tab === "prompts" ? "act" : "name"]: fName.trim(),
      prompt: fPrompt.trim(),
      category: fCat,
      _custom: true,
    };
    if (tab === "skills") item.description = fDesc.trim() || fPrompt.trim().slice(0, 200);
    try {
      const { data } = await apiPost<any>("/api/custom/save", {
        type: metaKey,
        item,
        index: editIdx,
      });
      if (data?.ok) notify(editIdx >= 0 ? "已保存" : "已添加", "success");
    } catch { notify("保存失败", "error"); }
    setShowForm(false); setEditIdx(-1);
    loadItems();
  };

  // 编辑现有自定义
  const handleEdit = (idx: number) => {
    // idx 是 items 中的位置，需要找到它在自定义列表中的索引
    const customItem = items[idx];
    if (!customItem?._custom) return;
    setFName(customItem.act || customItem.name || "");
    setFPrompt(customItem.prompt || "");
    setFDesc(customItem.description || "");
    setFCat(customItem.category || "通用");
    setEditIdx(idx);
    setShowForm(true);
    setExpanded(null);
  };

  // 删除
  const handleDelete = async (idx: number) => {
    const item = items[idx];
    if (!item?._custom) return;
    try {
      await apiPost("/api/custom/delete", { type: metaKey, index: idx });
      notify("已删除", "success");
    } catch {}
    setExpanded(null);
    loadItems();
  };

  const closeForm = () => { setShowForm(false); setEditIdx(-1); setFName(""); setFPrompt(""); setFDesc(""); setFCat("通用"); };

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      <div className="sticky top-0 bg-white border-b border-sakura-100 px-3 py-2 flex items-center justify-between z-10">
        <span className="text-xs font-semibold text-sakura-500">资源库</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>

      {/* Tab */}
      <div className="flex border-b border-sakura-100">
        {(Object.entries(TAB_LABELS) as [TabType, string][]).map(([k, v]) => (
          <button key={k} onClick={() => { setTab(k); setExpanded(null); closeForm(); }}
            className={`flex-1 text-[11px] py-2 text-center font-medium transition-colors ${tab === k ? "text-sakura-600 border-b-2 border-sakura-400" : "text-sakura-300 hover:text-sakura-500"}`}>{v}</button>
        ))}
      </div>

      {/* 搜索 + 分类 */}
      <div className="px-3 py-2 space-y-1.5 border-b border-sakura-100">
        <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-sakura-50 border border-sakura-100">
          <Search size={11} className="text-sakura-300 shrink-0" />
          <input className="flex-1 bg-transparent text-[11px] text-sakura-600 outline-none placeholder:text-sakura-300"
            value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索..." />
        </div>
        <div className="flex flex-wrap gap-1">
          {tabCats.map(c => (
            <button key={c} onClick={() => setCategory(c)}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${category === c ? "bg-sakura-200 text-sakura-600" : "text-sakura-400 hover:bg-sakura-50"}`}>{c}</button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {/* 添加按钮 */}
        {!showForm && (
          <button onClick={() => { setEditIdx(-1); setFName(""); setFPrompt(""); setFDesc(""); setFCat("通用"); setShowForm(true); }}
            className="flex items-center gap-1 w-full px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
            <Plus size={10} /> 添加{TAB_LABELS[tab]}
          </button>
        )}

        {/* 添加/编辑表单 */}
        {showForm && (
          <div className="bg-white border border-sakura-200 rounded-lg p-2.5 space-y-1.5 text-xs">
            <p className="text-[10px] font-semibold text-sakura-500">{editIdx >= 0 ? "编辑" : "添加"} {TAB_LABELS[tab]}</p>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">名称</p>
              <input className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px]" value={fName} onChange={e => setFName(e.target.value)} placeholder="名称" />
            </div>
            {tab === "skills" && (
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">描述</p>
                <input className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px]" value={fDesc} onChange={e => setFDesc(e.target.value)} placeholder="简短描述" />
              </div>
            )}
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">内容</p>
              <textarea className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] resize-none" rows={4} value={fPrompt} onChange={e => setFPrompt(e.target.value)} placeholder={tab === "prompts" ? "提示词内容..." : tab === "experts" ? "专家人设描述..." : "Skill 执行步骤..."} />
            </div>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">分类</p>
              <input className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px]" value={fCat} onChange={e => setFCat(e.target.value)} placeholder="通用 / 开发 / 自定义分类..." />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={closeForm} className="px-2.5 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleSave} className="flex items-center gap-1 px-3 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white"><Check size={10} /> {editIdx >= 0 ? "保存" : "添加"}</button>
            </div>
          </div>
        )}

        {/* 列表项 */}
        {loading ? (
          <div className="text-center py-8 text-sakura-300 text-[11px]">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-sakura-300 text-[11px]">未找到匹配结果</div>
        ) : (
          items.map((item, i) => {
            const name = item.act || item.name || "";
            const desc = item.prompt || item.description || "";
            const isExpanded = expanded === `${tab}-${i}`;
            return (
              <div key={i} className={`bg-sakura-50 border rounded-lg ${item._custom ? "border-purple-200" : "border-sakura-100"}`}>
                <button onClick={() => setExpanded(isExpanded ? null : `${tab}-${i}`)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left">
                  {tab === "experts" ? (
                    <img src={getAvatarUrl(name)} alt={name}
                      className="w-6 h-6 rounded-full bg-sakura-100 shrink-0" loading="lazy" />
                  ) : tab === "skills" ? <Cpu size={11} className="text-sakura-400 shrink-0" /> :
                   <Sparkles size={11} className="text-sakura-400 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-medium text-sakura-600 truncate">{name}</p>
                    <p className="text-[9px] text-sakura-400">{item.category}{item._custom ? " · 自定义" : ""}</p>
                  </div>
                  {isExpanded ? <ChevronUp size={11} className="text-sakura-300" /> : <ChevronDown size={11} className="text-sakura-300" />}
                </button>
                {isExpanded && (
                  <div className="px-2.5 pb-2 space-y-1.5">
                    <p className="text-[10px] text-sakura-500 leading-relaxed line-clamp-6">{desc}</p>
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => onApply(desc, name, tab)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">
                        {tab === "skills" ? <Play size={10} /> : <Sparkles size={10} />}
                        {tab === "skills" ? "执行 Skill" : tab === "experts" ? "切换专家" : "应用提示词"}
                      </button>
                      {item._custom && (
                        <>
                          <button onClick={() => handleEdit(i)} className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500" title="编辑"><Pencil size={10} /></button>
                          <button onClick={() => handleDelete(i)} className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500" title="删除"><Trash2 size={10} /></button>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
