import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { StatResult } from "../src/api";

const shell = {
  projectId: "p1",
  scope: { corpus_id: "c1" } as { corpus_id: string },
  setScope: () => {},
  scopeInfo: { corpus: null, subcorpus: null, name: "UD 英文" },
  assistantOpen: false,
  setAssistantOpen: () => {},
  assistantContext: null,
  setAssistantContext: () => {},
  openPalette: () => {},
  openKeys: () => {},
};
vi.mock("../src/components/shell/shell", () => ({ useShell: () => shell, useOptionalShell: () => shell }));
vi.mock("../src/components/shell/AppShell", () => ({
  PageHeader: ({ title, actions }: { title: string; actions?: React.ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  ),
}));
vi.mock("../src/components/global/MethodAppendix", () => ({ MethodAppendix: () => null }));

import Stats from "../src/features/stats/Stats";
import { sideOf } from "../src/features/stats/P10Results";

const WAIT = { timeout: 10_000 };
const SLOW = 30_000;
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });

const corpora = [
  { id: "c1", name: "UD 英文", language: "en", parallel: false, status: "ready", stats: { tokens: 1000, sentences: 50, documents: 3 }, index_version: 3 },
  { id: "c2", name: "学习者中文", language: "zh", parallel: false, status: "ready", stats: { tokens: 2000, sentences: 80, documents: 4 }, index_version: 1 },
];
const vocabLists = [
  { id: "ngsl", project_id: null, name: "NGSL 1.2", language: "en", levels: ["1", "2", "3"], source: "NGSL", license: "CC BY-SA 4.0", entries: 2801, created_at: "2026-11-01T00:00:00Z" },
  { id: "hsk", project_id: "p1", name: "HSK 3.0", language: "zh", levels: ["1", "2"], source: null, license: null, entries: 500, created_at: "2026-11-02T00:00:00Z" },
];

const base = {
  project_id: "p1",
  scope: { corpus_id: "c1", subcorpus_id: null, name: "UD 英文" },
  index_version: 3,
  totals: { tokens: 1000, sentences: 50, documents: 3 },
  created_at: "2026-11-06T00:00:00Z",
};

type Call = { method: string; path: string; body: unknown };

function mockFetch(handle: (method: string, path: string, body: unknown) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    const raw = init?.body;
    const body = raw instanceof FormData ? raw : raw ? JSON.parse(String(raw)) : undefined;
    calls.push({ method, path: url.pathname, body });
    const out = handle(method, url.pathname, body);
    return out instanceof Response ? out : json(out ?? {});
  });
  return calls;
}

function defaults(path: string): unknown {
  if (path === "/api/corpora") return { items: corpora, total: corpora.length };
  if (path === "/api/projects/p1") return { id: "p1", name: "P", role: "owner" };
  if (path === "/api/projects/p1/subcorpora") return { items: [], total: 0 };
  if (path === "/api/projects/p1/layers") return [{ id: "L1", kind: "dep", status: "ready", corpus_id: "c2", name: "依存预标" }];
  if (path === "/api/projects/p1/vocab-lists") return vocabLists;
  if (/^\/api\/corpora\/c\d\/metadata-fields$/.test(path))
    return [
      { field: "year", type: "number" },
      { field: "genre", type: "string", values: ["news", "fiction"] },
    ];
  return {};
}

const queued = { id: "j1", kind: "stats", state: "queued", progress: { done: 0, total: 0 }, result: null };

function SearchProbe() {
  const p = new URLSearchParams(useLocation().search);
  return (
    <div>
      <span data-testid="q">{p.get("q")}</span>
      <span data-testid="layers">{p.get("layers")}</span>
      <span data-testid="scope">{p.get("scope")}</span>
      <span data-testid="kind">{p.get("kind")}</span>
    </div>
  );
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/p/:projectId/stats" element={<Stats />} />
            <Route path="/p/:projectId/search" element={<SearchProbe />} />
            <Route path="/p/:projectId/annotate" element={<SearchProbe />} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

async function pick(label: string, option: string, root: HTMLElement = document.body) {
  const item = within(root).getByText(label, { selector: "label" }).closest(".ant-form-item") as HTMLElement;
  fireEvent.mouseDown(item.querySelector(".ant-select-selector")!);
  const opts = await screen.findAllByText(option, { selector: ".ant-select-item-option-content" }, WAIT);
  fireEvent.click(opts[opts.length - 1]);
}

const posted = (calls: Call[], path: string) => calls.find((c) => c.method === "POST" && c.path === path)?.body as Record<string, unknown> | undefined;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  shell.scope = { corpus_id: "c1" };
});

describe("文本指标", () => {
  it("posts metrics, group and window", async () => {
    const calls = mockFetch((m, path) => (m === "POST" ? queued : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /文本指标/ }, WAIT));
    await screen.findByText("STTR 窗口（词）", { selector: "label" }, WAIT);
    await pick("按元数据分组", "genre");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/text_metrics")).toBeTruthy(), WAIT);
    const body = posted(calls, "/api/stats/text_metrics")!;
    expect(body).toMatchObject({ project_id: "p1", scope: { corpus_id: "c1" }, group_by: "genre", sttr_window: 1000 });
    expect(body.metrics).toEqual(["words", "sentences", "ttr", "sttr", "mtld", "lexical_density", "mean_sentence_length", "mean_dependency_distance", "flesch_reading_ease", "flesch_kincaid_grade"]);
  }, SLOW);

  it("shows documents, the group summary, notes and formula headers", async () => {
    const stat: StatResult = {
      ...base,
      id: "tm1",
      method: "text_metrics",
      params: { scope: { corpus_id: "c1" }, group_by: "genre", sttr_window: 1000 },
      totals: {
        ...base.totals,
        groups: {
          words: [
            { value: "news", documents: 2, mean: 450, sd: 70.71 },
            { value: "（无）", documents: 1, mean: 80, sd: null },
          ],
          ttr: [
            { value: "news", documents: 2, mean: 0.5, sd: 0.05 },
            { value: "（无）", documents: 1, mean: 0.6, sd: null },
          ],
          mtld: [
            { value: "news", documents: 2, mean: 70, sd: 4.2 },
            { value: "（无）", documents: 0, mean: null, sd: null },
          ],
        },
        notes: ["1 篇词数 < 100，STTR、MTLD 为空"],
      },
      columns: [
        { key: "title", label: "标题", type: "string" },
        { key: "group", label: "genre", type: "string" },
        { key: "words", label: "词数（不含标点）", type: "number" },
        { key: "ttr", label: "TTR", type: "number" },
        { key: "mtld", label: "MTLD", type: "number" },
      ],
      rows: [
        { key: "d1", values: { title: "Doc 1", group: "news", words: 500, ttr: 0.45, mtld: 67 }, search_query: null, search_scope: { corpus_id: "c1" } },
        { key: "d2", values: { title: "Doc 2", group: "news", words: 400, ttr: 0.55, mtld: 73 }, search_query: null, search_scope: { corpus_id: "c1" } },
        { key: "d3", values: { title: "Doc 3", group: "（无）", words: 80, ttr: 0.6, mtld: null }, search_query: null, search_scope: { corpus_id: "c1" } },
      ],
      row_count: 3,
    };
    mockFetch((_m, path) => (path === "/api/stats/tm1" ? stat : defaults(path)));
    const { container } = renderAt("/p/p1/stats?stat=tm1");
    expect(await screen.findByText("Doc 1", {}, WAIT)).toBeTruthy();
    expect(screen.getByText("1 篇词数 < 100，STTR、MTLD 为空")).toBeTruthy();
    const summary = screen.getByRole("table", { name: "分组汇总" });
    expect(within(summary).getByText("0.5 ± 0.05")).toBeTruthy();
    expect(within(summary).getByText("70 ± 4.2")).toBeTruthy();
    expect(screen.getByText(/STTR 窗口 1,000 词/)).toBeTruthy();
    const tips = Array.from(container.querySelectorAll("th .col-tip")).map((x) => x.textContent);
    expect(tips).toContain("TTR");
    expect(tips).toContain("MTLD");
    // per-document rows have no example link
    expect(screen.queryByRole("button", { name: /回到例句/ })).toBeNull();
    expect(screen.getByText(/箱线图 · TTR/)).toBeTruthy();
  }, SLOW);
});

describe("词汇等级", () => {
  it("defaults to a list in the corpus language and posts list and by", async () => {
    const calls = mockFetch((m, path) => (m === "POST" ? queued : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /词汇等级/ }, WAIT));
    await screen.findByText("NGSL 1.2（内置） · en", {}, WAIT);
    await pick("按", "每篇");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/vocab_profile")).toBeTruthy(), WAIT);
    expect(posted(calls, "/api/stats/vocab_profile")).toMatchObject({ scope: { corpus_id: "c1" }, list_id: "ngsl", by: "document" });
  }, SLOW);

  it("管理词表 lists, uploads and deletes project lists", async () => {
    const calls = mockFetch((m, path) => {
      if (m === "POST" && path === "/api/projects/p1/vocab-lists") return { ...vocabLists[1], id: "new", name: "AWL" };
      if (m === "DELETE") return new Response(null, { status: 204 });
      return defaults(path);
    });
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /词汇等级/ }, WAIT));
    fireEvent.click(await screen.findByRole("button", { name: /管理词表/ }, WAIT));
    const dialog = await screen.findByRole("dialog", {}, WAIT);
    expect(await within(dialog).findByText("NGSL · CC BY-SA 4.0", {}, WAIT)).toBeTruthy();
    expect(within(dialog).getByText("2,801")).toBeTruthy();
    // the built-in list cannot be deleted
    expect(within(dialog).queryByRole("button", { name: "删除 NGSL 1.2" })).toBeNull();

    fireEvent.change(within(dialog).getByLabelText("名称"), { target: { value: "AWL" } });
    const file = new File(["analyse,1\nconcept,1\n"], "awl.csv", { type: "text/csv" });
    fireEvent.change(within(dialog).getByLabelText("词表文件"), { target: { files: [file] } });
    fireEvent.click(within(dialog).getByRole("button", { name: /上传/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/projects/p1/vocab-lists")).toBe(true), WAIT);
    const form = calls.find((c) => c.method === "POST" && c.path === "/api/projects/p1/vocab-lists")!.body as FormData;
    expect(form.get("name")).toBe("AWL");
    expect(form.get("language")).toBe("zh");
    expect((form.get("file") as File).name).toBe("awl.csv");

    fireEvent.click(within(dialog).getByRole("button", { name: "删除 HSK 3.0" }));
    fireEvent.click(await screen.findByRole("button", { name: /^删.?除$/ }, WAIT));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/vocab-lists/hsk")).toBe(true), WAIT);
  }, SLOW);

  it("level rows go back to the search; the off-list row is kept", async () => {
    const stat: StatResult = {
      ...base,
      id: "vp1",
      method: "vocab_profile",
      params: { scope: { corpus_id: "c1" }, list_id: "ngsl", by: "corpus" },
      totals: { ...base.totals, words: 1000, levels: ["1", "2", "表外"], off_list: [{ item: "zyx", freq: 7, search_query: '"zyx"' }] },
      columns: [
        { key: "level", label: "等级", type: "string" },
        { key: "tokens", label: "词次", type: "number" },
        { key: "types", label: "词种", type: "number" },
        { key: "coverage", label: "词次覆盖率 %", type: "number" },
      ],
      rows: [
        { key: "1", values: { level: "1", tokens: 700, types: 300, coverage: 70 }, search_query: "{lemma=the|be}", search_scope: { corpus_id: "c1" } },
        { key: "2", values: { level: "2", tokens: 200, types: 150, coverage: 20 }, search_query: null, search_scope: { corpus_id: "c1" } },
        { key: "表外", values: { level: "表外", tokens: 100, types: 90, coverage: 10 }, search_query: null, search_scope: { corpus_id: "c1" } },
      ],
      row_count: 3,
    };
    mockFetch((_m, path) => (path === "/api/stats/vp1" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=vp1");
    expect((await screen.findAllByText("表外", {}, WAIT)).length).toBeGreaterThan(0);
    expect(screen.getByText("等级覆盖率 · 词次 %")).toBeTruthy();
    fireEvent.click(within(screen.getByLabelText("表外词")).getByRole("button", { name: "7" }));
    expect(screen.getByTestId("q").textContent).toBe('"zyx"');
  }, SLOW);

  it("level rows go back to the search", async () => {
    const stat: StatResult = {
      ...base,
      id: "vp0",
      method: "vocab_profile",
      params: { scope: { corpus_id: "c1" }, list_id: "ngsl", by: "corpus" },
      totals: { ...base.totals, levels: ["1", "表外"] },
      columns: [
        { key: "level", label: "等级", type: "string" },
        { key: "tokens", label: "词次", type: "number" },
        { key: "coverage", label: "词次覆盖率 %", type: "number" },
      ],
      rows: [{ key: "1", values: { level: "1", tokens: 700, coverage: 70 }, search_query: '"the"|"be"', search_scope: { corpus_id: "c1" } }],
      row_count: 1,
    };
    mockFetch((_m, path) => (path === "/api/stats/vp0" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=vp0");
    fireEvent.click(await screen.findByRole("button", { name: "700" }, WAIT));
    expect(screen.getByTestId("q").textContent).toBe('"the"|"be"');
  }, SLOW);

  it("by document: a coverage column per level", async () => {
    const stat: StatResult = {
      ...base,
      id: "vp2",
      method: "vocab_profile",
      params: { scope: { corpus_id: "c1" }, list_id: "ngsl", by: "document" },
      totals: { ...base.totals, levels: ["1", "2", "表外"] },
      columns: [
        { key: "item", label: "文档", type: "string" },
        { key: "words", label: "词数", type: "number" },
        { key: "level_1", label: "1 %", type: "number" },
        { key: "level_2", label: "2 %", type: "number" },
        { key: "off_list", label: "表外 %", type: "number" },
      ],
      rows: [{ key: "d1", values: { item: "Doc 1", words: 300, level_1: 80.5, level_2: 12, off_list: 7.5 }, search_query: null, search_scope: { corpus_id: "c1" } }],
      row_count: 1,
    };
    mockFetch((_m, path) => (path === "/api/stats/vp2" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=vp2");
    expect(await screen.findByText("80.5", {}, WAIT)).toBeTruthy();
    expect(screen.getByText("表外 %")).toBeTruthy();
    expect(screen.getByText(/按每篇/)).toBeTruthy();
  }, SLOW);
});

describe("对比", () => {
  it("posts 2 items with labels, ranges and queries; Mann-Whitney only for two items", async () => {
    const calls = mockFetch((m, path) => (m === "POST" ? queued : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: "对比" }, WAIT));
    fireEvent.change(await screen.findByLabelText("第 1 项查询式", {}, WAIT), { target: { value: "big" } });
    fireEvent.change(screen.getByLabelText("第 2 项查询式"), { target: { value: "large" } });
    await pick("检验", "Mann-Whitney U（两项）");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/compare")).toBeTruthy(), WAIT);
    expect(posted(calls, "/api/stats/compare")).toEqual({
      project_id: "p1",
      items: [
        { label: "A", scope: { corpus_id: "c1" }, query: "big" },
        { label: "B", scope: { corpus_id: "c1" }, query: "large" },
      ],
      by: null,
      test: "mann_whitney",
    });

    // a third item turns the two-item test off
    fireEvent.click(screen.getByRole("button", { name: /添加一项/ }));
    expect(await screen.findByLabelText("第 3 项查询式", {}, WAIT)).toBeTruthy();
    await waitFor(() => expect(screen.getByText("无", { selector: ".ant-select-selection-item" })).toBeTruthy(), WAIT);
  }, SLOW);

  it("shows the test card and a per-field chart", async () => {
    const stat: StatResult = {
      ...base,
      id: "cmp1",
      method: "compare",
      params: { items: [{ label: "big", scope: { corpus_id: "c1" }, query: "big" }, { label: "large", scope: { corpus_id: "c1" }, query: "large" }], by: null, test: "mann_whitney" },
      totals: { ...base.totals, items: 2, comparison: { ll: 12.345, log_ratio: -0.8, significance: "***", smoothed: false }, test: { method: "mann_whitney", u: 12, z: -2.1, p: 0.0357, r: -0.42, n1: 10, n2: 12 } },
      columns: [
        { key: "label", label: "项", type: "string" },
        { key: "hits", label: "命中", type: "number" },
        { key: "per_million", label: "每百万词", type: "number" },
        { key: "doc_freq_pct", label: "文档频率 %", type: "number" },
      ],
      rows: [
        { key: "big", values: { label: "big", hits: 30, per_million: 300, doc_freq_pct: 66.7 }, search_query: "big", search_scope: { corpus_id: "c1" } },
        { key: "large", values: { label: "large", hits: 12, per_million: 120, doc_freq_pct: 33.3 }, search_query: "large", search_scope: { corpus_id: "c1" } },
      ],
      row_count: 2,
    };
    mockFetch((_m, path) => (path === "/api/stats/cmp1" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=cmp1");
    const card = await screen.findByLabelText("检验结果", {}, WAIT);
    expect(within(card).getByText("Mann-Whitney U")).toBeTruthy();
    expect(within(card).getByText("−2.1")).toBeTruthy();
    expect(within(card).getByText("0.036")).toBeTruthy();
    expect(within(card).getByText("−0.42")).toBeTruthy();
    expect(within(card).getByText("10 / 12 篇")).toBeTruthy();
    expect(within(card).getByText("12.35 ***")).toBeTruthy();
    expect(within(card).getByText("−0.8")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "30" }));
    expect(screen.getByTestId("q").textContent).toBe("big");
  }, SLOW);

  it("shows Spearman per item", async () => {
    const stat: StatResult = {
      ...base,
      id: "cmp2",
      method: "compare",
      params: { items: [{ label: "A", scope: { corpus_id: "c1" }, query: "a" }, { label: "B", scope: { corpus_id: "c1" }, query: "b" }], by: "year", test: "spearman" },
      totals: { ...base.totals, test: { method: "spearman", field: "year", items: [{ label: "A", rho: 0.61, p: 0.0004, n: 30 }, { label: "B", rho: -0.2, p: 0.29, n: 30 }] } },
      columns: [
        { key: "value", label: "year", type: "number" },
        { key: "hits_1", label: "A 命中数", type: "number" },
        { key: "per_million_1", label: "A 每百万词", type: "number" },
        { key: "hits_2", label: "B 命中数", type: "number" },
        { key: "per_million_2", label: "B 每百万词", type: "number" },
      ],
      rows: [2000, 2010].map((y, i) => ({
        key: String(y),
        values: { value: y, hits_1: 3 + i, per_million_1: 10 + i * 10, hits_2: 2, per_million_2: 5 - i },
        search_query: null,
        search_scope: { corpus_id: "c1" },
        searches: [
          { label: "A", search_query: "a", search_scope: { corpus_id: "c1", filter: { year: y } } },
          { label: "B", search_query: "b", search_scope: { corpus_id: "c1", filter: { year: y } } },
        ],
      })),
      row_count: 2,
    };
    mockFetch((_m, path) => (path === "/api/stats/cmp2" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=cmp2");
    const table = await screen.findByRole("table", { name: "Spearman" }, WAIT);
    expect(within(table).getByText("0.61")).toBeTruthy();
    expect(within(table).getByText("4.00e-4")).toBeTruthy();
    expect(within(table).getByText("−0.2")).toBeTruthy();
    expect(screen.getByText("每百万词 · 按 year")).toBeTruthy();
    // a by row has no single 回到例句; each item's hits open that item narrowed to the value
    expect(screen.queryByRole("button", { name: /回到例句/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    expect(screen.getByTestId("q").textContent).toBe("a");
    expect(JSON.parse(screen.getByTestId("scope").textContent!)).toEqual({ corpus_id: "c1", filter: { year: 2010 } });
  }, SLOW);
});

const sketch: StatResult = {
  ...base,
  id: "ws1",
  method: "word_sketch",
  params: { scope: { corpus_id: "c1" }, lemma: "make", pos: "VERB", min_freq: 2, top: 25 },
  totals: {
    ...base.totals,
    lemma: "make",
    node_freq: 40,
    relations: [
      { key: "object", label: "宾语", freq: 17, rows: 2 },
      { key: "subject", label: "主语", freq: 8, rows: 1 },
      { key: "pp:with", label: "with + N", freq: 0, rows: 0 },
    ],
  },
  columns: [
    { key: "relation_label", label: "关系", type: "string" },
    { key: "collocate", label: "搭配词", type: "string" },
    { key: "freq", label: "共现频次", type: "number" },
    { key: "coll_freq", label: "该关系中搭配词频次", type: "number" },
    { key: "logdice", label: "logDice", type: "number" },
  ],
  rows: [
    {
      key: "object\tdecision",
      values: { relation: "object", relation_label: "宾语", collocate: "decision", freq: 12, coll_freq: 14, logdice: 10.5 },
      search_query: '"decision"{dep=obj} + "made"',
      search_scope: { corpus_id: "c1" },
      search_layers: { dep: "L9" },
    },
    { key: "object\tsense", values: { relation: "object", relation_label: "宾语", collocate: "sense", freq: 5, coll_freq: 6, logdice: 9.1 }, search_query: null, search_scope: { corpus_id: "c1" } },
    { key: "subject\twe", values: { relation: "subject", relation_label: "主语", collocate: "we", freq: 8, coll_freq: 30, logdice: 8.2 }, search_query: null, search_scope: { corpus_id: "c1" } },
  ],
  row_count: 3,
};

describe("词汇画像", () => {
  it("posts lemma, pos and the Chinese dependency layer", async () => {
    shell.scope = { corpus_id: "c2" };
    const calls = mockFetch((m, path) => (m === "POST" ? queued : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /词汇画像/ }, WAIT));
    fireEvent.change(await screen.findByPlaceholderText("make", {}, WAIT), { target: { value: "打" } });
    await pick("词性", "动词 VERB");
    await pick("依存层", "依存预标");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/word_sketch")).toBeTruthy(), WAIT);
    expect(posted(calls, "/api/stats/word_sketch")).toEqual({ project_id: "p1", scope: { corpus_id: "c2" }, lemma: "打", pos: "VERB", min_freq: 2, top: 25, layers: { dep: "L1" } });
  }, SLOW);

  it("shows one card per relation; a collocate opens its examples", async () => {
    mockFetch((_m, path) => (path === "/api/stats/ws1" ? sketch : defaults(path)));
    renderAt("/p/p1/stats?stat=ws1");
    const obj = await screen.findByRole("region", { name: "宾语" }, WAIT);
    expect(within(obj).getByText("10.5")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "主语" })).getByText("we")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "with + N" })).getByText("无")).toBeTruthy();
    // no link when the query cannot be expressed
    expect(within(obj).queryByRole("button", { name: "sense" })).toBeNull();
    fireEvent.click(within(obj).getByRole("button", { name: "decision" }));
    expect(screen.getByTestId("q").textContent).toBe('"decision"{dep=obj} + "made"');
    expect(JSON.parse(screen.getByTestId("layers").textContent!)).toEqual({ dep: "L9" });
  }, SLOW);

  it("NO_DEPENDENCIES shows the backend message and a link to the annotate page", async () => {
    shell.scope = { corpus_id: "c2" };
    mockFetch((m, path) =>
      m === "POST" ? json({ error: { code: "NO_DEPENDENCIES", message: "该语料没有依存标注，请先在标注页建依存层" } }, 422) : defaults(path),
    );
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /词汇画像/ }, WAIT));
    fireEvent.change(await screen.findByPlaceholderText("make", {}, WAIT), { target: { value: "打" } });
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    expect(await screen.findByText("该语料没有依存标注，请先在标注页建依存层", {}, WAIT)).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "去标注页建依存层" }));
    expect(screen.getByTestId("kind").textContent).toBe("dep");
  }, SLOW);
});

describe("近义词对比", () => {
  it("posts both lemmas and rejects the same lemma", async () => {
    const calls = mockFetch((m, path) => (m === "POST" ? queued : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("tab", { name: /近义词对比/ }, WAIT));
    fireEvent.change(await screen.findByPlaceholderText("big", {}, WAIT), { target: { value: "big" } });
    fireEvent.change(screen.getByPlaceholderText("large"), { target: { value: "big" } });
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    expect(await screen.findByText("与词元 A 相同", {}, WAIT)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("large"), { target: { value: "large" } });
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/sketch_diff")).toBeTruthy(), WAIT);
    expect(posted(calls, "/api/stats/sketch_diff")).toMatchObject({ scope: { corpus_id: "c1" }, lemma_a: "big", lemma_b: "large", min_freq: 2, top: 25 });
  }, SLOW);

  it("splits each relation into 偏 A / 共同 / 偏 B", async () => {
    const row = (c: string, fa: number, fb: number, diff: number, group: string) => ({
      key: `amod_of\t${c}`,
      values: { relation: "amod_of", relation_label: "所修饰的词（amod）", collocate: c, freq_a: fa, freq_b: fb, logdice_a: 8, logdice_b: 8 - diff, diff, group },
      search_query: fa ? `"${c}" + "big"` : `"${c}" + "large"`,
      search_query_b: fb ? `"${c}" + "large"` : null,
      search_scope: { corpus_id: "c1" },
    });
    const stat: StatResult = {
      ...base,
      id: "sd1",
      method: "sketch_diff",
      params: { scope: { corpus_id: "c1" }, lemma_a: "big", lemma_b: "large", min_freq: 2, top: 25 },
      totals: { ...base.totals, relations: [{ key: "amod_of", label: "所修饰的词（amod）", freq_a: 16, freq_b: 21, rows: 4 }] },
      columns: [
        { key: "relation", label: "关系", type: "string" },
        { key: "collocate", label: "搭配词", type: "string" },
        { key: "freq_a", label: "频次 A", type: "number" },
        { key: "freq_b", label: "频次 B", type: "number" },
        { key: "diff", label: "diff", type: "number" },
      ],
      rows: [row("deal", 9, 0, 6, "a"), row("house", 4, 5, 0.3, "common"), row("number", 1, 9, -2.5, "b"), row("scale", 0, 7, -5, "b")],
      row_count: 4,
    };
    mockFetch((_m, path) => (path === "/api/stats/sd1" ? stat : defaults(path)));
    renderAt("/p/p1/stats?stat=sd1");
    const rel = await screen.findByRole("region", { name: "所修饰的词（amod）" }, WAIT);
    const colA = within(rel).getByLabelText("偏 big");
    const common = within(rel).getByLabelText("共同");
    const colB = within(rel).getByLabelText("偏 large");
    expect(within(colA).getByText("deal")).toBeTruthy();
    expect(within(common).getByText("house")).toBeTruthy();
    expect(within(colB).getByText("scale")).toBeTruthy();
    expect(within(colB).getByText("number")).toBeTruthy();
    expect(within(colB).getByText("−5")).toBeTruthy();
    expect(sideOf(stat.rows[3])).toBe("b");
  }, SLOW);
});

describe("导出整洁数据", () => {
  it("starts an export job with range, queries, metrics and format", async () => {
    const calls = mockFetch((m, path) => (m === "POST" && path === "/api/stats/tidy_export" ? { id: "e1", kind: "export", state: "queued", progress: { done: 0, total: 0 }, result: null } : defaults(path)));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("button", { name: /导出整洁数据/ }, WAIT));
    const dialog = await screen.findByRole("dialog", {}, WAIT);
    fireEvent.change(within(dialog).getByLabelText("查询式"), { target: { value: "big\n\n large \n" } });
    fireEvent.click(within(dialog).getByText("附文本指标"));
    fireEvent.click(within(dialog).getByText("XLSX"));
    fireEvent.click(within(dialog).getByRole("button", { name: /导.?出/ }));
    await waitFor(() => expect(posted(calls, "/api/stats/tidy_export")).toBeTruthy(), WAIT);
    expect(posted(calls, "/api/stats/tidy_export")).toEqual({ project_id: "p1", scope: { corpus_id: "c1" }, queries: ["big", "large"], metrics: true, format: "xlsx" });
  }, SLOW);

  it("refuses more than 10 queries", async () => {
    const calls = mockFetch((_m, path) => defaults(path));
    renderAt("/p/p1/stats");
    fireEvent.click(await screen.findByRole("button", { name: /导出整洁数据/ }, WAIT));
    const dialog = await screen.findByRole("dialog", {}, WAIT);
    fireEvent.change(within(dialog).getByLabelText("查询式"), { target: { value: Array.from({ length: 11 }, (_, i) => `q${i}`).join("\n") } });
    fireEvent.click(within(dialog).getByRole("button", { name: /导.?出/ }));
    expect(await within(dialog).findByText("最多 10 个查询式", {}, WAIT)).toBeTruthy();
    expect(posted(calls, "/api/stats/tidy_export")).toBeUndefined();
  }, SLOW);
});
