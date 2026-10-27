import { DeleteOutlined } from "@ant-design/icons";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Statistic,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import {
  ApiError,
  MAX_PAGE_SIZE,
  api,
  errorText,
  type Hit,
  type Job,
  type Page,
  type ParseResult,
  type SavedQuery,
  type Scope,
  type SearchRequest,
  type SearchResult,
} from "../api";
import { useCorpora } from "../corpora";
import { useSubcorpora } from "../pages/Subcorpora";
import { useProjectId } from "../projects";
import ContextDrawer from "./ContextDrawer";
import KwicTable from "./KwicTable";
import QueryHelper, { appendSnippet } from "./QueryHelper";

const PAGE_SIZE = 50;
const COUNT_POLL_MS = 3000;
const COUNT_POLL_MAX = 20; // 3 s × 20 = 1 min

const isExpired = (e: unknown) => e instanceof ApiError && e.code === "SEARCH_EXPIRED";
function withoutSearchId(r: SearchRequest): SearchRequest {
  const { search_id: _ignored, ...rest } = r;
  return rest;
}

const scopeKey = (s: Scope) => ("corpus_id" in s ? `corpus:${s.corpus_id}` : `subcorpus:${s.subcorpus_id}`);
function scopeFromKey(key: string): Scope {
  const [kind, id] = key.split(":", 2);
  return kind === "corpus" ? { corpus_id: id } : { subcorpus_id: id };
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ParseFeedback({ query, parse }: { query: string; parse: ParseResult }) {
  if (!parse.ok && parse.error) {
    const chars = Array.from(query);
    const p = parse.error.position;
    return (
      <Alert
        type="error"
        showIcon
        message={`第 ${p + 1} 个字符：${parse.error.message}`}
        description={
          <Typography.Text code>
            {chars.slice(0, p).join("")}
            <span style={{ background: "#ffccc7", textDecoration: "underline wavy red" }}>{chars[p] ?? " "}</span>
            {chars.slice(p + 1).join("")}
          </Typography.Text>
        }
      />
    );
  }
  return (
    <Space size="large" wrap>
      <span>
        主查询 <Typography.Text code>{parse.anchor}</Typography.Text>
      </span>
      <span>
        条件{" "}
        {parse.conditions.length === 0
          ? "无"
          : parse.conditions.map((c, i) => (
              <Typography.Text key={i} code>
                {c.op === "+" ? "同句出现" : "同句不出现"} {c.text}
              </Typography.Text>
            ))}
      </span>
    </Space>
  );
}

export function CountsBar({ counts, timedOut }: { counts: SearchResult["counts"]; timedOut: boolean }) {
  const pending = timedOut ? "未完成" : "计算中";
  const v = (n: number) => (counts.complete ? n.toLocaleString("zh-CN") : pending);
  return (
    <Space size={48}>
      <Statistic title="命中" value={v(counts.hits)} />
      <Statistic title="句" value={v(counts.sentences)} />
      <Statistic title="文档" value={v(counts.documents)} />
    </Space>
  );
}

export default function Search() {
  const projectId = useProjectId();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const corpora = useCorpora(projectId);
  const subcorpora = useSubcorpora(projectId);
  const savedQueries = useQuery({
    queryKey: ["queries", projectId],
    queryFn: () => api.get<Page<SavedQuery>>(`/projects/${projectId}/queries`, { page_size: MAX_PAGE_SIZE }),
  });

  const [scope, setScope] = useState<string>();
  const [query, setQuery] = useState("");
  const [unit, setUnit] = useState<SearchRequest["context"]["unit"]>("char");
  const [size, setSize] = useState(40);
  const [sort, setSort] = useState<SearchRequest["sort"]>("position");
  const [req, setReq] = useState<SearchRequest | null>(null);
  const [open, setOpen] = useState<Hit | null>(null);
  const [saving, setSaving] = useState(false);
  const [runId, setRunId] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const debounced = useDebounced(query.trim(), 400);
  const parse = useQuery({
    queryKey: ["parse", debounced],
    queryFn: () => api.post<ParseResult>("/search/parse", { query: debounced }),
    enabled: debounced.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });

  const search = useQuery({
    queryKey: ["search", runId, req],
    queryFn: async () => {
      try {
        return await api.post<SearchResult>("/search", req);
      } catch (e) {
        if (!isExpired(e) || !req?.search_id) throw e;
        message.info(errorText(e));
        return api.post<SearchResult>("/search", withoutSearchId(req));
      }
    },
    enabled: !!req,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const result = search.data;

  // Re-request the same search_id while counts are incomplete, every 3 s for up to 1 min.
  const [polled, setPolled] = useState<{ id: string; counts: SearchResult["counts"] } | null>(null);
  const [pollState, setPollState] = useState<{ id: string; timedOut: boolean; error?: string } | null>(null);
  const [pollRound, setPollRound] = useState(0);
  useEffect(() => {
    if (!req || !result || result.counts.complete) return;
    const id = result.search_id;
    let n = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    setPollState({ id, timedOut: false });
    const tick = async () => {
      n += 1;
      try {
        const r = await api.post<SearchResult>("/search", { ...req, search_id: id });
        if (stopped) return;
        setPolled({ id, counts: r.counts });
        if (r.counts.complete) return;
      } catch (e) {
        if (stopped) return;
        if (isExpired(e)) {
          message.info(errorText(e));
          setRunId((k) => k + 1);
          setReq(withoutSearchId(req));
        } else {
          setPollState({ id, timedOut: true, error: errorText(e) });
        }
        return;
      }
      if (n < COUNT_POLL_MAX) timer = setTimeout(tick, COUNT_POLL_MS);
      else setPollState({ id, timedOut: true });
    };
    timer = setTimeout(tick, COUNT_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [result?.search_id, result?.counts.complete, pollRound]);

  const counts =
    result && !result.counts.complete && polled?.id === result.search_id ? polled.counts : result?.counts;
  const timedOut = !!result && pollState?.id === result.search_id && pollState.timedOut && !counts?.complete;

  const exportJob = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      return api.post<Job>("/search/export", { ...withoutSearchId(req!), format, project_id: projectId });
    },
    onSuccess: () =>
      message.success(
        <span>
          已创建导出任务，<Link to={`/p/${projectId}/jobs`}>查看任务</Link>
        </span>,
      ),
    onError: (e) => message.error(errorText(e)),
  });

  const saveQuery = useMutation({
    mutationFn: (name: string) =>
      api.post<SavedQuery>(`/projects/${projectId}/queries`, {
        name,
        query: query.trim(),
        scope: scopeFromKey(scope!),
      }),
    onSuccess: () => {
      setSaving(false);
      message.success("已保存");
      qc.invalidateQueries({ queryKey: ["queries", projectId] });
    },
  });
  const deleteQuery = useMutation({
    mutationFn: (id: string) => api.del(`/queries/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queries", projectId] }),
    onError: (e) => message.error(errorText(e)),
  });

  function run() {
    if (!scope || !query.trim()) return;
    const next: SearchRequest = {
      scope: scopeFromKey(scope),
      query: query.trim(),
      context: { unit, size },
      sort,
      page: 1,
      page_size: PAGE_SIZE,
    };
    if (sort === "random") next.seed = Math.floor(Math.random() * 1e9);
    setRunId((n) => n + 1);
    setReq(next);
  }

  function changePage(page: number) {
    if (!req || !result) return;
    setReq({ ...req, page, search_id: result.search_id });
  }

  const scopeOptions = [
    {
      label: "语料库",
      options: (corpora.data?.items ?? []).map((c) => ({
        value: `corpus:${c.id}`,
        label: c.name,
        disabled: c.status !== "ready" && c.status !== "stale",
      })),
    },
    {
      label: "子库",
      options: (subcorpora.data?.items ?? []).map((s) => ({ value: `subcorpus:${s.id}`, label: s.name })),
    },
  ];

  const parseShown = debounced.length > 0 && debounced === query.trim() ? parse.data : undefined;
  const total = counts?.complete
    ? counts.hits
    : result
      ? (result.page - 1) * result.page_size + result.items.length + (result.items.length === result.page_size ? 1 : 0)
      : 0;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Space wrap>
            <Select
              placeholder="范围"
              value={scope}
              onChange={setScope}
              options={scopeOptions}
              style={{ width: 260 }}
              loading={corpora.isPending || subcorpora.isPending}
              showSearch
              optionFilterProp="label"
            />
            <Select
              placeholder="已保存的查询"
              value={null}
              style={{ width: 220 }}
              loading={savedQueries.isPending}
              notFoundContent="暂无保存的查询"
              options={savedQueries.data?.items.map((q) => ({ value: q.id, label: q.name }))}
              optionRender={(o) => (
                <Space style={{ width: "100%", justifyContent: "space-between" }}>
                  <span>{o.label}</span>
                  <DeleteOutlined
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteQuery.mutate(String(o.value));
                    }}
                  />
                </Space>
              )}
              onChange={(id) => {
                const q = savedQueries.data?.items.find((x) => x.id === id);
                if (!q) return;
                setQuery(q.query);
                setScope(scopeKey(q.scope));
              }}
            />
          </Space>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              ref={(el) => {
                inputRef.current = el?.input ?? null;
              }}
              placeholder="查询式"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={() => run()}
              allowClear
            />
            <Button type="primary" onClick={() => run()} disabled={!scope || !query.trim()} loading={search.isFetching}>
              检索
            </Button>
          </Space.Compact>
          {parse.error && <Alert type="error" showIcon message={errorText(parse.error)} />}
          {parseShown && <ParseFeedback query={debounced} parse={parseShown} />}
          <Collapse
            size="small"
            items={[
              {
                key: "helper",
                label: "查询辅助",
                children: (
                  <QueryHelper
                    onInsert={(s) => {
                      setQuery((q) => appendSnippet(q, s));
                      inputRef.current?.focus();
                    }}
                  />
                ),
              },
            ]}
          />
          <Space wrap>
            <span>语境</span>
            <Select
              value={unit}
              onChange={setUnit}
              style={{ width: 100 }}
              options={[
                { value: "char", label: "字符" },
                { value: "sentence", label: "整句" },
                { value: "paragraph", label: "整段" },
              ]}
            />
            {unit === "char" && (
              <InputNumber min={5} max={200} value={size} onChange={(v) => setSize(v ?? 40)} addonAfter="字" />
            )}
            <span>排序</span>
            <Select
              value={sort}
              onChange={setSort}
              style={{ width: 110 }}
              options={[
                { value: "position", label: "出处" },
                { value: "left", label: "左语境" },
                { value: "right", label: "右语境" },
                { value: "random", label: "随机" },
              ]}
            />
            <Button onClick={() => setSaving(true)} disabled={!scope || !query.trim()}>
              保存查询
            </Button>
          </Space>
        </Space>
      </Card>

      {search.error && <Alert type="error" showIcon message={errorText(search.error)} />}
      {result && counts && (
        <Card
          title={<CountsBar counts={counts} timedOut={timedOut} />}
          extra={
            <Space>
              {timedOut && (
                <Button onClick={() => setPollRound((n) => n + 1)}>继续计数</Button>
              )}
              <Button onClick={() => exportJob.mutate("csv")} loading={exportJob.isPending}>
                导出 CSV
              </Button>
              <Button onClick={() => exportJob.mutate("xlsx")} loading={exportJob.isPending}>
                导出 XLSX
              </Button>
            </Space>
          }
        >
          {pollState?.error && pollState.id === result.search_id && (
            <Alert type="error" showIcon message={pollState.error} style={{ marginBottom: 12 }} />
          )}
          <KwicTable
            items={result.items}
            offset={(result.page - 1) * result.page_size}
            loading={search.isFetching}
            onOpen={setOpen}
            pagination={{
              current: result.page,
              pageSize: result.page_size,
              total,
              showSizeChanger: false,
              onChange: changePage,
            }}
          />
        </Card>
      )}

      <ContextDrawer hit={open} onClose={() => setOpen(null)} />
      <Modal title="保存查询" open={saving} footer={null} onCancel={() => setSaving(false)} destroyOnClose>
        <Form layout="vertical" onFinish={(v: { name: string }) => saveQuery.mutate(v.name.trim())}>
          <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}>
            <Input maxLength={100} />
          </Form.Item>
          {saveQuery.error && (
            <Alert type="error" showIcon message={errorText(saveQuery.error)} style={{ marginBottom: 12 }} />
          )}
          <Button type="primary" htmlType="submit" loading={saveQuery.isPending}>
            保存
          </Button>
        </Form>
      </Modal>
    </Space>
  );
}
