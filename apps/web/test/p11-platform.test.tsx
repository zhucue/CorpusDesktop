import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, fireEvent, render, screen } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { METRIC_GROUPS } from "../src/features/help/content";
import Help from "../src/features/help/Help";
import { postForm, sourceBody } from "../src/features/corpora/UploadDialog";

configure({ asyncUtilTimeout: 8000 });
vi.setConfig({ testTimeout: 20000 });

vi.mock("../src/components/shell/AppShell", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });

function Where() {
  const loc = useLocation();
  return <output data-testid="where">{loc.pathname + loc.search}</output>;
}

function renderHelp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={["/p/p1/help"]}>
          <Routes>
            <Route path="/p/:projectId/help" element={<Help />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("help page", () => {
  it("lists every section, shows metrics from the api and opens an example on the search page", async () => {
    const metric = (key: string) => ({ key, name: key.toUpperCase(), formula: `${key} = …`, references: [{ key: `r-${key}`, label: `Ref ${key}`, text: `REF ${key}.` }] });
    const keys = [...new Set(METRIC_GROUPS.flatMap((g) => g.keys))];
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ style: "gbt7714", items: keys.map(metric) }));
    renderHelp();
    for (const name of ["查询语法", "导入格式", "统计指标", "角色与权限", "数据与隐私", "常见错误"]) expect(screen.getByRole("heading", { name })).toBeTruthy();
    expect(await screen.findByText("dp = …")).toBeTruthy();
    expect(screen.getByText("REF dp.")).toBeTruthy();
    expect(String(fetch.mock.calls[0][0])).toBe("/api/help/metrics?style=gbt7714");
    fireEvent.click(screen.getByRole("button", { name: "检索 语言/n" }));
    expect(screen.getByTestId("where").textContent).toBe("/p/p1/search?q=%E8%AF%AD%E8%A8%80%2Fn");
  });
});

describe("upload", () => {
  it("source body: only when changed, empty fields remove", () => {
    expect(sourceBody({ license: "CC BY", attribution: "", source_url: "" }, { license: "CC BY" })).toBeUndefined();
    expect(sourceBody({ license: " CC0 " }, { license: "CC BY", attribution: "A" })).toEqual({ license: "CC0", attribution: "", source_url: "" });
  });

  it("postForm reports upload progress and can be cancelled", async () => {
    const sent: XMLHttpRequest[] = [];
    class FakeXhr {
      upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
      status = 0;
      statusText = "";
      responseText = "";
      withCredentials = false;
      onload?: () => void;
      onerror?: () => void;
      onabort?: () => void;
      url = "";
      open(_: string, url: string) {
        this.url = url;
      }
      send() {
        sent.push(this as unknown as XMLHttpRequest);
      }
      abort() {
        this.onabort?.();
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const seen: number[] = [];
    const done = postForm<{ id: string }>("/corpora/c1/documents", new FormData(), { onProgress: (l, t) => seen.push(l / t) });
    const xhr = sent[0] as unknown as FakeXhr;
    expect(xhr.url).toBe("/api/corpora/c1/documents");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 100 });
    xhr.status = 200;
    xhr.responseText = '{"id":"j1"}';
    xhr.onload?.();
    await expect(done).resolves.toEqual({ id: "j1" });
    expect(seen).toEqual([0.5]);

    const ctrl = new AbortController();
    const cancelled = postForm("/x", new FormData(), { signal: ctrl.signal });
    ctrl.abort();
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });

    const failing = postForm("/x", new FormData());
    const bad = sent[2] as unknown as FakeXhr;
    bad.status = 413;
    bad.responseText = '{"error":{"code":"TOO_LARGE","message":"单次上传不超过 500 MB"}}';
    bad.onload?.();
    await expect(failing).rejects.toMatchObject({ code: "TOO_LARGE", status: 413 });
    vi.unstubAllGlobals();
  });
});
