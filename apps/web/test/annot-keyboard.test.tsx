import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Annotation, Layer, SentenceAnnot } from "../src/api";
import { keyCommand, keyHint, labelForKey } from "../src/features/annotate/model";
import Workspace from "../src/features/annotate/Workspace";

const LABELS = ["NOUN", "VERB", "PRON", "ADJ", "ADV", "ADP", "AUX", "DET", "NUM", "PUNCT", "X"].map((n) => ({ id: n, name: n }));

function sentence(idx: number, toks: [string, string][]): SentenceAnnot {
  return {
    document_id: "d1",
    sentence_index: idx,
    text: toks.map((t) => t[0]).join(""),
    status: "pending",
    tokens: toks.map(([form, pos], i) => ({ index: i + 1, form, start_cp: 0, end_cp: 0, system: { pos, head: null, deprel: null } })),
    annotations: toks.map(([, pos], i) => ({
      id: `a${idx}-${i + 1}`,
      token_index: i + 1,
      label: pos,
      head: null,
      model_label: pos,
      model_head: null,
      source: "system",
      status: "suggested",
      revision: 0,
      updated_by: null,
      updated_at: "2026-10-27T00:00:00Z",
    })),
  };
}

const S0 = sentence(0, [
  ["她", "PRON"],
  ["翻译", "VERB"],
  ["展板", "NOUN"],
]);
const S1 = sentence(1, [["好", "ADJ"]]);

const LAYER: Layer = {
  id: "L1",
  project_id: "p1",
  corpus_id: "c1",
  corpus_name: "UD 中文",
  kind: "pos",
  name: "词性",
  label_set_id: "ls1",
  source_model: "jieba 0.42",
  status: "ready",
  job_id: null,
  progress: { total: 4, suggested: 4, confirmed: 0, modified: 0, rejected: 0 },
  documents: { total: 1, done: 0 },
  error: null,
  created_by: "u1",
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
};

type Call = { method: string; path: string; body: unknown };

function mockApi() {
  const calls: Call[] = [];
  const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, body });
    const p = url.pathname;
    if (p === "/api/label-sets") return json({ items: [{ id: "ls1", project_id: null, name: "upos", kind: "pos", language: null, labels: LABELS, created_at: "" }], total: 1 });
    if (p === "/api/layers/L1/documents") return json({ items: [{ document_id: "d1", title: "样本", sentences: 2, done: 0, pending: 2 }], total: 1 });
    if (p === "/api/layers/L1/sentences") return json({ items: [S0, S1], next_cursor: null });
    if (p === "/api/layers/L1/annotations" && method === "POST") {
      const b = body as { token_index: number; action: string; label?: string };
      const a: Annotation = {
        ...S0.annotations[0],
        id: `srv-${b.token_index}`,
        token_index: b.token_index,
        label: b.label ?? null,
        status: b.action === "confirm" ? "confirmed" : b.action === "reject" ? "rejected" : "modified",
        revision: 1,
      };
      if (b.action === "confirm") a.label = null;
      return json(a);
    }
    const m = p.match(/^\/api\/layers\/L1\/sentences\/d1\/(\d+)\/confirm$/);
    if (m && method === "POST") {
      const s = Number(m[1]) === 0 ? S0 : S1;
      return json({ ...s, status: "done", annotations: s.annotations.map((x) => ({ ...x, status: "confirmed" })) });
    }
    return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
  });
  return calls;
}

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={["/p/p1/annotate?layer=L1"]}>
          <Workspace layer={LAYER} projectId="p1" canAnnotate />
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const key = (k: string, extra: Partial<KeyboardEventInit> = {}) => fireEvent.keyDown(document.body, { key: k, ...extra });

describe("annotation keyboard reducer", () => {
  it("maps keys to commands", () => {
    const ctx = { kind: "pos" as const, labels: LABELS };
    expect(keyCommand({ key: "Enter" }, ctx)).toEqual({ type: "confirm" });
    expect(keyCommand({ key: "Enter", shiftKey: true }, ctx)).toEqual({ type: "confirmSentence" });
    expect(keyCommand({ key: "Delete" }, ctx)).toEqual({ type: "reject" });
    expect(keyCommand({ key: "Delete" }, { ...ctx, kind: "dep" })).toBeNull();
    expect(keyCommand({ key: "j" }, ctx)).toEqual({ type: "sentence", delta: 1 });
    expect(keyCommand({ key: "K" }, ctx)).toEqual({ type: "sentence", delta: -1 });
    expect(keyCommand({ key: "ArrowRight" }, ctx)).toEqual({ type: "token", delta: 1 });
    expect(keyCommand({ key: "3" }, ctx)).toEqual({ type: "label", label: "PRON" });
    expect(keyCommand({ key: "a" }, ctx)).toEqual({ type: "label", label: "PUNCT" }); // 10th label
    expect(keyCommand({ key: "k", ctrlKey: true }, ctx)).toBeNull();
    expect(keyHint(0)).toBe("1");
    expect(keyHint(9)).toBe("A");
    expect(labelForKey("e", LABELS)).toBeNull(); // E is 修改
  });

  it("drives the API from the keyboard: Enter, Del, number keys, J/K, Shift+Enter", async () => {
    const calls = mockApi();
    renderWorkspace();
    await screen.findByText("翻译");
    await waitFor(() => expect(document.querySelector(".tk.sel")?.textContent).toContain("她"));

    key("Enter");
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]).toEqual({
      method: "POST",
      path: "/api/layers/L1/annotations",
      body: { document_id: "d1", sentence_index: 0, token_index: 1, action: "confirm" },
    });
    // Optimistic chip state, then the cursor moves to the next pending token.
    expect(document.querySelector('.tk[data-index="1"] .pchip')?.className).toContain("confirmed");
    await waitFor(() => expect(document.querySelector(".tk.sel")?.getAttribute("data-index")).toBe("2"));

    key("Delete");
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(posts(calls)[1].body).toEqual({ document_id: "d1", sentence_index: 0, token_index: 2, action: "reject" });
    await waitFor(() => expect(document.querySelector(".tk.sel")?.getAttribute("data-index")).toBe("3"));

    key("2"); // VERB for 展板 (NOUN) → modify
    await waitFor(() => expect(posts(calls)).toHaveLength(3));
    expect(posts(calls)[2].body).toEqual({ document_id: "d1", sentence_index: 0, token_index: 3, action: "modify", label: "VERB" });

    key("j");
    await waitFor(() => expect(document.querySelector(".sent.on .n")?.textContent).toBe("1"));
    await waitFor(() => expect(document.querySelector(".tokrow")?.textContent).toContain("好"));
    key("Enter");
    await waitFor(() => expect(posts(calls)).toHaveLength(4));
    expect(posts(calls)[3].body).toEqual({ document_id: "d1", sentence_index: 1, token_index: 1, action: "confirm" });

    key("k");
    await waitFor(() => expect(document.querySelector(".sent.on .n")?.textContent).toBe("0"));
    key("Enter", { shiftKey: true });
    await waitFor(() => expect(posts(calls)).toHaveLength(5));
    expect(posts(calls)[4].path).toBe("/api/layers/L1/sentences/d1/0/confirm");
  });

  it("rolls back and shows the API error when an action fails", async () => {
    const calls = mockApi();
    const original = globalThis.fetch as unknown as (i: RequestInfo | URL, n?: RequestInit) => Promise<Response>;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).includes("/annotations")) {
        calls.push({ method: "POST", path: "/api/layers/L1/annotations", body: null });
        return new Response(JSON.stringify({ error: { code: "FORBIDDEN", message: "查看者不能标注" } }), { status: 403 });
      }
      return original(input, init);
    });
    renderWorkspace();
    await screen.findByText("翻译");
    key("Enter");
    expect(await screen.findByText("查看者不能标注")).toBeTruthy();
    await waitFor(() => expect(document.querySelector('.tk[data-index="1"] .pchip')?.className).toContain("suggested"));
  });
});
