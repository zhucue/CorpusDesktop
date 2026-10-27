import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { ResultContext } from "../src/components/results/cards";
import UiBlock, { parseJsonBlock } from "../src/openui/UiBlock";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>{node}</ResultContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("UiBlock", () => {
  it("detects the JSON fallback only for {component, props}", () => {
    expect(parseJsonBlock('{"component":"Callout","props":{"tone":"info","text":"x"}}')).toHaveLength(1);
    expect(parseJsonBlock('root = Callout("info", "x")')).toBeNull();
    expect(parseJsonBlock('{"a":1}')).toBeNull();
  });

  it("renders the JSON fallback through the registered components", () => {
    const block = JSON.stringify({
      component: "KwicTable",
      props: {
        search_id: "s1",
        query: "翻译/v",
        scope_name: "UD 中文",
        counts: { hits: 1284, sentences: 1190, documents: 7 },
        rows: [{ hit_id: "d1:3-5", left: "这本书已经被", match: "翻译", right: "成三十多种语言。", source: "zh#1120394", aligned: "The book has been translated." }],
        total: 1284,
      },
    });
    wrap(<UiBlock lang={block} />);
    expect(screen.getByText("KWIC")).toBeTruthy();
    expect(screen.getByText("1,284 命中")).toBeTruthy();
    expect(screen.getByTestId("kwic-match").textContent).toBe("翻译");
    expect(screen.getByText(/The book has been translated/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /打开完整结果/ });
    expect(decodeURIComponent(link.getAttribute("href")!).replace(/\+/g, " ")).toBe('/p/p1/search?q=翻译/v&scope={"corpus_id":"c1"}');
  });

  it("reports unknown components", () => {
    wrap(<UiBlock lang='{"component":"Nope","props":{}}' />);
    expect(screen.getByText("未注册的组件：Nope")).toBeTruthy();
  });

  it("renders OpenUI Lang through the official renderer", async () => {
    wrap(<UiBlock lang={'root = Callout("warning", "结果只含前 50 行")'} />);
    expect(await screen.findByText("结果只含前 50 行")).toBeTruthy();
    expect(document.querySelector(".callout.warning")).toBeTruthy();
  });
});
