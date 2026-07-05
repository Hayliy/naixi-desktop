import { Terminal, X, Check } from "lucide-react";
import { apiPost } from "@/lib/api";

export default function PermissionDialog({ reqId, name, args, onClose }: {
  reqId: string; name: string; args?: Record<string, unknown>; onClose: () => void;
}) {
  const handleApprove = async () => {
    try { await apiPost("/api/tool/permit", { id: reqId, approved: true }); } catch {}
    onClose();
  };
  const handleDeny = async () => {
    try { await apiPost("/api/tool/permit", { id: reqId, approved: false }); } catch {}
    onClose();
  };

  const cmdText = args?.command || args?.name || "";

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center" onClick={handleDeny}>
      <div className="bg-white rounded-2xl shadow-2xl w-[420px]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-5 py-4 border-b border-sakura-100">
          <Terminal size={16} className="text-amber-500" />
          <span className="text-sm font-semibold text-sakura-600">权限确认</span>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-xs text-sakua-600">
            <span className="font-medium text-sakura-700">奶昔</span> 想要执行以下操作：
          </p>
          <div className="px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200">
            <p className="text-[11px] font-medium text-amber-800">{name}</p>
            {cmdText && (
              <code className="block mt-1 text-[11px] text-amber-700 font-mono break-all bg-amber-100/50 px-2 py-1 rounded">
                {typeof cmdText === "string" ? cmdText : JSON.stringify(cmdText)}
              </code>
            )}
          </div>
          <p className="text-[11px] text-sakura-400">确认执行此操作？你可以随时拒绝。</p>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-sakura-100">
          <button onClick={handleDeny}
            className="flex items-center gap-1 px-4 py-2 rounded-lg text-xs text-sakura-400 hover:bg-sakura-50 transition-colors">
            <X size={12} /> 拒绝
          </button>
          <button onClick={handleApprove}
            className="flex items-center gap-1 px-4 py-2 rounded-lg text-xs bg-gradient-to-br from-amber-400 to-amber-500 text-white hover:shadow-md transition-shadow">
            <Check size={12} /> 允许
          </button>
        </div>
      </div>
    </div>
  );
}
