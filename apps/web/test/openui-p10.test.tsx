import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { ResultContext } from "../src/components/results/cards";
import UiBlock from "../src/openui/UiBlock";

// jsdom has no canvas for ECharts text measuring; the chart host is checked by its label.
vi.mock("../src/components/results/EChart", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/components/results/EChart")>()),
  EChart: ({ label }: { label?: string }) => <div role="img" aria-label={label} />,
}));

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/p/p1/assistant"]}>
        <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>
          {node}
          <Where />
        </ResultContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const where = () => new URL(screen.getByTestId("where").textContent!, "http://x");

describe("P10 OpenUI components (OpenUI Lang through the renderer)", () => {
  it("WordSketch: one column per relation; a row with search_query opens its examples", async () => {
    const lang = [
      'root = WordSketch("stat-ws", "make", relations, "VERB")',
      'relations = [{relation: "宾语", rows: [{collocate: "decision", freq: 40, logdice: 11.2, search_query: "{lemma=make} []{0,3} {lemma=decision}"}, {collocate: "mistake", freq: 12, logdice: 9.5, search_query: null}]}, {relation: "主语", rows: [{collocate: "we", freq: 9, logdice: 8.2}]}]',
    ].join("\n");
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("Word Sketch")).toBeTruthy();
    expect(screen.getByText("make · VERB")).toBeTruthy();
    expect(screen.getByText("2 栏")).toBeTruthy();
    expect(screen.getByText("宾语")).toBeTruthy();
    expect(screen.getByText("主语")).toBeTruthy();
    const row = screen.getByText("decision").closest("tr")!;
    expect(within(row).getByText("40")).toBeTruthy();
    expect(within(row).getByText("11.2")).toBeTruthy();
    // a row without search_query is not a link
    expect(screen.getByText("mistake").closest("tr")!.getAttribute("role")).toBeNull();
    fireEvent.click(row);
    const url = where();
    expect(url.pathname).toBe("/p/p1/search");
    expect(url.searchParams.get("q")).toBe("{lemma=make} []{0,3} {lemma=decision}");
    expect(JSON.parse(url.searchParams.get("scope")!)).toEqual({ corpus_id: "c1" });
    expect(url.searchParams.get("layers")).toBeNull();
    expect(screen.getByRole("link", { name: /在统计中打开/ }).getAttribute("href")).toBe("/p/p1/stats?stat=stat-ws");
  });

  it("SketchDiff: three columns 偏 A / 共同 / 偏 B with both counts and the difference", async () => {
    const lang = [
      'root = SketchDiff("stat-sd", "big", "large", a, common, b, {dep: "layer-dep"})',
      'a = [{relation: "修饰", collocate: "deal", freq_a: 12, freq_b: 0, diff: 9.1, search_query: "{lemma=big} {lemma=deal}"}]',
      "common = []",
      'b = [{relation: "修饰", collocate: "number", freq_a: 0, freq_b: 20, diff: -10.2}]',
    ].join("\n");
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("近义词对比")).toBeTruthy();
    const columns = [...document.querySelectorAll(".sk-col")] as HTMLElement[];
    expect(columns.map((c) => c.querySelector(".sk-col-h span")!.textContent)).toEqual(["偏 big", "共同", "偏 large"]);
    expect(within(columns[1]).getByText("无")).toBeTruthy();
    const number = within(columns[2]).getByText("number").closest("tr")!;
    expect(within(number).getByText("20")).toBeTruthy();
    expect(within(number).getByText("-10.2")).toBeTruthy();
    fireEvent.click(within(columns[0]).getByText("deal").closest("tr")!);
    expect(where().searchParams.get("q")).toBe("{lemma=big} {lemma=deal}");
    // a sketch on a dependency layer searches the same layer
    expect(JSON.parse(where().searchParams.get("layers")!)).toEqual({ dep: "layer-dep" });
  });

  it("SketchDiff shows every row of the stored result, not only the rows the model copied (B14)", async () => {
    const row = (collocate: string, group: string, fa: number, fb: number, diff: number) => ({
      key: `${group}:${collocate}`,
      values: { relation: "amod", relation_label: "修饰", collocate, freq_a: fa, freq_b: fb, diff, group },
      search_query: `{lemma=big} {lemma=${collocate}}`,
      search_query_b: `{lemma=large} {lemma=${collocate}}`,
      search_scope: { corpus_id: "c1" },
      search_layers: { dep: "layer-dep" },
    });
    const rows = [row("deal", "a", 12, 0, 9.1), row("house", "common", 5, 6, -0.3), ...Array.from({ length: 17 }, (_, i) => row(`w${i}`, "b", 0, 2, -(1 + i)))];
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ id: "stat-sd", method: "sketch_diff", params: {}, scope: {}, totals: {}, columns: [], rows, row_count: rows.length }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    try {
      // the model copied one row per side
      const lang = [
        'root = SketchDiff("stat-sd", "big", "large", a, [], b)',
        'a = [{relation: "修饰", collocate: "deal", freq_a: 12, freq_b: 0, diff: 9.1}]',
        'b = [{relation: "修饰", collocate: "w0", freq_a: 0, freq_b: 2, diff: -1}]',
      ].join("\n");
      wrap(<UiBlock lang={lang} />);
      expect(await screen.findByText("19 项")).toBeTruthy();
      expect(String(fetch.mock.calls[0][0])).toContain("/stats/stat-sd");
      const columns = [...document.querySelectorAll(".sk-col")] as HTMLElement[];
      expect(columns.map((c) => c.querySelectorAll("tr").length)).toEqual([1, 1, 17]);
      // B: most distinctive first; its rows open B's search on the sketch's layer
      const first = columns[2].querySelector("tr")!;
      expect(within(first).getByText("w16")).toBeTruthy();
      fireEvent.click(first);
      expect(where().searchParams.get("q")).toBe("{lemma=large} {lemma=w16}");
      expect(JSON.parse(where().searchParams.get("layers")!)).toEqual({ dep: "layer-dep" });
    } finally {
      fetch.mockRestore();
    }
  });

  it("SketchDiff falls back to the model's rows when the result is gone and says they are part of it (B14)", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "统计结果不存在" } }), { status: 404, headers: { "Content-Type": "application/json" } }),
    );
    try {
      const lang = [
        'root = SketchDiff("stat-gone", "big", "large", a, [], b, null, {a: 15, common: 1, b: 15})',
        'a = [{relation: "修饰", collocate: "deal", freq_a: 12, freq_b: 0, diff: 9.1}]',
        'b = [{relation: "修饰", collocate: "w0", freq_a: 0, freq_b: 2, diff: -1}]',
      ].join("\n");
      wrap(<UiBlock lang={lang} />);
      expect(await screen.findByText("显示 2 / 共 31")).toBeTruthy();
      expect(screen.getByText("deal")).toBeTruthy();
    } finally {
      fetch.mockRestore();
    }
  });

  it("CompareChart: series legend and chart host", async () => {
    const lang = 'root = CompareChart("stat-cmp", "big / large", "每百万词", ["2001", "2002"], [{name: "big", values: [120.5, 98]}, {name: "large", values: [80, null]}], "line")';
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("big / large")).toBeTruthy();
    expect(screen.getByText("每百万词")).toBeTruthy();
    const legend = document.querySelector(".cmp-legend")!;
    expect([...legend.querySelectorAll("span")].map((s) => s.textContent)).toEqual(["big", "large"]);
    expect(screen.getByRole("img", { name: "big / large：big、large" })).toBeTruthy();
  });

  it("KwicTable in semantic mode shows the similarity and no full-results link", async () => {
    const lang =
      'root = KwicTable("", "我喜欢读书", "UD 中文", {hits: 2, sentences: 2, documents: 1}, [{hit_id: "d1:0-5", left: "", match: "我爱看书。", right: "", source: "文档 1", score: 0.873}, {hit_id: "d1:6-11", left: "", match: "他喜欢阅读。", right: "", source: "文档 1", score: 0.81}], 2, "semantic")';
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("语义检索")).toBeTruthy();
    expect(screen.getByText("2 句")).toBeTruthy();
    expect(screen.getByText("相似度 0.873")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /打开完整结果/ })).toBeNull();
  });

  it("KwicTable without mode stays the query KWIC card", async () => {
    const lang =
      'root = KwicTable("s1", "翻译", "UD 中文", {hits: 3, sentences: 3, documents: 1}, [{hit_id: "d1:3-5", left: "已经被", match: "翻译", right: "成英文。", source: "文档 1"}], 3)';
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("KWIC")).toBeTruthy();
    expect(screen.getByText("3 命中")).toBeTruthy();
    expect(screen.queryByText(/相似度/)).toBeNull();
    expect(screen.getByRole("link", { name: /打开完整结果/ })).toBeTruthy();
  });
});
