/** Wire types from contracts/p2.md §五. */

export type Scope = { corpus_id: string } | { subcorpus_id: string } | null;

export interface Session {
  id: string; project_id: string; owner_id: string; title: string; scope: Scope;
  state: 'idle' | 'running'; created_at: string; updated_at: string; message_count: number;
}

export type Part =
  | { type: 'text'; text: string }
  | { type: 'ui'; lang: string }
  | { type: 'thinking'; text: string };

export interface ToolCall {
  id: string; name: string; args: unknown;
  state: 'running' | 'succeeded' | 'failed' | 'cancelled';
  result_summary: string;
  result_ref?: { kind: string; id: string };
  duration_ms: number;
}

export interface Message {
  id: string; role: 'user' | 'assistant'; content: string; parts: Part[]; tool_calls: ToolCall[];
  created_at: string; duration_ms?: number | null;
}
