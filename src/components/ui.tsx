import React from "react";
import { cn } from "@/lib/api";

/* ─── Card ─── */
interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}
export function Card({ className, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-sakura-100 bg-white shadow-sm",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/* ─── StatCard ─── */
interface StatCardProps {
  icon: React.ReactNode;
  value: string | number;
  label: string;
  sublabel: string;
  color: string;
}
export function StatCard({ icon, value, label, sublabel, color }: StatCardProps) {
  return (
    <Card className="p-4 flex-1 min-w-0">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-sakura-400 font-medium">{label}</p>
          <p className="text-2xl font-bold mt-1" style={{ color }}>
            {value}
          </p>
          <p className="text-xs text-green-600 mt-0.5">{sublabel}</p>
        </div>
        <div className="p-2 rounded-lg" style={{ backgroundColor: `${color}18`, color }}>
          {icon}
        </div>
      </div>
    </Card>
  );
}

/* ─── Badge ─── */
export function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-flex items-center text-xs rounded px-1.5 py-0.5 font-medium"
      style={{ background: `${color}18`, color }}
    >
      {text}
    </span>
  );
}

/* ─── StatusBadge ─── */
export function StatusBadge({ online, label }: { online: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`w-2 h-2 rounded-full ${online ? "bg-green-500" : "bg-red-400"}`}
      />
      <span className="text-xs text-sakura-400">{label || (online ? "运行中" : "离线")}</span>
    </span>
  );
}

/* ─── SectionTitle ─── */
export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-sm font-semibold text-sakura-500 mb-3">{children}</h3>
  );
}
