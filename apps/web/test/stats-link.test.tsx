import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import type { StatResult } from "../src/api";
import { rowSearchHref, StatTable } from "../src/features/stats/StatTable";

function SearchProbe() {
  const loc = useLocation();
  const p = new URLSearchParams(loc.search);
  return (
    <div>
      <span data-testid="q">{p.get("q")}</span>
      <span data-testid="scope">{p.get("scope")}</span>
    </div>
  );
}

function renderTable(stat: StatResult) {
  return render(
    <MemoryRouter initialEntries={["/p/p1/stats"]}>
      <Routes>
        <Route path="/p/:projectId/stats" element={<StatTable stat={stat} projectId="p1" />} />
        <Route path="/p/:projectId/search" element={<SearchProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const base = {
  project_id: "p1",
  params: {},
  scope: { corpus_id: "c1", subcorpus_id: null, name: "UD 中文" },
  index_version: 3,
  totals: { tokens: 1000, sentences: 50, documents: 2 },
  created_at: "2026-10-27T00:00:00Z",
};

describe("stats → search", () => {
  it("builds the search URL with query and scope", () => {
    const url = rowSearchHref("p1", '"翻译"', { corpus_id: "c1", filter: { year: [2017] } });
    const p = new URLSearchParams(url.split("?")[1]);
    expect(url.startsWith("/p/p1/search?")).toBe(true);
    expect(p.get("q")).toBe('"翻译"');
    expect(JSON.parse(p.get("scope")!)).toEqual({ corpus_id: "c1", filter: { year: [2017] } });
  });

  it("回到例句 opens the search page with search_query and search_scope", () => {
    const stat: StatResult = {
      ...base,
      id: "s1",
      method: "distribution",
      columns: [
        { key: "bin", label: "区间或字段值", type: "string" },
        { key: "hits", label: "命中数", type: "number" },
        { key: "per_million", label: "每百万", type: "number" },
      ],
      rows: [{ key: "2017", values: { bin: "2017", hits: 12, per_million: 345.678 }, search_query: "翻译/v +文化", search_scope: { corpus_id: "c1", filter: { year: [2017] } } }],
      row_count: 1,
    };
    renderTable(stat);
    expect(screen.getByText("345.68")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /回到例句/ }));
    expect(screen.getByTestId("q").textContent).toBe("翻译/v +文化");
    expect(JSON.parse(screen.getByTestId("scope").textContent!)).toEqual({ corpus_id: "c1", filter: { year: [2017] } });
  });

  it("collocation rows offer right and left queries; missing queries are disabled", () => {
    const stat: StatResult = {
      ...base,
      id: "s2",
      method: "collocations",
      columns: [
        { key: "collocate", label: "搭配词", type: "string" },
        { key: "freq", label: "共现频次", type: "number" },
        { key: "logdice", label: "logDice", type: "number" },
      ],
      rows: [
        { key: "成", values: { collocate: "成", freq: 412, logdice: 11.4 }, search_query: '翻译/v $4 "成"', search_query_reverse: '"成" $4 翻译/v', search_scope: { corpus_id: "c1" } },
        { key: "x", values: { collocate: "x", freq: 3, logdice: 1 }, search_query: null, search_query_reverse: null, search_scope: { corpus_id: "c1" } },
      ],
      row_count: 2,
    };
    renderTable(stat);
    const left = screen.getAllByRole("button", { name: /左侧/ });
    expect((left[1] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(left[0]);
    expect(screen.getByTestId("q").textContent).toBe('"成" $4 翻译/v');
  });

  it("the frequency number links to the examples", () => {
    const stat: StatResult = {
      ...base,
      id: "s3",
      method: "frequency",
      columns: [
        { key: "item", label: "项", type: "string" },
        { key: "freq", label: "频次", type: "number" },
      ],
      rows: [{ key: "是", values: { item: "是", freq: 9874 }, search_query: '"是"', search_scope: { subcorpus_id: "sc1" } }],
      row_count: 1,
    };
    renderTable(stat);
    fireEvent.click(screen.getByRole("button", { name: "9,874" }));
    expect(screen.getByTestId("q").textContent).toBe('"是"');
    expect(JSON.parse(screen.getByTestId("scope").textContent!)).toEqual({ subcorpus_id: "sc1" });
  });
});
