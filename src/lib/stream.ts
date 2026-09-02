import { API_BASE } from "./api";
import type { ContentBlock } from "@/components/ContentRenderer";

/* ─── StreamProcessor 状态 ─── */
export interface StreamState {
  contentBlocks: ContentBlock[];
  currentText: ContentBlock | null;
  currentReasoning: ContentBlock | null;
  usage: { input?: number; output?: number } | null;
}

export function createInitialState(): StreamState {
  return { contentBlocks: [], currentText: null, currentReasoning: null, usage: null };
}

/* ─── 处理单个 SSE chunk（仿 Chatbox processStreamChunk） ─── */
export function processStreamChunk(
  eventType: string,
  data: Record<string, unknown>,
  state: StreamState
): { state: StreamState; skipRender: boolean } {
  let { contentBlocks, currentText, currentReasoning, usage } = state;
  const skipRender = eventType === "status" || eventType === "finish";

  switch (eventType) {
    case "text-delta": {
      const text = String(data.text || "");
      currentReasoning = null;
      if (currentText) {
        contentBlocks = contentBlocks.map(b =>
          b === currentText ? { ...b, text: (b.text || "") + text } : b
        );
        currentText = contentBlocks[contentBlocks.length - 1];
      } else {
        const block: ContentBlock = { type: "text", text };
        contentBlocks = [...contentBlocks, block];
        currentText = block;
      }
      break;
    }
    case "reasoning": {
      const text = String(data.text || "");
      if (currentReasoning) {
        contentBlocks = contentBlocks.map(b =>
          b === currentReasoning ? { ...b, text: (b.text || "") + text } : b
        );
        currentReasoning = contentBlocks[contentBlocks.length - 1];
      } else {
        const block: ContentBlock = { type: "reasoning", text };
        contentBlocks = [...contentBlocks, block];
        currentReasoning = block;
      }
      break;
    }
    case "tool_use": {
      currentText = null;
      currentReasoning = null;
      const block: ContentBlock = {
        type: "tool_use",
        name: String(data.name || ""),
        args: data.args as Record<string, unknown> || {},
        id: String(data.id || ""),
        state: "loading",
      };
      contentBlocks = [...contentBlocks, block];
      break;
    }
    case "tool_result": {
      const callId = String(data.tool_call_id || "");
      contentBlocks = contentBlocks.map(b =>
        b.type === "tool_use" && b.id === callId
          ? { ...b, type: "tool_result" as const, content: String(data.content || ""), state: "done" }
          : b
      );
      break;
    }
    case "status": {
      const block: ContentBlock = {
        type: "status",
        state: (data.state as "loading" | "done" | "error") || "loading",
        text: String(data.text || ""),
      };
      // Replace last status block if exists
      const last = contentBlocks[contentBlocks.length - 1];
      if (last?.type === "status") {
        contentBlocks = contentBlocks.map((b, i) =>
          i === contentBlocks.length - 1 ? block : b
        );
      } else {
        contentBlocks = [...contentBlocks, block];
      }
      break;
    }
    case "finish": {
      usage = (data.usage as { input?: number; output?: number }) || null;
      // Remove trailing status blocks
      contentBlocks = contentBlocks.filter(b => b.type !== "status");
      currentText = null;
      currentReasoning = null;
      break;
    }
    case "image": {
      const block: ContentBlock = { type: "image", url: String(data.url || "") };
      contentBlocks = [...contentBlocks, block];
      break;
    }
  }

  return { state: { contentBlocks, currentText, currentReasoning, usage }, skipRender };
}

/* ─── SSE 流解析 ─── */
export interface SSEChunk {
  eventType: string;
  data: Record<string, unknown>;
}

export async function* parseSSEStream(reader: ReadableStreamDefaultReader<Uint8Array>): AsyncGenerator<SSEChunk> {
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    let eventType = "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try {
          yield { eventType, data: JSON.parse(raw) };
        } catch { /* skip malformed */ }
      }
    }
  }
}

/* ─── 发送消息 + StreamProcessor 回调 ─── */
export interface StreamCallbacks {
  onUpdate: (blocks: ContentBlock[], generating: boolean, usage?: { input?: number; output?: number } | null) => void;
  onDone: (usage?: { input?: number; output?: number } | null) => void;
  onError: (err: string) => void;
  onPermissionRequest?: (reqId: string, name: string, args: Record<string, unknown>) => void;
}

export async function sendChatStream(
  url: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  try {
    const res = await fetch(url.startsWith("http") ? url : `${API_BASE}${url}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });

    if (!res.ok) {
      callbacks.onError(`HTTP ${res.status}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      callbacks.onError("无法读取响应流");
      return;
    }

    const state = createInitialState();

    for await (const { eventType, data } of parseSSEStream(reader)) {
      const { state: newState, skipRender } = processStreamChunk(eventType, data, state);

      // Handle permission request events
      if (eventType === "permission_request" && callbacks.onPermissionRequest) {
        callbacks.onPermissionRequest(
          String(data.id || ""),
          String(data.name || ""),
          (data.args || {}) as Record<string, unknown>
        );
      }

      // Update state in place
      Object.assign(state, newState);

      if (!skipRender) {
        callbacks.onUpdate(state.contentBlocks, true);
      }
    }

    // Streaming complete
    callbacks.onUpdate(state.contentBlocks, false, state.usage);
    callbacks.onDone(state.usage);
  } catch (err) {
    callbacks.onError(String(err));
  }
}
