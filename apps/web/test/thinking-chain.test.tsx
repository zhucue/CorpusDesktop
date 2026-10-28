import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { ToolCall } from "../src/api";
import { applyEvent, fmtChars, fromMessage, markStopped, newChain, type ChainMessage } from "../src/features/assistant/chain";
import { AiMessage, chainLabel } from "../src/features/assistant/ChainView";
import type { SseEvent } from "../src/features/assistant/sse";

const call: ToolCall = { id: "t1", name: "corpus.search", args: { query: "翻译/v +文化" }, state: "running", result_summary: "", duration_ms: 0 };
const ev = (event: string, data: unknown): SseEvent => ({ event, data: JSON.stringify(data) });

const script: SseEvent[] = [
  ev("start", { message_id: "m1" }),
  ev("thinking", { delta: "先检索命中规模。", part: 0 }),
  ev("tool_call", call),
  ev("tool_result", { ...call, state: "succeeded", result_summary: "1,284 条命中", duration_ms: 1500, result_ref: { kind: "search", id: "s1" } }),
  ev("text", { delta: "共 1,284 条", part: 1 }),
  ev("text", { delta: "命中 [1]。", part: 1 }),
  ev("done", {
    message: {
      id: "m1",
      role: "assistant",
      content: "共 1,284 条命中 [1]。",
      parts: [
        { type: "thinking", text: "先检索命中规模。" },
        { type: "text", text: "共 1,284 条命中 [1]。" },
      ],
      tool_calls: [{ ...call, state: "succeeded", result_summary: "1,284 条命中", duration_ms: 1500 }],
      created_at: "2026-10-27T00:00:00Z",
      duration_ms: 4200,
    },
  }),
];

let push: (e: SseEvent, t: number) => void = () => {};
let stop: () => void = () => {};
function Harness() {
  const [m, setM] = useState<ChainMessage>(() => newChain(0));
  push = (e, t) => setM((x) => applyEvent(x, e, t));
  stop = () => setM((x) => markStopped(x, 9000));
  return <AiMessage m={m} />;
}

const label = () => document.querySelector(".think-label")?.textContent;
const open = () => document.querySelector(".think")?.getAttribute("data-open");
const head = () => document.querySelector<HTMLButtonElement>(".think-head")!;

describe("thinking chain", () => {
  it("thinks in one line with a peek, then collapses to the trace line when the answer starts", () => {
    render(<Harness />);
    expect(label()).toBe("思考中");
    expect(document.querySelector(".think .dots")).toBeTruthy();
    expect(open()).toBe("false");
    expect(head().getAttribute("aria-expanded")).toBe("false");

    act(() => push(script[0], 100));
    act(() => push(script[1], 200));
    act(() => push(script[2], 300));
    expect(label()).toBe("思考中");
    expect(document.querySelector(".think-tool")?.textContent).toBe("正在检索语料…");
    // Peek: ticker + only the current tool row; the full timeline is not rendered.
    expect(document.querySelector(".think-peek .think-ticker")).toBeTruthy();
    const step = document.querySelector(".think-peek .step")!;
    expect(step.className).toContain("active");
    expect(step.querySelector(".step-title")?.textContent).toBe("检索语料");
    expect(step.querySelector(".step-key")?.textContent).toBe('"翻译/v +文化"');
    expect(step.querySelector(".step-res")?.textContent).toBe("运行中");
    expect(document.querySelector(".think-scroll")).toBeNull();

    act(() => push(script[3], 1800));
    expect(document.querySelector(".step")!.className).toContain("done");
    expect(screen.getByText("1,284 条命中")).toBeTruthy();

    act(() => push(script[4], 2500));
    expect(open()).toBe("false");
    expect(document.querySelector(".think-peek")).toBeNull();
    expect(label()).toBe("已思考 2.5 秒 · 1 次工具调用 · 8 字");
    expect(document.querySelector(".caret")).toBeTruthy();

    act(() => push(script[5], 2600));
    act(() => push(script[6], 4200));
    expect(document.querySelector(".caret")).toBeNull();
    expect(document.querySelector(".answer")?.textContent).toBe("共 1,284 条命中 1。");
    expect(document.querySelector(".cite")?.textContent).toBe("1");
    expect(label()).toBe("已思考 2.5 秒 · 1 次工具调用 · 8 字");
    expect(screen.getByRole("button", { name: /复制/ })).toBeTruthy();

    // Trace line expands to the full reasoning and timeline, and folds back.
    act(() => head().click());
    expect(open()).toBe("true");
    expect(head().getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector(".think-scroll .think-text")?.textContent).toBe("先检索命中规模。");
    expect(document.querySelector(".think-scroll .step-tool")?.textContent).toBe("corpus.search");
    expect(document.querySelector(".think-scroll .step-args b")?.textContent).toBe('"翻译/v +文化"');
    act(() => head().click());
    expect(open()).toBe("false");
  });

  it("keeps a manual expand when the answer starts", () => {
    render(<Harness />);
    act(() => push(script[0], 100));
    act(() => push(script[1], 200));
    act(() => push(script[2], 300));
    act(() => head().click());
    expect(open()).toBe("true");
    expect(document.querySelector(".think-peek")).toBeNull();
    expect(document.querySelectorAll(".think-scroll .step").length).toBe(1);
    act(() => push(script[3], 1800));
    act(() => push(script[4], 2500));
    expect(open()).toBe("true");
    expect(label()).toBe("已思考 2.5 秒 · 1 次工具调用 · 8 字");
  });

  it("labels elapsed seconds and reasoning length while thinking", () => {
    let m = newChain(0);
    m = applyEvent(m, ev("thinking", { delta: "先检索命中规模。", part: 0 }), 100);
    expect(chainLabel(m, 3240)).toEqual({ text: "思考中", live: true, meta: "3.2 秒 · 8 字", tool: null });
    m = applyEvent(m, ev("tool_call", call), 300);
    expect(chainLabel(m, 4000).tool).toBe("正在检索语料…");
    expect(fmtChars(860)).toBe("860 字");
    expect(fmtChars(1234)).toBe("1.2k 字");
    expect(fmtChars(2000)).toBe("2k 字");
  });

  it("renders a stored message as the collapsed trace line", () => {
    const done = JSON.parse(script[6].data).message;
    render(<AiMessage m={fromMessage(done)} />);
    expect(open()).toBe("false");
    expect(label()).toBe("已思考 4.2 秒 · 1 次工具调用 · 8 字");
    expect(document.querySelector(".think-peek")).toBeNull();
  });

  it("marks running steps cancelled when stopped", () => {
    render(<Harness />);
    act(() => push(script[0], 100));
    act(() => push(script[2], 300));
    act(() => stop());
    expect(label()).toBe("已停止 · 1 次工具调用");
    act(() => head().click());
    const step = document.querySelector(".think-scroll .step")!;
    expect(step.className).toContain("failed");
    expect(step.querySelector(".step-res")?.textContent).toBe("已取消");
  });

  it("shows the error code from an error event", () => {
    render(<Harness />);
    act(() => push(script[0], 100));
    act(() => push(script[2], 300));
    act(() => push(ev("error", { code: "MODEL_TIMEOUT", message: "模型响应超时" }), 900));
    expect(label()).toBe("出错 · 1 次工具调用");
    expect(screen.getByText("MODEL_TIMEOUT")).toBeTruthy();
    act(() => head().click());
    expect(document.querySelector(".step")!.className).toContain("failed");
  });
});
