import { useState, useEffect } from "react";
import { Plus, Trash2, Check, X, ChevronDown, ChevronUp, Save, Users, ArrowUp, ArrowDown, Play } from "lucide-react";
import { useToast } from "@/components/Toast";
import { apiGet } from "@/lib/api";

interface ExpertInfo {
  name: string;
  category: string;
  prompt: string;
}

export interface TeamMember {
  name: string;
  prompt: string;
}

export interface TeamPreset {
  name: string;
  members: TeamMember[];
}

export default function TeamPanel({ onClose, onApplyTeam }: {
  onClose: () => void;
  onApplyTeam: (members: TeamMember[], teamName: string) => void;
}) {
  const { notify } = useToast();
  const [experts, setExperts] = useState<ExpertInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [cats, setCats] = useState<string[]>([]);

  const [team, setTeam] = useState<TeamMember[]>([]);
  const [teamName, setTeamName] = useState("");
  const [presets, setPresets] = useState<TeamPreset[]>(() => {
    try { return JSON.parse(localStorage.getItem("naixi_team_presets") || "[]"); }
    catch { return []; }
  });
  const [showPresets, setShowPresets] = useState(false);

  useEffect(() => {
    apiGet<{ experts: ExpertInfo[]; total: number }>("/api/github/experts")
      .then(d => {
        setExperts(d.experts);
        const c = [...new Set(d.experts.map(e => e.category))].filter(Boolean) as string[];
        setCats(c);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = experts.filter(e => {
    if (category && e.category !== category) return false;
    if (search && !e.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const addMember = (expert: ExpertInfo) => {
    setTeam(prev => [...prev, { name: expert.name, prompt: expert.prompt }]);
    notify(`已添加「${expert.name}」`, "success");
  };

  const removeMember = (idx: number) => {
    setTeam(prev => prev.filter((_, i) => i !== idx));
  };

  const moveMember = (idx: number, dir: -1 | 1) => {
    const newTeam = [...team];
    const target = idx + dir;
    if (target < 0 || target >= newTeam.length) return;
    [newTeam[idx], newTeam[target]] = [newTeam[target], newTeam[idx]];
    setTeam(newTeam);
  };

  const savePreset = () => {
    if (!teamName.trim() || team.length === 0) return;
    const newPreset: TeamPreset = { name: teamName.trim(), members: [...team] };
    const updated = [...presets.filter(p => p.name !== teamName.trim()), newPreset];
    setPresets(updated);
    localStorage.setItem("naixi_team_presets", JSON.stringify(updated));
    setTeamName("");
    notify(`团队「${newPreset.name}」已保存`, "success");
  };

  const loadPreset = (preset: TeamPreset) => {
    setTeam(preset.members);
    setShowPresets(false);
    notify(`已加载团队「${preset.name}」`, "success");
  };

  const deletePreset = (name: string) => {
    const updated = presets.filter(p => p.name !== name);
    setPresets(updated);
    localStorage.setItem("naixi_team_presets", JSON.stringify(updated));
  };

  const startTeam = () => {
    if (team.length === 0) { notify("请至少添加一个成员", "error"); return; }
    const name = teamName.trim() || `团队 (${team.length}人)`;
    onApplyTeam(team, name);
  };

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="bg-white border-b border-sakura-100 px-3 py-2 flex items-center justify-between shrink-0">
        <span className="text-xs font-semibold text-sakura-500">专家团队</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>

      {/* 当前组队（固定顶部） */}
      <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
        <p className="text-[10px] text-sakura-400 mb-1.5">当前组队 ({team.length}人)</p>
        {team.length === 0 ? (
          <p className="text-[10px] text-sakura-300 italic py-2">从下方选择专家添加到团队</p>
        ) : (
          <div className="space-y-1 mb-2 max-h-[120px] overflow-y-auto pr-0.5">
            {team.map((m, i) => (
              <div key={i} className="flex items-center gap-1 px-2 py-1 rounded bg-sakura-50 border border-sakura-100 text-xs">
                <span className="w-4 h-4 rounded flex items-center justify-center text-[8px] font-bold bg-sakura-200 text-sakura-500 shrink-0">{i + 1}</span>
                <span className="flex-1 text-[10px] text-sakura-600 truncate">{m.name}</span>
                <button onClick={() => moveMember(i, -1)} disabled={i === 0}
                  className="p-0.5 text-sakura-300 hover:text-sakura-500 disabled:opacity-20"><ArrowUp size={9} /></button>
                <button onClick={() => moveMember(i, 1)} disabled={i === team.length - 1}
                  className="p-0.5 text-sakura-300 hover:text-sakura-500 disabled:opacity-20"><ArrowDown size={9} /></button>
                <button onClick={() => removeMember(i)}
                  className="p-0.5 text-sakura-300 hover:text-red-500"><X size={9} /></button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <input value={teamName} onChange={e => setTeamName(e.target.value)}
            className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 placeholder:text-sakura-300"
            placeholder="团队名称（可选）" />
          <button onClick={savePreset} disabled={team.length === 0}
            className="p-1 rounded text-sakura-300 hover:text-sakura-500 disabled:opacity-30" title="保存团队">
            <Save size={12} />
          </button>
          <button onClick={startTeam} disabled={team.length === 0}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-gradient-to-r from-sakura-400 to-sakura-500 text-white disabled:opacity-40">
            <Play size={10} /> 启动团队
          </button>
        </div>
      </div>

      {/* 已保存团队（固定顶部） */}
      {presets.length > 0 && (
        <div className="px-3 py-2 border-b border-sakura-100 shrink-0">
          <button onClick={() => setShowPresets(!showPresets)}
            className="flex items-center gap-1 text-[10px] text-sakura-400 hover:text-sakura-500 w-full">
            <Users size={10} /> 已保存团队 ({presets.length})
            {showPresets ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          </button>
          {showPresets && (
            <div className="mt-1 space-y-1 max-h-[100px] overflow-y-auto pr-0.5">
              {presets.map(p => (
                <div key={p.name} className="flex items-center gap-1 px-2 py-1 rounded bg-sakura-50 text-xs">
                  <span className="flex-1 text-[10px] text-sakura-600 truncate">{p.name} ({p.members.length}人)</span>
                  <button onClick={() => loadPreset(p)}
                    className="p-0.5 text-sakura-300 hover:text-sakura-500"><Check size={9} /></button>
                  <button onClick={() => deletePreset(p.name)}
                    className="p-0.5 text-sakura-300 hover:text-red-500"><Trash2 size={9} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 专家筛选 + 列表（可滚动） */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="px-3 py-2 border-b border-sakura-100">
          <div className="flex items-center gap-1 mb-1.5">
            <input value={search} onChange={e => setSearch(e.target.value)}
              className="flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 placeholder:text-sakura-300"
              placeholder="搜索专家..." />
          </div>
          <div className="flex flex-wrap gap-1">
            <button onClick={() => setCategory("")}
              className={`px-1.5 py-0.5 rounded text-[9px] ${!category ? "bg-sakura-200 text-sakura-600" : "bg-sakura-50 text-sakura-400 hover:bg-sakura-100"}`}>全部</button>
            {cats.map(c => (
              <button key={c} onClick={() => setCategory(c)}
                className={`px-1.5 py-0.5 rounded text-[9px] ${category === c ? "bg-sakura-200 text-sakura-600" : "bg-sakura-50 text-sakura-400 hover:bg-sakura-100"}`}>{c}</button>
            ))}
          </div>
        </div>

        <div className="px-2 py-2 space-y-1">
          {loading ? (
            <p className="text-[10px] text-sakura-300 text-center py-4">加载中...</p>
          ) : filtered.length === 0 ? (
            <p className="text-[10px] text-sakura-300 text-center py-4">无匹配专家</p>
          ) : (
            filtered.slice(0, 50).map((expert, i) => {
              const inTeam = team.some(t => t.name === expert.name);
              return (
                <div key={expert.name + i}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-sakura-50 transition-colors">
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] text-sakura-600 truncate">{expert.name}</p>
                    <p className="text-[9px] text-sakura-400 truncate">{expert.category}</p>
                  </div>
                  <button onClick={() => addMember(expert)} disabled={inTeam}
                    className="p-0.5 text-sakura-300 hover:text-sakura-500 disabled:opacity-20 disabled:cursor-not-allowed"
                    title={inTeam ? "已在团队中" : "添加到团队"}>
                    <Plus size={10} />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
