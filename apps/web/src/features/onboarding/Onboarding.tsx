import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Select, Upload, type UploadFile } from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, type Corpus, type Job, type ParseResult, type Project, type SavedQuery, type SearchResult } from "../../api";
import { Empty, Count, CorpusStatusTag, ErrorAlert, Monogram, Progress, QueryChip } from "../../components/common";
import { Icon, type IconName } from "../../components/Icon";
import { KwicTable } from "../../components/results/Kwic";
import { isActiveJob, useCorpora, useCorpus, useJob, useProjectJobs, useProjects } from "../../lib/data";
import { fmt, fmtRelative } from "../../lib/format";
import AssistantPanel from "../assistant/AssistantPanel";
import { useAgentHealth } from "../assistant/useAgentChat";
import { TOOL_COUNT } from "../../components/global/tools";
import { ACCEPT, languageOptions, uploadFiles } from "../corpora/UploadDialog";
import { MAX_PROJECT_NAME } from "../settings/project";
import "./onboarding.css";

const STEPS = ["创建项目", "导入语料", "第一次检索", "试试助手", "完成"];
const UPLOAD = "__upload__";
const DEFAULT_PROJECT = "我的研究项目";

/** Prefill candidates, most instructive first; the last ones hit in almost any text of the language. */
function queryCandidates(language: string | undefined): string[] {
  return language === "en"
    ? ["translate/v", "translation", "language", "people", "the"]
    : ["翻译/v +文化", "翻译", "文化", "语言", "我们", "的"];
}

/** First candidate with a hit in the corpus (one-row searches), so the first search is never empty. */
async function pickQuery(corpusId: string, language: string | undefined): Promise<string> {
  const cands = queryCandidates(language);
  for (const q of cands) {
    try {
      const r = await api.post<SearchResult>("/search", { scope: { corpus_id: corpusId }, query: q, context: { unit: "char", size: 10 }, sort: "position", page: 1, page_size: 1 });
      if (r.items.length > 0 || r.counts.hits > 0) return q;
    } catch {
      /* try the next one */
    }
  }
  return cands[0];
}

/** " · 索引更新 3 天前" from meta.indexed_at; nothing when unknown (the index hash means nothing to users). */
function indexedText(c: Corpus): string {
  const at = c.meta?.indexed_at;
  return at ? ` · 索引更新 ${fmtRelative(at)}` : "";
}

/** Search page link carrying the onboarding corpus and its last query. */
export function searchLanding(projectId: string, corpusId: string | null, query: string | null): string {
  const p = new URLSearchParams();
  if (query) p.set("q", query);
  if (corpusId) p.set("scope", JSON.stringify({ corpus_id: corpusId }));
  const s = p.toString();
  return `/p/${projectId}/search${s ? `?${s}` : ""}`;
}

const POS_NAMES: Record<string, string> = { v: "动词", n: "名词", a: "形容词", d: "副词", VERB: "动词", NOUN: "名词", ADJ: "形容词", ADV: "副词" };

/** The explanation line under the query: what the parser reads from it, as typed. */
function QueryExplain({ query }: { query: string }) {
  const [shown, setShown] = useState(query);
  useEffect(() => {
    const t = setTimeout(() => setShown(query), 300);
    return () => clearTimeout(t);
  }, [query]);
  const parse = useQuery({
    queryKey: ["parse", shown],
    queryFn: () => api.post<ParseResult>("/search/parse", { query: shown }),
    enabled: !!shown,
    staleTime: Infinity,
    meta: { background: true },
  });
  const p = shown === query ? parse.data : undefined;
  if (!query || !p) return <p className="hint" />;
  if (!p.ok) return <p className="hint" style={{ color: "var(--err)" }}>第 {(p.error?.position ?? 0) + 1} 个字符：{p.error?.message}</p>;
  const attrs = [...p.anchor.matchAll(/\/([A-Za-z]+)\b/g)].map((m) => POS_NAMES[m[1]] ?? m[1]);
  return (
    <p className="hint">
      <QueryChip q={p.anchor} />
      {attrs.length ? `限定${attrs.join("、")}` : "查找该词"}
      {p.conditions.map((c, i) => (
        <span key={i} className="row" style={{ gap: 6 }}>
          ，<QueryChip q={c.text} />
          {c.op === "+" ? "须同句出现" : "同句不出现"}
        </span>
      ))}
    </p>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const projects = useProjects();
  const health = useAgentHealth();
  const [step, setStep] = useState(0);
  const [projectId, setProjectId] = useState<string | null>(params.get("project"));
  const [name, setName] = useState("");
  const project = projects.data?.items.find((p) => p.id === projectId);

  useEffect(() => {
    if (params.get("project")) setStep(1);
  }, [params]);

  const createProject = useMutation({
    mutationFn: (n?: string) => api.post<Project>("/projects", { name: (n ?? name).trim() }),
    onSuccess: (p) => {
      setProjectId(p.id);
      qc.invalidateQueries({ queryKey: ["projects"] });
      setStep(1);
    },
  });

  /* ---------- step 2: corpus ---------- */
  const corpora = useCorpora(projectId ?? undefined);
  const builtin = (corpora.data?.items ?? []).filter((c) => c.project_id === null && c.status === "ready");
  const [source, setSource] = useState<string | null>(null);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [language, setLanguage] = useState("zh");
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const [corpusId, setCorpusId] = useState<string | null>(null);
  useEffect(() => {
    if (!source && corpora.data) setSource(builtin[0]?.id ?? UPLOAD);
  }, [corpora.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = useMutation({
    mutationFn: async () => {
      const c = await api.post<Corpus>(`/projects/${projectId}/corpora`, { name: files.length === 1 ? files[0].name.replace(/\.[^.]+$/, "") : "我的语料", language });
      setCorpusId(c.id);
      return uploadFiles(c.id, files.map((f) => f.originFileObj as File), language);
    },
    onSuccess: (job) => setImportJobId(job.id),
  });
  const activeCorpusId = source === UPLOAD ? corpusId : source;
  const corpus = useCorpus(activeCorpusId ?? undefined);
  const importJob = useJob(importJobId);
  const projectJobs = useProjectJobs(projectId ?? undefined);
  const indexJob = useMemo(() => {
    if (!importJob.data) return null;
    return (projectJobs.data?.items ?? []).find((j) => j.kind === "index" && j.created_at >= importJob.data!.created_at) ?? null;
  }, [projectJobs.data, importJob.data]);
  useEffect(() => {
    if (importJob.data?.state === "succeeded") qc.invalidateQueries({ queryKey: ["jobs", projectId] });
  }, [importJob.data?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  // The corpus is first read while still "empty" (not polled); refresh it as its jobs advance.
  useEffect(() => {
    if (corpusId) qc.invalidateQueries({ queryKey: ["corpus", corpusId] });
  }, [importJob.data?.state, indexJob?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const retry = useMutation({
    mutationFn: (job: Job) => api.post<Job>(`/jobs/${job.id}/retry`),
    onSuccess: (j) => (j.kind === "import" ? setImportJobId(j.id) : qc.invalidateQueries({ queryKey: ["jobs", projectId] })),
  });
  const ready = corpus.data?.status === "ready" || corpus.data?.status === "stale";

  /* ---------- step 3: search ---------- */
  const [query, setQuery] = useState("");
  const [edited, setEdited] = useState(false);
  // Prefill a query that hits in the chosen corpus; follows a corpus change until the user types.
  const prefill = useQuery({
    queryKey: ["onboarding-prefill", activeCorpusId],
    queryFn: () => pickQuery(activeCorpusId!, corpus.data?.language),
    enabled: !!activeCorpusId && ready,
    staleTime: Infinity,
    meta: { background: true },
  });
  useEffect(() => {
    if (prefill.data && !edited) setQuery(prefill.data);
  }, [prefill.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const [lastQuery, setLastQuery] = useState<string | null>(null);
  const search = useMutation({
    mutationFn: (q: string) =>
      api.post<SearchResult>("/search", { scope: { corpus_id: activeCorpusId }, query: q, context: { unit: "char", size: 30 }, sort: "position", page: 1, page_size: 3 }),
    onSuccess: (_, q) => setLastQuery(q),
  });
  const saveQuery = useMutation({
    mutationFn: () => api.post<SavedQuery>(`/projects/${projectId}/queries`, { name: query.trim(), query: query.trim(), scope: { corpus_id: activeCorpusId } }),
  });

  /* ---------- navigation ---------- */
  const canNext = [!!projectId || name.trim().length > 0, ready, true, true, true][step];
  // Leaving for search keeps the corpus chosen here and the last query searched (Q16).
  const landing = projectId ? searchLanding(projectId, ready ? activeCorpusId : null, ready ? lastQuery : null) : "/";
  function next() {
    if (step === 0 && !projectId) return createProject.mutate(undefined);
    if (step === STEPS.length - 1) return navigate(landing);
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  }
  /** 跳过 in the header: out of the guide. Without a project yet, one is created (typed or default name). */
  function skipAll() {
    if (projectId) return navigate(landing);
    if ((projects.data?.items.length ?? 0) > 0) return navigate("/");
    createProject.mutate(name.trim() || DEFAULT_PROJECT, { onSuccess: (p) => navigate(`/p/${p.id}/corpora`) });
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select, .ant-select")) return;
      if (e.key === "ArrowRight" && canNext && (step > 0 || projectId)) setStep((s) => Math.min(STEPS.length - 1, s + 1));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(projectId ? 1 : 0, s - 1));
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [canNext, step, projectId]);

  const stage = corpus.data?.status;
  const sums: { icon: IconName; title: React.ReactNode; sub: React.ReactNode; tag: string; cls: string }[] = [
    { icon: "folder", title: project?.name ?? name, sub: "仅成员可见", tag: projectId ? "已创建" : "未创建", cls: projectId ? "t-ok" : "t-gray" },
    {
      icon: "library",
      title: corpus.data?.name ?? "未选择语料",
      sub: corpus.data ? `${fmt(corpus.data.stats.sentences)} 句${indexedText(corpus.data)}` : "",
      tag: ready ? "可检索" : "未就绪",
      cls: ready ? "t-ok" : "t-gray",
    },
    {
      icon: "textsearch",
      title: query ? <QueryChip q={query} /> : "未检索",
      sub: search.data ? `${search.data.counts.complete ? fmt(search.data.counts.hits) : "计算中"} 次命中${saveQuery.isSuccess ? " · 已保存查询" : ""}` : "",
      tag: saveQuery.isSuccess ? "已保存" : search.data ? "已检索" : "未检索",
      cls: search.data ? "t-ok" : "t-gray",
    },
    {
      icon: "sparkles",
      title: "助手",
      sub: health.data?.ok ? `${health.data.model_id ?? ""} · ${TOOL_COUNT} 个工具` : (health.data?.reason ?? "不可用"),
      tag: health.data?.ok ? "可用" : "不可用",
      cls: health.data?.ok ? "t-ok" : "t-warn",
    },
  ];

  return (
    <div className="ob-page dotgrid">
      <header className="ob-top">
        <span className="brand" style={{ padding: 0 }}>
          <span className="brand-mark">
            <Icon name="hash" />
          </span>
          语料研究平台
        </span>
        <div className="grow" />
        <button className="skip linkish" type="button" disabled={createProject.isPending} onClick={skipAll}>
          跳过引导
        </button>
      </header>
      <main className="ob">
        <nav className="stepper" aria-label="引导步骤" style={{ ["--p" as string]: step / (STEPS.length - 1) }}>
          <span className="fill" aria-hidden />
          {STEPS.map((s, k) => (
            <button
              key={s}
              className={`st ${k === step ? "cur" : ""} ${k < step ? "done" : ""}`}
              type="button"
              aria-current={k === step ? "step" : undefined}
              disabled={!projectId && k > 0}
              onClick={() => setStep(k)}
            >
              <span className="dotn">{k < step ? <Icon name="check" size={14} /> : k + 1}</span>
              {s}
            </button>
          ))}
        </nav>
        <section className="card ob-card" aria-live="polite">
          <div className="track" style={{ transform: `translateX(${-100 * step}%)` }}>
            {/* 1 */}
            <div className="pane" aria-hidden={step !== 0}>
              <h2>创建项目</h2>
              {projectId ? (
                <div className="row" style={{ gap: 14 }}>
                  <Monogram name={project?.name ?? "项"} size="xl" />
                  <b style={{ fontSize: 16 }}>{project?.name}</b>
                  <span className="tag t-ok">已创建</span>
                </div>
              ) : (
                <div className="row" style={{ gap: 14, alignItems: "flex-end" }}>
                  <Monogram name={name.trim() || "项"} size="xl" />
                  <div className="field grow">
                    <label htmlFor="pname" className="row between">
                      项目名称
                      <span className="small muted num">
                        {Array.from(name).length} / {MAX_PROJECT_NAME}
                      </span>
                    </label>
                    <input
                      className="input"
                      id="pname"
                      value={name}
                      maxLength={MAX_PROJECT_NAME}
                      autoFocus
                      onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && name.trim() && createProject.mutate(undefined)}
                      style={{ height: 42, fontSize: 15 }}
                    />
                  </div>
                </div>
              )}
              <ErrorAlert error={createProject.error} />
            </div>
            {/* 2 */}
            <div className="pane" aria-hidden={step !== 1}>
              <h2>导入语料</h2>
              <div className="opt-grid" role="radiogroup" aria-label="语料来源">
                {builtin.slice(0, 2).map((c) => (
                  <button key={c.id} className="opt" type="button" role="radio" aria-checked={source === c.id} onClick={() => setSource(c.id)}>
                    <b>{c.name}</b>
                    <span className="small muted num">
                      {fmt(c.stats.sentences)} 句 · {c.language}
                      {c.parallel ? " · 对齐" : ""}
                    </span>
                    <span className="tag t-gray" style={{ alignSelf: "flex-start" }}>
                      内置
                    </span>
                  </button>
                ))}
                <button className="opt" type="button" role="radio" aria-checked={source === UPLOAD} onClick={() => setSource(UPLOAD)}>
                  <b>上传文件</b>
                  <span className="small muted">TXT · DOCX · CSV · CoNLL-U · TMX</span>
                  <span className="tag t-gray" style={{ alignSelf: "flex-start" }}>
                    本地
                  </span>
                </button>
              </div>
              {source === UPLOAD && !importJobId && (
                <div className="col">
                  <Upload.Dragger multiple fileList={files} beforeUpload={() => false} onChange={(i) => setFiles(i.fileList)} accept={ACCEPT}>
                    <div className="col" style={{ alignItems: "center", gap: 6, padding: "4px 0" }}>
                      <Icon name="upload" size={20} />
                      <span>拖入文件或点击选择</span>
                    </div>
                  </Upload.Dragger>
                  <div className="row">
                    <Select value={language} onChange={setLanguage} options={languageOptions} style={{ width: 140 }} />
                    <div className="grow" />
                    <button className="btn p" type="button" disabled={!files.length || upload.isPending} onClick={() => upload.mutate()}>
                      {upload.isPending ? <span className="spin" /> : <Icon name="upload" size={14} />}
                      导入
                    </button>
                  </div>
                  <ErrorAlert error={upload.error} />
                </div>
              )}
              {corpus.data && (source !== UPLOAD || importJobId) && (
                <div className="card" style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
                  <div className="row">
                    <h2 className="sec-title grow">{corpus.data.name}</h2>
                    {stage && <CorpusStatusTag status={stage} />}
                  </div>
                  {source === UPLOAD ? (
                    <>
                      <StageRow label="导入" job={importJob.data ?? null} onRetry={(j) => retry.mutate(j)} />
                      <StageRow label="建索引" job={indexJob} done={ready} onRetry={(j) => retry.mutate(j)} />
                    </>
                  ) : (
                    <div className="small muted num">
                      {fmt(corpus.data.stats.documents)} 篇 · {fmt(corpus.data.stats.sentences)} 句 · {fmt(corpus.data.stats.tokens)} 词{indexedText(corpus.data)}
                    </div>
                  )}
                  {corpus.data.status === "failed" && corpus.data.error && <div className="alert err">{corpus.data.error}</div>}
                </div>
              )}
            </div>
            {/* 3 */}
            <div className="pane" aria-hidden={step !== 2}>
              <h2>第一次检索</h2>
              <form
                className="row"
                style={{ gap: 10 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (query.trim() && activeCorpusId) search.mutate(query.trim());
                }}
              >
                <label htmlFor="oq" className="sr-only">
                  查询式
                </label>
                <input
                  className="query-input"
                  id="oq"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setEdited(true);
                  }}
                  placeholder={prefill.isFetching ? "正在挑选示例查询" : undefined}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button className="btn p lg" type="submit" disabled={!query.trim() || !activeCorpusId || !ready || search.isPending}>
                  {search.isPending ? <span className="spin" /> : <Icon name="search" />}
                  检索
                </button>
              </form>
              <QueryExplain query={query.trim()} />
              <ErrorAlert error={search.error} />
              {search.data && (
                <div className="col" style={{ gap: 12 }}>
                  <div className="row" style={{ gap: 28 }}>
                    <div>
                      <div className="stat-label">命中</div>
                      <Count value={search.data.counts.hits} unit="次" pending={search.data.counts.complete ? undefined : "计算中"} />
                    </div>
                    <div>
                      <div className="stat-label">句</div>
                      <Count value={search.data.counts.sentences} unit="句" pending={search.data.counts.complete ? undefined : "计算中"} />
                    </div>
                    <div className="grow" />
                    <button className="btn s" type="button" disabled={saveQuery.isPending || saveQuery.isSuccess} onClick={() => saveQuery.mutate()}>
                      <Icon name={saveQuery.isSuccess ? "check" : "plus"} size={14} />
                      {saveQuery.isSuccess ? "已保存" : "保存查询"}
                    </button>
                  </div>
                  {search.data.items.length ? (
                    <div className="card" style={{ overflow: "hidden" }}>
                      <KwicTable compact rows={search.data.items.map((h) => ({ id: h.hit_id, left: h.left, match: h.match, right: h.right, source: h.document_title }))} />
                    </div>
                  ) : (
                    <Empty icon="searchx" text="没有命中" />
                  )}
                </div>
              )}
            </div>
            {/* 4 */}
            <div className="pane" aria-hidden={step !== 3}>
              <h2>试试助手</h2>
              {health.data?.ok && projectId && step === 3 ? (
                <div className="ob-chat">
                  <AssistantPanel
                    compact
                    projectId={projectId}
                    sessionId={null}
                    scope={activeCorpusId ? { corpus_id: activeCorpusId } : null}
                    scopeLabel={corpus.data?.name ?? ""}
                    prefill={corpus.data?.language === "en" ? "List the 10 most frequent verbs in this corpus." : "统计这个语料库里最常见的 10 个动词，并画频次图"}
                  />
                </div>
              ) : (
                <div className="alert info">
                  <Icon name="info" size={14} />
                  <span>
                    助手用对话调用检索、统计等工具，结果以表格和图表返回。当前不可用
                    {health.data?.reason && <span className="err-code">{health.data.reason}</span>}
                    {health.error ? <span className="err-code">服务不可达</span> : null}，配置模型后在“助手”页使用。
                  </span>
                </div>
              )}
            </div>
            {/* 5 */}
            <div className="pane" aria-hidden={step !== 4}>
              <h2>完成</h2>
              <div>
                {sums.map((s, i) => (
                  <div className="sum" key={i} style={{ ["--i" as string]: i }}>
                    <span className="si">
                      <Icon name={s.icon} />
                    </span>
                    <div>
                      <b style={{ fontWeight: 600 }}>{s.title}</b>
                      <div className="small muted num">{s.sub}</div>
                    </div>
                    <span className={`tag ${s.cls}`}>{s.tag}</span>
                  </div>
                ))}
              </div>
              {projectId && (
                <div className="go-grid">
                  {(
                    [
                      ["search", "检索", "search"],
                      ["stats", "统计", "chart"],
                      ["annotate", "标注", "pen"],
                      ["knowledge", "知识库", "book"],
                      ["assistant", "助手", "spark"],
                    ] as [string, string, IconName][]
                  ).map(([p, l, ic]) => (
                    <Link key={p} className="go lift" to={p === "search" ? landing : `/p/${projectId}/${p}`}>
                      <span className="gi">
                        <Icon name={ic} />
                      </span>
                      <b className="grow" style={{ fontWeight: 600 }}>
                        {l}
                      </b>
                      <Icon name="right" size={14} className="muted" />
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="ob-foot">
            <span className="small muted num">
              {step + 1} / {STEPS.length}
            </span>
            <div className="grow" />
            {step >= 1 && step <= 3 && (
              <button className="btn ghost" type="button" onClick={() => setStep((s) => s + 1)}>
                跳过此步
              </button>
            )}
            <button className="btn" type="button" disabled={step === 0 || (step === 1 && !!projectId && !!params.get("project"))} onClick={() => setStep((s) => Math.max(0, s - 1))}>
              上一步
            </button>
            <button className="btn p" type="button" disabled={!canNext || createProject.isPending} onClick={next}>
              {step === STEPS.length - 1 ? "进入检索" : step === 0 && !projectId ? "创建项目" : "下一步"}
              <Icon name="right" size={14} />
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}

function StageRow({ label, job, done, onRetry }: { label: string; job: Job | null; done?: boolean; onRetry: (j: Job) => void }) {
  const total = job?.progress.total ?? null;
  return (
    <div className="stage-row">
      <span>{label}</span>
      {job ? <Progress done={job.progress.done} total={total} state={job.state} /> : <Progress done={done ? 1 : 0} total={1} state={done ? "succeeded" : "queued"} />}
      <span className="num">
        {job
          ? job.state === "failed"
            ? "失败"
            : total
              ? `${fmt(job.progress.done)} / ${fmt(total)}`
              : isActiveJob(job)
                ? `已处理 ${fmt(job.progress.done)}`
                : job.state === "succeeded"
                  ? "完成"
                  : ""
          : done
            ? "完成"
            : "等待"}
      </span>
      {job?.state === "failed" && (
        <div className="alert err" style={{ gridColumn: "1 / -1" }}>
          <Icon name="alert" size={14} />
          <span className="grow">
            {job.error?.message}
            <span className="err-code">{job.error?.code}</span>
          </span>
          <button className="btn xs" type="button" onClick={() => onRetry(job)}>
            重试
          </button>
        </div>
      )}
    </div>
  );
}
