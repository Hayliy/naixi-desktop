import { useState, useEffect } from "react";
import { apiGet } from "@/lib/api";
import { X, Search, ChevronDown, ChevronUp, Sparkles, User, Cpu, Play } from "lucide-react";

/* ─── 类型 ─── */
interface PromptItem { act: string; prompt: string; category: string }
interface ExpertItem { name: string; category: string; prompt: string }
interface SkillItem { name: string; description: string; prompt: string; category: string }

type TabType = "prompts" | "experts" | "skills";
const TAB_LABELS: Record<TabType, string> = { prompts: "提示词", experts: "专家团队", skills: "Skill 技能" };
const CATEGORIES = ["全部", "通用", "开发", "代码开发", "写作文案", "数据分析", "设计创意", "翻译语言", "教育学习", "商业运营", "法律合规"];

export default function ResourcePanel({ onClose, onApply }: {
  onClose: () => void;
  onApply: (text: string, label: string, type: TabType) => void;
}) {
  const [tab, setTab] = useState<TabType>("prompts");
  const [search, setSearch] = useState("");
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [experts, setExperts] = useState<ExpertItem[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("全部");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    const cat = category === "全部" ? "" : tab === "experts" ? category : category === "通用" ? "" : category;
    const endpoint = tab === "prompts" ? "/api/github/prompts" : tab === "experts" ? "/api/github/experts" : "/api/github/skills";
    const params = new URLSearchParams();
    if (cat) params.set("category", cat);
    if (search) params.set("search", search);
    apiGet<{ prompts?: PromptItem[]; experts?: ExpertItem[]; skills?: SkillItem[]; total: number }>(`${endpoint}?${params}`)
      .then(d => {
        if (tab === "prompts") setPrompts(d.prompts || []);
        else if (tab === "experts") setExperts(d.experts || []);
        else setSkills(d.skills || []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tab, search, category]);

  const items = tab === "prompts" ? prompts : tab === "experts" ? experts : skills;
  const listLabel = TAB_LABELS[tab];

  return (
    <div className="w-80 min-w-[20rem] border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="sticky top-0 bg-white border-b border-sakura-100 px-3 py-2 flex items-center justify-between z-10">
        <span className="text-xs font-semibold text-sakura-500">资源库</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>

      {/* Tab 切换 */}
      <div className="flex border-b border-sakura-100">
        {(Object.entries(TAB_LABELS) as [TabType, string][]).map(([k, v]) => (
          <button key={k} onClick={() => { setTab(k); setExpanded(null); }}
            className={`flex-1 text-[11px] py-2 text-center font-medium transition-colors ${
              tab === k ? "text-sakura-600 border-b-2 border-sakura-400" : "text-sakura-300 hover:text-sakura-500"
            }`}>{v}</button>
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
          {CATEGORIES.filter(c => tab === "prompts" ? ["全部", "通用", "开发"].includes(c) : c !== "开发").map(c => (
            <button key={c} onClick={() => setCategory(c)}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                category === c ? "bg-sakura-200 text-sakura-600" : "text-sakura-400 hover:bg-sakura-50"
              }`}>{c}</button>
          ))}
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {loading ? (
          <div className="text-center py-8 text-sakura-300 text-[11px]">加载中...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-sakura-300 text-[11px]">未找到匹配结果</div>
        ) : (
          items.map((item, i) => {
            const name = (item as any).act || (item as any).name || "";
            const desc = (item as any).prompt || (item as any).description || "";
            const cat = (item as any).category || "";
            const isExpanded = expanded === `${tab}-${i}`;
            return (
              <div key={i} className="bg-sakura-50 border border-sakura-100 rounded-lg">
                <button onClick={() => setExpanded(isExpanded ? null : `${tab}-${i}`)}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left">
                  {tab === "experts" ? <User size={11} className="text-sakura-400 shrink-0" /> :
                   tab === "skills" ? <Cpu size={11} className="text-sakura-400 shrink-0" /> :
                   <Sparkles size={11} className="text-sakura-400 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-medium text-sakura-600 truncate">{name}</p>
                    {cat && <p className="text-[9px] text-sakura-400">{cat}</p>}
                  </div>
                  {isExpanded ? <ChevronUp size={11} className="text-sakura-300" /> : <ChevronDown size={11} className="text-sakura-300" />}
                </button>
                {isExpanded && (
                  <div className="px-2.5 pb-2 space-y-1.5">
                    <p className="text-[10px] text-sakura-500 leading-relaxed line-clamp-6">{desc}</p>
                    <button onClick={() => onApply(desc, name, tab)}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white">
                      {tab === "skills" ? <Play size={10} /> : <Sparkles size={10} />}
                      {tab === "skills" ? "执行 Skill" : tab === "experts" ? "切换专家" : "应用提示词"}
                    </button>
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
