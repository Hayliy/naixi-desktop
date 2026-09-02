import { useEffect, useRef, useState, useCallback } from "react";
import { cn, apiPost, apiGet } from "@/lib/api";
import { useToast } from "@/components/Toast";

/**
 * 自绘顶栏（奶昔桌面端 · 适配真实功能面）
 * - decorations:false 无边框窗口下提供：拖拽区 + 6 栏菜单 + 窗口按钮（同一行，Edge 风格）
 * - 严格遵循前端 Tauri API 安全铁则：绝不在渲染期调用 getCurrentWindow()，
 *   一律在 async 事件处理器内动态 import + isTauri 守卫 + try/catch。
 * - 菜单内容对标前端 NAV_ITEMS（12 面板）与后端 api.py 真实端点：导航 / 桌宠 / 生成 / 直播 / 系统 / 帮助。
 */

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function getWin() {
  if (!isTauri) return null;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    return getCurrentWindow();
  } catch {
    return null;
  }
}

type MenuItem = { label: string; action: () => void; shortcut?: string };
type MenuCol = { id: string; label: string; accel: string; items: (MenuItem | "sep")[] };

function DevRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-md bg-sakura-50/40 px-2.5 py-1.5">
      <span className="text-xs text-sakura-400">{label}</span>
      <span className="max-w-[60%] truncate text-right text-xs font-medium text-sakura-500" title={value}>{value}</span>
    </div>
  );
}

export function TopBar({ onNavigate }: { onNavigate: (k: string) => void }) {
  const { notify } = useToast();
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [altOn, setAltOn] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const menusRef = useRef<HTMLDivElement | null>(null);

  /* ── 窗口控制（动态导入 + 守卫）── */
  const minimize = useCallback(async () => {
    const w = await getWin();
    try { await w?.minimize(); } catch {}
  }, []);
  const toggleMax = useCallback(async () => {
    const w = await getWin();
    try {
      if (await w?.isMaximized()) await w?.unmaximize();
      else await w?.maximize();
    } catch {}
  }, []);
  const closeWin = useCallback(async () => {
    const w = await getWin();
    try { await w?.close(); } catch {}
  }, []);
  const toggleFullscreen = useCallback(async () => {
    const w = await getWin();
    try {
      const f = await w?.isFullscreen();
      await w?.setFullscreen(!f);
    } catch {}
  }, []);
  const restartBackend = useCallback(async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("restart_backend");
      notify("正在重启奶昔后端…", "info");
    } catch {
      notify("重启后端失败（非 Tauri 环境或后端未就绪）", "error");
    }
  }, [notify]);

  /* ── 生成弹窗（文生图/视频/语音，直接调真实端点）── */
  const [genOpen, setGenOpen] = useState(false);
  const [genType, setGenType] = useState<"image" | "video" | "voice">("image");
  const [genPrompt, setGenPrompt] = useState("");
  const [genResult, setGenResult] = useState<string | null>(null);
  const [genLoading, setGenLoading] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);
  const [sceneAuto, setSceneAuto] = useState(false);

  const openGen = (t: "image" | "video" | "voice") => {
    setGenType(t); setGenPrompt(""); setGenResult(null); setGenErr(null); setGenOpen(true);
  };
  const runGenerate = useCallback(async () => {
    if (!genPrompt.trim()) { setGenErr("请输入提示词"); return; }
    setGenLoading(true); setGenErr(null); setGenResult(null);
    try {
      const path = genType === "image" ? "/api/generate_image" : genType === "video" ? "/api/generate_video" : "/api/generate_voice";
      const body = genType === "voice" ? { text: genPrompt } : { prompt: genPrompt };
      const j: any = await apiPost(path, body);
      if (j && j.error) { setGenErr(j.error); return; }
      if (genType === "image") setGenResult(j.url);
      else if (genType === "voice") setGenResult(`data:audio/${j.format};base64,${j.audio}`);
      else setGenResult(j.url || JSON.stringify(j)); // 视频为异步任务
    } catch (e: any) {
      setGenErr(String(e?.message || e));
    } finally {
      setGenLoading(false);
    }
  }, [genType, genPrompt]);

  /* ── 桌宠事件（pet 是 /pet 路由页，经全局事件驱动控制）── */
  const emitPet = (name: string) => {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(name));
  };
  const openConfigDir = useCallback(async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_config_dir");
    } catch {
      notify("打开配置目录失败（非 Tauri 环境）", "error");
    }
  }, [notify]);

  const RELEASES_URL = "https://github.com/Hayliy/naixi-desktop/releases";
  /* ── 版本更新 / 开发者工具（帮助菜单）── */
  const [verOpen, setVerOpen] = useState(false);
  const [verLoading, setVerLoading] = useState(false);
  const [verData, setVerData] = useState<{ version: string; changelog: any[] }>({ version: "0.1.0", changelog: [] });
  const [verCheck, setVerCheck] = useState<{ status: "idle" | "checking" | "done" | "error"; data?: any; msg?: string }>({ status: "idle" });
  const [devOpen, setDevOpen] = useState(false);
  const [devLoading, setDevLoading] = useState(false);
  const [devData, setDevData] = useState<{ stats: any; sysinfo: any }>({ stats: null, sysinfo: null });
  const [isDebug, setIsDebug] = useState(false);

  const fmtTs = (ts: number) => {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  const openVersion = useCallback(async () => {
    setVerOpen(true); setVerLoading(true);
    try {
      const [ver, clog] = await Promise.all([
        (async () => {
          if (!isTauri) return "0.1.0";
          try { const { getVersion } = await import("@tauri-apps/api/app"); return await getVersion(); }
          catch { return "0.1.0"; }
        })(),
        apiGet<any>("/api/ops/changelog?limit=30").catch(() => ({ changelog: [] })),
      ]);
      setVerData({ version: ver || "0.1.0", changelog: clog?.changelog || [] });
    } catch {
      setVerData({ version: "0.1.0", changelog: [] });
    } finally {
      setVerLoading(false);
    }
  }, []);

  const checkUpdate = useCallback(async () => {
    setVerCheck({ status: "checking" });
    try {
      const res = await apiGet<any>(`/api/check_update?current=${encodeURIComponent(verData.version || "0.1.0")}`);
      setVerCheck({ status: res.ok ? "done" : "error", data: res, msg: res.error || res.message });
    } catch (e: any) {
      setVerCheck({ status: "error", msg: String(e?.message || e) });
    }
  }, [verData.version]);

  const openReleaseUrl = useCallback(async (url: string) => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_url", { url });
    } catch {
      try { window.open(url, "_blank"); } catch {}
    }
  }, []);

  const openDevTools = useCallback(async () => {
    setDevOpen(true); setDevLoading(true);
    try {
      const [stats, sysinfo] = await Promise.all([
        apiGet<any>("/api/stats").catch(() => null),
        apiGet<any>("/api/system_info").catch(() => null),
      ]);
      setDevData({ stats, sysinfo });
    } catch {
      setDevData({ stats: null, sysinfo: null });
    } finally {
      setDevLoading(false);
    }
  }, []);

  const openWebviewDevtools = useCallback(async () => {
    if (!isTauri) { notify("开发者工具仅在 Tauri 环境中可用", "error"); return; }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_devtools");
    } catch (e) {
      notify("开发者工具打开失败：" + (e?.message || String(e) || "未知错误"), "error");
    }
  }, [notify]);

  /* ── 判断是否为调试构建（release 下隐藏「开发者工具」）── */
  useEffect(() => {
    (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const d = await invoke<boolean>("is_debug");
        setIsDebug(d);
      } catch { setIsDebug(false); }
    })();
  }, []);

  /* ── 同步最大化状态（图标随窗口状态切换）── */
  useEffect(() => {
    let un: (() => void) | null = null;
    (async () => {
      const w = await getWin();
      if (!w) return;
      try { setMaximized(await w.isMaximized()); } catch {}
      try {
        un = await w.onResized(async () => {
          try { setMaximized(await w.isMaximized()); } catch {}
        });
      } catch {}
    })();
    return () => { if (un) un(); };
  }, []);

  /* ── 点击菜单外部关闭下拉 ── */
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menusRef.current && !menusRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  /* ── 键盘：访问键(Alt+字母) + 快捷键 ── */
  useEffect(() => {
    const accelMap: Record<string, string> = {
      n: "nav", p: "pet", g: "gen", l: "live", s: "sys", h: "help",
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const ak = e.key.toLowerCase();
        if (accelMap[ak]) { e.preventDefault(); setOpenMenu(accelMap[ak]); return; }
      }
      if (e.key === "Alt") setAltOn(true);
      if (e.key === "F10") { e.preventDefault(); setOpenMenu("nav"); return; }
      const ctrl = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (ctrl && e.shiftKey && k === "r") { e.preventDefault(); restartBackend(); return; }
      if (ctrl && k === "q") { e.preventDefault(); closeWin(); return; }
      if (k === "f11") { e.preventDefault(); toggleFullscreen(); return; }
      if (k === "f1") {
        e.preventDefault();
        notify("顶栏菜单：导航 / 桌宠 / 生成 / 直播 / 系统 / 帮助；按 Alt+字母 打开对应菜单", "info");
        return;
      }
      if (e.key === "Escape") { setOpenMenu(null); setAboutOpen(false); }
    };
    const onKeyUp = (e: KeyboardEvent) => { if (e.key === "Alt") setAltOn(false); };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("keyup", onKeyUp);
    };
  }, [restartBackend, closeWin, toggleFullscreen, notify]);

  /* ── 菜单数据（适配奶昔真实功能面）── */
  const MENUS: MenuCol[] = [
    {
      id: "nav", label: "导航", accel: "n",
      items: ([
        ["dashboard", "仪表盘"], ["chat", "对话"], ["workflow", "工作流"],
        ["scheduler", "自动化"], ["knowledge", "知识库"], ["tools", "工具"],
        ["memory", "记忆"], ["connection", "连接"], ["ops", "运维"],
        ["live", "直播"], ["logs", "日志"], ["settings", "设置"],
      ] as [string, string][]).map(([k, l]) => ({ label: l, action: () => onNavigate(k) })),
    },
    {
      id: "pet", label: "桌宠", accel: "p",
      items: [
        { label: "显示桌宠", action: () => onNavigate("pet") },
        { label: "隐藏桌宠", action: () => onNavigate("dashboard") },
        { label: "鼠标穿透", action: () => { emitPet("naixi:pet:toggle-clickthrough"); notify("已切换桌宠鼠标穿透", "info"); } },
        "sep",
        { label: "切换模型", action: () => { emitPet("naixi:pet:next-model"); notify("已切换桌宠模型", "info"); } },
      ],
    },
    {
      id: "gen", label: "生成", accel: "g",
      items: [
        { label: "文生图", action: () => openGen("image") },
        { label: "文生视频", action: () => openGen("video") },
        { label: "文生语音", action: () => openGen("voice") },
      ],
    },
    {
      id: "live", label: "直播", accel: "l",
      items: [
        { label: "启动引擎", action: () => { apiPost("/api/live/start", {}).then(() => notify("直播引擎已启动", "info")).catch(() => notify("启动失败", "error")); } },
        { label: "保存配置", action: () => { apiPost("/api/live/save-config", {}).then(() => notify("直播配置已保存", "info")).catch(() => notify("保存失败", "error")); } },
        { label: "看视频反应 开/关", action: async () => { const next = !sceneAuto; setSceneAuto(next); try { await apiPost("/api/live/scene-auto", { enabled: next }); notify(next ? "场景感知已开启" : "场景感知已关闭", "info"); } catch { notify("操作失败", "error"); } } },
      ],
    },
    {
      id: "sys", label: "系统", accel: "s",
      items: [
        { label: "重启后端", shortcut: "Ctrl+Shift+R", action: () => restartBackend() },
        { label: "重启 SearXNG", action: () => { apiPost("/api/system/restart_searxng", {}).then(() => notify("SearXNG 重启中…", "info")).catch(() => notify("SearXNG 重启失败", "error")); } },
        { label: "打开配置目录", action: () => openConfigDir() },
        { label: "查看日志", action: () => onNavigate("logs") },
        "sep",
        { label: "全屏", shortcut: "F11", action: () => toggleFullscreen() },
        { label: "退出", shortcut: "Ctrl+Q", action: () => closeWin() },
      ],
    },
    {
      id: "help", label: "帮助", accel: "h",
      items: [
        { label: "使用帮助", shortcut: "F1", action: () => notify("顶栏菜单：导航 / 桌宠 / 生成 / 直播 / 系统 / 帮助；按 Alt+字母 打开对应菜单", "info") },
        { label: "版本更新", action: () => openVersion() },
        { label: "开发者工具", action: () => openDevTools() },
        { label: "关于", action: () => setAboutOpen(true) },
      ],
    },
  ];

  return (
    <>
      <div className="fixed top-0 left-0 right-0 z-[60] flex h-9 shrink-0 select-none items-center border-b border-sakura-100 bg-white px-1 text-sakura-600">
        {/* 拖拽区：logo + 标题（data-tauri-drag-region 触发窗口拖动） */}
        <div data-tauri-drag-region className="flex h-full items-center gap-2 pl-1.5 cursor-pointer" onDoubleClick={toggleMax} title="双击最大化/还原 · 拖拽移动窗口">
          <img src="/naixi-logo.png" className="h-5 w-5 rounded-full object-cover shadow-[0_0_0_2px_#fff,0_0_0_3px_#ffe1ec]" alt="Naixi" />
          <span className="whitespace-nowrap text-[13px] font-semibold">奶昔 · Naixi</span>
        </div>

        {/* 菜单栏 */}
        <div ref={menusRef} className="flex h-full">
          {MENUS.map((col) => (
            <div key={col.id} className="relative h-full">
              <button
                onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === col.id ? null : col.id); }}
                className={cn(
                  "flex h-full items-center px-2.5 text-[12px] hover:bg-sakura-50",
                  openMenu === col.id && "bg-sakura-50"
                )}
              >
                <span>{col.label}</span>
                <span className={cn("ml-0.5 text-[11px] text-sakura-300", altOn && "underline underline-offset-2")}>
                  ({col.accel.toUpperCase()})
                </span>
              </button>
              {openMenu === col.id && (
                <div className="absolute left-0 top-9 z-40 min-w-[184px] rounded-lg border border-sakura-100 bg-white py-1 shadow-[0_8px_22px_rgba(236,72,153,0.18)]">
                  {col.items.map((it, i) =>
                    it === "sep" ? (
                      <div key={i} className="my-1 h-px bg-sakura-100" />
                    ) : (
                      <button
                        key={i}
                        onClick={(e) => { e.stopPropagation(); it.action(); setOpenMenu(null); }}
                        className="flex w-full items-center justify-between gap-5 px-3.5 py-1.5 text-left text-[12px] text-sakura-500 hover:bg-sakura-50"
                      >
                        <span>{it.label}</span>
                        {it.shortcut && <span className="text-[11px] text-sakura-300">{it.shortcut}</span>}
                      </button>
                    )
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* 拖拽区：菜单与窗口按钮之间的空白 */}
        <div data-tauri-drag-region className="h-full flex-1" />

        {/* 窗口按钮 */}
        <div className="flex h-full">
          <button
            onClick={minimize}
            title="最小化"
            className="flex h-full w-10 items-center justify-center hover:bg-sakura-50"
          >
            <svg width="11" height="11" viewBox="0 0 12 12"><line x1="2" y1="6" x2="10" y2="6" stroke="currentColor" strokeWidth="1.3" /></svg>
          </button>
          <button
            onClick={toggleMax}
            title={maximized ? "还原" : "最大化"}
            className="flex h-full w-10 items-center justify-center hover:bg-sakura-50"
          >
            {maximized ? (
              <svg width="11" height="11" viewBox="0 0 12 12"><rect x="4.2" y="3.2" width="5.3" height="5.3" fill="none" stroke="currentColor" strokeWidth="1.1" /><rect x="2.3" y="2.3" width="5.3" height="5.3" fill="none" stroke="currentColor" strokeWidth="1.1" /></svg>
            ) : (
              <svg width="11" height="11" viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
            )}
          </button>
          <button
            onClick={closeWin}
            title="关闭"
            className="flex h-full w-10 items-center justify-center hover:bg-rose-500 hover:text-white"
          >
            <svg width="11" height="11" viewBox="0 0 12 12"><line x1="3" y1="3" x2="9" y2="9" stroke="currentColor" strokeWidth="1.3" /><line x1="9" y1="3" x2="3" y2="9" stroke="currentColor" strokeWidth="1.3" /></svg>
          </button>
        </div>
      </div>

      {/* 关于弹窗 */}
      {aboutOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setAboutOpen(false)}>
          <div className="w-80 rounded-2xl bg-white p-6 text-center shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <img src="/naixi-logo.png" className="mx-auto mb-3 h-12 w-12 rounded-full object-cover shadow-[0_0_0_4px_#fff0f5]" alt="Naixi" />
            <h2 className="text-base font-bold text-sakura-500">奶昔 · Naixi</h2>
            <p className="mt-2 text-xs leading-relaxed text-sakura-400">
              桌面智能体 · 看屏操控 / 对话 / 工作流 / 直播反应。<br />
              顶栏菜单已适配奶昔真实功能面（导航 / 桌宠 / 生成 / 直播 / 系统 / 帮助）。
            </p>
            <button
              onClick={() => setAboutOpen(false)}
              className="mt-4 rounded-lg bg-sakura-500 px-5 py-1.5 text-sm text-white hover:bg-sakura-600"
            >
              知道了
            </button>
          </div>
        </div>
      )}

      {/* 生成弹窗：文生图/视频/语音，直接调真实后端端点 */}
      {genOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40" onClick={() => setGenOpen(false)}>
          <div className="w-[420px] rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 text-sm font-bold text-sakura-500">
              {genType === "image" ? "文生图" : genType === "video" ? "文生视频" : "文生语音"}
            </h2>
            <textarea
              value={genPrompt}
              onChange={(e) => setGenPrompt(e.target.value)}
              placeholder={genType === "voice" ? "输入要合成的文本…" : "输入提示词…"}
              className="h-24 w-full resize-none rounded-lg border border-sakura-100 p-2 text-xs text-sakura-600 outline-none focus:border-sakura-300"
            />
            <div className="mt-3 flex items-center justify-end gap-2">
              <button onClick={() => setGenOpen(false)} className="rounded-lg px-3 py-1.5 text-xs text-sakura-400 hover:bg-sakura-50">取消</button>
              <button
                onClick={runGenerate}
                disabled={genLoading}
                className="rounded-lg bg-sakura-500 px-4 py-1.5 text-xs text-white hover:bg-sakura-600 disabled:opacity-50"
              >
                {genLoading ? "生成中…" : "生成"}
              </button>
            </div>
            {genErr && <p className="mt-3 text-xs text-rose-500">{genErr}</p>}
            {genResult && genType === "image" && (
              <img src={genResult} alt="生成结果" className="mt-3 max-h-64 w-full rounded-lg object-contain" />
            )}
            {genResult && genType === "voice" && (
              <audio controls src={genResult} className="mt-3 w-full" />
            )}
            {genResult && genType === "video" && (
              <p className="mt-3 break-all text-xs text-sakura-500">视频为异步任务，结果：{genResult}</p>
            )}
          </div>
        </div>
      )}

      {/* 版本更新弹窗：当前版本 + 变更记录 + 离线说明 */}
      {verOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40" onClick={() => setVerOpen(false)}>
          <div className="flex max-h-[80vh] w-[460px] flex-col rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-bold text-sakura-500">版本更新</h2>
              <button
                onClick={checkUpdate}
                disabled={verCheck.status === "checking"}
                className="rounded-lg bg-sakura-500 px-3 py-1 text-xs text-white hover:bg-sakura-600 disabled:opacity-50"
              >
                {verCheck.status === "checking" ? "检查中…" : "检查更新"}
              </button>
            </div>
            <div className="mb-3 flex items-center gap-2 text-xs text-sakura-400">
              <span className="rounded bg-sakura-50 px-2 py-0.5 font-semibold text-sakura-500">当前版本 v{verData?.version || "0.1.0"}</span>
            </div>
            <div className="mb-3 rounded-lg border border-sakura-100 bg-sakura-50/50 p-3 text-xs leading-relaxed text-sakura-400">
              默认从 GitHub Releases（Hayliy/naixi-desktop）检查更新。如需用自己的更新源，可在「设置」中配置 desktop_config.update_source（返回 {"{ version, notes, url }"} 的 JSON 地址）覆盖默认源。
            </div>
            {verCheck.status === "done" && verCheck.data?.configured === true && verCheck.data?.has_update === true && (
              <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs leading-relaxed text-emerald-600">
                <div className="font-semibold">发现新版本 v{verCheck.data.latest}{verCheck.data.published_at ? `（发布于 ${verCheck.data.published_at}）` : ""}</div>
                {verCheck.data.notes && <div className="mt-1 whitespace-pre-wrap">{verCheck.data.notes}</div>}
                {verCheck.data.url && (
                  <button onClick={() => openReleaseUrl(verCheck.data.url)} className="mt-2 rounded-lg bg-emerald-500 px-3 py-1 text-white hover:bg-emerald-600">前往发布页</button>
                )}
              </div>
            )}
            {verCheck.status === "done" && verCheck.data?.configured === true && verCheck.data?.has_update === false && (
              <div className="mb-3 rounded-lg border border-sakura-100 bg-sakura-50 p-3 text-xs leading-relaxed text-sakura-400">已是最新版本（v{verCheck.data.current}）</div>
            )}
            {verCheck.status === "error" && (
              <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-500">检查失败：{verCheck.msg}</div>
            )}
            <div className="mb-3 flex justify-end">
              <button
                onClick={() => openReleaseUrl(verCheck.data?.releases_url || RELEASES_URL)}
                className="rounded-lg border border-sakura-200 px-3 py-1 text-xs text-sakura-500 hover:bg-sakura-50"
              >前往发布页（GitHub）</button>
            </div>
            <div className="mb-2 text-xs font-semibold text-sakura-500">近期变更</div>
            <div className="flex-1 overflow-y-auto rounded-lg border border-sakura-100 p-2">
              {verLoading ? (
                <div className="p-4 text-center text-xs text-sakura-300">加载中…</div>
              ) : verData?.changelog?.length ? (
                <ul className="space-y-2">
                  {verData.changelog.map((c: any) => (
                    <li key={c.id} className="text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-sakura-500">{c.action}{c.target ? ` · ${c.target}` : ""}</span>
                        <span className="shrink-0 text-sakura-300">{fmtTs(c.ts)}</span>
                      </div>
                      {c.detail && <div className="mt-0.5 text-sakura-400">{c.detail}</div>}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="p-4 text-center text-xs text-sakura-300">暂无变更记录</div>
              )}
            </div>
            <div className="mt-4 flex items-center justify-end">
              <button onClick={() => setVerOpen(false)} className="rounded-lg bg-sakura-500 px-4 py-1.5 text-xs text-white hover:bg-sakura-600">关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* 开发者工具弹窗：后端/运行时状态 + 打开 Webview 开发者工具 */}
      {devOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40" onClick={() => setDevOpen(false)}>
          <div className="flex max-h-[82vh] w-[480px] flex-col rounded-2xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-1 text-sm font-bold text-sakura-500">开发者工具</h2>
            <div className="mb-2 text-xs text-sakura-400">构建模式：{isDebug ? "调试版 (Debug)" : "发布版 (Release)"}</div>
            <div className="flex-1 space-y-2 overflow-y-auto">
              {devLoading ? (
                <div className="p-4 text-center text-xs text-sakura-300">加载中…</div>
              ) : (
                <>
                  <DevRow label="后端版本" value={devData?.stats?.backend?.version || "—"} />
                  <DevRow label="后端 PID" value={String(devData?.stats?.backend?.pid ?? "—")} />
                  <DevRow label="后端内存" value={`${devData?.stats?.backend?.memory_mb ?? "?"} MB`} />
                  <DevRow label="Python" value={devData?.sysinfo?.python || "—"} />
                  <DevRow label="主机名" value={devData?.sysinfo?.hostname || "—"} />
                  <DevRow label="操作系统" value={devData?.sysinfo?.os || "—"} />
                  <DevRow label="后端 API (9845)" value={devData?.stats?.services?.["后端API"] ? "在线" : "离线"} />
                  <DevRow label="SearXNG (8899)" value={devData?.stats?.services?.["SearXNG"] ? "在线" : "离线"} />
                  <DevRow label="模型提供商" value={`${devData?.stats?.providers?.with_key ?? 0}/${devData?.stats?.providers?.total ?? 0} 已配密钥`} />
                  <DevRow label="数据库" value={`${devData?.stats?.database?.size_mb ?? 0} MB`} />
                </>
              )}
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              <button onClick={openWebviewDevtools} className="rounded-lg border border-sakura-200 px-3 py-1.5 text-xs text-sakura-500 hover:bg-sakura-50">Webview 开发者工具</button>
              <button onClick={() => openConfigDir()} className="rounded-lg border border-sakura-200 px-3 py-1.5 text-xs text-sakura-500 hover:bg-sakura-50">打开配置目录</button>
              <button onClick={() => setDevOpen(false)} className="rounded-lg bg-sakura-500 px-4 py-1.5 text-xs text-white hover:bg-sakura-600">关闭</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
