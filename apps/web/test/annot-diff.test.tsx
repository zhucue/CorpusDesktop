import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Layer, SentenceAnnot } from "../src/api";
import { DiffRows, diffCounts } from "../src/components/annot/DiffRows";
import { diffTokens } from "../src/features/annotate/model";
import { DiffTab } from "../src/features/annotate/Tabs";

const S: SentenceAnnot = {
  document_id: "d1",
  sentence_index: 12,
  text: "这本书被翻译成英文",
  status: "pending",
  tokens: ["这", "本", "书", "被", "翻译", "成", "英文"].map((form, i) => ({ index: i + 1, form, start_cp: 0, end_cp: 0, system: { pos: "X", head: null, deprel: null } })),
  annotations: (
    [
      ["DET", "DET", "confirmed"],
      ["NOUN", "NOUN", "suggested"],
      ["NOUN", "NOUN", "confirmed"],
      ["AUX", "ADP", "modified"],
      ["VERB", "VERB", "confirmed"],
      ["ADP", "ADP", "rejected"],
      ["PROPN", "PROPN", "confirmed"],
    ] as const
  ).map(([label, model, status], i) => ({
    id: `a${i}`,
    token_index: i + 1,
    label,
    head: null,
    model_label: model,
    model_head: null,
    source: "human:u1",
    status,
    revision: 1,
    updated_by: "u1",
    updated_at: "",
  })),
};

describe("diff view", () => {
  it("derives model and human values per token", () => {
    const toks = diffTokens(S, "pos");
    expect(toks[3]).toEqual({ form: "被", model: "ADP", human: "AUX", status: "modified" });
    expect(toks[1]).toEqual({ form: "本", model: "NOUN", human: "", status: "suggested" });
    expect(diffCounts(toks)).toEqual({ changed: 1, confirmed: 4, rejected: 1, pending: 1 });
  });

  it("renders the dependency form as relation→head", () => {
    const dep: SentenceAnnot = {
      ...S,
      tokens: S.tokens.slice(0, 2),
      annotations: [
        { ...S.annotations[0], label: "det", model_label: "nmod", head: 2, model_head: 2, status: "modified" },
        { ...S.annotations[1], label: "root", model_label: "root", head: 0, model_head: 0, status: "confirmed" },
      ],
    };
    expect(diffTokens(dep, "dep")).toEqual([
      { form: "这", model: "nmod→本", human: "det→本", status: "modified" },
      { form: "本", model: "root→root", human: "root→root", status: "confirmed" },
    ]);
  });

  it("renders two lines with changed and rejected tokens highlighted", () => {
    render(<DiffRows tokens={diffTokens(S, "pos")} modelSource="jieba 0.42" humanSource="人工" />);
    const human = document.querySelector('[data-row="human"]')!;
    const model = document.querySelector('[data-row="model"]')!;
    expect(human.querySelectorAll(".dtok.chg")).toHaveLength(1);
    expect(human.querySelector(".dtok.chg")!.textContent).toBe("被AUX");
    expect(model.querySelector(".dtok.rej")!.textContent).toBe("成ADP");
    expect(human.querySelector(".dtok.pend")!.textContent).toBe("本待办");
    expect(screen.getByText("jieba 0.42")).toBeTruthy();
  });

  it("loads GET /layers/{id}/diff with only_changed, shows the counts bar and filters blocks", async () => {
    const urls: string[] = [];
    const other: SentenceAnnot = { ...S, sentence_index: 13, annotations: S.annotations.map((a) => ({ ...a, status: "confirmed", label: a.model_label })) };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ items: [S, other], counts: { changed: 1, confirmed: 10, rejected: 1, pending: 1 } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    const layer = { id: "L1", kind: "pos", source_model: "jieba 0.42" } as Layer;
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <DiffTab layer={layer} docId="d1" onOpen={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(document.querySelectorAll(".diff-blk")).toHaveLength(2));
    expect(urls[0]).toBe("/api/layers/L1/diff?document_id=d1&only_changed=true");
    const bar = document.querySelector(".diff-sum")!;
    expect(bar.querySelector('[data-kind="changed"] b')!.textContent).toBe("1");
    expect(bar.querySelector('[data-kind="confirmed"] b')!.textContent).toBe("10");
    fireEvent.click(bar.querySelector('[data-kind="changed"]')!);
    expect(document.querySelectorAll(".diff-blk")).toHaveLength(1);
    expect(screen.getByText("1 处改动")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "只看改动" }));
    await waitFor(() => expect(urls).toContain("/api/layers/L1/diff?document_id=d1&only_changed=false"));
  });
});
