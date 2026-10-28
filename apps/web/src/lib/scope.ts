import { useCallback, useSyncExternalStore } from "react";
import type { Scope } from "../api";
import { readJson, writeJson } from "./storage";

/**
 * The project's one working scope (corpus or subcorpus): search, every stats tab, the breadcrumb, the command
 * palette and the assistant read and write this store, so switching the corpus anywhere switches it everywhere.
 * Persisted per project in localStorage (`scope:<projectId>`). A search-only temporary filter is not stored here.
 */
const cache = new Map<string, Scope | null>();
const listeners = new Set<() => void>();
const storageKey = (projectId: string) => `scope:${projectId}`;

export function getProjectScope(projectId: string): Scope | null {
  if (!cache.has(projectId)) cache.set(projectId, readJson<Scope | null>(storageKey(projectId), null));
  return cache.get(projectId) ?? null;
}

export function setProjectScope(projectId: string, scope: Scope | null) {
  const next = scope && ("subcorpus_id" in scope ? { subcorpus_id: scope.subcorpus_id } : { corpus_id: scope.corpus_id });
  if (JSON.stringify(getProjectScope(projectId)) === JSON.stringify(next)) return;
  cache.set(projectId, next);
  writeJson(storageKey(projectId), next);
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** [scope, setScope] of a project; every caller re-renders when any of them sets it. */
export function useProjectScope(projectId: string): [Scope | null, (s: Scope | null) => void] {
  const scope = useSyncExternalStore(subscribe, () => getProjectScope(projectId));
  const set = useCallback((s: Scope | null) => setProjectScope(projectId, s), [projectId]);
  return [scope, set];
}

/** Tests only. */
export function resetScopeStore() {
  cache.clear();
}
