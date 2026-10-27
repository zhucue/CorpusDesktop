import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Alignment, Layer, SentenceSpans, Span } from "../src/api";
import { ResultContext } from "../src/components/results/cards";
import { alignmentGraphHref } from "../src/components/results/annot2Cards";
import { canWriteLayer } from "../src/features/annotate/data";
import { failedRetryBody } from "../src/features/annotate/model";
import { effectiveAlignPatch, effectiveSpanPatch, spanDiffBlocks } from "../src/features/annotate/spanModel";
import SpanWorkspace from "../src/features/annotate/SpanWorkspace";
import { labelSearchHref } from "../src/features/annotate/Tabs";
import { fmtVersion } from "../src/lib/format";
import UiBlock from "../src/openui/UiBlock";

function wrap(node: React.ReactNode, entry = "/p/p1/assistant") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[entry]}>
          <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>{node}</ResultContext.Provider>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

const span = (o: Partial<Span>): Span => ({
  id: "s1",
  start_cp: 0,
  end_cp: 2,
  text: "go",
  label: "时态",
  attrs: {},
  source: "model:m",
  status: "suggested",
  model_label: "时态",
  revision: 0,
  annotator_id: null,
  updated_at: "",
  ...o,
});

describe("index version", () => {
  it("keeps numeric versions and shortens hashes", () => {
    expect(fmtVersion(14)).toBe("v14");
    expect(fmtVersion("7")).toBe("v7");
    expect(fmtVersion("b1a59108360923ce")).toBe("b1a59108");
    expect(fmtVersion(null)).toBe("—");
  });
});

describe("unchanged modify", () => {
  it("confirms a suggested span whose label, bounds and attributes do not change; skips a reviewed one", () => {
    const s = span({ attrs: { k: "v" } });
    expect(effectiveSpanPatch(s, { action: "modify", label: "时态", start_cp: 0, end_cp: 2, attrs: { k: "v" } })).toEqual({ action: "confirm" });
    expect(effectiveSpanPatch({ ...s, status: "confirmed" }, { action: "modify", label: "时态" })).toBeNull();
    expect(effectiveSpanPatch(s, { action: "modify", end_cp: 3 })).toEqual({ action: "modify", end_cp: 3 });
    expect(effectiveSpanPatch(s, { action: "modify", attrs: { k: "w" } })).toEqual({ action: "modify", attrs: { k: "w" } });
    // modifying a rejected span restores it
    expect(effectiveSpanPatch({ ...s, status: "rejected" }, { action: "modify", label: "时态" })).toEqual({ action: "modify", label: "时态" });
  });

  it("does the same for alignments (token order does not matter)", () => {
    const a: Alignment = { id: "a1", level: "word", src_tokens: [2, 1], tgt_tokens: [3], score: null, source: "model:m", status: "suggested", revision: 0, annotator_id: null };
    expect(effectiveAlignPatch(a, { action: "modify", src_tokens: [1, 2], tgt_tokens: [3] }, 0)).toEqual({ action: "confirm" });
    expect(effectiveAlignPatch(a, { action: "modify", tgt_sentence_index: 0 }, 0)).toEqual({ action: "confirm" });
    expect(effectiveAlignPatch(a, { action: "modify", tgt_sentence_index: 1 }, 0)).toEqual({ action: "modify", tgt_sentence_index: 1 });
    expect(effectiveAlignPatch({ ...a, status: "modified" }, { action: "modify", tgt_tokens: [3] }, 0)).toBeNull();
  });
});

describe("span diff", () => {
  it("lists a span that crosses sentences once, in its first sentence", () => {
    const cross = span({ id: "x", start_cp: 8, end_cp: 14, text: "ab. cd" });
    const s1: SentenceSpans = { document_id: "d", sentence_index: 0, text: "", start_cp: 0, end_cp: 10, spans: [span({ id: "a" }), cross], relations: [] };
    const s2: SentenceSpans = { document_id: "d", sentence_index: 1, text: "", start_cp: 10, end_cp: 20, spans: [cross], relations: [] };
    const blocks = spanDiffBlocks([s1, s2], () => true);
    expect(blocks.map((b) => [b.s.sentence_index, b.toks.map((t) => t.form)])).toEqual([[0, ["go", "ab. cd"]]]);
  });
});

describe("layer write access", () => {
  const base = { mode: "single" as const, annotators: ["u1"], created_by: "u1" };
  it("lets only the creator or listed annotators write a single-mode layer", () => {
    expect(canWriteLayer(base, "u1", "editor")).toBe(true);
    expect(canWriteLayer(base, "u2", "owner")).toBe(false);
    expect(canWriteLayer({ ...base, annotators: ["u1", "u2"] }, "u2", "annotator")).toBe(true);
    expect(canWriteLayer(base, "u1", "viewer")).toBe(false);
  });
  it("lets only listed annotators write a multi-mode layer", () => {
    const multi = { mode: "multi" as const, annotators: ["u2", "u3"], created_by: "u1" };
    expect(canWriteLayer(multi, "u1", "owner")).toBe(false);
    expect(canWriteLayer(multi, "u3", "annotator")).toBe(true);
  });
});

describe("failed pre-annotation retry", () => {
  it("redoes the failed sentences' documents over one range", () => {
    expect(
      failedRetryBody([
        { document_id: "d1", sentence_index: 4 },
        { document_id: "d2", sentence_index: 1 },
        { document_id: "d1", sentence_index: 7 },
      ]),
    ).toEqual({ document_ids: ["d1", "d2"], sentence_range: { start: 1, end: 8 } });
    expect(failedRetryBody([])).toBeNull();
    expect(failedRetryBody(["bad"])).toBeNull();
  });
});

describe("links that carry the layer", () => {
  it("label stats rows search the same layer", () => {
    const href = labelSearchHref("p1", { id: "L5", kind: "span", corpus_id: "c1" }, "时态")!;
    const q = new URLSearchParams(href.split("?")[1]);
    expect(q.get("q")).toBe("[时态]");
    expect(JSON.parse(q.get("layers")!)).toEqual({ span: "L5" });
    expect(labelSearchHref("p1", { id: "R", kind: "relation", corpus_id: "c1" }, "cause")).toBeNull();
    expect(labelSearchHref("p1", { id: "P", kind: "pos", corpus_id: "c1" }, "NOUN")).toContain(encodeURIComponent("{pos=NOUN}"));
  });

  it("AlignmentGraph opens the exact layer and source sentence when the ids are given", async () => {
    expect(alignmentGraphHref("p1", {})).toBe("/p/p1/annotate?kind=alignment");
    const lang = [
      'root = AlignmentGraph(src, tgt, links, "LA", "doc9", 12)',
      'src = ["她", "翻译"]',
      'tgt = ["She", "translated"]',
      'links = [{src: [1], tgt: [1], status: "confirmed"}]',
    ].join("\n");
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("词对齐")).toBeTruthy();
    expect(screen.getByRole("link", { name: /在标注中打开/ }).getAttribute("href")).toBe("/p/p1/annotate?layer=LA&doc=doc9&s=12");
  });
});

/* ---------- span workspace with a relation layer built on it ---------- */

const SENT: SentenceSpans = {
  document_id: "d1",
  sentence_index: 0,
  text: "Yesterday I go to the library.",
  start_cp: 40,
  end_cp: 70,
  spans: [span({ id: "sp1", start_cp: 52, end_cp: 54, text: "go" }), span({ id: "sp2", start_cp: 62, end_cp: 69, text: "library", label: "冠词", model_label: "冠词" })],
  relations: [],
};

const LAYER: Layer = {
  id: "L5",
  project_id: "p1",
  corpus_id: "c1",
  corpus_name: "学习者作文",
  kind: "span",
  name: "偏误",
  label_set_id: "ls-le",
  source_model: "qwen",
  status: "ready",
  job_id: null,
  progress: { total: 2, suggested: 2, confirmed: 0, modified: 0, rejected: 0 },
  documents: { total: 1, done: 0 },
  error: null,
  created_by: "u1",
  created_at: "",
  updated_at: "",
  mode: "single",
};
const REL: Layer = { ...LAYER, id: "R1", kind: "relation", name: "纠正", label_set_id: "ls-ec", base_layer_id: "L5" };

describe("span workspace relations", () => {
  it("creates a relation on the relation layer built on the span layer", async () => {
    const calls: { method: string; path: string; body: unknown }[] = [];
    const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, path: url.pathname, body });
      const p = url.pathname;
      if (p === "/api/auth/me") return json({ id: "u1", email: "a@b", display_name: "A", is_admin: false });
      if (p === "/api/label-sets")
        return json({
          items: [
            { id: "ls-le", project_id: null, name: "learner-errors", kind: "span", language: null, labels: [{ id: "1", name: "时态" }, { id: "2", name: "冠词" }], created_at: "" },
            { id: "ls-ec", project_id: null, name: "error-correction", kind: "relation", language: null, labels: [{ id: "c", name: "cause" }], created_at: "" },
          ],
        });
      if (p === "/api/layers/L5/documents") return json({ items: [{ document_id: "d1", title: "作文 1", sentences: 1, done: 0, pending: 1 }] });
      if (p === "/api/layers/L5/spans" && method === "GET") return json({ items: [SENT], next_cursor: null });
      if (p === "/api/layers/R1/spans" && method === "GET") return json({ items: [SENT], next_cursor: null });
      if (p === "/api/layers/R1/relations" && method === "POST")
        return json({ id: 9, from_span_id: body.from_span_id, to_span_id: body.to_span_id, label: body.label, source: "human", status: "confirmed", revision: 1, annotator_id: "u1" });
      return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
    });
    wrap(<SpanWorkspace layer={LAYER} layers={[LAYER, REL]} projectId="p1" canAnnotate canManage />, "/p/p1/annotate?layer=L5");
    await waitFor(() => expect([...document.querySelectorAll(".stag")].length).toBe(2));
    expect(screen.getByRole("combobox", { name: "关系层" })).toBeTruthy();

    fireEvent.click(document.querySelector("[data-tag='sp1']")!);
    fireEvent.keyDown(document.body, { key: "r" });
    fireEvent.click(document.querySelector("[data-tag='sp2']")!);
    await waitFor(() => expect(screen.getByText("选择关系标签")).toBeTruthy());
    fireEvent.keyDown(document.body, { key: "1" });
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")).toEqual({ method: "POST", path: "/api/layers/R1/relations", body: { from_span_id: "sp1", to_span_id: "sp2", label: "cause" } });
    await waitFor(() => expect(document.querySelector(".rel-svg text")?.textContent).toBe("cause"));
  });
});
