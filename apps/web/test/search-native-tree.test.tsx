import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Hit } from "../src/api";
import SentenceTree, { hitTokens, nativeGraph, type CorpusSentence } from "../src/features/search/SentenceTree";

// "他 加入 了 公司" as GSD stores it: CoNLL-U head / deprel from import, no annotation layer
const sentence: CorpusSentence = {
  document_id: "d1",
  sentence_index: 3,
  text: "他加入了公司",
  start_cp: 100,
  end_cp: 106,
  tokens: [
    { index: 1, form: "他", start_cp: 100, end_cp: 101, pos: "PRON", lemma: "他", head: 2, deprel: "nsubj" },
    { index: 2, form: "加入", start_cp: 101, end_cp: 103, pos: "VERB", lemma: "加入", head: 0, deprel: "root" },
    { index: 3, form: "了", start_cp: 103, end_cp: 104, pos: "AUX", lemma: "了", head: 2, deprel: "aux" },
    { index: 4, form: "公司", start_cp: 104, end_cp: 106, pos: "NOUN", lemma: "公司", head: 2, deprel: "obj" },
  ],
};
const hit = { hit_id: "h1", document_id: "d1", document_title: "GSD", sentence_index: 3, left: "", match: "他", right: "加入了公司", start_cp: 100, end_cp: 101, metadata: {}, aligned: [] } as Hit;

afterEach(() => vi.restoreAllMocks());

describe("B04 native dependencies in the KWIC tree", () => {
  it("maps stored head / deprel to solid arcs and highlights the hit's tokens", () => {
    const g = nativeGraph(sentence);
    expect(g.tokens.map((t) => [t.index, t.form, t.pos])).toEqual([
      [1, "他", "PRON"],
      [2, "加入", "VERB"],
      [3, "了", "AUX"],
      [4, "公司", "NOUN"],
    ]);
    expect(g.arcs).toEqual([
      { dep: 1, head: 2, label: "nsubj" },
      { dep: 2, head: 0, label: "root" },
      { dep: 3, head: 2, label: "aux" },
      { dep: 4, head: 2, label: "obj" },
    ]);
    expect(g.arcs.some((a) => "suggested" in a)).toBe(false);
    expect(hitTokens(sentence.tokens, hit)).toEqual([1]);
    expect(hitTokens(sentence.tokens, { start_cp: 101, end_cp: 106 })).toEqual([2, 3, 4]);
  });

  it("reads the sentence from the corpus without a layer and draws the relation labels", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      calls.push(new URL(String(input), "http://x").pathname);
      return new Response(JSON.stringify(sentence), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <SentenceTree layerId={null} corpusId="c1" hit={hit} projectId="p1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("nsubj")).toBeTruthy();
    expect(screen.getByText("obj")).toBeTruthy();
    expect(calls).toEqual(["/api/corpora/c1/documents/d1/sentences/3"]);
    expect(container.textContent).not.toContain("在标注中打开");
  });
});
