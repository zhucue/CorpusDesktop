import type { SearchScope } from "../../api";
import { readJson, writeJson } from "../../lib/storage";

export interface HistoryEntry {
  query: string;
  scope: SearchScope;
  scopeName: string;
  hits: number | null;
  at: string;
}

const MAX = 20;
const key = (projectId: string) => `search-history:${projectId}`;

export function loadHistory(projectId: string): HistoryEntry[] {
  return readJson<HistoryEntry[]>(key(projectId), []);
}

/** Most recent first; the same query + scope is kept once. */
export function pushHistory(projectId: string, entry: HistoryEntry): HistoryEntry[] {
  const same = (h: HistoryEntry) => h.query === entry.query && JSON.stringify(h.scope) === JSON.stringify(entry.scope);
  const prev = loadHistory(projectId);
  const old = prev.find(same);
  const next = [{ ...entry, hits: entry.hits ?? old?.hits ?? null }, ...prev.filter((h) => !same(h))].slice(0, MAX);
  writeJson(key(projectId), next);
  return next;
}
