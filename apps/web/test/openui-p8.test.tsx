import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import { ResultContext } from "../src/components/results/cards";
import { TranslationTableCard, type TranslationTableProps } from "../src/openui/statCards";

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function wrap(node: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/p/p1/assistant"]}>
      <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>
        {node}
        <Where />
      </ResultContext.Provider>
    </MemoryRouter>,
  );
}

const rows: TranslationTableProps["rows"] = [
  { item: "translate", cooc: 55, pct: 78.6, score: 0.9, search_query: '"翻译"', search_aligned: { op: "+", query: "{lemma=translate}" } },
  { item: "render", cooc: 4, pct: 5.7, score: 0.2, search_query: null, search_aligned: { op: "+", query: '"render"' } },
  { item: 'say"', cooc: 3, pct: 4.3, score: 0.1, search_query: '"翻译"' },
];

describe("TranslationTable", () => {
  it("opens the search with the row's own query and translation condition; rows without both have no link", () => {
    wrap(<TranslationTableCard stat_id="s1" query='"翻译"' measure="dice" rows={rows} />);
    const buttons = screen.getAllByRole("button", { name: /例句/ }) as HTMLButtonElement[];
    expect(buttons.map((b) => b.disabled)).toEqual([false, true, true]);
    fireEvent.click(buttons[0]);
    const url = new URL(screen.getByTestId("where").textContent!, "http://x");
    expect(url.pathname).toBe("/p/p1/search");
    expect(url.searchParams.get("q")).toBe('"翻译"');
    expect(JSON.parse(url.searchParams.get("scope")!)).toEqual({ corpus_id: "c1" });
    expect(JSON.parse(url.searchParams.get("aligned")!)).toEqual({ op: "+", query: "{lemma=translate}" });
    fireEvent.click(buttons[2]);
    expect(screen.getByTestId("where").textContent).toContain("lemma%3Dtranslate"); // unchanged
  });
});
