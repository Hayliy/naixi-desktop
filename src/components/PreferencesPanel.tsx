import { useState, useEffect } from "react";
import { X, ChevronDown, ChevronUp, Image, Loader2, Pencil, Check, Plus, Save } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";
import ThemeSettings from "@/components/ThemeSettings";
import { prefillAvatars, getAvatarTotal, refreshAvatarCache } from "@/lib/avatar";

export default function PreferencesPanel({ onClose }: { onClose: () => void }) {
  const { notify } = useToast();
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [avatarCount, setAvatarCount] = useState(() => getAvatarTotal());
  const [avatarGenerating, setAvatarGenerating] = useState(false);

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500 flex items-center gap-1">
          <ChevronDown size={13} /> 外观与偏好
        </span>
        <button onClick={onClose} className="p-0.5 hover:bg-sakura-50 rounded text-sakura-300"><X size={13} /></button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {/* 头像与昵称 */}
        <div>
          <button onClick={() => setAvatarOpen(!avatarOpen)}
            className="flex items-center gap-1.5 text-xs font-semibold text-sakura-500 hover:text-sakura-600 transition-colors mb-2">
            {avatarOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            头像与昵称
          </button>
          {avatarOpen && (
            <div className="space-y-3 text-xs">
              <AvatarRow label="我的头像" storageKey="naixi_user_avatar" previewKey="用户" />
              <AvatarRow label="我的昵称" storageKey="naixi_user_name" isName />
              <AvatarRow label="奶昔头像" storageKey="naixi_bot_avatar" previewKey="奶昔" />
              <AvatarRow label="奶昔昵称" storageKey="naixi_bot_name" isName />
              {/* AI 头像预生成 */}
              <div className="pt-1 border-t border-sakura-100">
                {avatarGenerating ? (
                  <div className="space-y-1.5">
                    <p className="text-[10px] text-sakura-400">AI 头像生成中（每张约 5-15 秒）...</p>
                    <div className="flex items-center gap-2">
                      <Loader2 size={11} className="animate-spin text-sakura-400 shrink-0" />
                      <span className="text-[10px] text-sakura-500 font-medium">{avatarCount} 个已生成</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-sakura-100 overflow-hidden">
                      <div className="h-full rounded-full bg-gradient-to-r from-sakura-300 to-sakura-500 transition-all"
                        style={{ width: `${Math.min(100, (avatarCount / 50) * 100)}%` }} />
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={async () => {
                      setAvatarGenerating(true);
                      setAvatarCount(0);
                      const ok = await prefillAvatars(50);
                      if (ok) {
                        const poll = setInterval(async () => {
                          try {
                            const res = await apiGet<{running: boolean; completed: number; total: number}>("/api/avatar/gen-status");
                            if (res.completed !== undefined) setAvatarCount(res.completed);
                            if (!res.running && res.completed >= res.total) {
                              clearInterval(poll);
                              await refreshAvatarCache();
                              setAvatarCount(getAvatarTotal());
                              setAvatarGenerating(false);
                            }
                          } catch {}
                        }, 3000);
                      } else {
                        setAvatarGenerating(false);
                        notify("请先在「模型供应商」中添加画图模型（如阿里百炼 Wanx2.1）", "warning");
                      }
                    }}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] bg-gradient-to-br from-sakura-400 to-sakura-500 text-white hover:shadow-md transition-shadow"
                  >
                    <Image size={11} />
                    批量生成 50 个头像
                  </button>
                )}
                <p className="text-[9px] text-sakura-300 mt-1">使用 Wanx 2.1 生成二次元风格头像，生成后所有图标自动替换</p>
              </div>
            </div>
          )}
        </div>

        {/* 主题与快捷键 */}
        <div>
          <button onClick={() => setThemeOpen(!themeOpen)}
            className="flex items-center gap-1.5 text-xs font-semibold text-sakura-500 hover:text-sakura-600 transition-colors mb-2">
            {themeOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            主题与快捷键
          </button>
          {themeOpen && (
            <div className="space-y-3">
              <ThemeSettings />
              <ShortcutsSettings />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── 头像与昵称设置项 ─── */
function AvatarRow({ label, storageKey, isName, previewKey }: { label: string; storageKey: string; isName?: boolean; previewKey?: string }) {
  const [val, setVal] = useState(() => localStorage.getItem(storageKey) || "");
  const save = (v: string) => { setVal(v); localStorage.setItem(storageKey, v); };
  const clear = () => { setVal(""); localStorage.removeItem(storageKey); };

  return (
    <div className="flex items-center gap-2">
      {!isName && (
        <div className="w-7 h-7 rounded-full overflow-hidden bg-sakura-100 shrink-0">
          {val ? (
            <img src={val} alt={label} className="w-full h-full object-cover" onError={e => { (e.target as HTMLImageElement).style.display = "none"; }} />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-[8px] text-sakura-400">{previewKey?.[0] || "?"}</div>
          )}
        </div>
      )}
      <input value={val} onChange={e => save(e.target.value)}
        className={`flex-1 px-2 py-1 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600 ${isName ? "" : "font-mono"}`}
        placeholder={isName ? "留空使用默认" : "头像图片 URL（留空自动 DiceBear）"} />
      {val && (
        <button onClick={clear} className="p-0.5 text-sakura-300 hover:text-red-500 shrink-0"><X size={10} /></button>
      )}
    </div>
  );
}

/* ─── 快捷键设置 ─── */
const DEFAULT_SHORTCUTS: { key: string; desc: string }[] = [
  { key: "Ctrl+Enter", desc: "发送消息" },
  { key: "Enter", desc: "换行" },
  { key: "Ctrl+,", desc: "打开/关闭设置面板" },
  { key: "Escape", desc: "取消/关闭当前弹窗" },
  { key: "Ctrl+L", desc: "清空对话" },
  { key: "↑ (输入框)", desc: "上一条消息" },
];

function ShortcutsSettings() {
  const [s, setS] = useState<{ key: string; desc: string }[]>(() => {
    try { return JSON.parse(localStorage.getItem("naixi_shortcuts") || "null") || DEFAULT_SHORTCUTS; } catch { return DEFAULT_SHORTCUTS; }
  });
  const [ei, setEi] = useState<number | null>(null);
  const [ek, setEk] = useState("");
  const [ed, setEd] = useState("");
  const save = (v: typeof s) => { setS(v); localStorage.setItem("naixi_shortcuts", JSON.stringify(v)); };

  return (
    <div className="space-y-2 text-xs">
      <p className="text-[10px] text-sakura-400 mb-1">快捷键列表（按 Ctrl+, 打开设置面板）</p>
      <div className="space-y-1">
        {s.map((item, i) => ei === i ? (
          <div key={i} className="flex items-center gap-1">
            <input value={ek} onChange={e => setEk(e.target.value)} className="flex-1 px-1.5 py-0.5 rounded border border-sakura-100 bg-sakura-50 text-[10px] font-mono text-sakura-600 w-20" placeholder="快捷键" />
            <input value={ed} onChange={e => setEd(e.target.value)} className="flex-1 px-1.5 py-0.5 rounded border border-sakura-100 bg-sakura-50 text-[10px] text-sakura-600" placeholder="说明" />
            <button onClick={() => { if (ek.trim() && ed.trim()) { const n = [...s]; n[i] = { key: ek.trim(), desc: ed.trim() }; save(n); setEi(null); } }} className="p-0.5 text-sakura-400 hover:text-sakura-600"><Check size={10} /></button>
          </div>
        ) : (
          <div key={i} className="flex items-center justify-between group">
            <span className="flex items-center gap-1.5">
              <code className="px-1 py-0.5 rounded bg-sakura-50 text-[10px] font-mono text-sakura-500">{item.key}</code>
              <span className="text-[10px] text-sakura-400">{item.desc}</span>
            </span>
            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button onClick={() => { setEi(i); setEk(item.key); setEd(item.desc); }} className="p-0.5 text-sakura-300 hover:text-sakura-500"><Pencil size={9} /></button>
              <button onClick={() => save(s.filter((_, j) => j !== i))} className="p-0.5 text-sakura-300 hover:text-red-500"><X size={9} /></button>
            </div>
          </div>
        ))}
      </div>
      <button onClick={() => save([...s, { key: "新快捷键", desc: "说明" }])}
        className="flex items-center gap-1 text-[10px] text-sakura-400 hover:text-sakura-500">
        <Plus size={10} /> 添加快捷键
      </button>
      <button onClick={() => save(DEFAULT_SHORTCUTS)}
        className="w-full mt-1 px-2.5 py-1 rounded-lg text-[10px] border border-sakura-100 text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 transition-colors">
        恢复默认
      </button>
      <p className="text-[9px] text-sakura-300 mt-1">部分快捷键（如 Ctrl+L 清空对话）需要页面刷新后生效。</p>
    </div>
  );
}
