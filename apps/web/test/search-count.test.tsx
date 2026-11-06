import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchRequest } from "../src/api";
import { refetchOnComplete, SORT_PENDING, sortNote, useCountPoll, type SearchCounts, type SearchPage } from "../src/features/search/countPoll";

const req: SearchRequest = { scope: { corpus_id: "c1" }, query: "语言", sort: "left", page: 1, page_size: 2 } as SearchRequest;
const pending: SearchCounts = { hits: null as unknown as number, sentences: null as unknown as number, documents: null as unknown as number, complete: false };
const done: SearchCounts = { hits: 5, sentences: 4, documents: 2, complete: true };

function page(o: Partial<SearchPage> = {}): SearchPage {
  return {
    search_id: "s1",
    parse: {} as SearchPage["parse"],
    counts: pending,
    items: [{}, {}] as SearchPage["items"],
    page: 1,
    page_size: 2,
    sort_applied: false,
    ...o,
  };
}

describe("sort note and refetch rule", () => {
  it("shows the note while the sort waits for the count, not after a failure", () => {
    expect(sortNote(page(), pending)).toBe(SORT_PENDING);
    expect(sortNote(page({ sort_applied: true }), pending)).toBeNull();
    expect(sortNote(page(), { ...pending, failed: true, message: "计数超时（300 秒），请缩小范围或加条件" })).toBeNull();
  });

  it("refetches an unsorted page, or a short page that is not the last", () => {
    expect(refetchOnComplete(page(), done)).toBe(true);
    expect(refetchOnComplete(page({ sort_applied: true }), done)).toBe(false);
    expect(refetchOnComplete(page({ sort_applied: true, items: [{}] as SearchPage["items"] }), done)).toBe(true);
    expect(refetchOnComplete(page({ sort_applied: true, items: [{}] as SearchPage["items"], page: 3 }), done)).toBe(false);
    expect(refetchOnComplete(page(), pending)).toBe(false);
  });
});

describe("count polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup(answers: SearchPage[]) {
    const post = vi.fn(async () => answers.shift() ?? answers[answers.length - 1]);
    const refetch = vi.fn();
    const hook = renderHook(() =>
      useCountPoll({ req, result: page(), placeholder: false, post, refetch, expired: vi.fn(), isExpired: () => false, intervalMs: 100 }),
    );
    const tick = () => act(async () => void (await vi.advanceTimersByTimeAsync(100)));
    return { post, refetch, hook, tick };
  }

  it("polls until complete, then fetches the shown page again in the chosen order", async () => {
    const { post, refetch, hook, tick } = setup([page(), page({ counts: done, sort_applied: true })]);
    await tick();
    expect(hook.result.current.counts?.complete).toBe(false);
    expect(refetch).not.toHaveBeenCalled();
    await tick();
    expect(hook.result.current.counts).toEqual(done);
    expect(refetch).toHaveBeenCalledWith({ ...req, search_id: "s1" });
    await tick();
    await tick();
    expect(post).toHaveBeenCalledTimes(2);
    expect(post).toHaveBeenLastCalledWith({ ...req, search_id: "s1" });
  });

  it("stops polling when the count fails", async () => {
    const failed = { ...pending, failed: true, message: "计数超时（300 秒），请缩小范围或加条件" };
    const { post, refetch, hook, tick } = setup([page({ counts: failed })]);
    await tick();
    await tick();
    await tick();
    expect(post).toHaveBeenCalledTimes(1);
    expect(refetch).not.toHaveBeenCalled();
    expect(hook.result.current.counts?.message).toBe("计数超时（300 秒），请缩小范围或加条件");
  });
});
