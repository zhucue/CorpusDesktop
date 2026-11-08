import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { Fragment } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssistantContext } from "../src/components/shell/shell";

const shell = {
  projectId: "p1",
  scope: { corpus_id: "c2" } as { corpus_id: string } | null,
  setScope: () => {},
  scopeInfo: { corpus: null, subcorpus: null, name: "UD 英文 EWT" },
  assistantOpen: true,
  setAssistantOpen: () => {},
  assistantContext: null as AssistantContext | null,
  setAssistantContext: () => {},
  openPalette: () => {},
  openKeys: () => {},
};
vi.mock("../src/components/shell/shell", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/components/shell/shell")>()),
  useShell: () => shell,
  useOptionalShell: () => shell,
}));

import { pageKey } from "../src/components/shell/shell";
import AssistantDrawer from "../src/features/assistant/AssistantDrawer";
import AssistantPanel from "../src/features/assistant/AssistantPanel";

// jsdom has no scrolling
Element.prototype.scrollTo = () => {};

const WAIT = { timeout: 10_000 };
const SLOW = 20_000;
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  shell.assistantContext = null;
  shell.scope = { corpus_id: "c2" };
});

function wrap(path: string, node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

/** The assistant page as the shell mounts it: a new conversation navigates to its URL, keyed like AppShell. */
function Page() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  return (
    <AssistantPanel
      projectId="p1"
      sessionId={sessionId ?? null}
      onSessionCreated={(s) => navigate(`/p/p1/assistant/${s.id}`, { replace: true })}
      scope={{ corpus_id: "c2" }}
      scopeLabel="UD 英文 EWT"
    />
  );
}
function Shell() {
  const loc = useLocation();
  return (
    <Fragment key={pageKey(loc.pathname)}>
      <Routes>
        <Route path="/p/:projectId/assistant" element={<Page />} />
        <Route path="/p/:projectId/assistant/:sessionId" element={<Page />} />
      </Routes>
    </Fragment>
  );
}

describe("B15 concurrent run limit", () => {
  it("keeps the page when a new conversation gets its URL", () => {
    expect(pageKey("/p/p1/assistant/s9")).toBe("/p/p1/assistant");
    expect(pageKey("/p/p1/assistant")).toBe("/p/p1/assistant");
    expect(pageKey("/p/p1/corpora/c1")).toBe("/p/p1/corpora/c1");
  });

  it(
    "shows the backend message, keeps the question, and sends again once another run stopped",
    async () => {
      const session = { id: "s9", project_id: "p1", owner_id: "u1", title: "比较", scope: { corpus_id: "c2" }, state: "idle", created_at: "", updated_at: "", message_count: 0 };
      let limited = true;
      const posts: string[] = [];
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://x");
        const method = init?.method ?? "GET";
        if (method === "POST") posts.push(url.pathname);
        if (url.pathname === "/agent/health") return json({ ok: true, model_id: "m" });
        if (url.pathname === "/agent/sessions" && method === "POST") return json(session);
        if (url.pathname === "/agent/sessions") return json({ items: [session], total: 1 });
        if (url.pathname === "/agent/sessions/s9/messages") {
          if (limited) return json({ error: { code: "TOO_MANY_RUNS", message: "已有 2 个对话在运行，请等待完成或停止后再试" } }, 429);
          const done = { message: { id: "m1", role: "assistant", content: "好的", parts: [{ type: "text", text: "好的" }], tool_calls: [], created_at: "2026-11-07T00:00:00Z" } };
          return new Response(`event: start\ndata: {"message_id":"m1"}\n\nevent: done\ndata: ${JSON.stringify(done)}\n\n`, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (url.pathname === "/agent/sessions/s9") return json({ ...session, messages: [] });
        return json({});
      });
      wrap("/p/p1/assistant", <Shell />);
      const box = (await screen.findByLabelText("向助手提问", {}, WAIT)) as HTMLTextAreaElement;
      await waitFor(() => expect(box.disabled).toBe(false), WAIT);
      fireEvent.change(box, { target: { value: "比较 big 和 large 的用法" } });
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      expect(await screen.findByText("已有 2 个对话在运行，请等待完成或停止后再试", {}, WAIT)).toBeTruthy();
      const after = screen.getByLabelText("向助手提问") as HTMLTextAreaElement;
      expect(after.value).toBe("比较 big 和 large 的用法");
      expect(posts).toEqual(["/agent/sessions", "/agent/sessions/s9/messages"]);

      limited = false;
      fireEvent.click(screen.getByRole("button", { name: "发送" }));
      expect(await screen.findByText("好的", {}, WAIT)).toBeTruthy();
      expect(posts).toEqual(["/agent/sessions", "/agent/sessions/s9/messages", "/agent/sessions/s9/messages"]);
      expect(screen.queryByText("已有 2 个对话在运行，请等待完成或停止后再试")).toBeNull();
    },
    SLOW,
  );
});

describe("B16 drawer follows the corpus picked on the page", () => {
  it(
    "shows the mismatch after the breadcrumb switches corpus, with no new search",
    async () => {
      localStorage.setItem("drawer-session:p1", JSON.stringify("s1"));
      const session = { id: "s1", project_id: "p1", owner_id: "u1", title: "翻译", scope: { corpus_id: "c1" }, state: "idle", created_at: "", updated_at: "", message_count: 2 };
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
        const path = new URL(String(input), "http://x").pathname;
        if (path === "/api/corpora")
          return json({
            items: [
              { id: "c1", name: "Tatoeba 中文侧" },
              { id: "c2", name: "UD 英文 EWT" },
            ],
            total: 2,
          });
        if (path === "/api/projects/p1/subcorpora") return json({ items: [], total: 0 });
        if (path === "/agent/health") return json({ ok: true, model_id: "m" });
        if (path === "/agent/sessions") return json({ items: [session], total: 1 });
        if (path === "/agent/sessions/s1") return json({ ...session, messages: [] });
        return json({});
      });
      // the search page still holds the old Tatoeba search; the breadcrumb already set EWT
      shell.assistantContext = { label: "当前检索 · 84 命中", scope: { corpus_id: "c1" }, query: "翻译", search_id: "x1" };
      shell.scope = { corpus_id: "c2" };
      wrap("/p/p1/search", <AssistantDrawer onClose={() => {}} />);
      expect(await screen.findByText("会话范围：Tatoeba 中文侧；当前页面：UD 英文 EWT", {}, WAIT)).toBeTruthy();
      expect(screen.getByRole("button", { name: "按当前范围新对话" })).toBeTruthy();
    },
    SLOW,
  );
});
