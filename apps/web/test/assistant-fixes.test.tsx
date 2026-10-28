import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import type { AgentMessage, ToolCall } from "../src/api";
import { ResultContext } from "../src/components/results/cards";
import { fromMessage, scrubIds, type ChainMessage } from "../src/features/assistant/chain";
import { AiMessage } from "../src/features/assistant/ChainView";
import { Markdown } from "../src/features/assistant/Markdown";
import { ToolList } from "../src/features/assistant/ToolList";
import UiBlock from "../src/openui/UiBlock";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ResultContext.Provider value={{ projectId: "p1", scope: { corpus_id: "c1" } }}>{node}</ResultContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const stored = (over: Partial<AgentMessage>): ChainMessage =>
  fromMessage({ id: "m1", role: "assistant", content: "", parts: [], tool_calls: [], created_at: "2026-10-28T00:00:00Z", duration_ms: 3200, ...over });

const proposal: ToolCall = {
  id: "t1",
  name: "annot.create_layer",
  args: { corpus_id: "c1", kind: "pos", name: "词性" },
  state: "needs_confirmation",
  result_summary: "等待确认",
  duration_ms: 3,
  confirm: { title: "新建词性标注层「词性」并预标", lines: ["语料库：导入验收", "文档：1 篇"] },
};

describe("internal IDs", () => {
  it("drops id pairs, UUIDs and hex ids from prose and leaves ordinary text alone", () => {
    expect(scrubIds("统计已完成（stat_id `4e543dce-52ab-4752-b730-3a857788dbea`）：节点为“翻译”")).toBe("统计已完成：节点为“翻译”");
    expect(scrubIds("检索完成，search_id: d855d9a4a1780d91。共 46 次")).toBe("检索完成。共 46 次");
    expect(scrubIds("文档 d707a3b0-1111-4111-8111-111111111111:10-12 里")).toBe("文档 里");
    expect(scrubIds("共 1,284 条命中 [1]，logDice 10.61，2020 年")).toBe("共 1,284 条命中 [1]，logDice 10.61，2020 年");
  });
});

describe("answer Markdown", () => {
  it("renders tables, headings, lists and bold instead of pipes and markers", () => {
    render(<Markdown text={"## 结果\n\n| 语料库 | 语言 | 规模 |\n|---|---|---:|\n| 维基百科中文 | zh | 1,000 篇 |\n\n- **第一** 项\n- 第二项"} />);
    expect(document.querySelector("h3.md-h")?.textContent).toBe("结果");
    const cells = [...document.querySelectorAll(".md-table th")].map((th) => th.textContent);
    expect(cells).toEqual(["语料库", "语言", "规模"]);
    expect(document.querySelector(".md-table td")?.textContent).toBe("维基百科中文");
    expect(document.body.textContent).not.toContain("|");
    expect(document.querySelectorAll(".md-list li")).toHaveLength(2);
    expect(document.querySelector(".md-list strong")?.textContent).toBe("第一");
  });
});

describe("confirm card", () => {
  it("shows the proposal with 执行 / 取消 on the latest message and sends the answer", async () => {
    const onConfirm = vi.fn(async () => {});
    wrap(<AiMessage m={stored({ tool_calls: [proposal], parts: [{ type: "text", text: "将新建词性层，请确认。" }] })} onConfirm={onConfirm} />);
    expect(screen.getByText("新建词性标注层「词性」并预标")).toBeTruthy();
    expect(screen.getByText("文档：1 篇")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    });
    expect(onConfirm).toHaveBeenCalledWith(["t1"], "execute");
    expect(screen.getByRole("button", { name: "取消" })).toBeTruthy();
  });

  it("older or answered cards show what happened instead of buttons", () => {
    const { unmount } = wrap(<AiMessage m={stored({ tool_calls: [proposal] })} />);
    expect(screen.getByText("未执行")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /执行/ })).toBeNull();
    unmount();
    wrap(<AiMessage m={stored({ tool_calls: [{ ...proposal, state: "confirmed" }] })} />);
    expect(screen.getByText("已执行")).toBeTruthy();
  });
});

describe("stop and actions", () => {
  it("a stopped empty answer says 已停止 and offers only 重新生成", () => {
    wrap(<AiMessage m={stored({ stopped: true })} onRegenerate={() => {}} noteTitle="x" />);
    expect(screen.getByText("已停止")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /复制/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /保存为笔记/ })).toBeNull();
    expect(screen.getByRole("button", { name: /重新生成/ })).toBeTruthy();
  });

  it("a stored stopped message with reasoning keeps the 已停止 trace line", () => {
    wrap(<AiMessage m={stored({ stopped: true, parts: [{ type: "thinking", text: "先检索。" }] })} />);
    expect(document.querySelector(".think-label")?.textContent).toBe("已停止 · 0 次工具调用");
  });

  it("no action row while the answer is still empty", () => {
    const m: ChainMessage = { ...stored({}), status: "running" };
    wrap(<AiMessage m={m} onRegenerate={() => {}} />);
    expect(document.querySelector(".ans-actions")).toBeNull();
  });

  it("the expanded chain lists the tool steps before the reasoning", () => {
    const call: ToolCall = { id: "c1", name: "stats.collocations", args: { node: "翻译", window: 5, scope: { corpus_id: "c1" } }, state: "succeeded", result_summary: "搭配：62 行" };
    wrap(<AiMessage m={stored({ tool_calls: [call], parts: [{ type: "thinking", text: "Scope corpus d837a3b0-1111-4111-8111-111111111111 统计搭配。" }, { type: "text", text: "完成。" }] })} />);
    fireEvent.click(document.querySelector<HTMLButtonElement>(".think-head")!);
    const scroll = document.querySelector(".think-scroll")!;
    expect(scroll.firstElementChild?.className).toBe("steps");
    expect(scroll.querySelector(".step-title")?.textContent).toBe("计算搭配");
    expect(scroll.querySelector(".step-args")?.textContent).toBe("节点词 翻译　窗口 5");
    expect(scroll.querySelector(".think-text")?.textContent).not.toMatch(/d837a3b0/);
  });
});

describe("tools rail", () => {
  it("groups tools by capability with Chinese names, folded until opened", () => {
    render(<ToolList used={new Set(["corpus.search"])} />);
    expect(screen.getByText("语料与检索")).toBeTruthy();
    expect(screen.queryByText("检索语料")).toBeNull();
    fireEvent.click(screen.getByText("语料与检索"));
    expect(screen.getByText("检索语料")).toBeTruthy();
    expect(screen.getByText("已用 1")).toBeTruthy();
    expect(document.body.textContent).not.toContain("corpus.search");
  });
});

describe("unknown OpenUI components", () => {
  it("renders the children of an unregistered layout component instead of dropping them", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    wrap(<UiBlock lang={'root = Stack([a, b])\na = Callout("info", "三条例句已列出")\nb = Callout("warning", "只含前 20 行")'} />);
    expect(await screen.findByText("三条例句已列出")).toBeTruthy();
    expect(screen.getByText("只含前 20 行")).toBeTruthy();
    expect(warn.mock.calls.filter((c) => String(c[0]).includes('"Stack"'))).toHaveLength(1);
    warn.mockRestore();
  });
});
