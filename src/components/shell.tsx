import { useState, useEffect } from "react";
import { cn } from "@/lib/api";
import { TopBar } from "@/components/TopBar";

/* ─── AppShell ─── */
export function AppShell({ sidebar, children, onNavigate }: { sidebar: React.ReactNode; children: React.ReactNode; onNavigate: (k: string) => void }) {
  return (
    <div className="flex h-screen flex-col bg-sakura-50">
      <TopBar onNavigate={onNavigate} />
      <div className="flex flex-1 overflow-hidden pt-9">
        {sidebar}
        <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
      </div>
    </div>
  );
}

/* ─── Sidebar ─── */
interface NavItem { key: string; icon: React.ReactNode; label: string; }
export function Sidebar({ items, activeNav, onNavChange, version }: {
  items: NavItem[]; activeNav: string; onNavChange: (k: string) => void; version?: string;
}) {
  return (
    <aside className="w-48 min-w-[12rem] bg-white border-r border-sakura-100 flex flex-col">
      <div className="px-4 pt-5 pb-4 border-b border-sakura-100">
        <h1 className="text-base font-bold text-sakura-500 tracking-wide">奶昔</h1>
        <p className="text-[11px] text-sakura-300 mt-0.5">Naixi</p>
      </div>
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {items.map((item) => (
          <button
            key={item.key}
            onClick={() => onNavChange(item.key)}
            className={cn(
              "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors",
              activeNav === item.key
                ? "bg-sakura-100 text-sakura-600 font-semibold"
                : "text-sakura-500 hover:bg-sakura-50 hover:text-sakura-600"
            )}
          >
            <span className="shrink-0 w-4 h-4 flex items-center justify-center">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      {version && (
        <div className="p-3 border-t border-sakura-100">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-[11px] text-sakura-400">{version}</span>
          </div>
        </div>
      )}
    </aside>
  );
}

/* ─── Header ─── */
export function Header({ children, className }: { children?: React.ReactNode; className?: string }) {
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const onScroll = () => setOffset(window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <header className={cn("sticky top-0 z-20 h-14 transition-shadow duration-200", offset > 10 ? "shadow-sm" : "shadow-none", className)}>
      <div className={cn(
        "relative flex h-full items-center gap-3 px-4 sm:gap-4",
        offset > 10 && "after:absolute after:inset-0 after:-z-10 after:bg-white/70 after:backdrop-blur-lg"
      )}>
        {children}
      </div>
    </header>
  );
}

/* ─── Main ─── */
export function Main({ children, className, fluid }: { children: React.ReactNode; className?: string; fluid?: boolean }) {
  return (
    <main className={cn("flex-1 overflow-y-auto px-4 py-6", className)}>
      <div className={cn("h-full", !fluid && "mx-auto w-full max-w-7xl")}>{children}</div>
    </main>
  );
}
