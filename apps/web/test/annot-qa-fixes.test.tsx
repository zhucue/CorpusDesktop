import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Span } from "../src/api";
import { anchors } from "../src/components/annot/SpanText";
import { MarkedText, valueText } from "../src/features/annotate/Agreement";
import { labelName, modelName, sourceText, uposOf } from "../src/features/annotate/model";
import { sortSpans, spanKeyCommand, stepSpan } from "../src/features/annotate/spanModel";

const span = (id: string, start_cp: number, end_cp: number): Span => ({
  id,
  start_cp,
  end_cp,
  text: "",
  label: "时态",
  attrs: null,
  source: "model:x",
  status: "suggested",
  model_label: "时态",
  revision: 0,
  annotator_id: null,
  updated_at: "",
});

describe("span traversal (Q53)", () => {
  // QA sentence 6: have visited (12–24), have (12–16), take (40–44), listed out of order
  const spans = [span("take", 40, 44), span("have", 12, 16), span("hv", 12, 24)];

  it("orders by start, the longer span first at the same start", () => {
    expect(sortSpans(spans).map((s) => s.id)).toEqual(["hv", "have", "take"]);
  });

  it("walks every span by position with → and ←, wrapping", () => {
    let cur: Span | null = null;
    const seen: string[] = [];
    for (let i = 0; i < 4; i++) {
      cur = stepSpan(spans, cur, 1);
      seen.push(cur!.id);
    }
    expect(seen).toEqual(["hv", "have", "take", "hv"]);
    expect(stepSpan(spans, null, -1)?.id).toBe("take");
    expect(stepSpan(spans, spans[2], -1)?.id).toBe("take"); // hv ← wraps to the last
  });

  it("continues from the start offset of a selection outside the list", () => {
    expect(stepSpan(spans, { id: "ctx", start_cp: 20 }, 1)?.id).toBe("take");
    expect(stepSpan(spans, { id: "ctx", start_cp: 20 }, -1)?.id).toBe("have");
  });

  it("Shift+Enter confirms the sentence", () => {
    expect(spanKeyCommand({ key: "Enter", shiftKey: true }, { labels: [], relations: false })).toEqual({ type: "confirmSentence" });
    expect(spanKeyCommand({ key: "Enter" }, { labels: [], relations: false })).toEqual({ type: "confirm" });
  });
});

describe("display details", () => {
  it("shows UPOS for jieba tags on dependency layers (Q48)", () => {
    expect(["v", "n", "uj", "w", "nr", "eng", "NOUN", null].map(uposOf)).toEqual(["VERB", "NOUN", "PART", "PUNCT", "PROPN", "X", "NOUN", null]);
  });

  it("keeps the origin of a confirmed suggestion (Q50) and names internal sources (Q54)", () => {
    expect(sourceText("human:u1", "deepseek-flash", { modelLabel: "时态", status: "confirmed" })).toBe("模型建议 · 人工确认");
    expect(sourceText("human:u1", "deepseek-flash", { modelLabel: "时态", status: "modified" })).toBe("模型建议 · 人工修改");
    expect(sourceText("human:u1", "deepseek-flash", { modelLabel: null, status: "confirmed" })).toBe("人工");
    expect(sourceText("system", "sentence_alignments")).toBe("导入句对齐");
    expect(modelName("sentence_alignments + deepseek-flash")).toBe("导入句对齐 + deepseek-flash");
    expect(labelName([{ id: "correction", name: "更正" }], "correction")).toBe("更正");
  });

  it("labels ∅ as 未标注 and marks the disputed words (Q55)", () => {
    expect(valueText("∅")).toBe("未标注");
    expect(valueText(null)).toBe("未标注");
    const { container } = render(<MarkedText text="We was happy ." marks={[[3, 6]]} />);
    expect(container.querySelector("mark")?.textContent).toBe("was");
    expect(container.textContent).toBe("We was happy .");
  });

  it("spreads arcs between nested spans (Q50)", () => {
    // book (720–768) inside three book (680–768): centres 20 px apart
    const book = { x: 744, left: 720, right: 768 };
    const three = { x: 724, left: 680, right: 768 };
    const [a, b] = anchors(book, three);
    expect(a - b).toBeGreaterThanOrEqual(60);
    const [c, d] = anchors(three, book);
    expect(d - c).toBeGreaterThanOrEqual(60);
    expect(anchors({ x: 100, left: 80, right: 120 }, { x: 300, left: 280, right: 320 })).toEqual([100, 300]);
  });
});
