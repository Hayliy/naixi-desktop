import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet } from "@/lib/api";
import { AlertTriangle, RotateCw, RefreshCw } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { apiPost } from "@/lib/api";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Status = "checking" | "up" | "down";

// 后端健康守卫：定期探测后端状态，失联时显示横幅并提供重启入口。
// 后端正常时右下角悬浮显示状态指示 + 手动重启按钮。
export default function BackendGuard({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("checking");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [restarting, setRestarting] = useState(false);
  const timerRef = useRef<number | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

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
      listen<string>("backend-error", (e) => {
        setStatus("down");
        setErrorMsg(e.payload);
        setBannerDismissed(false);
      }).then((fn) => (unlisten = fn));
    }
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      unlisten?.();
    };
  }, []);

  const restart = async () => {
    setRestarting(true);
    setErrorMsg("");
    setBannerDismissed(false);
    try {
      if (isTauri) {
        // Tauri 模式走真正的 restart_backend：kill 旧进程 + 重新拉起 sidecar，
        // 即使后端卡死/死透也能可靠重启（不再依赖「端口占用则跳过」的 start_backend）。
        await invoke("restart_backend");
      } else {
        // 浏览器模式：后端是独立进程，死透时无法由前端拉起，仅存活时可自重启。
        await apiPost("/api/desktop/restart", {});
      }
    } catch (e) {
      setErrorMsg(typeof e === "string" ? e : "后端启动失败，请查看日志");
    }
    setTimeout(() => probe(), 1500);
    setRestarting(false);
  };

  // 掉线横幅（可关闭）
  const showBanner = status === "down" && !bannerDismissed;

  return (
    <>
      {children}

      {/* ═══ 后端掉线横幅 ═══ */}
      {showBanner && (
        <div className="fixed top-0 left-0 right-0 z-50 flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-300 text-amber-800 text-xs">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="flex-1">
            {errorMsg || "后端未运行，部分功能不可用"}
          </span>
          {isTauri ? (
            <>
              <button
                onClick={restart}
                disabled={restarting}
                className="flex items-center gap-1 px-2 py-1 rounded bg-amber-600 text-white text-xs hover:bg-amber-700 disabled:opacity-50"
              >
                <RotateCw size={12} className={restarting ? "animate-spin" : ""} />
                {restarting ? "重启中" : "重启后端"}
              </button>
              <button
                onClick={() => setBannerDismissed(true)}
                className="text-amber-500 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-200 text-xs px-1"
              >
                关闭
              </button>
            </>
          ) : (
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

      {/* ═══ 悬浮状态按钮（右下角常驻，掉线时也显示） ═══ */}
      {status !== "checking" && (
        <div className="fixed bottom-4 right-4 z-50 flex items-center gap-1.5 px-2.5 py-1.5 rounded-full bg-white/80 dark:bg-gray-800/80 border border-gray-200 dark:border-gray-600 shadow-sm text-xs text-gray-500 dark:text-gray-300 backdrop-blur-sm hover:shadow-md transition-shadow">
          <span className={`inline-block w-2 h-2 rounded-full ${status === "up" ? "bg-green-500" : "bg-red-500"}`} />
          <span className="hidden sm:inline">后端</span>
          <button
            onClick={restart}
            disabled={restarting}
            title={isTauri ? "重启后端" : "重启后端（浏览器模式）"}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw size={12} className={restarting ? "animate-spin" : ""} />
          </button>
        </div>
      )}
    </>
  );
}
