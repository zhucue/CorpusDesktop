import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Layer } from "../src/api";
import SpanWorkspace from "../src/features/annotate/SpanWorkspace";
import { sampleKeyCommand, sampleState } from "../src/features/annotate/spanModel";
import { isAlignedError, labelsFromText, parseAlignedParam } from "../src/features/search/SearchTools";

vi.mock("../src/components/global/MethodAppendix", () => ({
  MethodAppendix: (p: { layerIds?: string[] }) => <div data-testid="appendix">{p.layerIds?.join(",")}</div>,
}));

afterEach(() => vi.restoreAllMocks());

describe("translation condition helpers", () => {
  it("reads ?aligned= and ignores malformed values", () => {
    expect(parseAlignedParam(JSON.stringify({ op: "+", query: '"translate"' }))).toEqual({ op: "+", query: '"translate"' });
    expect(parseAlignedParam(JSON.stringify({ op: "-", query: "x" }))?.op).toBe("-");
    expect(parseAlignedParam("{bad")).toBeNull();
    expect(parseAlignedParam(JSON.stringify({ op: "?", query: "x" }))).toBeNull();
    expect(parseAlignedParam(JSON.stringify({ op: "+", query: " " }))).toBeNull();
    expect(isAlignedError(new Error("查询式无效：译文条件第 1 个字符：引号未闭合"))).toBe(true);
    expect(isAlignedError(new Error("查询式无效：第 1 个字符"))).toBe(false);
  });

  it("makes label ids from names", () => {
    expect(labelsFromText("字面\n比 喻, 字面")).toEqual([
      { id: "字面", name: "字面" },
      { id: "比_喻", name: "比 喻" },
      { id: "字面_2", name: "字面" },
    ]);
  });
});

describe("sample coding keys", () => {
  const labels = [
    { id: "lit", name: "字面" },
    { id: "fig", name: "比喻" },
  ];
  it("digits pick labels, Enter confirms, X rejects, J/K move", () => {
    expect(sampleKeyCommand({ key: "2" }, labels)).toEqual({ type: "label", label: "fig" });
    expect(sampleKeyCommand({ key: "Enter" }, labels)).toEqual({ type: "confirm" });
    expect(sampleKeyCommand({ key: "x" }, labels)).toEqual({ type: "reject" });
    expect(sampleKeyCommand({ key: "j" }, labels)).toEqual({ type: "move", delta: 1 });
    expect(sampleKeyCommand({ key: "Enter", shiftKey: true }, labels)).toBeNull();
    expect(sampleState({ label: "", status: "suggested" })).toBe("todo");
    expect(sampleState({ label: "lit", status: "modified" })).toBe("coded");
    expect(sampleState({ label: "", status: "rejected" })).toBe("rejected");
  });
});

const LAYER = {
  id: "S1",
  project_id: "p1",
  corpus_id: "c1",
  corpus_name: "c",
  kind: "span",
  name: "抽样",
  label_set_id: "ls1",
  source_model: "human",
  status: "ready",
  job_id: null,
  progress: { total: 2, suggested: 2, confirmed: 0, modified: 0, rejected: 0 },
  documents: { total: 1, done: 0 },
  error: null,
  created_by: "u1",
  created_at: "",
  updated_at: "",
  mode: "single",
  meta: { sample: { query: "language", scope: { corpus_id: "c1" }, aligned: null, n: 2, seed: 7, total_hits: 30, created_at: "" } },
} as unknown as Layer;

const span = (id: number, start: number) => ({
  id,
  document_id: "d1",
  sentence_index: 0,
  start_cp: start,
  end_cp: start + 8,
  text: "language",
  label: "",
  attrs: {},
  source: "sample:7",
  status: "suggested",
  model_label: "",
  revision: 1,
  annotator_id: "u1",
  updated_at: "",
});

describe("sample mode", () => {
  it("lists hits in sampling order, codes with a digit and shows the Wilson summary", async () => {
    const calls: { method: string; path: string; body: unknown }[] = [];
    const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, path: url.pathname, body });
      const p = url.pathname;
      if (p === "/api/label-sets")
        return json({ items: [{ id: "ls1", project_id: "p1", name: "用法", kind: "span", language: null, labels: [{ id: "lit", name: "字面" }, { id: "fig", name: "比喻" }], created_at: "" }] });
      if (p === "/api/layers/S1/sample-items")
        return json({
          items: [
            { n: 1, span: span(11, 8), document_title: "a", sentence: { start_cp: 0, end_cp: 21, text: "Line on language now." } },
            { n: 2, span: span(12, 30), document_title: "a", sentence: { start_cp: 22, end_cp: 45, text: "Another language line." } },
          ],
        });
      if (p === "/api/layers/S1/sample-summary")
        return json({
          total_hits: 30,
          sampled: 2,
          coded: 1,
          rejected: 0,
          seed: 7,
          labels: [
            { label: "lit", name: "字面", count: 1, pct: 1, ci_low: 0.2066, ci_high: 1, estimate: 30 },
            { label: "fig", name: "比喻", count: 0, pct: 0, ci_low: 0, ci_high: 0.7935, estimate: 0 },
          ],
        });
      if (p === "/api/layers/S1/spans/11" && method === "PATCH") return json({ ...span(11, 8), label: "fig", status: "modified" });
      return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <App>
          <MemoryRouter initialEntries={["/p/p1/annotate?layer=S1"]}>
            <SpanWorkspace layer={LAYER} layers={[LAYER]} projectId="p1" canAnnotate canManage />
          </MemoryRouter>
        </App>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(document.querySelector("mark")?.textContent).toBe("language"));
    expect(screen.getByText(/第 1 条/)).toBeTruthy();
    expect(await screen.findByText("20.7% – 100.0%")).toBeTruthy();
    expect(screen.getByText("≈ 30")).toBeTruthy();

    // Enter on an uncoded hit asks for a label; 2 codes it as 比喻 and moves on
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(await screen.findByText(/先选择标签/)).toBeTruthy();
    fireEvent.keyDown(document.body, { key: "2" });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")).toEqual({ method: "PATCH", path: "/api/layers/S1/spans/11", body: { action: "modify", label: "fig" } });
    await waitFor(() => expect(screen.getByText(/第 2 条/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /方法说明/ }));
    expect(screen.getByTestId("appendix").textContent).toBe("S1");
  });
});
