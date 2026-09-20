import { useState, useEffect } from "react";
import { X, ChevronDown, ChevronUp, Image, Loader2, Pencil, Check, Plus, Save } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useToast } from "@/components/Toast";
import ThemeSettings from "@/components/ThemeSettings";
import { prefillAvatars, getAvatarTotal, refreshAvatarCache } from "@/lib/avatar";
import { loadShortcuts, saveShortcuts, eventToCombo, SHORTCUT_ACTIONS, type ShortcutItem } from "@/lib/shortcuts";

export default function PreferencesPanel({ onClose }: { onClose: () => void }) {
  const { notify } = useToast();
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [themeOpen, setThemeOpen] = useState(false);
  const [avatarCount, setAvatarCount] = useState(() => getAvatarTotal());
  const [avatarGenerating, setAvatarGenerating] = useState(false);

  return (
    <div className="flex-1 w-full border-l border-sakura-100 bg-white flex flex-col h-full">
      {/* 头部 */}
      <div className="bg-white flex items-center justify-between px-3 py-2 border-b border-sakura-100 shrink-0">
        <span className="text-xs font-semibold text-sakura-500">外观与偏好</span>
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

/* ─── 快捷键设置 ───
   此前这里只有 desc 为「清空对话」的一条真正绑定，其余条目是纯展示
   （改键位 / 添加条目都不生效）——占位假实现，全功能测试点名后重做。
   现在全部动作真正绑定生效：全局动作（设置面板 / 关闭弹窗 / 清空对话）由
   Chat.tsx 的 window keydown 分发；输入框动作（发送消息 / 换行 / 上一条消息）
   由 ChatInput.tsx 的 textarea keydown 处理。键位用「按下即录制」录入。 */
function ShortcutsSettings() {
  const [s, setS] = useState<ShortcutItem[]>(() => loadShortcuts());
  const [ei, setEi] = useState<number | null>(null);
  const [ek, setEk] = useState("");
  const [dupIdx, setDupIdx] = useState<number | null>(null);
  const commit = (v: ShortcutItem[]) => { setS(v); saveShortcuts(v); };
  const conflict = (key: string, exceptIdx: number) =>
    s.some((x, i) => i !== exceptIdx && x.key.toLowerCase() === key.toLowerCase());
  // 被删除的动作会出现在这里，点击即可重新加回（键位用该动作的默认键）
  const missing = SHORTCUT_ACTIONS.filter(a => !s.some(x => x.desc === a.desc));

  return (
    <div className="space-y-2 text-xs">
      <p className="text-[10px] text-sakura-400 mb-1">快捷键列表（点击铅笔后按下新键位即录制）</p>
      <div className="space-y-1">
        {s.map((item, i) => ei === i ? (
          <div key={item.desc} className="flex items-center gap-1">
            <input readOnly value={ek}
              onKeyDown={e => { e.preventDefault(); const c = eventToCombo(e); if (c) setEk(c); }}
              onBlur={() => {
                if (ek && ek !== item.key) {
                  if (conflict(ek, i)) { setDupIdx(i); return; }
                  const n = [...s]; n[i] = { ...n[i], key: ek }; commit(n);
                }
                setEi(null);
              }}
              className="flex-1 px-1.5 py-0.5 rounded border border-sakura-200 bg-white text-[10px] font-mono text-sakura-600 w-20"
              placeholder="按下新键位" autoFocus />
            <span className="text-[10px] text-sakura-400 flex-1">{item.desc}</span>
            <button onClick={() => {
              if (ek && ek !== item.key && !conflict(ek, i)) { const n = [...s]; n[i] = { ...n[i], key: ek }; commit(n); }
              setEi(null); setDupIdx(null);
            }} className="p-0.5 text-sakura-400 hover:text-sakura-600"><Check size={10} /></button>
          </div>
        ) : (
          <div key={item.desc} className="flex items-center justify-between group">
            <span className="flex items-center gap-1.5">
              <code className="px-1 py-0.5 rounded bg-sakura-50 text-[10px] font-mono text-sakura-500">{item.key}</code>
              <span className="text-[10px] text-sakura-400">{item.desc}</span>
              {dupIdx === i && <span className="text-[9px] text-red-500">键位重复，换个键位</span>}
            </span>
            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100">
              <button onClick={() => { setEi(i); setEk(item.key); setDupIdx(null); }} className="p-0.5 text-sakura-300 hover:text-sakura-500"><Pencil size={9} /></button>
              <button onClick={() => commit(s.filter((_, j) => j !== i))} className="p-0.5 text-sakura-300 hover:text-red-500"><X size={9} /></button>
            </div>
          </div>
        ))}
      </div>
      {missing.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {missing.map(a => (
            <button key={a.desc} onClick={() => commit([...s, { ...a }])}
              className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-sakura-100 text-sakura-400 hover:text-sakura-600 hover:bg-sakura-50">
              <Plus size={9} /> 添加：{a.desc}
            </button>
          ))}
        </div>
      )}
      <button onClick={() => commit(SHORTCUT_ACTIONS.map(a => ({ ...a })))}
        className="w-full mt-1 px-2.5 py-1 rounded-lg text-[10px] border border-sakura-100 text-sakura-400 hover:text-sakura-500 hover:bg-sakura-50 transition-colors">
        恢复默认
      </button>
      <div className="text-[9px] text-sakura-300 leading-relaxed">
        以上所有快捷键均可改键、<b>即刻生效</b>（无需刷新，键位冲突会提示）。<br />
        「发送消息 / 换行 / 上一条消息」在输入框内生效；其余为全局动作（输入框内不触发，避免打字误触）。
      </div>
    </div>
  );
}
