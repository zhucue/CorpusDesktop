import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

const shell = {
  projectId: "p1",
  scope: { corpus_id: "c2" },
  setScope: () => {},
  scopeInfo: { corpus: null, subcorpus: null, name: "Tatoeba" },
  assistantOpen: true,
  setAssistantOpen: () => {},
  assistantContext: null,
  setAssistantContext: () => {},
  openPalette: () => {},
  openKeys: () => {},
};
// a small page size keeps the basket test light (the real one is 200)
vi.mock("../src/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../src/api")>()), MAX_PAGE_SIZE: 4 }));
vi.mock("../src/components/shell/shell", () => ({ useShell: () => shell, useOptionalShell: () => shell }));

import { EvidenceBasket, EvidenceProvider } from "../src/components/global/evidence";
import AssistantDrawer from "../src/features/assistant/AssistantDrawer";

const WAIT = { timeout: 10_000 };
const SLOW = 20_000;
const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });

function mockFetch(handle: (method: string, path: string, q: URLSearchParams) => unknown) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url.pathname}${url.search}`);
    return json(handle(method, url.pathname, url.searchParams));
  });
  return calls;
}

function renderAt(path: string, node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("assistant drawer scope", () => {
  it("shows the session and page scopes when they differ and starts a new conversation on request", async () => {
    localStorage.setItem("drawer-session:p1", JSON.stringify("s1"));
    const session = { id: "s1", project_id: "p1", owner_id: "u1", title: "旧会话", scope: { corpus_id: "c1" }, state: "idle", created_at: "", updated_at: "", message_count: 0 };
    mockFetch((_m, path) => {
      if (path === "/api/corpora")
        return {
          items: [
            { id: "c1", name: "UD 中文" },
            { id: "c2", name: "Tatoeba" },
          ],
          total: 2,
        };
      if (path === "/api/projects/p1/subcorpora") return { items: [], total: 0 };
      if (path === "/agent/health") return { ok: true, model_id: "m" };
      if (path === "/agent/sessions") return { items: [session], total: 1 };
      if (path === "/agent/sessions/s1") return { ...session, messages: [] };
      return {};
    });
    renderAt("/p/p1/search", <AssistantDrawer onClose={() => {}} />);
    expect(await screen.findByText("会话范围：UD 中文；当前页面：Tatoeba", {}, WAIT)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "按当前范围新对话" }));
    await waitFor(() => expect(screen.queryByText(/会话范围：/)).toBeNull(), WAIT);
  }, SLOW);
});

describe("evidence basket", () => {
  const item = (i: number, mine: boolean) => ({
    id: `e${i}`,
    project_id: "p1",
    kind: "text",
    ref: {},
    text: `证据 ${i}`,
    source: "笔记",
    note: null,
    created_by: mine ? "me" : "other",
    created_at: "",
  });

  it("shows 显示 n / 共 N, loads the next page and clears only the user's own items", async () => {
    const all = Array.from({ length: 6 }, (_, i) => item(i, i % 2 === 0));
    const calls = mockFetch((method, path, q) => {
      if (path === "/api/projects/p1/evidence" && method === "GET") {
        const page = Number(q.get("page") ?? 1);
        return { items: all.slice((page - 1) * 4, page * 4), total: all.length };
      }
      if (path === "/api/projects/p1/evidence" && method === "DELETE") return { deleted: 3 };
      return {};
    });
    renderAt(
      "/p/p1/search",
      <EvidenceProvider projectId="p1">
        <EvidenceBasket projectId="p1" open onToggle={() => {}} />
      </EvidenceProvider>,
    );
    expect(await screen.findByText("显示 4 / 共 6", {}, WAIT)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
    expect(await screen.findByText("6 条", {}, WAIT)).toBeTruthy();
    expect(calls).toContain("GET /api/projects/p1/evidence?page=2&page_size=4");
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "清空我钉的" }));
    fireEvent.click(screen.getByRole("button", { name: "确认清空我钉的" }));
    await waitFor(() => expect(calls).toContain("DELETE /api/projects/p1/evidence?mine=true"), WAIT);
    // one request for the whole clear, never item by item
    expect(calls.some((c) => c.startsWith("DELETE /api/evidence/"))).toBe(false);
  }, SLOW);
});
