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
  scopeInfo: { corpus: null, subcorpus: null, name: "UD 中文" },
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
vi.mock("../src/components/global/MethodAppendix", () => ({
  MethodAppendix: (p: { projectId: string; statIds?: string[]; onClose: () => void }) => (
    <div data-testid="appendix">
      {p.projectId}:{(p.statIds ?? []).join(",")}
      <button type="button" onClick={p.onClose}>
        关闭附录
      </button>
    </div>
  ),
}));

import { rowSearchHref, StatTable } from "../src/features/stats/StatTable";
import Stats from "../src/features/stats/Stats";

const WAIT = { timeout: 10_000 };
const SLOW = 30_000;
const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });

const corpora = [
  { id: "c1", name: "UD 中文", language: "zh", parallel: false, status: "ready", stats: { tokens: 1000, sentences: 50, documents: 2 }, index_version: 3 },
  { id: "c2", name: "Tatoeba 中英", language: "zh-en", parallel: true, status: "ready", stats: { tokens: 2000, sentences: 80, documents: 1 }, index_version: 1 },
];

const base = {
  project_id: "p1",
  scope: { corpus_id: "c2", subcorpus_id: null, name: "Tatoeba 中英" },
  index_version: 1,
  totals: { tokens: 2000, sentences: 80, documents: 1, hit_sentences: 40, aligned_sentences: 38, unaligned: 2 },
  created_at: "2026-11-05T00:00:00Z",
};

const translations: StatResult = {
  ...base,
  id: "st1",
  method: "translations",
  params: { query: "翻译", unit: "word", measure: "dice" },
  columns: [
    { key: "item", label: "译文词", type: "string" },
    { key: "cooc", label: "共现句数", type: "number" },
    { key: "pct", label: "占命中句 %", type: "number" },
    { key: "target_freq", label: "目标侧句数", type: "number" },
    { key: "dice", label: "Dice", type: "number" },
    { key: "ll", label: "LL", type: "number" },
  ],
  rows: [
    {
      key: "translate",
      values: { item: "translate", cooc: 21, pct: 52.5, target_freq: 1234, dice: 0.0412, ll: 88.123 },
      search_query: "翻译",
      search_scope: { corpus_id: "c2" },
      search_aligned: { op: "+", query: '"translate"' },
    },
  ],
  row_count: 1,
};

function SearchProbe() {
  const p = new URLSearchParams(useLocation().search);
  return (
    <div>
      <span data-testid="q">{p.get("q")}</span>
      <span data-testid="aligned">{p.get("aligned")}</span>
    </div>
  );
}

function mockFetch(handle: (method: string, path: string, body: unknown) => unknown) {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (method === "POST") posts.push({ path: url.pathname, body });
    return json(handle(method, url.pathname, body));
  });
  return posts;
}

function defaults(path: string): unknown {
  if (path === "/api/corpora") return { items: corpora, total: corpora.length };
  if (path === "/api/projects/p1/subcorpora") return { items: [], total: 0 };
  if (path === "/api/projects/p1/layers") return [];
  if (/^\/api\/corpora\/c\d\/metadata-fields$/.test(path))
    return [
      { field: "year", type: "number" },
      { field: "language", type: "string", values: ["zh", "en"] },
    ];
  return {};
}

function renderAt(path: string, node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/p/:projectId/stats" element={node} />
            <Route path="/p/:projectId/search" element={<SearchProbe />} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

/** Open an AntD select by its form label and pick an option. */
async function pick(label: string, option: string) {
  const item = screen.getByText(label, { selector: "label" }).closest(".ant-form-item") as HTMLElement;
  fireEvent.mouseDown(item.querySelector(".ant-select-selector")!);
  const opts = await screen.findAllByText(option, { selector: ".ant-select-item-option-content" }, WAIT);
  fireEvent.click(opts[opts.length - 1]);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  shell.scope = { corpus_id: "c1" };
});

describe("stats rows → search with the translation condition", () => {
  it("adds ?aligned= as JSON {op, query}", () => {
    const url = rowSearchHref("p1", "翻译", { corpus_id: "c2" }, undefined, { op: "+", query: '"translate"' });
    const p = new URLSearchParams(url.split("?")[1]);
    expect(p.get("q")).toBe("翻译");
    expect(JSON.parse(p.get("aligned")!)).toEqual({ op: "+", query: '"translate"' });
    expect(new URLSearchParams(rowSearchHref("p1", "x", { corpus_id: "c1" }).split("?")[1]).has("aligned")).toBe(false);
  });

  it("回到例句 and the co-occurrence number carry search_aligned", () => {
    renderAt("/p/p1/stats", <StatTable stat={translations} projectId="p1" />);
    expect(screen.getByText("0.04")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "21" }));
    expect(screen.getByTestId("q").textContent).toBe("翻译");
    expect(JSON.parse(screen.getByTestId("aligned").textContent!)).toEqual({ op: "+", query: '"translate"' });
  });
});

describe("new columns", () => {
  it("formats signed effect sizes with a minus sign and gives formula headers", () => {
    const stat: StatResult = {
      ...base,
      id: "k1",
      method: "keywords",
      params: {},
      columns: [
        { key: "item", label: "词", type: "string" },
        { key: "target_freq", label: "目标频次", type: "number" },
        { key: "pct_diff", label: "%DIFF", type: "number" },
        { key: "odds_ratio", label: "Odds Ratio", type: "number" },
        { key: "log_ratio_ci_low", label: "LR 下限", type: "number" },
        { key: "log_ratio_ci_high", label: "LR 上限", type: "number" },
        { key: "bonferroni", label: "Bonferroni", type: "string" },
        { key: "dp", label: "DP", type: "number" },
      ],
      rows: [
        {
          key: "的",
          values: { item: "的", target_freq: 12345, smoothed: true, pct_diff: -42.123, odds_ratio: 0.57, log_ratio_ci_low: -1.2345, log_ratio_ci_high: 0.25, bonferroni: "**", dp: null },
          search_query: '"的"',
          search_scope: { corpus_id: "c1" },
        },
      ],
      row_count: 1,
    };
    const { container } = renderAt("/p/p1/stats", <StatTable stat={stat} projectId="p1" />);
    expect(screen.getByText("12,345")).toBeTruthy();
    expect(screen.getByText("−42.12")).toBeTruthy();
    expect(screen.getByText("−1.23")).toBeTruthy();
    expect(screen.getByText("**")).toBeTruthy();
    expect(screen.getAllByText("平滑")).toHaveLength(2);
    // DP is null when there are fewer than two parts
    const cells = container.querySelectorAll("tbody td");
    expect(cells[8].textContent).toBe("—");
    // headers with a formula are hover targets
    const tips = Array.from(container.querySelectorAll("th .col-tip")).map((x) => x.textContent);
    expect(tips).toEqual(["%DIFF", "Odds Ratio", "LR 下限", "LR 上限", "Bonferroni", "DP"]);
  });
});

describe("stats page forms", () => {
  it("命中分解 posts query and by; 译法 is off for a non-parallel range", async () => {
    const posts = mockFetch((m, path) => (m === "POST" ? { id: "j1", kind: "stats", state: "queued", progress: { done: 0, total: 0 }, result: null } : defaults(path)));
    renderAt("/p/p1/stats", <Stats />);
    const tab = await screen.findByRole("tab", { name: /译法/ }, WAIT);
    await waitFor(() => expect(tab.getAttribute("aria-disabled")).toBe("true"), WAIT);

    fireEvent.click(screen.getByRole("tab", { name: /命中分解/ }));
    fireEvent.change(await screen.findByPlaceholderText("翻译/v", {}, WAIT), { target: { value: "翻译/v" } });
    await pick("按", "左一词");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posts.some((p) => p.path === "/api/stats/breakdown")).toBe(true), WAIT);
    const body = posts.find((p) => p.path === "/api/stats/breakdown")!.body;
    expect(body).toMatchObject({ project_id: "p1", scope: { corpus_id: "c1" }, query: "翻译/v", by: "left1", top: 200, min_freq: 1 });
  }, SLOW);

  it("频次 sends parts; 关键词 sends direction and items", async () => {
    const posts = mockFetch((m, path) => (m === "POST" ? { id: "j1", kind: "stats", state: "queued", progress: { done: 0, total: 0 }, result: null } : defaults(path)));
    renderAt("/p/p1/stats", <Stats />);
    await screen.findByText("部分", { selector: "label" }, WAIT);
    await pick("部分", "等分 10 段");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posts.some((p) => p.path === "/api/stats/frequency")).toBe(true), WAIT);
    expect(posts.find((p) => p.path === "/api/stats/frequency")!.body).toMatchObject({ parts: "segments", dispersion: true });

    fireEvent.click(screen.getByRole("tab", { name: /关键词/ }));
    await screen.findByText("方向", { selector: "label" }, WAIT);
    await pick("方向", "双向");
    const itemsField = screen.getByText("指定词对比", { selector: "label" }).closest(".ant-form-item")!;
    fireEvent.mouseDown(itemsField.querySelector(".ant-select-selector")!);
    fireEvent.change(itemsField.querySelector("input")!, { target: { value: "翻译 文化 " } });
    // a word list ignores 最低频次 and 方向
    await waitFor(() => expect(screen.getByText("最低频次", { selector: "label" }).closest(".ant-form-item")!.querySelector("input")!.disabled).toBe(true), WAIT);
    // target and reference ranges are required; fill them from the corpora
    await pick("参照", "Tatoeba 中英");
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posts.some((p) => p.path === "/api/stats/keywords")).toBe(true), WAIT);
    expect(posts.find((p) => p.path === "/api/stats/keywords")!.body).toMatchObject({ target: { corpus_id: "c1" }, reference: { corpus_id: "c2" }, direction: "both", items: ["翻译", "文化"] });
  }, SLOW);

  it("译法 posts on a parallel range and the result offers 方法说明", async () => {
    shell.scope = { corpus_id: "c2" };
    let jobDone = false;
    const posts = mockFetch((m, path) => {
      if (m === "POST" && path === "/api/stats/translations") return { id: "j2", kind: "stats", state: "queued", progress: { done: 0, total: 0 }, result: null };
      if (path === "/api/jobs/j2") {
        jobDone = true;
        return { id: "j2", kind: "stats", state: "succeeded", progress: { done: 1, total: 1 }, result: { stat_id: "st1" } };
      }
      if (path === "/api/stats/st1") return translations;
      return defaults(path);
    });
    renderAt("/p/p1/stats", <Stats />);
    const tab = await screen.findByRole("tab", { name: /译法/ }, WAIT);
    await waitFor(() => expect(tab.getAttribute("aria-disabled")).toBe("false"), WAIT);
    fireEvent.click(tab);
    fireEvent.change(await screen.findByPlaceholderText("翻译", {}, WAIT), { target: { value: "翻译" } });
    fireEvent.click(screen.getByRole("button", { name: /计算/ }));
    await waitFor(() => expect(posts.some((p) => p.path === "/api/stats/translations")).toBe(true), WAIT);
    expect(posts.find((p) => p.path === "/api/stats/translations")!.body).toMatchObject({
      scope: { corpus_id: "c2" },
      query: "翻译",
      unit: "word",
      measure: "dice",
      min_freq: 2,
      top: 100,
      exclude_punct: true,
    });
    const card = (await screen.findByRole("button", { name: "方法说明" }, { timeout: 15_000 })).closest(".card") as HTMLElement;
    expect(jobDone).toBe(true);
    expect(within(card).getByText(/有对齐/)).toBeTruthy();
    expect(within(card).getByText(/无对齐/)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "方法说明" }));
    expect(screen.getByTestId("appendix").textContent).toContain("p1:st1");
    fireEvent.click(screen.getByRole("button", { name: "关闭附录" }));
    expect(screen.queryByTestId("appendix")).toBeNull();
  }, SLOW);
});
