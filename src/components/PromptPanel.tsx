import { useState, useEffect } from "react";
import { apiGet, apiPost } from "@/lib/api";
import {
  FileText, Save, X, ChevronDown, ChevronUp, Edit3, Sparkles,
  Plus, Trash2, Bot, Users, Zap, Wrench, Shield,
} from "lucide-react";

interface PromptItem {
  file: string;
  scene: string;
  desc: string;
  content: string;
  lines: number;
  char_count: number;
}

const SCENE_META: { scene: string; label: string; icon: typeof Bot }[] = [
  { scene: "owner", label: "日常助手", icon: Bot },
  { scene: "group", label: "创作模式", icon: Edit3 },
  { scene: "stranger", label: "快捷问答", icon: Zap },
];

const TYPE_ICONS: Record<string, typeof Bot> = {
  owner: Bot,
  group: Edit3,
  stranger: Zap,
  rules: Shield,
  ability: Zap,
  security: Shield,
};

export default function PromptPanel({
  activeScene,
  onSceneChange,
}: {
  activeScene: string;
  onSceneChange: (scene: string) => void;
}) {
  const [prompts, setPrompts] = useState<PromptItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingFile, setEditingFile] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [expandedFile, setExpandedFile] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const load = () => {
    setLoading(true);
    apiGet<{ prompts: PromptItem[] }>("/api/prompts")
      .then(d => { setPrompts(d.prompts || []); setLoading(false); })
      .catch(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleEdit = (p: PromptItem) => {
    setEditingFile(p.file);
    setEditTitle(p.desc);
    setEditContent(p.content);
    setSavedMsg("");
  };

  const handleSave = async () => {
    const fname = editingFile;
    if (!fname) return;
    setSaving(true);
    try {
      const res = await apiPost<{ ok: boolean; error?: string }>("/api/prompts/save", {
        file: fname,
        content: editContent,
      });
      if (res.ok) {
        setSavedMsg("已保存");
        setEditingFile(null);
        setIsCreating(false);
        load();
        setTimeout(() => setSavedMsg(""), 2000);
      } else {
        setSavedMsg(res.error || "保存失败");
      }
    } catch { setSavedMsg("保存失败"); }
    setSaving(false);
  };

  const handleCreate = async () => {
    if (!editTitle.trim()) return;
    setSaving(true);
    try {
      const fname = editTitle.trim().replace(/\.txt$/i, "") + ".txt";
      const res = await apiPost<{ ok: boolean; error?: string }>("/api/prompts/save", {
        file: fname,
        content: editContent,
      });
      if (res.ok) {
        setSavedMsg("已创建");
        setIsCreating(false);
        setEditingFile(null);
        load();
        setTimeout(() => setSavedMsg(""), 2000);
      } else {
        setSavedMsg(res.error || "创建失败");
      }
    } catch { setSavedMsg("创建失败"); }
    setSaving(false);
  };

  const handleDelete = async (fname: string) => {
    if (!confirm(`确定删除 ${fname} 吗？`)) return;
    try {
      const res = await apiPost<{ ok: boolean; error?: string }>("/api/prompts/delete", { file: fname });
      if (res.ok) {
        setSavedMsg("已删除");
        if (activeScene === fname) onSceneChange("owner");
        load();
        setTimeout(() => setSavedMsg(""), 2000);
      } else {
        setSavedMsg(res.error || "删除失败");
      }
    } catch { setSavedMsg("删除失败"); }
  };

  const startCreate = () => {
    setIsCreating(true);
    setEditingFile("__new__");
    setEditTitle("");
    setEditContent("");
    setSavedMsg("");
  };

  const cancelEdit = () => {
    setEditingFile(null);
    setIsCreating(false);
    setEditTitle("");
    setEditContent("");
  };

  const toggleExpand = (file: string) => {
    setExpandedFile(expandedFile === file ? null : file);
  };

  const scenePrompts = prompts.filter(p => SCENE_META.some(s => s.scene === p.scene));
  const otherPrompts = prompts.filter(p => !SCENE_META.some(s => s.scene === p.scene));
  const activePrompt = prompts.find(p => p.scene === activeScene) || prompts.find(p => p.file === activeScene);

  return (
    <div className="flex flex-col h-full px-3 py-3 space-y-3 text-xs">
      {/* 顶部新建按钮 */}
      <div className="flex items-center justify-between">
        {savedMsg ? (
          <span className={`text-[10px] ${savedMsg.includes("失败") ? "text-red-500" : "text-green-500"}`}>{savedMsg}</span>
        ) : (
          <span className="text-[10px] text-sakura-300">提示词文件</span>
        )}
        <button
          onClick={startCreate}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] bg-sakura-100 text-sakura-600 hover:bg-sakura-200 transition-colors"
        >
          <Plus size={10} />
          新建
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8"><Sparkles size={16} className="text-sakura-300 animate-pulse" /></div>
      ) : (
        <>
          {/* 场景选择 */}
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium text-sakura-400">当前场景</p>
            <div className="grid grid-cols-3 gap-1.5">
              {SCENE_META.map(({ scene, label, icon: Icon }) => {
                const p = scenePrompts.find(x => x.scene === scene);
                const active = activeScene === scene;
                return (
                  <button
                    key={scene}
                    onClick={() => onSceneChange(scene)}
                    className={`flex flex-col items-center gap-1 px-2 py-2 rounded-lg text-[10px] transition-colors border ${
                      active
                        ? "bg-gradient-to-br from-sakura-100 to-sakura-100 border-sakura-200 text-sakura-600 font-medium"
                        : "bg-white border-sakura-100 text-sakura-400 hover:border-sakura-200"
                    }`}
                  >
                    <Icon size={12} className={active ? "text-sakura-500" : "text-sakura-300"} />
                    <span className="truncate w-full text-center">{label}</span>
                    {p && <span className="text-[9px] text-sakura-300">{p.lines}行</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 新建/编辑表单 */}
          {(editingFile || isCreating) && (
            <PromptEditor
              title={editTitle}
              content={editContent}
              isCreating={isCreating}
              saving={saving}
              onTitleChange={setEditTitle}
              onContentChange={setEditContent}
              onSave={isCreating ? handleCreate : handleSave}
              onCancel={cancelEdit}
            />
          )}

          {/* 当前场景提示词卡片 */}
          {activePrompt && !editingFile && (
            <PromptCard
              prompt={activePrompt}
              expanded={expandedFile === activePrompt.file}
              active
              onEdit={handleEdit}
              onExpand={() => toggleExpand(activePrompt.file)}
            />
          )}

          {/* 自定义/其他提示词 */}
          {otherPrompts.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-medium text-sakura-400">其他提示词</p>
              <div className="space-y-1.5">
                {otherPrompts.map(p => (
                  <PromptCard
                    key={p.file}
                    prompt={p}
                    expanded={expandedFile === p.file}
                    active={activeScene === p.file}
                    onEdit={handleEdit}
                    onExpand={() => toggleExpand(p.file)}
                    onDelete={() => handleDelete(p.file)}
                    onActivate={() => onSceneChange(p.file)}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ─── 提示词卡片 ─── */
function PromptCard({
  prompt, expanded, active,
  onEdit, onExpand, onDelete, onActivate,
}: {
  prompt: PromptItem;
  expanded: boolean;
  active?: boolean;
  onEdit: (p: PromptItem) => void;
  onExpand: () => void;
  onDelete?: () => void;
  onActivate?: () => void;
}) {
  const Icon = TYPE_ICONS[prompt.scene] || FileText;
  const isScene = SCENE_META.some(s => s.scene === prompt.scene);

  return (
    <div className={`bg-white border rounded-lg overflow-hidden transition-colors ${
      active ? "border-sakura-300 ring-1 ring-sakura-100" : "border-sakura-100"
    }`}>
      <div className="flex items-center gap-2 px-2.5 py-2">
        <Icon size={12} className={active ? "text-sakura-500" : "text-sakura-300"} />
        <div className="flex-1 min-w-0">
          <p className={`text-[11px] truncate ${active ? "text-sakura-600 font-medium" : "text-sakura-500"}`}>{prompt.desc}</p>
          <p className="text-[9px] text-sakura-300">{prompt.lines}行 · {prompt.char_count}字符</p>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          {!isScene && onActivate && (
            <button onClick={onActivate} className={`p-1 rounded text-[9px] ${active ? "text-sakura-500 bg-sakura-50" : "text-sakura-300 hover:text-sakura-500"}`}>
              {active ? "已用" : "启用"}
            </button>
          )}
          <button onClick={() => onEdit(prompt)} className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
            <Edit3 size={10} />
          </button>
          <button onClick={onExpand} className="p-1 rounded text-sakura-300 hover:text-sakura-500 hover:bg-sakura-50">
            {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
          </button>
          {onDelete && (
            <button onClick={onDelete} className="p-1 rounded text-sakura-300 hover:text-red-500 hover:bg-red-50">
              <Trash2 size={10} />
            </button>
          )}
        </div>
      </div>
      {expanded && (
        <div className="px-2.5 pb-2">
          <pre className="text-[10px] text-sakura-600 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto bg-sakura-50 rounded p-2">
            {prompt.content || "(空)"}
          </pre>
        </div>
      )}
    </div>
  );
}

/* ─── 编辑/新建表单 ─── */
function PromptEditor({
  title, content, isCreating, saving,
  onTitleChange, onContentChange, onSave, onCancel,
}: {
  title: string;
  content: string;
  isCreating: boolean;
  saving: boolean;
  onTitleChange: (v: string) => void;
  onContentChange: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="bg-sakura-50 border border-sakura-100 rounded-lg p-2.5 space-y-2">
      <p className="text-[11px] font-medium text-sakura-500">{isCreating ? "新建提示词" : "编辑提示词"}</p>
      {isCreating && (
        <input
          className="w-full px-2 py-1 rounded border border-sakura-100 bg-white text-[11px] text-sakura-600"
          placeholder="提示词名称"
          value={title}
          onChange={e => onTitleChange(e.target.value)}
        />
      )}
      <textarea
        className="w-full h-32 px-2 py-1.5 rounded border border-sakura-100 bg-white text-[10px] font-mono text-sakura-600 resize-none"
        placeholder="在这里编写提示词内容..."
        value={content}
        onChange={e => onContentChange(e.target.value)}
      />
      <div className="flex gap-1.5 justify-end">
        <button onClick={onCancel} className="px-2.5 py-1 rounded text-[10px] text-sakura-400 hover:bg-sakura-100 transition-colors">
          取消
        </button>
        <button
          onClick={onSave}
          disabled={saving || (isCreating && !title.trim())}
          className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] bg-gradient-to-r from-sakura-400 to-sakura-500 text-white disabled:opacity-40 transition-shadow"
        >
          {saving ? "保存中..." : <><Save size={9} /> {isCreating ? "创建" : "保存"}</>}
        </button>
      </div>
    </div>
  );
}
