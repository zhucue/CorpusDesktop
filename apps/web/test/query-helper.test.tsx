import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import QueryHelper, { appendSnippet } from "../src/search/QueryHelper";

describe("QueryHelper", () => {
  it("inserts syntax built from the word input", () => {
    const onInsert = vi.fn();
    render(<QueryHelper onInsert={onInsert} />);

    fireEvent.change(screen.getByPlaceholderText("词"), { target: { value: "文化" } });
    fireEvent.click(screen.getByRole("button", { name: "插入词" }));
    fireEvent.click(screen.getByRole("button", { name: '精确 ""' }));
    fireEvent.click(screen.getByRole("button", { name: "或 |" }));
    fireEvent.click(screen.getByRole("button", { name: "同句出现 +" }));
    fireEvent.click(screen.getByRole("button", { name: "同句不出现 -" }));
    fireEvent.click(screen.getByRole("button", { name: "插入 $N" }));
    fireEvent.click(screen.getByRole("button", { name: "任意词 *" }));
    fireEvent.click(screen.getByRole("button", { name: "任意单字 ?" }));

    expect(onInsert.mock.calls.map((c) => c[0])).toEqual(["文化", '"文化"', "|文化", "+文化", "-文化", "$3", "*", "?"]);
  });

  it("shows the syntax table", () => {
    render(<QueryHelper onInsert={() => {}} />);
    expect(screen.getByText("语言 $3 文化")).toBeTruthy();
    expect(screen.getByText("同句不出现「文化」")).toBeTruthy();
  });

  it("joins snippets into one query", () => {
    let q = "";
    for (const s of ["语言/n", "$3", "文化", "|文明", "+研究"]) q = appendSnippet(q, s);
    expect(q).toBe("语言/n $3 文化|文明 +研究");
  });
});
