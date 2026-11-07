import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Corpus } from "../src/api";
import { estimateText, type SemanticIndex } from "../src/features/search/semantic";
import { SemanticIndexPanel } from "../src/features/search/SemanticIndexPanel";
import SemanticSearch from "../src/features/search/SemanticSearch";

afterEach(() => vi.restoreAllMocks());

const INDEX: SemanticIndex = {
  corpus_id: "c1",
  status: "none",
  error: null,
  sentences: 12000,
  languages: { zh: 12000 },
  language: null,
  rate: 120,
  indexed: null,
  searchable: false,
  model: null,
  built_at: null,
  estimate_seconds: 100,
  max_sentences: 300000,
  can_build: true,
  job: null,
};

const CORPUS = { id: "c1", project_id: "p1", name: "作文", language: "zh", parallel: false, status: "ready", stats: { documents: 2, sentences: 5, tokens: 20 } } as unknown as Corpus;

function mockApi(index: SemanticIndex) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, body });
    const p = url.pathname;
    if (p === "/api/corpora/c1/semantic-index" && method === "GET") return json(index);
    if (p === "/api/corpora/c1/semantic-index" && method === "POST")
      return json({ id: "j1", project_id: "p1", kind: "embed_corpus", state: "queued", progress: { done: 0, total: null, message: "" }, result: null, error: null, created_at: "", finished_at: null });
    if (p === "/api/search/semantic")
      return json({
        status: "ready",
        indexed: 5,
        model: "m",
        items: [
          { hit_id: "d1:0-6", document_id: "d1", document_title: "a", sentence_index: 0, left: "", match: "我喜欢读书。", right: "", start_cp: 0, end_cp: 6, metadata: {}, aligned: [], score: 0.912 },
          { hit_id: "d2:0-8", document_id: "d2", document_title: "b", sentence_index: 0, left: "", match: "我爱看书和读报。", right: "", start_cp: 0, end_cp: 8, metadata: {}, aligned: [], score: 0.64 },
        ],
      });
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
  });
  return calls;
}

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={["/p/p1/search"]}>{node}</MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

describe("semantic index panel", () => {
  it("shows the sentence count and estimate and starts a build", async () => {
    const calls = mockApi(INDEX);
    wrap(<SemanticIndexPanel corpusId="c1" projectId="p1" />);
    expect(await screen.findByText("未建")).toBeTruthy();
    expect(screen.getByText(/12,000 句 · 预计 约 2 分钟/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /建语义索引/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/corpora/c1/semantic-index")).toBe(true));
  });

  it("hides the button without the right and disables it above the limit", async () => {
    mockApi({ ...INDEX, can_build: false });
    const view = wrap(<SemanticIndexPanel corpusId="c1" projectId="p1" />);
    expect(await screen.findByText("未建")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /建语义索引/ })).toBeNull();
    view.unmount();
    vi.restoreAllMocks();
    mockApi({ ...INDEX, sentences: 400000, status: "stale", indexed: 10, searchable: true });
    wrap(<SemanticIndexPanel corpusId="c1" projectId="p1" />);
    const btn = await screen.findByRole("button", { name: /重建语义索引/ });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/超过语义索引上限 300,000 句/)).toBeTruthy();
  });

  it("builds one language of a parallel corpus", async () => {
    const calls = mockApi({ ...INDEX, sentences: 266098, languages: { en: 220395, zh: 45703 }, rate: 250 });
    wrap(<SemanticIndexPanel corpusId="c1" projectId="p1" />);
    expect(await screen.findByText("未建")).toBeTruthy();
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    fireEvent.click(await screen.findByText("zh · 45,703 句", { selector: ".ant-select-item-option-content" }));
    expect(screen.getByText(/预计 约 3 分钟/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /建语义索引/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ language: "zh" }));
  });

  it("estimates in seconds, minutes and hours", () => {
    expect(estimateText(20)).toBe("约 20 秒");
    expect(estimateText(600)).toBe("约 10 分钟");
    expect(estimateText(5400)).toBe("约 1.5 小时");
  });
});

describe("semantic search mode", () => {
  it("sends the sentence with the scope and lists similar sentences with their similarity", async () => {
    const calls = mockApi({ ...INDEX, status: "ready", indexed: 5, searchable: true, sentences: 5 });
    wrap(<SemanticSearch projectId="p1" scope={{ corpus_id: "c1", filter: { year: [2010] } }} corpus={CORPUS} />);
    expect(await screen.findByText("已建")).toBeTruthy();
    const input = screen.getByPlaceholderText("我喜欢读书") as HTMLInputElement;
    expect(input.maxLength).toBe(500);
    fireEvent.change(input, { target: { value: " 我喜欢读书 " } });
    fireEvent.click(screen.getByRole("button", { name: /检索/ }));
    expect(await screen.findByText("我喜欢读书。")).toBeTruthy();
    expect(screen.getByText(/相似度 0\.91/)).toBeTruthy();
    expect(screen.getByText(/相似度 0\.64/)).toBeTruthy();
    const post = calls.find((c) => c.path === "/api/search/semantic");
    expect(post?.body).toEqual({ scope: { corpus_id: "c1", filter: { year: [2010] } }, text: "我喜欢读书", top: 50 });
  });

  it("clears the results and the open context when the scope changes (B03)", async () => {
    mockApi({ ...INDEX, status: "ready", indexed: 5, searchable: true, sentences: 5 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const ui = (scope: { corpus_id: string; filter?: Record<string, number[]> }) => (
      <QueryClientProvider client={client}>
        <App>
          <MemoryRouter initialEntries={["/p/p1/search"]}>
            <SemanticSearch projectId="p1" scope={scope} corpus={CORPUS} />
          </MemoryRouter>
        </App>
      </QueryClientProvider>
    );
    const view = render(ui({ corpus_id: "c1" }));
    expect(await screen.findByText("已建")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("我喜欢读书"), { target: { value: "读书" } });
    fireEvent.click(screen.getByRole("button", { name: /检索/ }));
    fireEvent.click(await screen.findByText("我喜欢读书。")); // opens the context
    expect(screen.getByText("相似句")).toBeTruthy();
    view.rerender(ui({ corpus_id: "c1", filter: { year: [2019] } }));
    expect(screen.queryByText("相似句")).toBeNull();
    expect(screen.queryByText("我喜欢读书。")).toBeNull();
    expect((screen.getByPlaceholderText("我喜欢读书") as HTMLInputElement).value).toBe("读书");
  });

  it("keeps 检索 disabled until the index is built", async () => {
    mockApi(INDEX);
    wrap(<SemanticSearch projectId="p1" scope={{ corpus_id: "c1" }} corpus={CORPUS} />);
    expect(await screen.findByText("未建")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("我喜欢读书"), { target: { value: "读书" } });
    expect((screen.getByRole("button", { name: /^检索$/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
