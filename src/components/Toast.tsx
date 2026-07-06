import { useState, useCallback, createContext, useContext, type ReactNode } from "react";
import { X, Check, AlertTriangle, Info, Terminal } from "lucide-react";

/* ─── Toast 类型 ─── */
type ToastType = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

/* ─── Context ─── */
interface ToastCtx {
  notify: (msg: string, type?: ToastType) => void;
}
const Ctx = createContext<ToastCtx>({ notify: () => {} });
export const useToast = () => useContext(Ctx);

/* ─── Provider ─── */
let _id = 0;
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const notify = useCallback((msg: string, type: ToastType = "info") => {
    const id = ++_id;
    setToasts(prev => [...prev, { id, type, msg }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500);
  }, []);

  const remove = (id: number) => setToasts(prev => prev.filter(t => t.id !== id));

  return (
    <Ctx.Provider value={{ notify }}>
      {children}
      {/* Toast 容器：固定在右下角 */}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <div key={t.id}
            className={`pointer-events-auto flex items-start gap-2 px-3.5 py-2.5 rounded-xl shadow-lg border text-xs max-w-[360px] animate-in slide-in-from-right ${
              t.type === "success" ? "bg-green-50 border-green-200 text-green-700" :
              t.type === "error" ? "bg-red-50 border-red-200 text-red-700" :
              t.type === "warning" ? "bg-amber-50 border-amber-200 text-amber-700" :
              "bg-sakura-50 border-sakura-200 text-sakura-700"
            }`}>
            <span className="shrink-0 mt-0.5">
              {t.type === "success" ? <Check size={14} /> :
               t.type === "error" ? <X size={14} /> :
               t.type === "warning" ? <AlertTriangle size={14} /> :
               <Info size={14} />}
            </span>
            <span className="flex-1 break-words">{t.msg}</span>
            <button onClick={() => remove(t.id)} className="shrink-0 opacity-50 hover:opacity-100 transition-opacity">
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
