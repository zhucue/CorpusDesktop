export type Role = "owner" | "editor" | "annotator" | "viewer";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
}

export interface Project {
  id: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  role: Role;
}

export type CorpusStatus = "empty" | "importing" | "indexing" | "ready" | "stale" | "failed";

export interface Stats {
  documents: number;
  sentences: number;
  tokens: number;
}

export interface Corpus {
  id: string;
  project_id: string | null;
  name: string;
  language: string;
  description: string;
  parallel: boolean;
  status: CorpusStatus;
  error: string | null;
  stats: Stats;
  index_version: number | string | null;
  created_at: string;
}

export type Metadata = Record<string, unknown>;

export interface Doc {
  id: string;
  corpus_id: string;
  title: string;
  language: string;
  metadata: Metadata;
  sentences: number;
  tokens: number;
  created_at: string;
}

export interface MetadataField {
  field: string;
  type: "string" | "number";
  values?: (string | number)[];
}

export type FilterValue = string | number | (string | number)[] | { gte?: number; lte?: number };
export type Filter = Record<string, FilterValue>;

export interface Subcorpus {
  id: string;
  project_id: string;
  corpus_id: string;
  name: string;
  filter: Filter;
  stats: Stats;
}

/** Saved scopes. P2 adds the temporary filtered form returned by distribution rows. */
export type Scope = { corpus_id: string } | { subcorpus_id: string };
export type SearchScope = Scope | { corpus_id: string; filter: Filter };

export interface SearchRequest {
  scope: SearchScope;
  query: string;
  context: { unit: "char" | "sentence" | "paragraph"; size: number };
  sort: "position" | "left" | "right" | "random";
  seed?: number;
  page: number;
  page_size: number;
  search_id?: string;
  /** Adds Hit.tokens (part, form, pos) for POS colouring. */
  include_tokens?: boolean;
}

export interface ParseResult {
  ok: boolean;
  anchor: string;
  conditions: { op: "+" | "-"; text: string }[];
  tokens: { kind: string; text: string }[];
  error: { position: number; message: string } | null;
}

/** Token layer returned when SearchRequest.include_tokens is true (contracts/p2.md §十一). */
export interface HitToken {
  part: "left" | "match" | "right";
  form: string;
  pos: string | null;
}

export interface Hit {
  hit_id: string;
  document_id: string;
  document_title: string;
  sentence_index: number;
  left: string;
  match: string;
  right: string;
  start_cp: number;
  end_cp: number;
  metadata: Metadata;
  aligned: { language: string; text: string }[];
  tokens?: HitToken[];
}

export interface Counts {
  hits: number;
  sentences: number;
  documents: number;
  complete: boolean;
}

export interface SearchResult {
  search_id: string;
  parse: ParseResult;
  counts: Counts;
  items: Hit[];
  page: number;
  page_size: number;
}

export interface ContextResult {
  document: Doc;
  sentences: { index: number; text: string; highlight: [number, number] | null }[];
}

export interface SavedQuery {
  id: string;
  project_id: string;
  name: string;
  query: string;
  scope: Scope;
  created_at: string;
}

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobKind = "import" | "index" | "export" | "stats";

export interface Job {
  id: string;
  project_id: string;
  kind: JobKind;
  state: JobState;
  progress: { done: number; total: number | null; message: string };
  /** export: {rows, hits, filename}; stats: {stat_id} */
  result: { rows?: number; hits?: number; filename?: string; stat_id?: string; [k: string]: unknown } | null;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
}

// ---------- P2: statistics ----------

export type StatMethod = "frequency" | "ngrams" | "collocations" | "keywords" | "distribution";

export interface StatColumn {
  key: string;
  label: string;
  type: "string" | "number";
  unit?: string;
}

export interface StatRow {
  key: string;
  values: Record<string, string | number | null>;
  search_query: string | null;
  /** collocations: collocate on the left of the node */
  search_query_reverse?: string | null;
  search_scope: SearchScope;
}

export interface StatResult {
  id: string;
  project_id: string;
  method: StatMethod;
  params: Record<string, unknown>;
  scope: { corpus_id: string; subcorpus_id: string | null; name: string };
  index_version: number | string | null;
  totals: Stats & { node_hits?: number; window_tokens?: number; hits?: number | null; reference?: Stats };
  created_at: string;
  columns: StatColumn[];
  rows: StatRow[];
  row_count: number;
}

// ---------- P2: evidence ----------

export type EvidenceKind = "hit" | "stat_row" | "text";

export interface EvidenceRef {
  search_query?: string;
  scope?: SearchScope;
  hit_id?: string;
  document_id?: string;
  start_cp?: number;
  end_cp?: number;
  stat_id?: string;
  row_key?: string;
}

export interface Evidence {
  id: string;
  project_id: string;
  kind: EvidenceKind;
  ref: EvidenceRef;
  text: string;
  source: string;
  note: string | null;
  created_by: string;
  created_at: string;
}

export type EvidenceInput = Pick<Evidence, "kind" | "ref" | "text" | "source"> & { note?: string };

// ---------- P2: agent ----------

export interface AgentHealth {
  ok: boolean;
  model_id?: string;
  reason?: string;
}

export interface AgentSession {
  id: string;
  project_id: string;
  owner_id: string;
  title: string;
  scope: Scope | null;
  state: "idle" | "running";
  created_at: string;
  updated_at: string;
  message_count: number;
}

export type ToolState = "running" | "succeeded" | "failed" | "cancelled";

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  state: ToolState;
  result_summary: string;
  result_ref?: { kind: string; id: string };
  duration_ms?: number;
}

export type MessagePart = { type: "text"; text: string } | { type: "ui"; lang: string } | { type: "thinking"; text: string };

export interface AgentMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  parts: MessagePart[];
  tool_calls: ToolCall[];
  created_at: string;
  duration_ms?: number;
}

export type AgentSessionDetail = AgentSession & { messages: AgentMessage[] };
