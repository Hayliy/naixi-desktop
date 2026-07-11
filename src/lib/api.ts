import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const API_BASE = typeof import.meta !== 'undefined' && (import.meta as any).env?.DEV ? "" : "http://127.0.0.1:9845";

export async function apiGet<T>(path: string, timeoutMs = 10000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, { mode: "cors", signal: ctrl.signal });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

export async function apiPost<T>(path: string, body: unknown, timeoutMs = 30000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

export interface StatusData {
  napcat_connected: boolean;
  version: string;
  trust_total: number;
  trust_rate: number;
  knowledge_items: number;
  knowledge_cats: number;
  tools: number;
  skills: number;
  trust_level: number;
  experiences: number;
  agents: number;
  cases: number;
}
