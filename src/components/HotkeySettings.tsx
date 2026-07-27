import { useState, useEffect } from "react";
import { Trash2, Keyboard } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { Section, SettingRow, InfoRow, INPUT, BTN, BTN_GHOST } from "./settings/primitives";
import { ACTION_KEYWORDS, EMOTION_KEYWORDS } from "@/lib/avatarDriver";

type Hotkey = { id: string; combo: string; kind: string; label: string; enabled: number };

const LABEL_HINTS = [
  ...Object.keys(ACTION_KEYWORDS),
  ...Object.keys(EMOTION_KEYWORDS),
];

export default function HotkeySettings({ show }: { show?: (m: string, k?: "ok" | "err") => void }) {
  const [list, setList] = useState<Hotkey[]>([]);
  const [globalActive, setGlobalActive] = useState(false);
  const [combo, setCombo] = useState("");
  const [kind, setKind] = useState("motion");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [modelActions, setModelActions] = useState<{ expressions: string[]; motions: string[]; hotkeys: { name: string; kind: string }[] } | null>(null);
  const [importing, setImporting] = useState(false);

  const currentModel = typeof localStorage !== "undefined" ? (localStorage.getItem("naixi_pet_model") || "") : "";

  async function refresh() {
    try {
      const d = await apiGet<{ global_active: boolean; hotkeys: Hotkey[] }>("/api/hotkeys/config");
      setGlobalActive(!!d.global_active);
      setList(d.hotkeys || []);
    } catch {}
  }
  useEffect(() => { refresh(); }, []);

  // 拉取当前模型文件里原本写的快捷键动作（表情/动作名 + VTS Hotkeys）
  useEffect(() => {
    if (!currentModel) return;
    apiGet<{ expressions: string[]; motions: string[]; hotkeys: { name: string; kind: string }[] }>(
      "/api/live2d-model-actions?model=" + encodeURIComponent(currentModel)
    ).then(d => setModelActions(d)).catch(() => setModelActions(null));
  }, [currentModel]);

  async function onImportModel() {
    if (!currentModel) { show?.("未选择模型", "err"); return; }
    setImporting(true);
    try {
      await apiPost("/api/hotkeys/import-model", { model: currentModel, force: true });
      await refresh();
      show?.("已按当前模型快捷键动作重新导入", "ok");
    } catch (e: any) {
      show?.(e?.message || "导入失败", "err");
    } finally { setImporting(false); }
  }

  async function onAdd() {
    const c = combo.trim().toLowerCase();
    const l = label.trim();
    if (!c || !l) { show?.("combo 与 语义标签 必填", "err"); return; }
    if (!/^[a-z0-9+]+$/.test(c)) { show?.("combo 仅含字母/数字/+，如 f8、ctrl+shift+a", "err"); return; }
    setBusy(true);
    try {
      await apiPost("/api/hotkeys", { combo: c, kind, label: l });
      setCombo(""); setLabel("");
      await refresh();
      show?.("已添加热键", "ok");
    } catch (e: any) {
      show?.(e?.message || "添加失败", "err");
    } finally { setBusy(false); }
  }

  async function onDelete(id: string) {
    try {
      await apiPost("/api/hotkeys/delete", { id });
      await refresh();
      show?.("已删除", "ok");
    } catch (e: any) {
      show?.(e?.message || "删除失败", "err");
    }
  }

  return (
    <div>
      <Section
        title="VTS 风格全局热键"
        desc="按键 → 触发当前 Live2D 模型的动作 / 表情（语义标签跨模型通用，按名称模糊匹配）。系统级生效（窗口失焦也能触发，需后端安装 pynput）。"
      >
        <InfoRow
          label="系统级监听"
          value={globalActive ? "已启用（全局生效）" : "未启用 · 窗口聚焦时由浏览器 keydown 兜底"}
        />

        <div className="mt-2">
          <button onClick={onImportModel} disabled={importing || !currentModel} className={BTN_GHOST}>
            <Keyboard className="w-3.5 h-3.5" />
            {importing ? "导入中..." : "按当前模型快捷键动作重新导入"}
          </button>
          <p className="text-[11px] text-sakura-400 mt-1.5">
            一键导入模型文件里原本写的快捷键动作（{modelActions ? (modelActions.hotkeys.length + modelActions.expressions.length + modelActions.motions.length) : "—"} 项），按模型真实动作名精确触发。模型切换后点此重新绑定。
          </p>
        </div>

        {/* 当前模型文件里原本写的快捷键动作（默认支持清单） */}
        {modelActions && (modelActions.hotkeys.length > 0 || modelActions.expressions.length > 0 || modelActions.motions.length > 0) && (
          <div className="mt-3 p-3 rounded-xl bg-sakura-50/60 border border-sakura-200/60">
            <p className="text-[11px] text-sakura-400 mb-1.5">当前模型可用动作（模型文件里原本写的）：</p>
            {modelActions.hotkeys.length > 0 && (
              <div className="mb-1.5">
                <span className="text-[11px] text-violet-500">VTS 快捷键 {modelActions.hotkeys.length}：</span>
                <span className="text-[11px] text-sakura-500">{modelActions.hotkeys.map(h => h.name).join("、")}</span>
              </div>
            )}
            {modelActions.expressions.length > 0 && (
              <div className="mb-1.5">
                <span className="text-[11px] text-violet-500">表情 {modelActions.expressions.length}：</span>
                <span className="text-[11px] text-sakura-500">{modelActions.expressions.join("、")}</span>
              </div>
            )}
            {modelActions.motions.length > 0 && (
              <div>
                <span className="text-[11px] text-sky-500">动作 {modelActions.motions.length}：</span>
                <span className="text-[11px] text-sakura-500">{modelActions.motions.join("、")}</span>
              </div>
            )}
          </div>
        )}

        {/* 现有热键列表 */}
        <div className="mt-2">
          {list.length === 0 && (
            <p className="text-xs text-sakura-400 py-2">暂无热键，添加一条试试。</p>
          )}
          {list.map(h => (
            <div key={h.id} className="flex items-center justify-between gap-4 py-2.5 border-t border-sakura-200/50">
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-mono text-xs bg-sakura-100 text-sakura-700 px-2 py-1 rounded">{h.combo}</span>
                <span className={`text-[11px] px-1.5 py-0.5 rounded ${h.kind === "expression" ? "bg-violet-100 text-violet-600" : "bg-sky-100 text-sky-600"}`}>
                  {h.kind === "expression" ? "表情" : "动作"}
                </span>
                <span className="text-sm text-sakura-600">{h.label}</span>
              </div>
              <button onClick={() => onDelete(h.id)} className="shrink-0 text-sakura-400 hover:text-rose-500" title="删除">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>

        {/* 新增表单 */}
        <div className="flex flex-wrap items-end gap-3 mt-4 p-3 rounded-xl bg-sakura-50/60 border border-sakura-200/60">
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-sakura-400">组合键</span>
            <input className={INPUT} placeholder="f8 / ctrl+shift+a" value={combo}
              onChange={e => setCombo(e.target.value)} onKeyDown={e => e.stopPropagation()} />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-sakura-400">类型</span>
            <select className={INPUT} value={kind} onChange={e => setKind(e.target.value)}>
              <option value="motion">动作</option>
              <option value="expression">表情</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-sakura-400">语义标签</span>
            <input className={INPUT} list="hotkey-labels" placeholder="wave / 惊讶 ..." value={label}
              onChange={e => setLabel(e.target.value)} onKeyDown={e => e.stopPropagation()} />
            <datalist id="hotkey-labels">
              {LABEL_HINTS.map(k => <option key={k} value={k} />)}
            </datalist>
          </div>
          <button onClick={onAdd} disabled={busy} className={BTN}>{busy ? "添加中..." : "添加"}</button>
        </div>

        <p className="text-[11px] text-sakura-400 mt-3 leading-relaxed">
          常用组合：F1–F12 直接触发；Ctrl/Alt/Shift 可组合（如 ctrl+shift+h）。动作标签参考 {Object.keys(ACTION_KEYWORDS).join("、")}；
          表情标签参考 {Object.keys(EMOTION_KEYWORDS).join("、")}。模型若无对应动作/表情，会自动跳过或随机兜底。
        </p>
      </Section>
    </div>
  );
}
