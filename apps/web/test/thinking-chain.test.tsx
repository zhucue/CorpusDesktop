import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { ToolCall } from "../src/api";
import { applyEvent, markStopped, newChain, type ChainMessage } from "../src/features/assistant/chain";
import { AiMessage } from "../src/features/assistant/ChainView";
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

describe("thinking chain", () => {
  it("runs shimmer → tool timeline → collapsed summary → answer", () => {
    render(<Harness />);
    expect(label()).toBe("正在思考…");
    expect(document.querySelector(".think-label")?.classList.contains("shimmer-text")).toBe(true);

    act(() => push(script[0], 100));
    act(() => push(script[1], 200));
    act(() => push(script[2], 300));
    expect(label()).toBe("正在检索语料…");
    expect(open()).toBe("true");
    const step = document.querySelector(".step")!;
    expect(step.className).toContain("active");
    expect(step.querySelector(".step-tool")?.textContent).toBe("corpus.search");
    expect(step.querySelector(".step-res")?.textContent).toBe("运行中");
    expect(step.querySelector(".step-args b")?.textContent).toBe('"翻译/v +文化"');

    act(() => push(script[3], 1800));
    expect(document.querySelector(".step")!.className).toContain("done");
    expect(screen.getByText("1,284 条命中")).toBeTruthy();

    act(() => push(script[4], 2500));
    expect(open()).toBe("false");
    expect(label()).toBe("已思考 2.5 秒 · 1 次工具调用");
    expect(document.querySelector(".caret")).toBeTruthy();

    act(() => push(script[5], 2600));
    act(() => push(script[6], 4200));
    expect(document.querySelector(".caret")).toBeNull();
    expect(document.querySelector(".answer")?.textContent).toBe("共 1,284 条命中 1。");
    expect(document.querySelector(".cite")?.textContent).toBe("1");
    expect(label()).toBe("已思考 2.5 秒 · 1 次工具调用");
    expect(screen.getByRole("button", { name: /复制/ })).toBeTruthy();
  });

  it("marks running steps cancelled when stopped", () => {
    render(<Harness />);
    act(() => push(script[0], 100));
    act(() => push(script[2], 300));
    act(() => stop());
    expect(label()).toBe("已停止 · 1 次工具调用");
    const step = document.querySelector(".step")!;
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
    expect(document.querySelector(".step")!.className).toContain("failed");
  });
});
