export type Role = "owner" | "editor" | "annotator" | "viewer";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  /** Only on /auth/login and /auth/me: a temporary password must be replaced before anything else. */
  must_change_password?: boolean;
}

/** GET /admin/users item (contracts/p7.md §五). */
export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  disabled_at: string | null;
  last_login_at: string | null;
  created_at: string;
  projects: number;
}

/** GET /system/info (contracts/p7.md §六); hosts are host names only. */
export interface SystemInfo {
  version: string;
  model: { configured: boolean; host: string | null; model_id: string | null };
  embed: { mode: "local" | "remote"; host: string | null; model: string | null; ready: boolean };
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
  /** Parallel corpora: aligned sentence pairs. */
  pairs?: number;
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
  /** Searchable corpus with an import/index job running; the old index serves until it is replaced. */
  updating?: boolean;
  /** An index job is queued or running: results may still include deleted or edited documents (contracts/p9.md §八). */
  index_pending?: boolean;
  created_at: string;
}

export interface CorpusMeta {
  license?: string;
  attribution?: string;
  source_url?: string;
  version?: string;
  /** Set when the index is built: POS tag set the query engine resolves against. */
  tagset?: "upos" | "jieba" | "mixed";
  /** Chinese script of the corpus text; absent without enough Chinese text. */
  script?: "simplified" | "traditional" | "mixed";
  /** Document language codes, largest text share first. */
  languages?: string[];
  /** ISO time of the last index build. */
  indexed_at?: string;
}

/** GET /corpora/{id}/documents/{doc}/sentences item. */
export interface DocSentence {
  idx: number;
  text: string;
  aligned: { language: string; text: string }[];
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
/** Part `bin` (from 0) of `bins` equal parts of each document: 回到例句 of a 文档位置 distribution row (search only). */
export type ScopePosition = { bin: number; bins: number };
export type SearchScope = Scope | { corpus_id: string; filter: Filter; position?: ScopePosition };

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
  /** P8: keep only hits whose aligned sentence contains (+) / lacks (-) a match of `query` (parallel corpora). */
  aligned?: AlignedCondition;
}

/** P8 译文条件 (contracts/p8.md §四); also the stats row `search_aligned`. */
export interface AlignedCondition {
  op: "+" | "-";
  query: string;
}

export interface ParseResult {
  ok: boolean;
  anchor: string;
  conditions: { op: "+" | "-"; text: string }[];
  tokens: { kind: string; text: string }[];
  error: { position: number; message: string } | null;
  /** Present when parsed with a scope: what the searched corpus offers. */
  corpus?: ParseCorpus;
}

export interface ParseCorpus {
  tagset: "upos" | "jieba" | "mixed";
  tagset_name: string;
  /** POS tags present in the index. */
  pos_tags: string[];
  /** Corpus.meta.script when import recorded it. */
  script: "simplified" | "traditional" | "mixed" | null;
  parallel: boolean;
  layers: { dep: boolean; span: boolean };
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
export type JobKind = "import" | "index" | "export" | "stats" | "preannotate" | "kb_import" | "kb_summarize" | "kb_extract" | "embed_corpus";

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
  /** unit: what done/total count (字 / 个文件 / 篇), when the job reports it. */
  progress: { done: number; total: number | null; message: string; unit?: string };
  /** Queued jobs: jobs of the same lane ahead of it (running or queued earlier). */
  queue_ahead?: number | null;
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

/** P2 methods plus P8 breakdown (命中分解) and translations (译法), contracts/p8.md §一、§四. */
export type StatMethod =
  | "frequency"
  | "ngrams"
  | "collocations"
  | "keywords"
  | "distribution"
  | "breakdown"
  | "translations"
  // P10 (contracts/p10.md §一、§二、§四、§五)
  | "text_metrics"
  | "vocab_profile"
  | "compare"
  | "word_sketch"
  | "sketch_diff";

/** POST /stats/text_metrics `metrics` (the page always sends words and sentences). */
export type TextMetric =
  | "words"
  | "sentences"
  | "ttr"
  | "sttr"
  | "mtld"
  | "lexical_density"
  | "mean_sentence_length"
  | "mean_dependency_distance"
  | "flesch_reading_ease"
  | "flesch_kincaid_grade";

export interface TextMetricsRequest {
  project_id: string;
  scope: SearchScope;
  metrics?: TextMetric[];
  /** Metadata field; documents without it go to "（无）". */
  group_by?: string;
  sttr_window: number;
}

/** totals.groups of text_metrics with group_by: per metric, one entry per field value (documents with a value). */
export type TextMetricGroups = Record<string, { value: string; documents: number; mean: number | null; sd: number | null }[]>;

/** One field value with mean / sd per metric (the page's view of TextMetricGroups). */
export interface TextMetricGroup {
  value: string;
  documents: number;
  mean: Record<string, number | null>;
  sd: Record<string, number | null>;
}

/** GET /projects/{id}/vocab-lists item; project_id null = built-in (NGSL). */
export interface VocabList {
  id: string;
  project_id: string | null;
  builtin?: boolean;
  name: string;
  language: string;
  /** Level names in order. */
  levels: string[];
  source?: string | null;
  license?: string | null;
  /** Number of entries, when the API gives it. */
  entries?: number | null;
  created_by?: string | null;
  created_at: string;
}

/** POST /stats/vocab_profile `by`: whole range, per document, or a metadata field. */
export type VocabBy = "corpus" | "document" | (string & {});

export interface VocabProfileRequest {
  project_id: string;
  scope: SearchScope;
  list_id: string;
  by: VocabBy;
}

export type CompareTest = "none" | "mann_whitney" | "spearman";

export interface CompareItem {
  label: string;
  scope: SearchScope;
  query: string;
}

export interface CompareRequest {
  project_id: string;
  /** 2–10 items. */
  items: CompareItem[];
  by?: string | null;
  test?: CompareTest;
}

/** totals.test of compare; one observation per document (its hits per million). z, p, r null when σ = 0. */
export type CompareTestResult =
  | { method: "mann_whitney"; u: number | null; z: number | null; p: number | null; r: number | null; n1: number; n2: number }
  | { method: "spearman"; field: string; items: { label: string; rho: number | null; p: number | null; n: number }[] };

/** totals.relations of word_sketch / sketch_diff, in display order. */
export interface SketchRelation {
  key: string;
  label: string;
  freq?: number;
  freq_a?: number;
  freq_b?: number;
  rows: number;
}

export interface WordSketchRequest {
  project_id: string;
  scope: SearchScope;
  lemma: string;
  pos?: string;
  /** Chinese: the dependency layer (default: the corpus's latest finished dependency preannotation layer). */
  layers?: { dep?: string };
  min_freq: number;
  top: number;
}

export interface SketchDiffRequest {
  project_id: string;
  scope: SearchScope;
  lemma_a: string;
  lemma_b: string;
  pos?: string;
  layers?: { dep?: string };
  min_freq: number;
  top: number;
}

/** POST /stats/tidy_export → Job (kind export). */
export interface TidyExportRequest {
  project_id: string;
  scope: SearchScope;
  /** ≤ 10; each adds q{n}_hits and q{n}_pm. */
  queries?: string[];
  metrics?: boolean;
  format: "csv" | "xlsx";
}

/** POST /stats/breakdown `by`: the hit itself, its left / right neighbour, or a document metadata field. */
export type BreakdownBy = "word" | "lemma" | "pos" | "left1" | "right1" | `meta:${string}`;
/** POST /stats/frequency `parts` for dispersion: per document, 10 equal segments, or per metadata field value. */
export type FrequencyParts = "document" | "segments" | `field:${string}`;
/** POST /stats/keywords `direction`: positive = more in target (default), negative = more in reference. */
export type KeywordDirection = "positive" | "negative" | "both";
export type KeywordMeasure = "ll" | "log_ratio" | "pct_diff" | "odds_ratio";
/** POST /stats/collocations `measures`; delta_p yields two columns, delta_p_node and delta_p_coll. */
export type CollocationMeasure = "logdice" | "mi" | "t" | "ll" | "mi3" | "delta_p" | "z";

export interface BreakdownRequest {
  project_id: string;
  scope: SearchScope;
  query: string;
  by: BreakdownBy;
  top?: number;
  min_freq?: number;
  layers?: SearchRequest["layers"];
}

export interface TranslationsRequest {
  project_id: string;
  scope: SearchScope;
  query: string;
  unit: "word" | "lemma";
  target_language?: string;
  measure: "dice" | "ll";
  top?: number;
  min_freq?: number;
  exclude_punct?: boolean;
}

export interface StatColumn {
  key: string;
  label: string;
  type: "string" | "number";
  unit?: string;
}

export interface StatRow {
  key: string;
  values: Record<string, string | number | boolean | null>;
  search_query: string | null;
  /** collocations: collocate on the left of the node */
  search_query_reverse?: string | null;
  search_scope: SearchScope;
  /** P8 translations rows: the translation condition to open the search with. */
  search_aligned?: AlignedCondition | null;
  /** P10 compare rows with by: one search per item (its query, the item's corpus narrowed to the row's value). */
  searches?: { label: string; search_query: string | null; search_scope: SearchScope }[];
  /** P10 word_sketch / sketch_diff: the dependency layer the search must use. */
  search_layers?: SearchRequest["layers"];
  /** P10 sketch_diff: the search for lemma B (search_query is A's, or B's when only B has it). */
  search_query_b?: string | null;
}

export interface StatResult {
  id: string;
  project_id: string;
  method: StatMethod;
  params: Record<string, unknown>;
  scope: { corpus_id: string; subcorpus_id: string | null; name: string };
  index_version: number | string | null;
  /** tokens count every token, punctuation included; excluded_tokens = punctuation / digits left out (frequency). */
  totals: Stats & {
    node_hits?: number;
    window_tokens?: number;
    hits?: number | null;
    reference?: Stats;
    excluded_tokens?: number;
    /** P8 frequency with dispersion: number of parts. */
    parts?: number;
    /** P8 translations: hit sentences, those with / without an aligned sentence; the target side. */
    hit_sentences?: number;
    aligned_sentences?: number;
    unaligned?: number;
    target_language?: string;
    scope_aligned_sentences?: number;
    /** P8 keywords: word types tested (Bonferroni). */
    types_compared?: number;
    /** P10 text_metrics: group summary (group_by) and notes (e.g. documents under 100 words without STTR / MTLD). */
    groups?: TextMetricGroups;
    group_by?: string;
    notes?: string[];
    /** P10 text_metrics / vocab_profile: words without punctuation. */
    words?: number;
    /** P10 vocab_profile: level names in order, 表外 last; by=corpus: the most frequent off-list words. */
    levels?: string[];
    off_list?: { item: string; freq: number; search_query: string | null }[];
    /** P10 compare: number of items; two items without by: LL / log ratio (keyword formulas); the test result. */
    items?: number;
    comparison?: { ll: number | null; log_ratio: number | null; significance?: string | null; smoothed?: boolean };
    test?: CompareTestResult | null;
    /** P10 word_sketch / sketch_diff. */
    relations?: SketchRelation[];
    lemma?: string;
    lemma_a?: string;
    lemma_b?: string;
    node_freq?: number;
    node_freq_a?: number;
    node_freq_b?: number;
  };
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
  /** Pinned hits (filled by the server): the hit's own sentence, the match [start, end) in code points, aligned translations. */
  sentence_index?: number;
  sentence?: string;
  match?: [number, number];
  aligned?: { language: string; text: string }[];
  document_title?: string;
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

/** needs_confirmation: a write tool proposed, waiting for 执行 / 取消; confirmed / declined: the user's answer. */
export type ToolState = "running" | "succeeded" | "failed" | "cancelled" | "needs_confirmation" | "confirmed" | "declined";

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  state: ToolState;
  result_summary: string;
  result_ref?: { kind: string; id: string };
  duration_ms?: number;
  /** Confirm card text of a proposed write tool. */
  confirm?: { title: string; lines: string[] };
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
  /** The user stopped the run. */
  stopped?: boolean;
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
  /** Every required annotator annotated (rows, none suggested) or confirmed the sentence; untouched = false. */
  done?: boolean;
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
  /** n: units where at least one annotator gave the label. */
  per_label: { label: string; kappa: number | null; n?: number }[];
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
  /** The disputed words and their [start, end) code points in `text`. */
  target_text?: string | null;
  marks?: [number, number][];
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
  /** 相关度 for display: share of query words in the chunk and the vector similarity. */
  relevance?: "high" | "medium" | "low";
  /** Keyword-matched fragment; `<mark>` / `<b>` delimit the matches when present. */
  highlight?: string | null;
}

export interface KbSearchResult {
  items: KbSearchHit[];
  terms: Term[];
  /** EMBED_UNAVAILABLE: vector model not ready, keyword results only. */
  warning?: string | { code: string; message?: string } | null;
}

/* ---------- P9 operations (contracts/p9.md) ---------- */

/** GET /me/llm-usage: the current month; limit null = no limit. */
export interface MyLlmUsage {
  month: string;
  total_tokens: number;
  limit: number | null;
  by_source: { source: string; total_tokens: number }[];
}

/** GET /admin/llm-usage?group=user|project item. */
export interface LlmUsageRow {
  key: string;
  name: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
}

export interface LlmUsageReport {
  items: LlmUsageRow[];
  total: number;
}

/** GET /admin/projects item; deleted_at set for soft-deleted projects. */
export interface AdminProject {
  id: string;
  name: string;
  owner: { id: string; email: string; display_name: string } | null;
  members: number;
  corpora: number;
  layers: number;
  kb_documents: number;
  disk_bytes: number;
  created_at: string;
  deleted_at: string | null;
}

/** GET /admin/jobs item: a Job with its project name (null for built-in corpus jobs). */
export type AdminJob = Job & { project_name?: string | null };

/** GET /admin/system. */
export interface AdminSystem {
  version: string;
  model: SystemInfo["model"] | string | null;
  embed: SystemInfo["embed"] | string | null;
  workers: { id: string; kinds: string[] | string | null; last_seen: string | null; healthy: boolean }[];
  disk: { path: string; total: number | null; free: number | null } | null;
  search_cache_bytes: number;
  data_bytes: number;
  last_backup_at: string | null;
}

/** GET /admin/audit and GET /projects/{id}/audit item. */
export interface AuditEntry {
  id: number;
  at: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_name: string | null;
  project_id: string | null;
  project_name?: string | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
}

export type FeedbackStatus = "open" | "done";

/** GET /admin/feedback item. */
export interface FeedbackItem {
  id: number;
  created_at: string;
  user: { id: string; email: string; display_name: string } | null;
  project_id: string | null;
  project_name?: string | null;
  page: string;
  app_version: string;
  text: string;
  status: FeedbackStatus;
  admin_note: string;
  handled_at: string | null;
}

/** GET /me/deleted-projects item: own projects deleted within the restore window. */
export interface DeletedProject {
  id: string;
  name: string;
  deleted_at: string;
}
