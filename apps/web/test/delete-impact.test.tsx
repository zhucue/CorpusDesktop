import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DeleteConfirm } from "../src/features/corpora/DeleteConfirm";

// generous waits: the full suite runs many jsdom files in parallel and antd modals mount slowly under load
const WAIT = { timeout: 10_000 };
const TEST_TIMEOUT = 20_000;
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });

function renderConfirm(respond: () => Response, onConfirm = vi.fn()) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => respond());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App>
        <DeleteConfirm target={{ kind: "corpus", id: "c1", name: "作文" }} onConfirm={onConfirm} onClose={() => {}} />
      </App>
    </QueryClientProvider>,
  );
  return onConfirm;
}

const deleteButton = () => screen.getByRole("button", { name: /删\s*除/ });

afterEach(() => vi.restoreAllMocks());

describe("delete confirmation with impact", () => {
  it("lists layers with human counts and needs the checkbox before deleting", async () => {
    const onConfirm = renderConfirm(() =>
      json({
        documents: 2,
        sentences: 40,
        layers: [
          { id: "l1", name: "偏误", kind: "span", human: 12 },
          { id: "l2", name: "词性", kind: "pos", human: 0 },
        ],
        human_annotations: 12,
        evidence: 3,
        kb_refs: 1,
      }),
    );
    expect(await screen.findByText(/标注层「偏误」/, {}, WAIT)).toBeTruthy();
    expect(screen.getByText("人工 12 条")).toBeTruthy();
    expect(screen.getByText(/证据 3 条、笔记引用 1 条/)).toBeTruthy();
    expect(deleteButton()).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(deleteButton()).toHaveProperty("disabled", false), WAIT);
    fireEvent.click(deleteButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  }, TEST_TIMEOUT);

  it("keeps the plain confirmation when nothing else is affected", async () => {
    renderConfirm(() => json({ documents: 1, sentences: 5, layers: [], human_annotations: 0, evidence: 0, kb_refs: 0 }));
    expect(await screen.findByText("1 个文档、5 句一并删除。", {}, WAIT)).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    await waitFor(() => expect(deleteButton()).toHaveProperty("disabled", false), WAIT);
  }, TEST_TIMEOUT);

  it("shows the error with 重试 and keeps deleting disabled until the impact loads", async () => {
    let fail = true;
    renderConfirm(() =>
      fail
        ? json({ error: { code: "INTERNAL", message: "数据库忙" } }, 500)
        : json({ documents: 1, sentences: 5, layers: [], human_annotations: 0, evidence: 0, kb_refs: 0 }),
    );
    expect(await screen.findByText(/数据库忙/, {}, WAIT)).toBeTruthy();
    expect(deleteButton()).toHaveProperty("disabled", true);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    expect(await screen.findByText("1 个文档、5 句一并删除。", {}, WAIT)).toBeTruthy();
    await waitFor(() => expect(deleteButton()).toHaveProperty("disabled", false), WAIT);
  }, TEST_TIMEOUT);
});
