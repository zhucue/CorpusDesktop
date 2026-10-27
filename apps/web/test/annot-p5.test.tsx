import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { Agreement, Layer, SentenceSpans } from "../src/api";
import { linkPairs } from "../src/components/annot/AlignGraph";
import { toggleLink, type LinkGroup } from "../src/components/annot/align";
import { SpanText } from "../src/components/annot/SpanText";
import { cpLength, cpToUtf16, normalizeSelection, rangeToCp, utf16ToCp } from "../src/components/annot/spans";
import { ResultContext } from "../src/components/results/cards";
import { AgreementView } from "../src/features/annotate/Agreement";
import SpanWorkspace from "../src/features/annotate/SpanWorkspace";
import UiBlock from "../src/openui/UiBlock";

/** Text node of the holder whose flow code point is `cp`. */
function holderText(root: Element, cp: number): Text {
  const el = root.querySelector(`[data-cp="${cp}"]`);
  if (!el?.firstChild) throw new Error(`no holder at ${cp}`);
  return el.firstChild as Text;
}

function select(start: [Node, number], end: [Node, number]): Range {
  const r = document.createRange();
  r.setStart(...start);
  r.setEnd(...end);
  return r;
}

describe("code points", () => {
  it("counts surrogate pairs as one code point and maps UTF-16 offsets", () => {
    const s = "我😀好";
    expect(s.length).toBe(4);
    expect(cpLength(s)).toBe(3);
    expect(utf16ToCp(s, 3)).toBe(2);
    expect(utf16ToCp(s, 2)).toBe(2); // inside the pair counts the whole pair
    expect(cpToUtf16(s, 2)).toBe(3);
  });

  it("widens a selection to keep combining marks and trims spaces", () => {
    const s = "Café au lait";
    // Selection ends between "e" and U+0301: the mark joins the span.
    expect(normalizeSelection(s, 0, 4)).toEqual({ start: 0, end: 5 });
    expect(normalizeSelection(s, 5, 9)).toEqual({ start: 6, end: 8 });
    expect(normalizeSelection(s, 5, 6)).toBeNull();
    expect(normalizeSelection("她为博物馆翻译了展板。", 4, 2)).toEqual({ start: 2, end: 4 });
  });

  it("maps a DOM selection across span segments to document code points (CJK)", () => {
    const text = "她为博物馆翻译了展板。";
    const { container } = render(
      <SpanText pieces={[{ key: "s", cp: 100, text }]} spans={[{ id: "a", start: 102, end: 105, label: "地点", status: "suggested", color: 1 }]} />,
    );
    const root = container.querySelector(".span-flow")!;
    // From after 她 (holder 100, offset 1) to after 博物 inside the span holder (102, offset 2).
    expect(rangeToCp(root, select([holderText(root, 100), 1], [holderText(root, 102), 2]))).toEqual({ start: 101, end: 104 });
    // Ending inside the label tag snaps to the next holder start.
    const tag = container.querySelector("[data-tag='a']")!;
    expect(rangeToCp(root, select([holderText(root, 102), 0], [tag.firstChild!, 1]))).toEqual({ start: 102, end: 105 });
    expect(container.querySelector(".sm.suggested")?.textContent).toBe("博物馆");
    expect(tag.textContent).toBe("地点");
  });

  it("maps selections after an emoji and a combining mark", () => {
    const text = "我😀好 café!";
    const { container } = render(<SpanText pieces={[{ key: "s", cp: 0, text }]} spans={[]} />);
    const root = container.querySelector(".span-flow")!;
    const node = holderText(root, 0);
    expect(rangeToCp(root, select([node, 3], [node, 4]))).toEqual({ start: 2, end: 3 }); // 好
    const at = text.indexOf("cafe");
    expect(rangeToCp(root, select([node, at], [node, at + 5]))).toEqual({ start: 4, end: 9 }); // café = 5 code points
  });
});

describe("alignment link toggle", () => {
  const G = (id: string, src: number[], tgt: number[], status: LinkGroup["status"] = "suggested"): LinkGroup => ({ id, src, tgt, status });

  it("adds a new 1:1 link, or joins a group with the same single source / target", () => {
    expect(toggleLink([], 1, 2).ops).toEqual([{ op: "create", src: [1], tgt: [2] }]);
    expect(toggleLink([G("a", [1], [2])], 1, 3).ops).toEqual([{ op: "modify", id: "a", src: [1], tgt: [2, 3] }]);
    expect(toggleLink([G("a", [1], [2])], 4, 2).ops).toEqual([{ op: "modify", id: "a", src: [1, 4], tgt: [2] }]);
    // A rejected group does not count.
    expect(toggleLink([G("a", [1], [2], "rejected")], 1, 2).ops).toEqual([{ op: "create", src: [1], tgt: [2] }]);
  });

  it("removes a link: rejects a 1:1 group, shrinks 1:n, splits n:m", () => {
    const one = toggleLink([G("a", [1], [2])], 1, 2);
    expect(one.ops).toEqual([{ op: "reject", id: "a" }]);
    expect(linkPairs(one.next.map((g) => ({ key: g.id, ...g })))).toEqual([]);
    expect(toggleLink([G("a", [1], [2, 3])], 1, 3).ops).toEqual([{ op: "modify", id: "a", src: [1], tgt: [2] }]);
    expect(toggleLink([G("a", [1, 2], [3])], 2, 3).ops).toEqual([{ op: "modify", id: "a", src: [1], tgt: [3] }]);
    const nm = toggleLink([G("a", [1, 2], [3, 4])], 1, 3);
    expect(nm.ops).toEqual([
      { op: "modify", id: "a", src: [2], tgt: [3, 4] },
      { op: "create", src: [1], tgt: [4] },
    ]);
    const pairs = linkPairs(nm.next.map((g) => ({ key: g.id, ...g }))).map((p) => `${p.a}-${p.b}`);
    expect(pairs.sort()).toEqual(["1-4", "2-3", "2-4"]);
  });
});

describe("agreement", () => {
  const FIX: Agreement = {
    annotators: [
      { user_id: "u1", email: "lin@example.edu", done: 50 },
      { user_id: "u2", email: "wang@example.edu", done: 48 },
      { user_id: "u3", email: "zhao@example.edu", done: 50 },
    ],
    pairwise: [
      { a: "u1", b: "u2", kappa: 0.82, n: 120 },
      { a: "u1", b: "u3", kappa: 0.355, n: 118 },
      { a: "u2", b: "u3", kappa: null, n: 0 },
    ],
    alpha: 0.71,
    per_label: [
      { label: "时态", kappa: 0.9 },
      { label: "冠词", kappa: 0.42 },
    ],
  };

  it("renders the pairwise κ matrix, α and per-label κ", () => {
    render(<AgreementView data={FIX} />);
    const table = screen.getByTestId("kappa-table");
    const cell = (a: string, b: string) => table.querySelector(`[data-pair="${a}:${b}"]`)!.textContent;
    expect(cell("u1", "u2")).toBe("0.82 · 120");
    expect(cell("u2", "u1")).toBe("0.82 · 120"); // symmetric
    expect(cell("u1", "u3")).toBe("0.35 · 118");
    expect(cell("u2", "u3")).toBe("— · 0");
    expect(table.querySelector("[data-pair='u1:u3']")!.className).toContain("k-low");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(screen.getByTestId("alpha").textContent).toBe("0.71");
    expect(screen.getByTestId("kappa-mean").textContent).toBe("0.59"); // mean of 0.82 and 0.355
    expect(screen.getByText("冠词")).toBeTruthy();
  });
});

function wrap(node: React.ReactNode, entry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <MemoryRouter initialEntries={[entry]}>
          <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>{node}</ResultContext.Provider>
        </MemoryRouter>
      </App>
    </QueryClientProvider>,
  );
}

describe("P5 OpenUI components", () => {
  it("renders SpanView from OpenUI Lang with spans, tags and a relation arc", async () => {
    const lang = [
      'root = SpanView("doc1", 2, "Yesterday I go to the library.", spans, relations)',
      'spans = [{start: 12, end: 14, label: "时态"}, {start: 22, end: 29, label: "冠词"}]',
      'relations = [{from: 0, to: 1, label: "cause"}]',
    ].join("\n");
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("片段标注")).toBeTruthy();
    const marks = [...document.querySelectorAll(".sm")].map((m) => m.textContent);
    expect(marks).toEqual(["go", "library"]);
    expect([...document.querySelectorAll(".stag")].map((t) => t.textContent)).toEqual(["时态", "冠词"]);
    expect(document.querySelector(".rel-svg text")?.textContent).toBe("cause");
    expect(screen.getByRole("link", { name: /在标注中打开/ }).getAttribute("href")).toBe("/p/p1/annotate?doc=doc1&s=2&kind=span");
  });

  it("renders AlignmentGraph from OpenUI Lang with a curve per token pair", async () => {
    const lang = [
      "root = AlignmentGraph(src, tgt, links)",
      'src = ["她", "翻译", "了", "展板"]',
      'tgt = ["She", "translated", "the", "panels"]',
      'links = [{src: [1], tgt: [1], status: "confirmed"}, {src: [2, 3], tgt: [2], status: "suggested"}, {src: [4], tgt: [3, 4]}]',
    ].join("\n");
    wrap(<UiBlock lang={lang} />);
    expect(await screen.findByText("词对齐")).toBeTruthy();
    const lines = [...document.querySelectorAll(".align-line")].map((p) => `${p.getAttribute("data-la")}-${p.getAttribute("data-lb")}${p.classList.contains("sugg") ? "s" : ""}`);
    expect(lines.sort()).toEqual(["1-1", "2-2s", "3-2s", "4-3", "4-4"]);
    expect(screen.getByText("1 组建议")).toBeTruthy();
  });
});

/* ---------- span workspace: select text, pick a label → POST span ---------- */

const SENT: SentenceSpans = {
  document_id: "d1",
  sentence_index: 0,
  text: "Yesterday I go to the library.",
  start_cp: 40,
  end_cp: 70,
  spans: [
    {
      id: "sp1",
      start_cp: 52,
      end_cp: 54,
      text: "go",
      label: "时态",
      attrs: {},
      source: "model:qwen",
      status: "suggested",
      model_label: "时态",
      revision: 0,
      annotator_id: null,
      updated_at: "",
    },
  ],
  relations: [],
};

const LAYER: Layer = {
  id: "L5",
  project_id: "p1",
  corpus_id: "c1",
  corpus_name: "学习者作文",
  kind: "span",
  name: "偏误",
  label_set_id: "ls-le",
  source_model: "qwen",
  status: "ready",
  job_id: null,
  progress: { total: 1, suggested: 1, confirmed: 0, modified: 0, rejected: 0 },
  documents: { total: 1, done: 0 },
  error: null,
  created_by: "u1",
  created_at: "",
  updated_at: "",
  mode: "single",
};

describe("span workspace", () => {
  it("creates a span from a text selection and confirms a suggestion with Enter", async () => {
    const calls: { method: string; path: string; body: unknown }[] = [];
    const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, path: url.pathname, body });
      const p = url.pathname;
      if (p === "/api/auth/me") return json({ id: "u1", email: "a@b", display_name: "A", is_admin: false });
      if (p === "/api/label-sets")
        return json({ items: [{ id: "ls-le", project_id: null, name: "learner-errors", kind: "span", language: null, labels: [{ id: "1", name: "时态" }, { id: "2", name: "冠词" }], created_at: "" }] });
      if (p === "/api/layers/L5/documents") return json({ items: [{ document_id: "d1", title: "作文 1", sentences: 1, done: 0, pending: 1 }] });
      if (p === "/api/layers/L5/spans" && method === "GET") return json({ items: [SENT], next_cursor: null });
      if (p === "/api/layers/L5/spans" && method === "POST") return json({ ...SENT.spans[0], id: "sp2", ...body, text: "library", source: "human", status: "confirmed" });
      if (p === "/api/layers/L5/spans/sp1" && method === "PATCH") return json({ ...SENT.spans[0], status: "confirmed", revision: 1 });
      return new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: `unexpected ${method} ${p}` } }), { status: 404 });
    });
    wrap(<SpanWorkspace layer={LAYER} layers={[LAYER]} projectId="p1" canAnnotate canManage />, "/p/p1/annotate?layer=L5");
    await waitFor(() => expect(document.querySelector(".sm")?.textContent).toBe("go"));

    // Select "library" (sentence cps 22–29 → document 62–69) with a trailing space-free range, then press 2.
    const root = document.querySelector(".span-flow")!;
    const tail = holderText(root, 54); // text after the "go" span
    const from = tail.data.indexOf("library");
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(select([tail, from], [tail, from + 7]));
    fireEvent.mouseUp(root);
    await waitFor(() => expect(document.querySelector(".sm.pend")?.textContent).toBe("library"));
    fireEvent.keyDown(document.body, { key: "2" });
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")).toEqual({ method: "POST", path: "/api/layers/L5/spans", body: { document_id: "d1", start_cp: 62, end_cp: 69, label: "冠词" } });
    await waitFor(() => expect([...document.querySelectorAll(".stag")].map((t) => t.textContent)).toEqual(["时态", "冠词"]));

    // Select the suggestion and confirm it.
    fireEvent.click(document.querySelector("[data-tag='sp1']")!);
    fireEvent.keyDown(document.body, { key: "Enter" });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")).toEqual({ method: "PATCH", path: "/api/layers/L5/spans/sp1", body: { action: "confirm" } });
  });
});
