import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceBasket, EvidenceProvider } from "../src/components/global/evidence";
import { MethodAppendix } from "../src/components/global/MethodAppendix";

const WAIT = { timeout: 10_000 };
const SLOW = 20_000;
const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
const MD = { gbt7714: "# 方法附录\n\n## 1 语料\n\n- **作文**\n\n## 2 参考文献\n\n1. DUNNING T. Accurate methods[J].\n", apa: "# 方法附录\n\n1. Dunning, T. (1993).\n" };

interface Call {
  method: string;
  path: string;
  search: string;
  body: Record<string, unknown> | null;
}

function mockFetch(extra?: (c: Call) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const call = { method: init?.method ?? "GET", path: url.pathname, search: url.search, body: typeof init?.body === "string" ? JSON.parse(init.body) : null };
    calls.push(call);
    if (call.path.endsWith("/method-appendix")) {
      if (url.searchParams.get("format") === "docx")
        return new Response(new Blob(["docx"]), { status: 200, headers: { "Content-Disposition": "attachment; filename*=UTF-8''%E6%96%B9%E6%B3%95%E9%99%84%E5%BD%95.docx" } });
      const style = (call.body?.style as "gbt7714" | "apa") ?? "gbt7714";
      return json({ markdown: MD[style], citations: [] });
    }
    return json(extra?.(call) ?? {});
  });
  return calls;
}

function renderIt(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter>{node}</MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("method appendix dialog", () => {
  it(
    "previews the appendix, switches citation style, downloads DOCX and opens the note picker",
    async () => {
      const calls = mockFetch((c) => (c.path.endsWith("/kb/documents") ? { items: [], total: 0 } : {}));
      URL.createObjectURL = vi.fn(() => "blob:x");
      URL.revokeObjectURL = vi.fn();
      const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      const onClose = vi.fn();
      renderIt(<MethodAppendix projectId="p1" statIds={["s1"]} layerIds={["l1"]} onClose={onClose} />);
      expect(await screen.findByRole("heading", { name: "1 语料" }, WAIT)).toBeTruthy();
      const first = calls.find((c) => c.path === "/api/projects/p1/method-appendix")!;
      expect(first.body).toEqual({ stat_ids: ["s1"], searches: [], layer_ids: ["l1"], evidence: false, style: "gbt7714" });

      fireEvent.click(screen.getByText("APA"));
      expect(await screen.findByText("Dunning, T. (1993).", {}, WAIT)).toBeTruthy();
      expect(calls.some((c) => c.body?.style === "apa")).toBe(true);

      fireEvent.click(screen.getByRole("button", { name: /下载 DOCX/ }));
      await waitFor(() => expect(calls.some((c) => c.search === "?format=docx" && c.body?.style === "apa")).toBe(true), WAIT);
      await waitFor(() => expect(click).toHaveBeenCalled(), WAIT);

      fireEvent.click(screen.getByRole("button", { name: /保存为笔记/ }));
      expect(await screen.findByLabelText("笔记标题", {}, WAIT)).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "关闭" }));
      expect(onClose).toHaveBeenCalled();
    },
    SLOW,
  );

  it(
    "evidence basket opens the appendix for the basket",
    async () => {
      const items = [{ id: "e1", project_id: "p1", kind: "text", ref: {}, text: "证据", source: "笔记", note: null, created_by: "me", created_at: "" }];
      const calls = mockFetch((c) => (c.path === "/api/projects/p1/evidence" ? { items, total: 1 } : {}));
      renderIt(
        <EvidenceProvider projectId="p1">
          <EvidenceBasket projectId="p1" open onToggle={() => {}} />
        </EvidenceProvider>,
      );
      expect(await screen.findByText("1 条", {}, WAIT)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: /生成方法附录/ }));
      expect(await screen.findByRole("heading", { name: "1 语料" }, WAIT)).toBeTruthy();
      expect(calls.find((c) => c.path.endsWith("/method-appendix"))?.body).toMatchObject({ evidence: true });
    },
    SLOW,
  );
});
