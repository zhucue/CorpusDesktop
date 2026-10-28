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
  const cancelled = m.stopped || m.tool_calls.some((t) => t.state === "cancelled");
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
      const stopped = m.stopRequested || msg?.stopped || tools.some((t) => t.state === "cancelled");
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
    .map((p) => scrubIds(p.text))
    .join("\n\n");

/** Thinking phase: no answer yet, or a tool is still running. */
export const isThinking = (m: ChainMessage) => m.status === "running" && (m.answerAt == null || m.tools.some((t) => t.state === "running"));

/** Reasoning length in characters, whitespace excluded. */
export const thinkingChars = (m: ChainMessage) => Array.from(thinkingText(m).replace(/\s+/g, "")).length;

/** 860 字 / 1.2k 字 */
export const fmtChars = (n: number) => (n < 1000 ? `${n} 字` : `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k 字`);

/** The answer has text or a component (the action row only shows then). */
export const hasContent = (m: ChainMessage) => answerParts(m).some((p) => (p.type === "ui" ? p.lang.trim() : p.text.trim()));

/** Write tools proposed in this message, waiting for 执行 / 取消. */
export const pendingCalls = (m: ChainMessage) => m.tools.filter((t) => t.state === "needs_confirmation");

const ID_KEY =
  /\b(?:search|stat|hit|job|layer|document|doc|chunk|term|corpus|subcorpus|evidence|note|span|relation|annotation|alignment|label_set|query|kb_document|src_document|tgt_document)_ids?\s*[:=：]?\s*[`"'“]?(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?::\d+-\d+)?|[\w.:-]*\d[\w.:-]*)[`"'”]?/gi;
const UUID = /[`"']?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?::\d+-\d+)?[`"']?/gi;
/** Bare hex ids of 12+ characters mixing digits and letters (search ids, index versions). */
const HEX = /\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{12,}\b/gi;

/**
 * Internal IDs never reach the reader (the model is told so; this is the safety net): drop "xxx_id: …" pairs,
 * UUIDs and long hex strings, then the brackets and separators they leave behind.
 */
export function scrubIds(text: string): string {
  return text
    .replace(ID_KEY, "")
    .replace(UUID, "")
    .replace(HEX, "")
    .replace(/[（(][\s，,、；;:：]*[）)]/g, "")
    .replace(/([（(])[\s，,、；;]+/g, "$1")
    .replace(/[\s，,、；;]+([）)])/g, "$1")
    .replace(/[，,、；;]\s*([。！？：])/g, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ +([，。；：、）])/g, "$1");
}
