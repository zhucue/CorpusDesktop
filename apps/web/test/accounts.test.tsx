import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it, vi } from "vitest";
import Login from "../src/features/auth/Login";
import { safeNext } from "../src/features/auth/next";
import Settings from "../src/features/settings/Settings";

// antd tables and modals render slowly under a loaded full run: wait longer than the 1 s / 5 s defaults
configure({ asyncUtilTimeout: 8000 });
vi.setConfig({ testTimeout: 20000 });

vi.mock("../src/components/shell/AppShell", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });

function mockFetch(handle: (path: string, method: string, body: unknown) => unknown) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url.pathname}`);
    return json(handle(url.pathname, method, init?.body ? JSON.parse(String(init.body)) : undefined));
  });
  return calls;
}

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderAt(path: string, routes: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[path]}>
          <Routes>{routes}</Routes>
          <Where />
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

const admin = { id: "u1", email: "root@x.edu", display_name: "Root", is_admin: true, must_change_password: false };
const student = {
  id: "u2",
  email: "li@x.edu",
  display_name: "李",
  is_admin: false,
  disabled_at: null,
  last_login_at: null,
  created_at: "2026-11-01T00:00:00Z",
  projects: 2,
};

describe("login with a temporary password", () => {
  it("goes to the change-password page", async () => {
    mockFetch((path) => {
      if (path === "/api/auth/login") return { ...admin, must_change_password: true };
      throw new Error(path);
    });
    renderAt("/login?next=%2Fp%2Fp1%2Fsearch", <Route path="/login" element={<Login />} />);
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "root@x.edu" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "temporary-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/password?next=%2Fp%2Fp1%2Fsearch"));
  });

  it("ignores a next that leaves the site", async () => {
    mockFetch((path) => {
      if (path === "/api/auth/login") return admin;
      throw new Error(path);
    });
    renderAt("/login?next=%2F%2Fevil.example%2Fx", <Route path="/login" element={<Login />} />);
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "root@x.edu" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/"));
  });
});

describe("safeNext", () => {
  it("keeps same-site paths only", () => {
    expect(safeNext("/p/p1/search?q=a")).toBe("/p/p1/search?q=a");
    for (const bad of [null, "", "//evil.example", "/\\evil.example", "https://evil.example", "/login", "/password?next=/"]) expect(safeNext(bad)).toBe("/");
  });
});

describe("settings users tab", () => {
  it("lists accounts, creates one and shows its temporary password once", async () => {
    const calls = mockFetch((path, method, body) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/admin/users" && method === "GET") return { items: [student], total: 1 };
      if (path === "/api/admin/users" && method === "POST") {
        expect(body).toEqual({ email: "new@x.edu", display_name: "新同学", is_admin: false });
        return { user: { ...student, id: "u3", email: "new@x.edu", projects: 0 }, temporary_password: "Abcdefghjkmnpqrs" };
      }
      throw new Error(`${method} ${path}`);
    });
    renderAt("/p/p1/settings?tab=users", <Route path="/p/:projectId/settings" element={<Settings />} />);
    await screen.findByText("li@x.edu");
    expect(screen.getByText("从未")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /数据与隐私/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /新建/ }));
    fireEvent.change(await screen.findByLabelText("邮箱"), { target: { value: "new@x.edu" } });
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "新同学" } });
    fireEvent.click(screen.getByRole("button", { name: /创\s*建/ }));
    await screen.findByText("Abcdefghjkmnpqrs");
    expect(calls).toContain("POST /api/admin/users");
  });

  it("is hidden from non-admins", async () => {
    mockFetch((path) => {
      if (path === "/api/auth/me") return { ...admin, is_admin: false };
      if (path === "/api/projects/p1") return { id: "p1", name: "P", role: "viewer", created_at: "" };
      if (path === "/api/projects/p1/members") return { items: [], total: 0 };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=users", <Route path="/p/:projectId/settings" element={<Settings />} />);
    await screen.findByRole("tab", { name: /项目/ });
    await waitFor(() => expect(screen.queryByRole("tab", { name: /用户/ })).toBeNull());
    expect(screen.getByRole("tab", { name: /项目/ }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("data and privacy", () => {
  it("names the model host from /system/info", async () => {
    mockFetch((path) => {
      if (path === "/api/auth/me") return admin;
      if (path === "/api/system/info")
        return {
          version: "1.0.0",
          model: { configured: true, host: "api.example.com", model_id: "qwen-plus" },
          embed: { mode: "local", host: null, model: "minilm", ready: true },
        };
      throw new Error(path);
    });
    renderAt("/p/p1/settings?tab=privacy", <Route path="/p/:projectId/settings" element={<Settings />} />);
    await screen.findByText("api.example.com");
    expect(screen.getByText("版本 1.0.0")).toBeTruthy();
    expect(screen.getByText("本机模型处理，不外发")).toBeTruthy();
    expect(screen.getByText(/全局任务、模型用量、审计记录与反馈；不通过界面读取他人项目内的语料、标注与知识库内容/)).toBeTruthy();
  });
});

describe("adding a member", () => {
  it("trims and lower-cases the email before the lookup", async () => {
    const lookups: string[] = [];
    const calls = mockFetch((path, method) => {
      if (path === "/api/auth/me") return { ...admin, is_admin: false };
      if (path === "/api/projects/p1") return { id: "p1", name: "P", role: "owner", created_at: "" };
      if (path === "/api/projects/p1/members" && method === "GET") return { items: [], total: 0 };
      if (path === "/api/projects/deleted") return { items: [], total: 0 };
      if (path === "/api/users") return { items: [{ id: "u9", email: "sol-viewer@example.edu", display_name: "V" }] };
      if (path === "/api/projects/p1/members/u9" && method === "PUT") return { user_id: "u9", email: "sol-viewer@example.edu", role: "viewer" };
      return { items: [], total: 0 };
    });
    const fetchSpy = vi.mocked(globalThis.fetch);
    renderAt("/p/p1/settings?tab=project", <Route path="/p/:projectId/settings" element={<Settings />} />);
    fireEvent.change(await screen.findByPlaceholderText("邮箱"), { target: { value: "  SOL-VIEWER@Example.edu  " } });
    fireEvent.click(screen.getByRole("button", { name: /添加/ }));
    await waitFor(() => expect(calls).toContain("PUT /api/projects/p1/members/u9"));
    for (const [input] of fetchSpy.mock.calls) {
      const url = new URL(String(input), "http://x");
      if (url.pathname === "/api/users") lookups.push(url.searchParams.get("email") ?? "");
    }
    expect(lookups).toEqual(["sol-viewer@example.edu"]);
    expect(screen.queryByText("请输入邮箱")).toBeNull();
  });
});

describe("login errors", () => {
  it("shows the Chinese message without the error code", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ error: { code: "LOGIN_RATE_LIMITED", message: "登录尝试过多，请 1 分钟后再试" } }), {
          status: 429,
          headers: { "Content-Type": "application/json" },
        }),
    );
    renderAt("/login", <Route path="/login" element={<Login />} />);
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "root@x.edu" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "wrong-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await screen.findByText("登录尝试过多，请 1 分钟后再试");
    expect(screen.queryByText("LOGIN_RATE_LIMITED")).toBeNull();
  });
});
