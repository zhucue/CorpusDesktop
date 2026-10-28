import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KbHits } from "../src/features/knowledge/KbSearch";
import type { KbSearchResult } from "../src/api";
import { evidenceMarkdown, writeEvidenceToNote } from "../src/features/knowledge/NotePicker";
import { extractSummary } from "../src/features/knowledge/Terms";
import { searchLanding } from "../src/features/onboarding/Onboarding";
import { isGone } from "../src/features/settings/ProjectGate";
import { ApiError } from "../src/api";

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

afterEach(() => vi.restoreAllMocks());

const items = [0, 1, 2].map((i) => ({ id: `e${i}`, text: `第 ${i} 句`, source: "QA 平行", ref: { search_query: "翻译" } }));

describe("evidence basket → note (Q58)", () => {
  it("creates an empty note and posts one evidence ref per item; the body is left to the API", async () => {
    const calls = mockFetch((c) => (c.path.endsWith("/kb/documents") ? { id: "n1", title: "证据摘录", kind: "note" } : {}));
    const note = await writeEvidenceToNote("p1", { newTitle: "证据摘录" }, items);
    expect(note.id).toBe("n1");
    const create = calls.find((c) => c.path === "/api/projects/p1/kb/documents")!;
    expect(create.body).toMatchObject({ kind: "note", title: "证据摘录", body: "" });
    const refs = calls.filter((c) => c.path === "/api/kb/documents/n1/refs");
    expect(refs.map((r) => (r.body as { ref: { evidence_id: string } }).ref.evidence_id)).toEqual(["e0", "e1", "e2"]);
    expect(refs.every((r) => (r.body as { append: boolean }).append)).toBe(true);
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("formats a quote exactly like the API block", () => {
    expect(evidenceMarkdown({ text: "甲\n\n乙", source: "QA 平行", ref: { search_query: "翻译" } })).toBe("> 甲\n>\n> 乙\n>\n> —— QA 平行；查询式：`翻译`");
    expect(evidenceMarkdown({ text: "甲", source: "", ref: {} })).toBe("> 甲");
  });
});

describe("small fixes", () => {
  it("says why extracted terms were skipped (Q63)", () => {
    expect(extractSummary({ created: 0, skipped: 1, candidates: 1, skipped_existing: ["文化差异"], pool: 1 })).toBe(
      "抽取完成：新增 0 条草稿；跳过 1 条（术语表中已有：文化差异）",
    );
    expect(extractSummary({ created: 0, skipped: 0, candidates: 0, skipped_existing: [], pool: 0, min_freq: 2 })).toContain("没有出现 2 次及以上");
  });

  it("lands on search with the onboarding corpus and last query (Q16)", () => {
    const href = searchLanding("p1", "c1", "翻译");
    const u = new URL(href, "http://x");
    expect(u.pathname).toBe("/p/p1/search");
    expect(u.searchParams.get("q")).toBe("翻译");
    expect(JSON.parse(u.searchParams.get("scope")!)).toEqual({ corpus_id: "c1" });
    expect(searchLanding("p1", null, null)).toBe("/p/p1/search");
  });

  it("treats a 404 project as no longer a member (Q72)", () => {
    expect(isGone(new ApiError(404, "NOT_FOUND", "项目不存在"))).toBe(true);
    expect(isGone(new ApiError(403, "FORBIDDEN", "x"))).toBe(false);
  });
});


describe("KB search relevance (Q64)", () => {
  const hit = (id: string, relevance: "high" | "medium" | "low") => ({
    chunk: { id, document_id: "d1", ordinal: 0, text: `片段 ${id}`, locator: null },
    document: { id: "d1", title: "文献", kind: "literature" as const, source: "a.pdf" },
    score: 0.03,
    relevance,
  });
  it("shows 相关度 高/中/低 instead of scores and folds low hits", () => {
    const result = { items: [hit("1", "high"), hit("2", "medium"), hit("3", "low")], terms: [] } as unknown as KbSearchResult;
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App>
          <MemoryRouter>
            <KbHits projectId="p1" q="显化" result={result} />
          </MemoryRouter>
        </App>
      </QueryClientProvider>,
    );
    expect(screen.getAllByTestId("kb-hit")).toHaveLength(2);
    expect(screen.queryByText("0.030")).toBeNull();
    expect(screen.getByText("高")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /另有 1 条低相关结果/ }));
    expect(screen.getAllByTestId("kb-hit")).toHaveLength(3);
  });
});
