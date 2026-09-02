import { useEffect, useRef, useState, type ReactNode } from "react";
import { apiGet } from "@/lib/api";
import { AlertTriangle, RotateCw, RefreshCw } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { apiPost } from "@/lib/api";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Status = "checking" | "up" | "down";
// booting：启动期探测中（只渲染 loading，不挂载主应用）
// running：后端已就绪（渲染主应用 + 定时健康检查）
// forced：超时保底（后端可能彻底挂了，强制渲染主应用 + 横幅，避免永远 loading）
type Phase = "booting" | "running" | "forced";

// 后端健康守卫：
// 1) 启动期（booting）用 invoke("backend_ready") 探测（Tauri 通道，不走 HTTP），
//    后端就绪前不渲染主应用、不发任何 HTTP 请求 → 启动期零红色 error。
// 2) 就绪后（running）渲染主应用，并每 5s 健康检查，失联显示横幅 + 重启入口。
// 3) 超时保底（forced）：若 95s 仍连不上（后端可能彻底挂了），强制渲染主应用 + 横幅。
export default function BackendGuard({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("booting");
  const [status, setStatus] = useState<Status>("checking");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [restarting, setRestarting] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const timerRef = useRef<number | null>(null);

  // 探测后端是否就绪：Tauri 模式走 invoke（不记红），浏览器模式走 fetch（开发态无所谓）
  const checkBackend = async (): Promise<boolean> => {
    try {
      if (isTauri) {
        return (await invoke<boolean>("backend_ready")) === true;
      }
      await apiGet("/api/desktop/config", 4000);
      return true;
    } catch {
      return false;
    }
  };

  // 启动期快速探测（每 800ms）：后端就绪 → 直接切 running 渲染主应用；
  // 超时 95s 仍连不上（后端可能彻底挂了）→ 强制进入主应用（forced），避免永远 loading。
  useEffect(() => {
    let cancelled = false;
    const boot = window.setInterval(async () => {
      if (cancelled) return;
      const ok = await checkBackend();
      if (cancelled) return;
      if (ok) {
        setStatus("up");
        setErrorMsg("");
        setPhase("running");
      }
    }, 800);
    const to = window.setTimeout(() => {
      if (cancelled) return;
      setPhase("forced");
      setStatus("down");
    }, 95000);
    return () => {
      cancelled = true;
      window.clearInterval(boot);
      window.clearTimeout(to);
    };
  }, []);

  // 就绪后（running / forced）：每 5s 健康检查，维持横幅与状态按钮
  useEffect(() => {
    if (phase === "booting") return;
    timerRef.current = window.setInterval(async () => {
      const ok = await checkBackend();
      setStatus(ok ? "up" : "down");
      if (ok) setErrorMsg("");
    }, 5000);
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
  }, [phase]);

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
    setTimeout(() => {
      checkBackend().then((ok) => {
        if (ok) {
          setStatus("up");
          setPhase("running");
        } else {
          setStatus("down");
          setPhase("forced");
        }
      });
    }, 1500);
    setRestarting(false);
  };

  // 启动期：渲染 loading，不挂载主应用（避免首批请求在后端未就绪时失败记红）
  if (phase === "booting") {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-3 bg-white dark:bg-gray-900 text-gray-500 dark:text-gray-300">
        <RefreshCw size={36} className="animate-spin text-indigo-500" />
        <div className="text-sm">正在连接奶昔后端服务…</div>
        <div className="text-xs text-gray-400 dark:text-gray-500">
          首次启动需加载模型与技能，约需 30 秒，请稍候
        </div>
      </div>
    );
  }

  // 掉线横幅（可关闭）
  const showBanner = status === "down" && !bannerDismissed;

  return (
    <>
      {children}

      {/* ═══ 后端掉线横幅 ═══ */}
      {showBanner && (
        <div className="fixed top-9 left-0 right-0 z-50 flex items-center gap-2 px-3 py-2 bg-amber-50 border-b border-amber-300 text-amber-800 text-xs">
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
