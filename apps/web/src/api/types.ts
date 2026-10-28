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
  /** Source and license; empty object when none. */
  meta?: CorpusMeta;
  created_at: string;
}

export interface CorpusMeta {
  license?: string;
  attribution?: string;
  source_url?: string;
  version?: string;
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
  /** P3: resolve {pos=} / {dep=} against these annotation layers' effective values. */
  layers?: { pos?: string; dep?: string; span?: string };
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
export type JobKind = "import" | "index" | "export" | "stats" | "preannotate" | "kb_import" | "kb_summarize" | "kb_extract";

export interface Job {
  id: string;
  /** null for built-in corpus jobs. */
  project_id: string | null;
  owner_id?: string | null;
  owner_email?: string | null;
  /** Target and parameters in one line. */
  summary?: string | null;
  kind: JobKind;
  state: JobState;
  progress: { done: number; total: number | null; message: string };
  /** export: {rows, hits, filename}; stats: {stat_id} */
  result: { rows?: number; hits?: number; filename?: string; stat_id?: string; [k: string]: unknown } | null;
  error: { code: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

/** CSV/TSV column mapping for one upload batch; metadata null = every other column. */
export interface TableMapping {
  text: string[];
  title: string | null;
  language: string | null;
  metadata: string[] | null;
}

/** POST /imports/preview: header, first rows and detected mapping of a CSV/TSV. */
export interface TablePreview {
  columns: string[];
  rows: string[][];
  defaults: TableMapping;
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

// ---------- P3: annotation (contracts/p3.md; token indices are 1-based, head 0 = root) ----------

export type LayerKind = "pos" | "dep" | "span" | "relation" | "alignment";
export type AnnotStatus = "suggested" | "confirmed" | "modified" | "rejected";

export interface LabelDef {
  id: string;
  /** The tag value stored in Annotation.label (e.g. NOUN, nsubj). */
  name: string;
  color?: string;
  description?: string;
  parent?: string;
}

export interface LabelSet {
  id: string;
  project_id: string | null;
  name: string;
  kind: "pos" | "dep" | "span" | "relation";
  language: string | null;
  labels: LabelDef[];
  created_at: string;
}

export interface LayerProgress {
  total: number;
  suggested: number;
  confirmed: number;
  modified: number;
  rejected: number;
  /** P5 span / relation preannotation: sentences the model could not label. */
  failed_sentences?: unknown[];
}

export interface Layer {
  id: string;
  project_id: string;
  corpus_id: string;
  corpus_name: string;
  kind: LayerKind;
  name: string;
  label_set_id: string;
  source_model: string;
  status: "created" | "preannotating" | "ready" | "failed";
  job_id: string | null;
  progress: LayerProgress;
  documents: { total: number; done: number };
  error: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** P5 (contracts/p5.md §二). */
  mode?: "single" | "multi";
  annotators?: string[];
  base_layer_id?: string | null;
  src_corpus_id?: string | null;
  tgt_corpus_id?: string | null;
  level?: "sentence" | "word" | null;
  guideline_document_id?: string | null;
}

export interface LayerDocument {
  document_id: string;
  title: string;
  sentences: number;
  done: number;
  pending: number;
}

export interface Annotation {
  id: string;
  token_index: number;
  label: string | null;
  head: number | null;
  model_label: string | null;
  model_head: number | null;
  source: string;
  status: AnnotStatus;
  revision: number;
  updated_by: string | null;
  updated_at: string;
}

export interface AnnotToken {
  index: number;
  form: string;
  start_cp: number;
  end_cp: number;
  system: { pos: string | null; head: number | null; deprel: string | null };
}

export interface SentenceAnnot {
  document_id: string;
  sentence_index: number;
  text: string;
  tokens: AnnotToken[];
  annotations: Annotation[];
  status: "pending" | "done";
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface AnnotationInput {
  document_id: string;
  sentence_index: number;
  token_index: number;
  action: "confirm" | "modify" | "reject";
  label?: string;
  head?: number;
}

export interface DiffResult {
  items: SentenceAnnot[];
  counts: { changed: number; confirmed: number; rejected: number; pending: number };
}

// ---------- P5: spans, relations, alignment, agreement (contracts/p5.md; span cps are document code points) ----------

export interface Span {
  id: string;
  start_cp: number;
  end_cp: number;
  text: string;
  label: string;
  attrs: Record<string, string> | null;
  source: string;
  status: AnnotStatus;
  model_label: string | null;
  revision: number;
  annotator_id: string | null;
  updated_at: string;
}

export interface Relation {
  id: string;
  from_span_id: string;
  to_span_id: string;
  label: string;
  source: string;
  status: AnnotStatus;
  revision: number;
  annotator_id: string | null;
  model_label?: string | null;
}

export interface SentenceSpans {
  document_id: string;
  sentence_index: number;
  text: string;
  start_cp: number;
  end_cp: number;
  spans: Span[];
  relations: Relation[];
}

export type SpanPatch = {
  action: "confirm" | "modify" | "reject";
  label?: string;
  start_cp?: number;
  end_cp?: number;
  attrs?: Record<string, string>;
};

/** Tokens arrive as strings or `{index?, form}`; indices are 1-based. */
export type PairToken = string | { index?: number; form: string };

export interface PairSide {
  document_id: string;
  sentence_index: number;
  text: string;
  tokens: PairToken[];
}

export interface Alignment {
  id: string;
  level: "sentence" | "word";
  src_tokens: number[];
  tgt_tokens: number[];
  score: number | null;
  source: string;
  status: AnnotStatus;
  revision: number;
  annotator_id: string | null;
  tgt_document_id?: string;
  tgt_sentence_index?: number;
}

/** One source sentence and one target sentence; a source sentence with several targets has several pairs, an unaligned one has tgt null. */
export interface SentencePair {
  src: PairSide;
  tgt: PairSide | null;
  alignments: Alignment[];
}

export interface AlignmentPatch {
  action: "confirm" | "modify" | "reject";
  src_tokens?: number[];
  tgt_tokens?: number[];
  tgt_sentence_index?: number;
}

export interface Agreement {
  annotators: { user_id: string; email: string; done: number }[];
  pairwise: { a: string; b: string; kappa: number | null; n: number }[];
  alpha: number | null;
  per_label: { label: string; kappa: number | null }[];
  /** Span layers: overlap-tolerant version. */
  lenient?: { pairwise: { a: string; b: string; kappa: number | null; n: number }[]; alpha: number | null; n?: number };
}

export type AdjudicationKind = "token" | "span" | "relation" | "alignment";

export interface Adjudication {
  layer_id?: string;
  target_kind: AdjudicationKind;
  target_key: string;
  final: unknown;
  decided_by: string;
  decided_at: string;
}

/** GET /layers/{id}/disagreements item. `adjudicated` may be a flag or the adjudication itself. */
export interface Disagreement {
  target_kind: AdjudicationKind;
  target_key: string;
  document_id?: string;
  sentence_index?: number;
  text?: string;
  values: { annotator_id: string; email?: string; value: unknown }[];
  adjudicated?: boolean | Adjudication | null;
  final?: unknown;
}

/** POST /stats/alignment; field names are assumed (contract: 句对数、一对一 / 一对多 / 未对齐计数、平均词对数). */
export type AlignmentStats = Record<string, unknown>;

export interface LayerStats {
  labels: { label: string; count: number; confirmed: number; modified: number }[];
  progress: LayerProgress;
  /** Shape beyond the contract: assumed to mirror GET /layers/{id}/documents rows. */
  per_document: (Partial<LayerDocument> & { document_id: string })[];
}

// ---------- P4: knowledge base (contracts/p4.md) ----------

export type KbKind = "literature" | "guideline" | "note" | "url";
export type KbStatus = "queued" | "parsing" | "embedding" | "ready" | "failed";

/** `{page}`, `{heading_path}` or `{line}`. */
export interface KbLocator {
  page?: number;
  heading_path?: string[] | string;
  line?: number;
}

export interface KbMeta {
  author?: string;
  year?: number | string;
  pages?: number;
  label_set_id?: string;
  summary?: string;
  summary_source?: string;
  [k: string]: unknown;
}

export interface KbDocument {
  id: string;
  project_id: string;
  kind: KbKind;
  title: string;
  source: string;
  meta: KbMeta;
  status: KbStatus;
  error: string | null;
  chunk_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** File / URL import: the kb_import job (POST response; assumed on list rows while importing). */
  job_id?: string | null;
  /** GET /kb/documents/{id}: note / guideline body, otherwise a text preview. */
  body?: string;
  text_preview?: string;
  /** Assumed on GET of a note: its note_refs. */
  refs?: NoteRef[];
}

export interface KbChunk {
  id: string;
  document_id: string;
  ordinal: number;
  text: string;
  locator: KbLocator;
  score?: number;
}

export interface TermTranslation {
  language: string;
  text: string;
}

export interface TermExample {
  text: string;
  source: string;
  hit_id?: string;
  document_id?: string;
  start_cp?: number;
  end_cp?: number;
}

export interface Term {
  id: string;
  project_id: string;
  term: string;
  language: string;
  translations: TermTranslation[];
  definition: string;
  domain: string;
  examples: TermExample[];
  source: "manual" | "corpus" | "literature" | "model";
  status: "draft" | "confirmed";
  created_by: string;
  confirmed_by: string | null;
  created_at: string;
  updated_at: string;
}

export type NoteRefKind = "search" | "stat" | "evidence" | "chunk" | "term";

export interface NoteRef {
  note_id?: string;
  kind: NoteRefKind;
  ref: Record<string, unknown>;
  created_at?: string;
}

export interface KbSearchHit {
  chunk: KbChunk;
  document: { id: string; title: string; kind: KbKind; source: string };
  score: number;
  /** Keyword-matched fragment; `<mark>` / `<b>` delimit the matches when present. */
  highlight?: string | null;
}

export interface KbSearchResult {
  items: KbSearchHit[];
  terms: Term[];
  /** EMBED_UNAVAILABLE: vector model not ready, keyword results only. */
  warning?: string | { code: string; message?: string } | null;
}
