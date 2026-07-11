/* ─── 聊天模块共用类型 ─── */
import type { ContentBlock } from "@/components/ContentRenderer";

export interface ConvItem { key: string; last_role: string; last_msg: string; last_time: number; }
export interface MsgItem { id: number; role: string; content: string; content_blocks?: ContentBlock[] | null; time: number; }
export interface ProviderModel { key: string; label: string; provider_id: number; }

export function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diff = (now.getTime() - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function convName(key: string, msgs?: MsgItem[], customName?: string) {
  if (customName) return customName;
  if (msgs && msgs.length > 0) {
    const first = msgs.find(m => m.role === "user");
    if (first) {
      const txt = first.content.replace(/^\[[^\]]+\]\s*:\s*/, "").slice(0, 20);
      return txt + (txt.length >= 20 ? "..." : "");
    }
  }
  const parts = key.split(":");
  if (parts.length < 2) return key;
  const id = parts[1];
  if (parts[0] === "group") return `群聊 ${id.slice(-4)}`;
  if (parts[0] === "user") return `私聊 ${id.slice(-4)}`;
  if (parts[0] === "auto") return `自动: ${id.replace(/_/g, " ").slice(0, 15)}`;
  return "新对话";
}

import { ImageIcon, Video, Music, Code, Globe } from "lucide-react";
export const QUICK_ACTIONS = [
  { icon: ImageIcon, label: "画图", color: "text-pink-500", bg: "bg-pink-50", template: "画一张" },
  { icon: Video, label: "视频", color: "text-sakura-500", bg: "bg-sakura-50", template: "生成一段视频：" },
  { icon: Music, label: "语音", color: "text-blue-500", bg: "bg-blue-50", template: "用语音说：" },
  { icon: Code, label: "代码", color: "text-green-500", bg: "bg-green-50", template: "写一段代码：" },
  { icon: Globe, label: "搜索", color: "text-amber-500", bg: "bg-amber-50", template: "搜索一下：" },
];
