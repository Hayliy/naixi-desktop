import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { X, Plus, Trash2, Play, Pause, Clock, Check, ChevronDown, ChevronUp, History, Loader2, Calendar, Repeat, Zap, CircleAlert } from "lucide-react";
import { useToast } from "@/components/Toast";

interface RunRecord {
  time: string;
  status: string;
  result?: string;
}

interface Automation {
  id: string;
  name: string;
  prompt: string;
  schedule_type: "recurring" | "once";
  rrule?: string;
  scheduled_at?: string;
  status: "active" | "paused";
  last_run?: string;
  next_run?: string;
  created_at: string;
  history: RunRecord[];
}

const SCHEDULE_PRESETS = [
  { label: "每小时", rrule: "FREQ=HOURLY" },
  { label: "每天", rrule: "FREQ=DAILY" },
  { label: "每周", rrule: "FREQ=WEEKLY" },
  { label: "每 2 天", rrule: "FREQ=DAILY;INTERVAL=2" },
  { label: "工作日", rrule: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" },
];

function computeNextRun(rrule: string): string {
  const parts: Record<string, string> = {};
  rrule.split(";").forEach(p => { const [k, v] = p.split("="); if (k && v) parts[k] = v; });
  const freq = parts.FREQ || "DAILY";
  const interval = parseInt(parts.INTERVAL || "1");
  const now = new Date();
  const next = new Date(now);
  if (freq === "HOURLY") next.setHours(next.getHours() + interval);
  else if (freq === "DAILY") next.setDate(next.getDate() + interval);
  else if (freq === "WEEKLY") next.setDate(next.getDate() + 7 * interval);
  else next.setDate(next.getDate() + 1);
  return next.toISOString().slice(0, 16).replace("T", " ");
}

export default function AutomationPanel({ onClose }: { onClose: () => void }) {
  const { notify } = useToast();
  const [automations, setAutomations] = useState<Automation[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // 表单字段
  const [fName, setFName] = useState("");
  const [fPrompt, setFPrompt] = useState("");
  const [fSchedType, setFSchedType] = useState<"recurring" | "once">("recurring");
  const [fPreset, setFPreset] = useState("FREQ=DAILY");
  const [fOnceAt, setFOnceAt] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiGet<{ automations: Automation[] }>("/api/automations");
      setAutomations(res.automations || []);
    } catch { setAutomations([]); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const closeForm = () => {
    setShowForm(false); setEditId(null);
    setFName(""); setFPrompt(""); setFSchedType("recurring");
    setFPreset("FREQ=DAILY"); setFOnceAt("");
  };

  const handleSave = async () => {
    if (!fName.trim()) { notify("名称为必填", "warning"); return; }
    setLoading(true);
    try {
      await apiPost("/api/automations/save", {
        id: editId,
        name: fName.trim(),
        prompt: fPrompt.trim(),
        schedule_type: fSchedType,
        rrule: fSchedType === "recurring" ? fPreset : "",
        scheduled_at: fSchedType === "once" ? fOnceAt : "",
      });
      notify(editId ? "已保存" : "已创建", "success");
      closeForm();
      await load();
    } catch { notify("保存失败", "error"); }
    setLoading(false);
  };

  const handleToggle = async (id: string, status: string) => {
    try {
      await apiPost("/api/automations/toggle", { id, status: status === "active" ? "paused" : "active" });
      await load();
    } catch {}
  };

  const handleDelete = async (id: string) => {
    try {
      await apiPost("/api/automations/delete", { id });
      notify("已删除", "success");
      await load();
    } catch {}
  };

  const handleRun = async (id: string) => {
    try {
      const res = await apiPost<{ ok: boolean; result?: string; error?: string }>("/api/automations/run", { id });
      if (res?.ok) notify("执行成功", "success");
      else notify(res?.error || "执行失败", "error");
      await load();
    } catch { notify("执行失败", "error"); }
  };

  const openEdit = (a: Automation) => {
    setEditId(a.id);
    setFName(a.name);
    setFPrompt(a.prompt);
    setFSchedType(a.schedule_type);
    if (a.schedule_type === "recurring") setFPreset(a.rrule || "FREQ=DAILY");
    else setFOnceAt(a.scheduled_at || "");
    setShowForm(true);
  };

  const nextRun = (a: Automation): string => {
    if (a.status !== "active") return "已暂停";
    if (a.schedule_type === "once") return a.scheduled_at || "—";
    return computeNextRun(a.rrule || "FREQ=DAILY");
  };

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      <div className="bg-white flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500">自动化</span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3 text-xs">
        {/* 新建按钮 */}
        {!showForm && (
          <button onClick={() => { setEditId(null); setShowForm(true); setFName(""); setFPrompt(""); setFSchedType("recurring"); setFPreset("FREQ=DAILY"); setFOnceAt(""); }}
            className="flex items-center gap-1 w-full px-2.5 py-1.5 rounded-lg text-[10px] text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 border border-dashed border-sakura-200 transition-colors">
            <Plus size={10} /> 新建自动化
          </button>
        )}

        {/* 表单 */}
        {showForm && (
          <div className="bg-white border border-sakura-200 rounded-lg p-2.5 space-y-1.5 text-xs">
            <p className="text-[10px] font-semibold text-sakura-500">{editId ? "编辑自动化" : "新建自动化"}</p>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">名称</p>
              <input className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px]" value={fName} onChange={e => setFName(e.target.value)} placeholder="如：每日新闻摘要" />
            </div>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">执行内容（Prompt）</p>
              <textarea className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-sakura-50 text-sakura-600 text-[10px] resize-none" rows={3} value={fPrompt} onChange={e => setFPrompt(e.target.value)} placeholder="到时间后自动发送的内容..." />
            </div>
            <div>
              <p className="text-[9px] text-sakura-400 mb-0.5">调度方式</p>
              <div className="flex gap-1">
                <button onClick={() => setFSchedType("recurring")}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] border ${fSchedType === "recurring" ? "bg-sakura-100 border-sakura-300 text-sakura-600" : "bg-white border-sakura-100 text-sakura-400"}`}>
                  <Repeat size={10} /> 重复
                </button>
                <button onClick={() => setFSchedType("once")}
                  className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] border ${fSchedType === "once" ? "bg-sakura-100 border-sakura-300 text-sakura-600" : "bg-white border-sakura-100 text-sakura-400"}`}>
                  <Calendar size={10} /> 一次
                </button>
              </div>
            </div>
            {fSchedType === "recurring" ? (
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">频率</p>
                <div className="flex flex-wrap gap-1">
                  {SCHEDULE_PRESETS.map(p => (
                    <button key={p.rrule} onClick={() => setFPreset(p.rrule)}
                      className={`px-2 py-0.5 rounded text-[10px] border ${fPreset === p.rrule ? "bg-sakura-100 border-sakura-300 text-sakura-600" : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"}`}>
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div>
                <p className="text-[9px] text-sakura-400 mb-0.5">执行时间</p>
                <input type="datetime-local" className="w-full px-2 py-1.5 rounded border border-sakura-100 bg-white text-sakura-600 text-[10px]" value={fOnceAt} onChange={e => setFOnceAt(e.target.value)} />
              </div>
            )}
            <div className="flex items-center gap-1 pt-0.5">
              <button onClick={closeForm} className="px-2.5 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-50">取消</button>
              <button onClick={handleSave} disabled={loading || !fName.trim()}
                className="flex items-center gap-1 px-3 py-1 rounded text-[10px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white disabled:opacity-50">
                <Check size={10} /> {editId ? "保存" : "创建"}
              </button>
            </div>
          </div>
        )}

        {/* 列表 */}
        {loading && automations.length === 0 ? (
          <div className="flex items-center justify-center py-8"><Loader2 size={14} className="animate-spin text-sakura-300" /></div>
        ) : automations.length === 0 && !showForm ? (
          <div className="text-center py-8 text-sakura-300">还没有自动化任务</div>
        ) : automations.map(a => (
          <div key={a.id}>
            <div className="bg-sakura-50 border border-sakura-100 rounded-lg p-2.5 group">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0 space-y-0.5" onClick={() => setExpandedId(expandedId === a.id ? null : a.id)}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-medium text-sakura-600 truncate">{a.name}</span>
                    <span className={`text-[9px] px-1 py-0.5 rounded ${a.status === "active" ? "bg-green-100 text-green-600" : "bg-sakura-100 text-sakura-400"}`}>
                      {a.status === "active" ? "运行中" : "已暂停"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[9px] text-sakura-400">
                    <span className="flex items-center gap-0.5"><Clock size={8} /> 下次: {nextRun(a)}</span>
                    <span className="flex items-center gap-0.5"><History size={8} /> {a.history?.length || 0} 次</span>
                  </div>
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <button onClick={() => handleRun(a.id)} className="p-1 rounded hover:bg-teal-50 text-sakura-300 hover:text-teal-500" title="立即执行"><Zap size={11} /></button>
                  <button onClick={() => handleToggle(a.id, a.status)} className="p-1 rounded hover:bg-amber-50 text-sakura-300 hover:text-amber-500" title={a.status === "active" ? "暂停" : "启用"}>
                    {a.status === "active" ? <Pause size={11} /> : <Play size={11} />}
                  </button>
                  <button onClick={() => openEdit(a)} className="p-1 rounded hover:bg-sakura-100 text-sakura-300 hover:text-sakura-500"><ChevronDown size={11} /></button>
                  <button onClick={() => handleDelete(a.id)} className="p-1 rounded hover:bg-red-50 text-sakura-300 hover:text-red-500"><Trash2 size={11} /></button>
                </div>
              </div>
            </div>
            {/* 执行历史 */}
            {expandedId === a.id && a.history && a.history.length > 0 && (
              <div className="mx-2 mb-1 px-2.5 py-2 rounded bg-white border border-sakura-100 space-y-1">
                <p className="text-[9px] text-sakura-400 font-medium">执行记录</p>
                  {a.history.slice(-5).reverse().map((h, i) => (
                      <div key={i} className="flex items-start gap-1 text-[9px] text-sakura-500">
                        {h.status === "success" ? <Check size={9} className="text-green-500 shrink-0 mt-0.5" /> : <CircleAlert size={9} className="text-red-400 shrink-0 mt-0.5" />}
                        <span className="shrink-0 font-mono">{h.time}</span>
                        {h.result && <span className="text-sakura-400 line-clamp-1">{h.result}</span>}
                      </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
