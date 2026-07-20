import type { ReactNode } from "react";

/* ────────────────────────────────────────────────
 * 设置页共享的行式布局基础组件
 * 三方统一引用（SettingsPage / ThemeSettings / ProviderSettings），
 * 从根源消除样式漂移。零卡片，靠分隔线分组。
 * ──────────────────────────────────────────────── */

/* 输入框 / 按钮统一样式 */
export const INPUT = "min-w-[180px] bg-sakura-50 border border-sakura-200 rounded-lg px-3 py-1.5 text-sm text-sakura-700 focus:outline-none focus:border-sakura-300";
export const BTN = "px-5 py-1.5 bg-sakura-500 text-white rounded-lg text-sm hover:bg-sakura-400 transition-colors disabled:opacity-60";
export const BTN_GHOST = "px-5 py-1.5 border border-sakura-200 text-sakura-500 rounded-lg text-sm hover:bg-sakura-100 transition-colors";

/* 分组：粉色小标题 + 灰色说明 */
export function Section({ title, desc, children }: { title: string; desc?: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <p className="text-xs font-medium text-sakura-500 tracking-wide">{title}</p>
      {desc && <p className="text-xs text-sakura-400 mt-0.5 mb-1">{desc}</p>}
      <div>{children}</div>
    </section>
  );
}

/* 单行：左标题+说明，右控件右对齐，顶部细分隔线 */
export function SettingRow({ label, desc, children }: { label: string; desc?: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 py-3.5 border-t border-sakura-200/50">
      <div className="min-w-0">
        <p className="text-sm font-medium text-sakura-600">{label}</p>
        {desc && <p className="text-xs text-sakura-400 mt-0.5">{desc}</p>}
      </div>
      <div className="shrink-0 flex items-center">{children}</div>
    </div>
  );
}

/* 只读展示行（用于文件/安全/关于） */
export function InfoRow({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-6 py-3 border-t border-sakura-200/50">
      <span className="text-sm text-sakura-500 shrink-0">{label}</span>
      <span className={`text-sm text-sakura-600 text-right ${mono ? "font-mono text-[11px] break-all" : ""}`}>{value}</span>
    </div>
  );
}

/* 底部保存条 */
export function SaveBar({ onSave, saving }: { onSave: () => void; saving: boolean }) {
  return (
    <div className="flex justify-end mt-2 pt-4 border-t border-sakura-200/50">
      <button onClick={onSave} disabled={saving} className={BTN}>{saving ? "保存中..." : "保存更改"}</button>
    </div>
  );
}
