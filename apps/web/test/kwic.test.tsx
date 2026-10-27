import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Hit } from "../src/api";
import ContextDrawer from "../src/search/ContextDrawer";
import KwicTable from "../src/search/KwicTable";
import { CountsBar } from "../src/search/Search";

const hits: Hit[] = [
  {
    hit_id: "h1",
    document_id: "d1",
    document_title: "新闻 2020-01",
    sentence_index: 3,
    left: "我们研究",
    match: "语言",
    right: "与文化的关系",
    start_cp: 120,
    end_cp: 122,
    metadata: { year: 2020 },
    aligned: [{ language: "en", text: "We study language and culture." }],
  },
  {
    hit_id: "h2",
    document_id: "d2",
    document_title: "小说 A",
    sentence_index: 0,
    left: "",
    match: "语言",
    right: "是工具",
    start_cp: 0,
    end_cp: 2,
    metadata: {},
    aligned: [],
  },
];

function Harness() {
  const [open, setOpen] = useState<Hit | null>(null);
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return (
    <QueryClientProvider client={client}>
      <KwicTable items={hits} offset={0} pagination={false} onOpen={setOpen} />
      <ContextDrawer hit={open} onClose={() => setOpen(null)} />
    </QueryClientProvider>
  );
}

describe("KWIC", () => {
  it("renders rows with bold match, source, metadata and aligned sentence", () => {
    render(<Harness />);
    expect(screen.getAllByTestId("kwic-match").map((e) => e.tagName + e.textContent)).toEqual([
      "STRONG语言",
      "STRONG语言",
    ]);
    expect(screen.getByText("我们研究")).toBeTruthy();
    expect(screen.getByText("与文化的关系")).toBeTruthy();
    expect(screen.getByText("新闻 2020-01")).toBeTruthy();
    expect(screen.getByText("year: 2020")).toBeTruthy();
    expect(screen.getByText("We study language and culture.")).toBeTruthy();
  });

  it("opens context from GET /search/context on row click", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          document: {
            id: "d1",
            corpus_id: "c1",
            title: "新闻 2020-01",
            language: "zh",
            metadata: { year: 2020 },
            sentences: 9,
            tokens: 80,
            created_at: "",
          },
          sentences: [
            { index: 2, text: "前一句。", highlight: null },
            { index: 3, text: "我们研究语言与文化的关系。", highlight: [4, 6] },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<Harness />);
    fireEvent.click(screen.getByText("我们研究"));

    const highlighted = await screen.findByText("语言", { selector: "p strong" });
    expect(highlighted.parentElement?.textContent).toBe("我们研究语言与文化的关系。");
    await waitFor(() => expect(screen.getByText("前一句。")).toBeTruthy());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/search/context?");
    expect(url).toContain("document_id=d1");
    expect(url).toContain("sentence_index=3");
    expect(url).toContain("start_cp=120");
    expect(url).toContain("end_cp=122");
  });

  it("shows 计算中 instead of partial counts", () => {
    const { container } = render(
      <CountsBar counts={{ hits: 50, sentences: 48, documents: 3, complete: false }} timedOut={false} />,
    );
    expect(within(container).getAllByText("计算中")).toHaveLength(3);
    expect(within(container).queryByText("50")).toBeNull();
  });
});
