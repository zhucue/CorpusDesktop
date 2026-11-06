import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { ApiError, codeLabel } from "../src/api";
import { IndexPendingNote, INDEX_PENDING_TEXT } from "../src/components/common";
import { FeedbackButton } from "../src/components/shell/Feedback";
import Settings from "../src/features/settings/Settings";

// antd tables and modals render slowly under a loaded full run
configure({ asyncUtilTimeout: 8000 });
vi.setConfig({ testTimeout: 20000 });

vi.mock("../src/components/shell/AppShell", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

const json = (v: unknown, status = 200) => new Response(JSON.stringify(v ?? {}), { status, headers: { "Content-Type": "application/json" } });

interface Call {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
}

function mockFetch(handle: (c: Call) => unknown) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const c: Call = {
      method: init?.method ?? "GET",
      path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(c);
    const r = handle(c);
    return r instanceof Response ? r : json(r);
  });
  return calls;
}

function renderAt(path: string, el: React.ReactNode = <Settings />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/p/:projectId/*" element={el} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

const admin = { id: "u1", email: "root@x.edu", display_name: "Root", is_admin: true };
const owner = { id: "u2", email: "li@x.edu", display_name: "李", is_admin: false };
const proj = (over: Record<string, unknown> = {}) => ({
  id: "p9",
  name: "译介研究",
  owner: { id: "u2", email: "li@x.edu", display_name: "李" },
  members: 3,
  corpora: 2,
  layers: 1,
  kb_documents: 4,
  disk_bytes: 5 * 1024 * 1024,
  created_at: "2026-11-01T00:00:00Z",
  deleted_at: null,
  ...over,
});
const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  project_id: "p9",
  project_name: "译介研究",
  owner_email: "li@x.edu",
  summary: "频次 · 新闻",
  kind: "stats",
  state: "running",
  progress: { done: 1, total: 10, message: "" },
  result: null,
  error: null,
  created_at: "2026-11-06T00:00:00Z",
  finished_at: null,
  ...over,
});

describe("settings · 管理", () => {
  it("projects: lists, filters deleted, reassigns the owner and restores", async () => {
    const calls = mockFetch(({ method, path, query }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/projects") {
        expect(query.deleted).toMatch(/^[01]$/);
        return query.deleted === "1" ? { items: [proj({ id: "p8", name: "旧项目", deleted_at: "2026-11-05T00:00:00Z" })], total: 1 } : { items: [proj()], total: 1 };
      }
      if (path === "/api/admin/users") return { items: [{ id: "u3", email: "wang@x.edu", display_name: "王", is_admin: false, disabled_at: null, last_login_at: null, created_at: "", projects: 0 }], total: 1 };
      if (method === "POST") return {};
      throw new Error(`${method} ${path}`);
    });
    renderAt("/p/p1/settings?tab=admin&admin=projects");
    await screen.findByText("译介研究");
    expect(screen.getByText("5.0 MB")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /用户/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "改派负责人" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.mouseDown(within(dialog).getByRole("combobox"));
    fireEvent.click(await screen.findByText("王 · wang@x.edu"));
    fireEvent.click(within(dialog).getByRole("button", { name: /改\s*派/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/admin/projects/p9/owner" && (c.body as { user_id: string }).user_id === "u3")).toBe(true));

    fireEvent.click(screen.getByText("已删除"));
    await screen.findByText("旧项目");
    fireEvent.click(screen.getByRole("button", { name: /恢复/ }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: /恢\s*复/ }).length).toBe(2));
    fireEvent.click(screen.getAllByRole("button", { name: /恢\s*复/ })[1]);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/projects/p8/restore")).toBe(true));
  }, 40000);

  it("jobs: filters by state and cancels a running job", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/jobs") return { items: [job(), job({ id: "j2", state: "failed", summary: "导入 · 法语.tmx", project_id: null, project_name: null, error: { code: "PARSE_ERROR", message: "TMX 含暂不支持的语言：fr" } })], total: 2 };
      if (method === "POST") return {};
      throw new Error(`${method} ${path}`);
    });
    renderAt("/p/p1/settings?tab=admin&admin=jobs");
    await screen.findByText("频次 · 新闻");
    expect(screen.getByText("TMX 含暂不支持的语言：fr")).toBeTruthy();
    expect(screen.getByText("内置")).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "状态" }));
    fireEvent.click(await screen.findByTitle("失败"));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/admin/jobs" && c.query.state === "failed")).toBe(true));

    fireEvent.click(screen.getAllByRole("button", { name: "取消" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "取消任务" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/jobs/j1/cancel")).toBe(true));
  });

  it("usage: by user, then by project for another month", async () => {
    const calls = mockFetch(({ path, query }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/llm-usage")
        return {
          items: [{ key: query.group === "project" ? "p9" : "u2", name: query.group === "project" ? "译介研究" : "li@x.edu", total_tokens: 12345, prompt_tokens: 10000, completion_tokens: 2345, calls: 7 }],
          total: 12345,
        };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=admin&admin=usage");
    await screen.findByText("li@x.edu");
    expect(screen.getByText("12,345")).toBeTruthy();
    expect(screen.getByText("10,000 / 2,345")).toBeTruthy();
    fireEvent.click(screen.getByText("按项目"));
    fireEvent.change(screen.getByLabelText("月份"), { target: { value: "2026-10" } });
    await screen.findByText("译介研究");
    await waitFor(() => expect(calls.some((c) => c.path === "/api/admin/llm-usage" && c.query.group === "project" && c.query.month === "2026-10")).toBe(true));
  });

  it("audit: Chinese action names and filters", async () => {
    const calls = mockFetch(({ path }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/projects") return { items: [proj()], total: 1 };
      if (path === "/api/admin/audit")
        return {
          items: [
            { id: 1, at: "2026-11-06T01:00:00Z", actor_id: "u2", actor_email: "li@x.edu", action: "corpus_delete", target_type: "corpus", target_id: "c1", target_name: "新闻", project_id: "p9", detail: {}, ip: "10.0.0.8" },
            { id: 2, at: "2026-11-06T02:00:00Z", actor_id: null, actor_email: null, action: "login_failed", target_type: null, target_id: null, target_name: null, project_id: null, detail: { email: "x@y.edu" }, ip: "10.0.0.9" },
          ],
          total: 2,
        };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=admin&admin=audit");
    await screen.findByText("删除语料库");
    expect(screen.getByText("语料库 · 新闻")).toBeTruthy();
    expect(screen.getByText("登录失败")).toBeTruthy();
    expect(screen.getByText("x@y.edu")).toBeTruthy();
    expect(screen.getByText("10.0.0.8")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("译介研究").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("起始日期"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("操作人"), { target: { value: "li@x.edu" } });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/admin/audit" && c.query.from === "2026-11-01" && c.query.actor === "li@x.edu")).toBe(true));
  });

  it("feedback: marks an item handled with a note", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/feedback" && method === "GET")
        return { items: [{ id: 5, created_at: "2026-11-06T00:00:00Z", user: { id: "u2", email: "li@x.edu", display_name: "李" }, project_id: "p9", project_name: "译介研究", page: "/p/p9/search", app_version: "1.2.0", text: "检索结果翻页卡住", status: "open", admin_note: "", handled_at: null }], total: 1 };
      if (method === "PATCH") return {};
      throw new Error(`${method} ${path}`);
    });
    renderAt("/p/p1/settings?tab=admin&admin=feedback");
    await screen.findByText("检索结果翻页卡住");
    expect(calls[calls.length - 1].query.status).toBe("open");
    fireEvent.click(screen.getByRole("button", { name: "处理" }));
    fireEvent.change(await screen.findByLabelText("备注"), { target: { value: "已修复" } });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")).toMatchObject({ path: "/api/admin/feedback/5", body: { status: "done", admin_note: "已修复" } }));
  });

  it("system: version, workers, disk and backup", async () => {
    mockFetch(({ path }) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/system")
        return {
          version: "1.2.0",
          model: { configured: true, host: "api.example.com", model_id: "qwen-plus" },
          embed: { mode: "local", host: null, model: "minilm", ready: true },
          workers: [
            { id: "worker-light-1", kinds: ["import", "stats"], last_seen: "2026-11-06T00:00:00Z", healthy: true },
            { id: "worker-heavy-1", kinds: ["preannotate"], last_seen: null, healthy: false },
          ],
          disk: { path: "/data", total: 100 * 1024 ** 3, free: 40 * 1024 ** 3 },
          search_cache_bytes: 2048,
          data_bytes: 3 * 1024 ** 3,
          last_backup_at: null,
        };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=admin&admin=system");
    await screen.findByText("1.2.0");
    expect(screen.getByText("api.example.com · qwen-plus")).toBeTruthy();
    expect(screen.getByText("worker-light-1")).toBeTruthy();
    expect(screen.getByText("无响应")).toBeTruthy();
    expect(screen.getByText(/可用 40\.0 GB \/ 共 100\.0 GB/)).toBeTruthy();
    expect(screen.getByText("未找到")).toBeTruthy();
  });

  it("is hidden from non-admins", async () => {
    mockFetch(({ path }) => {
      if (path === "/api/auth/me") return owner;
      if (path === "/api/projects/p1") return { id: "p1", name: "P", role: "viewer", created_at: "" };
      if (path === "/api/projects/p1/members") return { items: [], total: 0 };
      if (path === "/api/me/deleted-projects") return { items: [], total: 0 };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=admin&admin=system");
    await screen.findByRole("tab", { name: /项目/ });
    await waitFor(() => expect(screen.queryByRole("tab", { name: /管理/ })).toBeNull());
    expect(screen.getByRole("tab", { name: /项目/ }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("settings · 账号 model usage", () => {
  it.each([
    [{ month: "2026-11", total_tokens: 1234, limit: null, by_source: [] }, "1,234 token / 上限 不限"],
    [{ month: "2026-11", total_tokens: 1234, limit: 100000, by_source: [] }, "1,234 token / 上限 100,000 token"],
  ])("shows the month's tokens against the limit", async (usage, text) => {
    mockFetch(({ path }) => {
      if (path === "/api/auth/me") return owner;
      if (path === "/api/me/llm-usage") return usage;
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=account");
    const el = await screen.findByTestId("llm-usage");
    expect(el.textContent?.replace(/\s+/g, " ").trim()).toBe(text);
  });
});

describe("settings · 项目 soft delete", () => {
  const routes = (role: string, deleted: unknown[]) => (c: Call) => {
    if (c.path === "/api/auth/me") return owner;
    if (c.path === "/api/projects/p1") return { id: "p1", name: "P", role, created_at: "" };
    if (c.path === "/api/projects/p1/members") return { items: [], total: 0 };
    if (c.path === "/api/projects/p1/usage") return { corpora: 1, layers: 0, notes: 0, kb_documents: 0, terms: 0, members: 1 };
    if (c.path === "/api/me/deleted-projects") return { items: deleted, total: deleted.length };
    if (c.path === "/api/projects/p1/audit")
      return { items: [{ id: 3, at: "2026-11-06T00:00:00Z", actor_id: "u2", actor_email: "li@x.edu", action: "member_add", target_type: "user", target_id: "u5", target_name: "zhao@x.edu", project_id: "p1", detail: {}, ip: "1.1.1.1" }], total: 1 };
    if (c.method === "POST") return {};
    throw new Error(`${c.method} ${c.path}`);
  };

  it("restores a recently deleted project and shows the project audit to owners", async () => {
    const calls = mockFetch(routes("owner", [{ id: "p7", name: "旧课题", deleted_at: "2026-11-05T00:00:00Z" }]));
    renderAt("/p/p1/settings");
    await screen.findByText("旧课题");
    await screen.findByText("添加成员");
    expect(screen.getByText("账号 · zhao@x.edu")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /恢复/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/projects/p7/restore")).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: /删除项目/ }));
    await screen.findByText("以下内容会一并删除，7 天内可由负责人或管理员恢复：");
  });

  it("hides 最近删除 when empty and the audit from non-owners", async () => {
    const calls = mockFetch(routes("editor", []));
    renderAt("/p/p1/settings");
    await screen.findByRole("region", { name: "角色权限" });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/me/deleted-projects")).toBe(true));
    expect(screen.queryByText("最近删除")).toBeNull();
    expect(calls.some((c) => c.path === "/api/projects/p1/audit")).toBe(false);
  });
});

describe("feedback", () => {
  it("sends the text with the route", async () => {
    const calls = mockFetch(({ method, path }) => {
      if (method === "POST" && path === "/api/feedback") return { id: 1 };
      throw new Error(`${method} ${path}`);
    });
    renderAt("/p/p1/search?q=x", <FeedbackButton />);
    fireEvent.click(screen.getByRole("button", { name: "反馈问题" }));
    const box = await screen.findByLabelText("反馈内容");
    fireEvent.change(box, { target: { value: "  导出按钮没反应  " } });
    fireEvent.click(screen.getByRole("button", { name: /提\s*交/ }));
    await screen.findByText("已收到");
    expect(calls.find((c) => c.path === "/api/feedback")?.body).toEqual({ text: "导出按钮没反应", page: "/p/p1/search?q=x", project_id: "p1" });
  });
});

describe("index pending and P9 error codes", () => {
  it("shows one line while the corpus index is pending", () => {
    const { rerender } = render(<IndexPendingNote corpus={{ index_pending: true }} />);
    expect(screen.getByText(INDEX_PENDING_TEXT)).toBeTruthy();
    expect(INDEX_PENDING_TEXT).toBe("索引更新中，完成前结果可能包含已删除或修改前的文档");
    rerender(<IndexPendingNote corpus={{ index_pending: false }} />);
    expect(screen.queryByText(INDEX_PENDING_TEXT)).toBeNull();
  });

  it("keeps the backend message for quota, run and language errors", () => {
    expect(new ApiError(429, "LLM_QUOTA_EXCEEDED", "本月模型用量已达上限（100000 token），请联系管理员").message).toBe("本月模型用量已达上限（100000 token），请联系管理员");
    expect(new ApiError(429, "TOO_MANY_RUNS", "已有 2 个对话在运行，请等待完成或停止后再试").message).toBe("已有 2 个对话在运行，请等待完成或停止后再试");
    expect(codeLabel("PURGED", "")).toBe("项目已超过恢复期限，无法恢复");
    expect(codeLabel("LANGUAGE_UNSUPPORTED", "暂只支持中文与英文语料")).toBe("暂只支持中文与英文语料");
    expect(codeLabel("EXPORT_EXPIRED", "")).toBe("导出文件已过期，请重新导出");
  });
});
