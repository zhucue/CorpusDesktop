import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Corpus, Job, User } from "../src/api";
import CorpusDrawer from "../src/features/corpora/CorpusDrawer";
import { metaEntries, metaFromForm } from "../src/features/corpora/CorpusMeta";
import Jobs, { canManageJob, filterJobs } from "../src/features/jobs/Jobs";
import { fmtRelative } from "../src/lib/format";

vi.mock("../src/components/shell/AppShell", () => ({
  PageHeader: ({
    title,
    actions,
  }: {
    title: string;
    actions?: React.ReactNode;
  }) => (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  ),
}));

const json = (v: unknown) =>
  new Response(JSON.stringify(v), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

function mockFetch(
  handle: (path: string, q: URLSearchParams, method: string) => unknown,
) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      calls.push(`${init?.method ?? "GET"} ${url.pathname}${url.search}`);
      return json(
        handle(url.pathname, url.searchParams, init?.method ?? "GET"),
      );
    },
  );
  return calls;
}

function renderAt(path: string, route: string, node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={node} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

const me: User = {
  id: "u1",
  email: "me@x.edu",
  display_name: "me",
  is_admin: false,
};
const job = (o: Partial<Job>): Job => ({
  id: "j0000000-0000",
  project_id: "p1",
  kind: "import",
  state: "succeeded",
  progress: { done: 1, total: 1, message: "" },
  result: null,
  error: null,
  created_at: new Date().toISOString(),
  finished_at: null,
  owner_id: "u1",
  owner_email: "me@x.edu",
  summary: "语料 新闻 · 3 个文件",
  ...o,
});

const MINE_FAILED = job({
  id: "a1111111-x",
  state: "failed",
  error: { code: "E", message: "解析失败" },
  summary: "语料 新闻 · 3 个文件",
});
const OTHERS_FAILED = job({
  id: "b2222222-x",
  state: "failed",
  owner_id: "u2",
  owner_email: "li@x.edu",
  error: { code: "E", message: "超时" },
  kind: "stats",
  summary: "频次 · 语料 小说",
});
const OTHERS_RUNNING = job({
  id: "c3333333-x",
  state: "running",
  owner_id: "u2",
  owner_email: "li@x.edu",
  kind: "index",
  summary: "语料 小说",
});

describe("job filter and permissions", () => {
  const items = [MINE_FAILED, OTHERS_FAILED, OTHERS_RUNNING];
  it("filters by state and by creator", () => {
    expect(filterJobs(items, "all", "u1")).toHaveLength(3);
    expect(filterJobs(items, "mine", "u1").map((j) => j.id)).toEqual([
      MINE_FAILED.id,
    ]);
    expect(filterJobs(items, "mine", undefined)).toEqual([]);
    expect(filterJobs(items, "failed", "u1")).toHaveLength(2);
    expect(filterJobs(items, "active", "u1").map((j) => j.id)).toEqual([
      OTHERS_RUNNING.id,
    ]);
  });
  it("lets the creator manage their job; others need edit rights, built-in jobs need an admin", () => {
    expect(canManageJob(MINE_FAILED, me, false)).toBe(true);
    expect(canManageJob(OTHERS_FAILED, me, false)).toBe(false);
    expect(canManageJob(OTHERS_FAILED, me, true)).toBe(true);
    const builtin = job({ project_id: null, owner_id: "u9" });
    expect(canManageJob(builtin, me, true)).toBe(false);
    expect(canManageJob(builtin, { ...me, is_admin: true }, false)).toBe(true);
    expect(canManageJob(MINE_FAILED, undefined, true)).toBe(false);
  });
});

describe("jobs page", () => {
  it("shows target and creator columns, filters to my jobs, offers retry only where allowed", async () => {
    mockFetch((path) => {
      if (path === "/api/auth/me") return me;
      if (path === "/api/projects/p1")
        return { id: "p1", name: "P", role: "viewer", created_at: "" };
      if (path === "/api/projects/p1/jobs")
        return {
          items: [MINE_FAILED, OTHERS_FAILED, OTHERS_RUNNING],
          total: 3,
        };
      throw new Error(path);
    });
    renderAt("/p/p1/jobs", "/p/:projectId/jobs", <Jobs />);
    await screen.findByText("频次 · 语料 小说");
    expect(
      screen.getByRole("columnheader", { name: "对象与参数" }),
    ).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "发起人" })).toBeTruthy();
    expect(screen.getAllByText("li@x.edu")).toHaveLength(2);
    expect(screen.getByText("我")).toBeTruthy();
    // viewer: retry only on their own failed job, no cancel on someone else's running job
    expect(screen.getAllByRole("button", { name: /重试/ })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "取消" })).toBeNull();
    expect(screen.queryByText("内置语料任务")).toBeNull();

    fireEvent.click(screen.getByText("我发起的"));
    await waitFor(() =>
      expect(screen.queryByText("频次 · 语料 小说")).toBeNull(),
    );
    expect(screen.getByText("语料 新闻 · 3 个文件")).toBeTruthy();
  });

  it("lists built-in corpus jobs for platform admins", async () => {
    const calls = mockFetch((path, q) => {
      if (path === "/api/auth/me") return { ...me, is_admin: true };
      if (path === "/api/projects/p1")
        return { id: "p1", name: "P", role: "owner", created_at: "" };
      if (path === "/api/projects/p1/jobs") return { items: [], total: 0 };
      if (path === "/api/jobs" && q.get("builtin") === "1")
        return {
          items: [
            job({
              id: "d4444444-x",
              project_id: null,
              summary: "内置语料 Tatoeba · 第 3 批",
              owner_id: "u7",
              owner_email: "admin@x.edu",
              state: "running",
            }),
          ],
          total: 1,
        };
      throw new Error(path);
    });
    renderAt("/p/p1/jobs", "/p/:projectId/jobs", <Jobs />);
    fireEvent.click(await screen.findByRole("switch"));
    await screen.findByText("内置语料 Tatoeba · 第 3 批");
    expect(calls.some((c) => c.startsWith("GET /api/jobs?builtin=1"))).toBe(
      true,
    );
    expect(screen.getByRole("button", { name: "取消" })).toBeTruthy();
  });
});

describe("corpus source and license", () => {
  it("keeps filled fields only", () => {
    expect(
      metaFromForm({
        license: " CC BY 2.0 FR ",
        attribution: "",
        version: undefined,
      }),
    ).toEqual({ license: "CC BY 2.0 FR" });
    expect(metaFromForm({ license: " " })).toBeUndefined();
    expect(metaEntries({}).length).toBe(0);
    expect(metaEntries(undefined).length).toBe(0);
  });

  const corpus = (meta: Corpus["meta"]): Corpus => ({
    id: "c1",
    project_id: null,
    name: "Tatoeba 中英",
    language: "zh",
    description: "",
    parallel: true,
    status: "ready",
    error: null,
    stats: { documents: 2, sentences: 10, tokens: 80 } as Corpus["stats"],
    index_version: 3,
    meta,
    created_at: "2026-10-01T00:00:00Z",
  });

  function drawer(c: Corpus) {
    mockFetch((path) => {
      if (path === "/api/auth/me") return me;
      if (path === "/api/projects/p1")
        return { id: "p1", name: "P", role: "viewer", created_at: "" };
      if (path === "/api/corpora/c1") return c;
      if (path === "/api/corpora/c1/documents") return { items: [], total: 0 };
      if (path === "/api/corpora/c1/metadata-fields") return [];
      throw new Error(path);
    });
    renderAt(
      "/p/p1/corpora/c1",
      "/p/:projectId/corpora/:corpusId",
      <CorpusDrawer corpusId="c1" onClose={() => {}} />,
    );
  }

  it("shows license, attribution, source link and version in the drawer", async () => {
    drawer(
      corpus({
        license: "CC BY 2.0 FR",
        attribution: "Tatoeba contributors",
        source_url: "https://tatoeba.org",
        version: "2026-09",
      }),
    );
    const dl = await screen.findByLabelText("来源与许可");
    const box = within(dl);
    expect(box.getByText("许可")).toBeTruthy();
    expect(box.getByText("CC BY 2.0 FR")).toBeTruthy();
    expect(box.getByText("Tatoeba contributors")).toBeTruthy();
    expect(
      box
        .getByRole("link", { name: "https://tatoeba.org" })
        .getAttribute("href"),
    ).toBe("https://tatoeba.org");
    expect(box.getByText("2026-09")).toBeTruthy();
  });

  it("shows nothing when the corpus has no source information", async () => {
    drawer(corpus({}));
    await screen.findByText("Tatoeba 中英");
    expect(screen.queryByLabelText("来源与许可")).toBeNull();
  });
});

describe("relative time", () => {
  it("counts minutes, hours and days", () => {
    const now = Date.parse("2026-10-27T12:00:00Z");
    expect(fmtRelative("2026-10-27T11:59:40Z", now)).toBe("刚刚");
    expect(fmtRelative("2026-10-27T11:55:00Z", now)).toBe("5 分钟前");
    expect(fmtRelative("2026-10-27T09:00:00Z", now)).toBe("3 小时前");
    expect(fmtRelative("2026-10-25T12:00:00Z", now)).toBe("2 天前");
  });
});
