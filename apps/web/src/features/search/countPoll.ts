import { useEffect, useRef, useState } from "react";
import type { Counts, SearchRequest, SearchResult } from "../../api";

/** POST /search fields of contracts/p7.md §1: the background count can fail; left / right / random apply
 *  only once the count is complete (sort_applied). */
export type SearchCounts = Counts & { failed?: boolean; message?: string };
export type SearchPage = Omit<SearchResult, "counts"> & { counts: SearchCounts; sort_applied?: boolean };

export const COUNT_POLL_MS = 3000;
export const SORT_PENDING = "排序在计数完成后生效";

/** Note in the results bar while the chosen sort is not applied yet. */
export function sortNote(result: SearchPage | undefined, counts: SearchCounts | null): string | null {
  return result?.sort_applied === false && !counts?.failed ? SORT_PENDING : null;
}

/** Once the count completes, the page on screen is fetched again when it was not sorted yet, or when it is
 *  short but not the last page (before the count, same-sentence conditions may have left too few hits). */
export function refetchOnComplete(shown: SearchPage, counts: SearchCounts): boolean {
  if (!counts.complete) return false;
  if (shown.sort_applied === false) return true;
  const pages = Math.max(1, Math.ceil((counts.hits ?? 0) / shown.page_size));
  return shown.items.length < shown.page_size && shown.page < pages;
}

/**
 * Re-request the shown page with its search_id every COUNT_POLL_MS while the background count runs; stop
 * once it is complete or failed. Returns the latest counts and a polling error.
 */
export function useCountPoll(o: {
  req: SearchRequest | null;
  result: SearchPage | undefined;
  /** result is the previous search's page while a newer request loads */
  placeholder: boolean;
  post: (body: SearchRequest) => Promise<SearchPage>;
  /** fetch this request again (the page on screen, now counted) */
  refetch: (req: SearchRequest) => void;
  /** the search_id expired: run this request again without it */
  expired: (req: SearchRequest) => void;
  isExpired: (e: unknown) => boolean;
  intervalMs?: number;
}): { counts: SearchCounts | null; error: unknown } {
  const { req, result } = o;
  const shown = useRef<{ req: SearchRequest; result: SearchPage } | null>(null);
  if (req && result && !o.placeholder) shown.current = { req, result };
  const latest = useRef(req);
  latest.current = req;
  const cb = useRef(o);
  cb.current = o;

  const [polled, setPolled] = useState<{ id: string; counts: SearchCounts } | null>(null);
  const [error, setError] = useState<{ id: string; error: unknown } | null>(null);
  useEffect(() => {
    if (!req || !result || result.counts.complete || result.counts.failed) return;
    const id = result.search_id;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const s = shown.current;
      const body = s?.result.search_id === id ? s.req : req;
      try {
        const r = await cb.current.post({ ...body, search_id: id });
        if (stopped) return;
        setPolled({ id, counts: r.counts });
        if (r.counts.complete) {
          if (s && s.result.search_id === id && latest.current === s.req && refetchOnComplete(s.result, r.counts)) {
            cb.current.refetch({ ...s.req, search_id: id });
          }
          return;
        }
        if (r.counts.failed) return;
      } catch (e) {
        if (stopped) return;
        if (cb.current.isExpired(e)) cb.current.expired(body);
        else setError({ id, error: e });
        return;
      }
      timer = setTimeout(tick, cb.current.intervalMs ?? COUNT_POLL_MS);
    };
    timer = setTimeout(tick, cb.current.intervalMs ?? COUNT_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.search_id, result?.counts.complete, result?.counts.failed]);

  const counts = result && !result.counts.complete && polled?.id === result.search_id ? polled.counts : (result?.counts ?? null);
  return { counts, error: error && error.id === result?.search_id ? error.error : null };
}
