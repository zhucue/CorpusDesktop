import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

const shell = {
  projectId: "p1",
  scope: { corpus_id: "c1" } as { corpus_id: string },
  setScope: () => {},
  scopeInfo: { corpus: null, subcorpus: null, name: "作文" },
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

import Search from "../src/features/search/Search";

const CORPUS = { id: "c1", project_id: "p1", name: "作文", language: "zh", parallel: false, status: "ready", index_version: "v1", stats: { documents: 2, sentences: 5, tokens: 20 }, meta: {} };

afterEach(() => vi.restoreAllMocks());

function mockApi() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, body });
    const p = url.pathname;
    if (p === "/api/corpora") return json({ items: [CORPUS], total: 1 });
    if (p === "/api/projects/p1/subcorpora" || p === "/api/projects/p1/layers" || p === "/api/label-sets") return json({ items: [], total: 0 });
    if (p === "/api/search/parse") return json({ ok: true, error: null, anchor: body?.query ?? "", conditions: [], tokens: [] });
    if (p === "/api/corpora/c1/semantic-index")
      return json({ corpus_id: "c1", status: "ready", error: null, sentences: 5, indexed: 5, searchable: true, model: "m", built_at: null, estimate_seconds: 1, max_sentences: 300000, can_build: true, job: null });
    if (p === "/api/search") {
      const hits = body?.scope?.position ? 7 : 60;
      return json({ search_id: "s1", parse: { ok: true, error: null, anchor: "语言", conditions: [], tokens: [] }, counts: { hits, sentences: hits, documents: 1, complete: true }, sort_applied: true, items: [], page: 1, page_size: 50 });
    }
    if (p === "/api/corpora/c1/metadata-fields") return json([]);
    if (p === "/api/stats/tidy_export")
      return json({ id: "j9", project_id: "p1", kind: "export", state: "queued", progress: { done: 0, total: null, message: "" }, result: null, error: null, created_at: "", finished_at: null });
    if (p === "/api/jobs/j9")
      return json({ id: "j9", project_id: "p1", kind: "export", state: "queued", progress: { done: 0, total: null, message: "" }, result: null, error: null, created_at: "", finished_at: null });
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
  });
  return calls;
}

function renderPage(entry = "/p/p1/search") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/p/:projectId/search" element={<Search />} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

describe("search page modes", () => {
  it("switches to 语义 and back to 查询式", async () => {
    mockApi();
    renderPage();
    expect(screen.getByPlaceholderText("翻译/v +文化")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "语义" }));
    expect(screen.getByPlaceholderText("我喜欢读书")).toBeTruthy();
    expect(screen.queryByPlaceholderText("翻译/v +文化")).toBeNull();
    expect(await screen.findByText("已建")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "查询式" }));
    expect(screen.getByPlaceholderText("翻译/v +文化")).toBeTruthy();
  });

  it("导出整洁数据 sends the current scope and query", async () => {
    const calls = mockApi();
    renderPage();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/corpora")).toBe(true));
    fireEvent.change(screen.getByPlaceholderText("翻译/v +文化"), { target: { value: "语言" } });
    await waitFor(() => expect((screen.getByRole("button", { name: /检索/ }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: /检索/ }));
    const btn = await screen.findByRole("button", { name: /导出整洁数据/ });
    fireEvent.click(btn);
    fireEvent.click(await screen.findByText("XLSX", { selector: ".ant-dropdown-menu-title-content" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/stats/tidy_export")).toBe(true));
    expect(calls.find((c) => c.path === "/api/stats/tidy_export")?.body).toEqual({ project_id: "p1", scope: { corpus_id: "c1" }, queries: ["语言"], format: "xlsx" });
  });

  it("a document-position part (B06): chip to clear it, the tools that would refuse it are off", async () => {
    const calls = mockApi();
    const scope = { corpus_id: "c1", filter: {}, position: { bin: 1, bins: 10 } };
    renderPage(`/p/p1/search?q=${encodeURIComponent("语言")}&scope=${encodeURIComponent(JSON.stringify(scope))}`);
    expect(await screen.findByText(/临时筛选 · 文档位置 10–20%/)).toBeTruthy();
    await waitFor(() => expect(calls.find((c) => c.path === "/api/search")?.body).toMatchObject({ scope, query: "语言" }));
    const off = "文档位置区间仅用于查看例句";
    const breakdown = (await screen.findByRole("button", { name: /分解/ })) as HTMLButtonElement;
    expect([breakdown.disabled, breakdown.title]).toEqual([true, off]);
    const tidy = screen.getByRole("button", { name: /导出整洁数据/ }) as HTMLButtonElement;
    expect([tidy.disabled, tidy.title]).toEqual([true, off]);
    expect((screen.getByRole("button", { name: /抽样编码/ }) as HTMLButtonElement).disabled).toBe(true);
    const semantic = screen.getByRole("tab", { name: "语义" }) as HTMLButtonElement;
    expect([semantic.disabled, semantic.title]).toEqual([true, off]);
    // the hit export keeps the part
    expect((screen.getByRole("button", { name: /^CSV$/ }) as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/search").at(-1)?.body).toMatchObject({ scope: { corpus_id: "c1" } }));
    expect(screen.queryByText(/文档位置 10–20%/)).toBeNull();
    await waitFor(() => expect((screen.getByRole("button", { name: /分解/ }) as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByRole("button", { name: /导出整洁数据/ }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: /抽样编码/ }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("tab", { name: "语义" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
