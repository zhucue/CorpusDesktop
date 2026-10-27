import type { AgentMessage, MessagePart, ToolCall } from "../../api";
import type { SseEvent } from "./sse";

export type ChainStatus = "running" | "done" | "stopped" | "error";

/** Assistant message as rendered: built from SSE events while running, or from a stored Message. */
export interface ChainMessage {
  id: string;
  status: ChainStatus;
  parts: MessagePart[];
  tools: ToolCall[];
  startedAt: number;
  /** When the answer started (thinking chain collapses); null while thinking. */
  answerAt: number | null;
  durationMs: number | null;
  error: { code: string; message: string } | null;
  stopRequested?: boolean;
}

export function newChain(now: number): ChainMessage {
  return { id: "", status: "running", parts: [], tools: [], startedAt: now, answerAt: null, durationMs: null, error: null };
}

export function fromMessage(m: AgentMessage): ChainMessage {
  const created = Date.parse(m.created_at) || 0;
  const cancelled = m.tool_calls.some((t) => t.state === "cancelled");
  return {
    id: m.id,
    status: m.tool_calls.some((t) => t.state === "running") ? "running" : cancelled ? "stopped" : "done",
    parts: m.parts ?? (m.content ? [{ type: "text", text: m.content }] : []),
    tools: m.tool_calls ?? [],
    startedAt: created,
    answerAt: null,
    durationMs: m.duration_ms ?? null,
    error: null,
  };
}

function appendPart(parts: MessagePart[], type: MessagePart["type"], index: number, delta: string): MessagePart[] {
  const next = parts.slice();
  while (next.length < index) next.push({ type: "text", text: "" });
  const cur = next[index];
  if (!cur || cur.type !== type) next[index] = type === "ui" ? { type: "ui", lang: delta } : { type, text: delta };
  else if (cur.type === "ui") next[index] = { type: "ui", lang: cur.lang + delta };
  else next[index] = { ...cur, text: cur.text + delta };
  return next;
}

function upsertTool(tools: ToolCall[], call: ToolCall): ToolCall[] {
  const i = tools.findIndex((t) => t.id === call.id);
  if (i < 0) return [...tools, call];
  const next = tools.slice();
  next[i] = { ...tools[i], ...call };
  return next;
}

/** Fold one SSE event (start / thinking / tool_call / tool_result / text / ui / done / error) into the message. */
export function applyEvent(m: ChainMessage, e: SseEvent, now: number): ChainMessage {
  let data: Record<string, unknown> = {};
  try {
    data = e.data ? JSON.parse(e.data) : {};
  } catch {
    return m;
  }
  switch (e.event) {
    case "start":
      return { ...m, id: String(data.message_id ?? m.id) };
    case "thinking":
    case "text":
    case "ui": {
      const delta = String(data.delta ?? "");
      const index = typeof data.part === "number" ? data.part : Math.max(0, m.parts.length - (m.parts.at(-1)?.type === e.event ? 1 : 0));
      const parts = appendPart(m.parts, e.event as MessagePart["type"], index, delta);
      const answering = e.event !== "thinking" && !m.tools.some((t) => t.state === "running");
      return { ...m, parts, answerAt: m.answerAt ?? (answering ? now : null) };
    }
    case "tool_call":
      return { ...m, tools: upsertTool(m.tools, data as unknown as ToolCall), answerAt: null };
    case "tool_result":
      return { ...m, tools: upsertTool(m.tools, data as unknown as ToolCall) };
    case "done": {
      const msg = data.message as AgentMessage | undefined;
      const tools = msg?.tool_calls ?? m.tools;
      const stopped = m.stopRequested || tools.some((t) => t.state === "cancelled");
      return {
        ...m,
        id: msg?.id ?? m.id,
        parts: msg?.parts ?? m.parts,
        tools,
        status: stopped ? "stopped" : "done",
        answerAt: m.answerAt ?? now,
        durationMs: msg?.duration_ms ?? now - m.startedAt,
      };
    }
    case "error":
      return {
        ...m,
        status: "error",
        error: { code: String(data.code ?? "INTERNAL"), message: String(data.message ?? "") },
        tools: m.tools.map((t) => (t.state === "running" ? { ...t, state: "failed" } : t)),
        durationMs: now - m.startedAt,
      };
    default:
      return m;
  }
}

/** Mark a local stop: running steps show 已取消 until the server's final message arrives. */
export function markStopped(m: ChainMessage, now: number): ChainMessage {
  return {
    ...m,
    stopRequested: true,
    status: "stopped",
    tools: m.tools.map((t) => (t.state === "running" ? { ...t, state: "cancelled", result_summary: "已取消" } : t)),
    durationMs: now - m.startedAt,
  };
}

export const thinkingText = (m: ChainMessage) =>
  m.parts
    .filter((p): p is { type: "thinking"; text: string } => p.type === "thinking")
    .map((p) => p.text)
    .join("\n");

export const answerParts = (m: ChainMessage) => m.parts.filter((p) => p.type !== "thinking");

export const plainText = (m: ChainMessage) =>
  m.parts
    .filter((p): p is { type: "text"; text: string } => p.type === "text")
    .map((p) => p.text)
    .join("\n\n");
