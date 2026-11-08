import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

// a page size of 2 leaves the third basket item unloaded (the real one is 200)
vi.mock("../src/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../src/api")>()), MAX_PAGE_SIZE: 2 }));

import type { EvidenceInput } from "../src/api";
import { EvidenceBasket, EvidenceProvider, PinButton, pinKey, sameEvidence } from "../src/components/global/evidence";

const WAIT = { timeout: 10_000 };
const SLOW = 20_000;
const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });

const D = "11111111-2222-3333-4444-555555555555";
const hit = (i: number): EvidenceInput => ({
  kind: "hit",
  ref: { hit_id: `${D}:${i * 10}-${i * 10 + 2}`, document_id: D, start_cp: i * 10, end_cp: i * 10 + 2 },
  text: `句 ${i}`,
  source: "Tatoeba",
});
const item = (i: number) => ({ id: `e${i}`, project_id: "p1", ...hit(i), note: null, created_by: "u", created_at: "" });

afterEach(() => vi.restoreAllMocks());

describe("pins beyond the loaded basket pages", () => {
  it("looks up unloaded items for pin state and never counts an existing item twice", async () => {
    const all = [item(1), item(2), item(3)]; // e3 is on page 2, not loaded
    const lookups: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/projects/p1/evidence" && method === "GET") {
        const page = Number(url.searchParams.get("page") ?? 1);
        return json({ items: all.slice((page - 1) * 2, page * 2), total: all.length });
      }
      if (url.pathname === "/api/projects/p1/evidence/lookup") {
        const body = JSON.parse(String(init?.body)) as { hit_ids: string[] };
        lookups.push(body);
        return json({ items: all.filter((e) => body.hit_ids.includes(e.ref.hit_id!)) });
      }
      // pinning hit 4 again: the server already has it (existing), the total stays 3
      if (url.pathname === "/api/projects/p1/evidence" && method === "POST") return json({ ...item(4), existing: true });
      return json({});
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <App>
          <MemoryRouter>
            <EvidenceProvider projectId="p1">
              <div data-testid="row3">
                <PinButton input={hit(3)} label />
              </div>
              <div data-testid="row4">
                <PinButton input={hit(4)} label />
              </div>
              <EvidenceBasket projectId="p1" open onToggle={() => {}} />
            </EvidenceProvider>
          </MemoryRouter>
        </App>
      </QueryClientProvider>,
    );
    const count = () => container.querySelector(".capsule .cnt")?.textContent;
    await waitFor(() => expect(count()).toBe("3"), WAIT);
    // e3 is not loaded, yet its row shows 已钉 from the lookup
    await waitFor(() => expect(screen.getByTestId("row3").textContent).toBe("已钉"), WAIT);
    expect(screen.getByTestId("row4").textContent).toBe("钉住");
    expect(lookups[lookups.length - 1]).toEqual({ hit_ids: [hit(3).ref.hit_id, hit(4).ref.hit_id].sort(), stat_rows: [] });

    fireEvent.click(screen.getByTestId("row4").querySelector("button")!);
    await waitFor(() => expect(screen.getByTestId("row4").textContent).toBe("已钉"), WAIT);
    expect(count()).toBe("3");
  }, SLOW);

  it("matches hits by document and offsets when hit_id is missing", () => {
    const { hit_id: _, ...ref } = hit(5).ref;
    expect(sameEvidence({ ...hit(5), ref }, hit(5))).toBe(true);
    expect(sameEvidence({ ...hit(5), ref }, hit(6))).toBe(false);
    expect(pinKey({ ...hit(5), ref })).toBe(`h:${hit(5).ref.hit_id}`);
    expect(pinKey({ kind: "text", ref: {}, text: "x", source: "y" })).toBeNull();
  });
});
