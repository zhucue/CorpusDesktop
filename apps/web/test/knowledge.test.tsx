import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { KbDocument, KbSearchResult, Term } from "../src/api";
import { ResultContext } from "../src/components/results/cards";
import { locatorText } from "../src/features/knowledge/data";
import { snippetParts } from "../src/features/knowledge/highlight";
import { KbHits } from "../src/features/knowledge/KbSearch";
import { NoteEditor } from "../src/features/knowledge/Notes";
import { TermDrawer } from "../src/features/knowledge/Terms";
import { blockMarkdown, uiBlocks } from "../src/features/knowledge/uiMarkdown";
import UiBlock from "../src/openui/UiBlock";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter>
          <ResultContext.Provider value={{ projectId: "p1", scope: null }}>{node}</ResultContext.Provider>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });

function mockFetch(handle: (c: Call) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const c = { method: init?.method ?? "GET", path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(c);
    return json(handle(c));
  });
  return calls;
}

afterEach(() => vi.useRealTimers());

describe("knowledge base search results", () => {
  const RESULT: KbSearchResult = {
    items: [
      {
        chunk: { id: "c1", document_id: "d1", ordinal: 4, text: "归化以目标语读者为中心；异化保留原文差异。", locator: { page: 3 } },
        document: { id: "d1", title: "文化负载词研究综述.pdf", kind: "literature", source: "a.pdf" },
        score: 0.031,
        highlight: "<mark>归化</mark>以目标语读者为中心；<mark>异化</mark>保留原文差异。",
      },
      {
        chunk: { id: "c2", document_id: "d2", ordinal: 0, text: "Domestication brings the author to the reader.", locator: { heading_path: ["2 核心概念", "2.1 定义"] } },
        document: { id: "d2", title: "Venuti 笔记.md", kind: "note", source: "" },
        score: 0.016,
        highlight: null,
      },
    ],
    terms: [
      {
        id: "t1",
        project_id: "p1",
        term: "归化",
        language: "zh",
        translations: [{ language: "en", text: "domestication" }],
        definition: "",
        domain: "翻译学",
        examples: [],
        source: "manual",
        status: "confirmed",
        created_by: "u1",
        confirmed_by: "u1",
        created_at: "",
        updated_at: "",
      },
    ],
    warning: "EMBED_UNAVAILABLE",
  };

  it("renders numbered hits with server highlights, locators, the terms row and the warning", () => {
    wrap(<KbHits projectId="p1" q="domestication 归化" result={RESULT} />);
    const hits = screen.getAllByTestId("kb-hit");
    expect(hits).toHaveLength(2);
    expect([...hits[0].querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["归化", "异化"]);
    expect(hits[0].textContent).toContain("第 3 页");
    expect(hits[0].textContent).toContain("文化负载词研究综述.pdf");
    // No server highlight: query words are marked client-side (case-insensitive).
    expect([...hits[1].querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["Domestication"]);
    expect(hits[1].textContent).toContain("2 核心概念 › 2.1 定义");
    expect(screen.getByRole("button", { name: /归化 \/ domestication/ })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("向量模型未就绪");
    expect(screen.getAllByRole("button", { name: /打开文档位置/ })).toHaveLength(2);
  });

  it("parses <b> highlights and formats locators", () => {
    expect(snippetParts("x", "a <b>b</b> c", [])).toEqual([
      { t: "a ", m: false },
      { t: "b", m: true },
      { t: " c", m: false },
    ]);
    expect(locatorText({ line: 12 })).toBe("第 12 行");
    expect(locatorText("第 7 页 · 3.2")).toBe("第 7 页 · 3.2");
  });
});

describe("term confirm flow", () => {
  const DRAFT: Term = {
    id: "t9",
    project_id: "p1",
    term: "显化",
    language: "zh",
    translations: [{ language: "en", text: "explicitation" }],
    definition: "译文比原文更明确。",
    domain: "翻译学",
    examples: [{ text: "他把隐含的意思说了出来。", source: "zh#1" }],
    source: "corpus",
    status: "draft",
    created_by: "u1",
    confirmed_by: null,
    created_at: "",
    updated_at: "",
  };

  function Host() {
    const [t, setT] = useState<Term | null>(DRAFT);
    return <TermDrawer term={t} editable onClose={() => setT(null)} onChange={setT} />;
  }

  it("confirms a draft with PATCH {status: confirmed} and can withdraw it", async () => {
    const calls = mockFetch((c) => ({ ...DRAFT, ...(c.body as object), confirmed_by: (c.body as Term).status === "confirmed" ? "u1" : null }));
    wrap(<Host />);
    expect(await screen.findByText("草稿")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /确认/ }));
    await waitFor(() => expect(screen.getByText("已确认")).toBeTruthy());
    expect(calls).toEqual([{ method: "PATCH", path: "/api/kb/terms/t9", body: { status: "confirmed" } }]);

    fireEvent.click(screen.getByRole("button", { name: /撤回确认/ }));
    await waitFor(() => expect(screen.getByText("草稿")).toBeTruthy());
    expect(calls[1]).toEqual({ method: "PATCH", path: "/api/kb/terms/t9", body: { status: "draft" } });
  });
});

describe("note autosave", () => {
  const NOTE: KbDocument = {
    id: "n1",
    project_id: "p1",
    kind: "note",
    title: "把字句英译",
    source: "",
    meta: {},
    status: "ready",
    error: null,
    chunk_count: 0,
    created_by: "u1",
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
    body: "初稿",
    refs: [{ kind: "search", ref: { search_query: "把/p" } }],
  };

  it("saves 1 s after the last edit, once, with the latest text", async () => {
    vi.useFakeTimers();
    const calls = mockFetch((c) => ({ ...NOTE, ...(c.body as object), updated_at: "2026-10-27T01:00:00Z" }));
    wrap(<NoteEditor note={NOTE} editable />);
    const box = screen.getByLabelText("笔记正文");
    fireEvent.change(box, { target: { value: "初稿 a" } });
    await act(async () => void vi.advanceTimersByTime(600));
    fireEvent.change(box, { target: { value: "初稿 ab" } });
    expect(screen.getByTestId("save-state").textContent).toBe("未保存");
    await act(async () => void vi.advanceTimersByTime(999));
    expect(calls).toHaveLength(0);
    await act(async () => void vi.advanceTimersByTime(1));
    expect(calls).toEqual([{ method: "PATCH", path: "/api/kb/documents/n1", body: { title: "把字句英译", body: "初稿 ab" } }]);
    await act(async () => void (await Promise.resolve()));
    expect(screen.getByTestId("save-state").textContent).toBe("已保存");
    // Refs panel links the stored search back to the search page.
    const ref = document.querySelector<HTMLAnchorElement>(".ref-row a")!;
    expect(ref.textContent).toBe("把/p");
    expect(ref.getAttribute("href")).toBe(`/p/p1/search?q=${encodeURIComponent("把/p")}`);
  });

  it("保存 saves at once without waiting", async () => {
    vi.useFakeTimers();
    const calls = mockFetch((c) => ({ ...NOTE, ...(c.body as object) }));
    wrap(<NoteEditor note={NOTE} editable />);
    fireEvent.change(screen.getByLabelText("笔记正文"), { target: { value: "立即保存" } });
    await act(async () => void fireEvent.click(screen.getByRole("button", { name: "保存" })));
    expect(calls).toHaveLength(1);
    expect((calls[0].body as { body: string }).body).toBe("立即保存");
    await act(async () => void vi.advanceTimersByTime(2000));
    expect(calls).toHaveLength(1);
  });
});

describe("P4 OpenUI components", () => {
  const TERM = [
    'root = TermCard("t1", "文化负载词", tr, "标志某种文化中特有事物的词。", "翻译学", ex, "confirmed")',
    'tr = [{language: "en", text: "culture-loaded words"}, {language: "en", text: "culturemes"}]',
    'ex = [{text: "很多文化负载词很难翻译。", source: "zh#5730218"}]',
  ].join("\n");

  it("renders TermCard from OpenUI Lang with translations, examples and 打开术语", async () => {
    wrap(<UiBlock lang={TERM} />);
    expect(await screen.findByText("文化负载词")).toBeTruthy();
    expect(screen.getByText("culture-loaded words")).toBeTruthy();
    expect(screen.getByText("culturemes")).toBeTruthy();
    expect(screen.getByText("已确认")).toBeTruthy();
    expect(screen.getByText(/很多文化负载词很难翻译/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /打开术语/ });
    expect(link.getAttribute("href")).toBe(`/p/p1/knowledge?tab=terms&term=t1&tq=${encodeURIComponent("文化负载词")}`);
  });

  it("renders KbCitation from OpenUI Lang with locator text and 打开文档位置", async () => {
    wrap(
      <UiBlock
        lang={'root = KbCitation([{chunk_id: "c7", document_id: "d3", title: "文化负载词研究综述.pdf", locator: "第 7 页", text: "以异化为主、归化为辅"}, {chunk_id: "c8", document_id: "d4", title: "讲义.docx", locator: "3 策略 › 3.2", text: "零翻译"}])'}
      />,
    );
    expect(await screen.findByText("知识库出处")).toBeTruthy();
    expect(screen.getByText("2 条")).toBeTruthy();
    expect(screen.getByText(/第 7 页/)).toBeTruthy();
    const links = screen.getAllByRole("link", { name: /打开文档位置/ });
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/p/p1/knowledge?doc=d3&chunk=c7", "/p/p1/knowledge?doc=d4&chunk=c8"]);
  });

  it("turns ui parts into Markdown for notes", () => {
    const [b] = uiBlocks(TERM);
    expect(b.component).toBe("TermCard");
    expect(blockMarkdown(b, "p1")).toContain("**文化负载词**（culture-loaded words、culturemes）");
    const kwic = blockMarkdown(
      { component: "KwicTable", props: { query: "翻译/v", scope_name: "UD", rows: [{ hit_id: "h", left: "已经被", match: "翻译", right: "成", source: "zh#1" }] } },
      "p1",
    );
    expect(kwic).toContain("| 已经被 | 翻译 | 成 | zh#1 |");
    expect(kwic).toContain("[打开完整结果](/p/p1/search?q=");
  });
});
