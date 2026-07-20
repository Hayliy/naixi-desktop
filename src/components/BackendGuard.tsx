import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet } from "@/lib/api";
import { AlertTriangle, RotateCw } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Status = "checking" | "up" | "down";

// 后端健康守卫：定期探测后端，失联时显示横幅并提供重启入口。
// 不阻塞主界面，仅在后端不可用时顶部浮出提示条。
export default function BackendGuard({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("checking");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [restarting, setRestarting] = useState(false);
  const timerRef = useRef<number | null>(null);

  const probe = async () => {
    try {
      await apiGet("/api/desktop/config", 4000);
      setStatus("up");
      setErrorMsg("");
    } catch {
      setStatus("down");
    }
  };

  useEffect(() => {
    probe();
    timerRef.current = window.setInterval(probe, 5000);
    let unlisten: UnlistenFn | undefined;
    if (isTauri) {
      // Rust 侧启动失败时（如未检测到 Python）主动推送原因
      listen<string>("backend-error", (e) => {
        setStatus("down");
        setErrorMsg(e.payload);
      }).then((fn) => (unlisten = fn));
    }
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      unlisten?.();
    };
  }, []);

  const restart = async () => {
    if (!isTauri) return;
    setRestarting(true);
    setErrorMsg("");
    try {
      await invoke("start_backend");
    } catch (e) {
      setErrorMsg(typeof e === "string" ? e : "后端启动失败，请查看日志");
    }
    await probe();
    setRestarting(false);
  };

  const showBanner = status === "down";

  return (
    <>
      {children}
      {showBanner && (
        <div className="fixed top-0 left-0 right-0 z-50 flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-300 text-amber-800 text-xs">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="flex-1">
            {errorMsg || "后端未运行，部分功能不可用"}
          </span>
          {isTauri && (
            <button
              onClick={restart}
              disabled={restarting}
              className="flex items-center gap-1 px-2 py-1 rounded bg-amber-600 text-white text-xs hover:bg-amber-700 disabled:opacity-50"
            >
              <RotateCw size={12} className={restarting ? "animate-spin" : ""} />
              {restarting ? "重启中" : "重启后端"}
            </button>
          )}
        </div>
      )}
    </>
  );
}
