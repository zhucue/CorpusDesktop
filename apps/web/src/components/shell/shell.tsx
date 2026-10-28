import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Scope } from "../../api";
import { describeScope, useCorpora, useSubcorpora, type ScopeInfo } from "../../lib/data";
import { useProjectScope } from "../../lib/scope";

/** What the assistant drawer should know about the page it was opened from. */
export interface AssistantContext {
  label: string; // e.g. "当前检索 · 1,284 命中"
  scope: Scope | null;
}

interface ShellState {
  projectId: string;
  scope: Scope | null;
  setScope: (s: Scope | null) => void;
  scopeInfo: ScopeInfo;
  assistantOpen: boolean;
  setAssistantOpen: (open: boolean) => void;
  assistantContext: AssistantContext | null;
  setAssistantContext: (c: AssistantContext | null) => void;
  openPalette: (query?: string) => void;
  openKeys: () => void;
}

const Ctx = createContext<ShellState | null>(null);

export function useShell(): ShellState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useShell outside AppShell");
  return v;
}

/** Safe variant for components that may render outside the shell (onboarding, tests). */
export function useOptionalShell(): ShellState | null {
  return useContext(Ctx);
}

export function ShellProvider({
  projectId,
  openPalette,
  openKeys,
  children,
}: {
  projectId: string;
  openPalette: (q?: string) => void;
  openKeys: () => void;
  children: React.ReactNode;
}) {
  // One scope per project for every page (lib/scope): stats tabs, search, breadcrumb and palette share it.
  const [scope, setScope] = useProjectScope(projectId);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantContext, setAssistantContext] = useState<AssistantContext | null>(null);
  const corpora = useCorpora(projectId);
  const subcorpora = useSubcorpora(projectId);

  // Default to the first ready corpus once the list arrives.
  const items = corpora.data?.items;
  useEffect(() => {
    if (scope || !items) return;
    const first = items.find((c) => c.status === "ready" || c.status === "stale");
    if (first) setScope({ corpus_id: first.id });
  }, [scope, items, setScope]);

  const scopeInfo = useMemo(
    () => describeScope(scope, corpora.data?.items ?? [], subcorpora.data?.items ?? []),
    [scope, corpora.data, subcorpora.data],
  );

  const value: ShellState = {
    projectId,
    scope,
    setScope,
    scopeInfo,
    assistantOpen,
    setAssistantOpen,
    assistantContext,
    setAssistantContext,
    openPalette,
    openKeys,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
