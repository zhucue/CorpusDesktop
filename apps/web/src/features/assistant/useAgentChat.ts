import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { agentApi, buildInit, errorFromResponse, type AgentHealth, type AgentSession, type AgentSessionDetail, type Page, type Scope } from "../../api";
import { applyEvent, fromMessage, markStopped, newChain, type ChainMessage } from "./chain";
import { readSse } from "./sse";

export type ChatItem = { kind: "user"; id: string; content: string } | { kind: "ai"; m: ChainMessage };

export function useAgentHealth() {
  return useQuery({
    queryKey: ["agent-health"],
    queryFn: () => agentApi.get<AgentHealth>("/health"),
    staleTime: 60_000,
    retry: false,
    meta: { background: true },
  });
}

export function useSessions(projectId: string) {
  return useQuery({
    queryKey: ["agent-sessions", projectId],
    queryFn: () => agentApi.get<Page<AgentSession>>("/sessions", { project_id: projectId }),
    meta: { background: true },
  });
}

function itemsFrom(detail: AgentSessionDetail): ChatItem[] {
  return detail.messages.map((m) =>
    m.role === "user" ? ({ kind: "user", id: m.id, content: m.content } as ChatItem) : ({ kind: "ai", m: fromMessage(m) } as ChatItem),
  );
}

/**
 * One agent conversation. Streams POST /agent/sessions/{id}/messages; when the stream drops without
 * `done`/`error` it reloads GET /agent/sessions/{id} and polls while the server still runs the turn.
 */
export function useAgentChat({
  projectId,
  sessionId,
  scope,
  onSessionCreated,
}: {
  projectId: string;
  sessionId: string | null;
  scope: Scope | null;
  onSessionCreated?: (s: AgentSession) => void;
}) {
  const qc = useQueryClient();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [remoteRunning, setRemoteRunning] = useState(false);
  const active = useRef<{ id: string; abort: AbortController } | null>(null);
  const current = useRef<string | null>(sessionId);

  const detail = useQuery({
    queryKey: ["agent-session", sessionId],
    queryFn: () => agentApi.get<AgentSessionDetail>(`/sessions/${sessionId}`),
    enabled: !!sessionId && !running,
    refetchInterval: remoteRunning ? 2000 : false,
    meta: { background: true },
  });

  // Load history when the session changes or after a reload; skip while we stream locally.
  useEffect(() => {
    if (!sessionId) {
      setItems([]);
      return;
    }
    if (detail.data && detail.data.id === sessionId && !active.current) {
      const loaded = itemsFrom(detail.data);
      // Keep live timing (thinking duration) for messages streamed in this view.
      setItems((prev) =>
        loaded.map((it) => {
          if (it.kind !== "ai") return it;
          const old = prev.find((p) => p.kind === "ai" && p.m.id === it.m.id);
          return old && old.kind === "ai" && old.m.answerAt ? { kind: "ai", m: { ...it.m, startedAt: old.m.startedAt, answerAt: old.m.answerAt } } : it;
        }),
      );
      setRemoteRunning(detail.data.state === "running");
    }
  }, [detail.data, sessionId]);

  // Switching to another session aborts the local stream (the server keeps running it);
  // a session created by send() itself is already current and keeps streaming.
  useEffect(() => {
    if (sessionId === current.current) return;
    current.current = sessionId;
    active.current?.abort.abort();
    active.current = null;
    setError(null);
    setItems([]);
    setRemoteRunning(false);
  }, [sessionId]);
  useEffect(() => () => active.current?.abort.abort(), []);

  const send = useCallback(
    async (content: string): Promise<boolean> => {
      const text = content.trim();
      if (!text || active.current) return false;
      setError(null);
      let sid = current.current;
      try {
        if (!sid) {
          const s = await agentApi.post<AgentSession>("/sessions", { project_id: projectId, scope, title: text.replace(/\s+/g, " ").slice(0, 40) });
          sid = s.id;
          current.current = s.id;
          qc.invalidateQueries({ queryKey: ["agent-sessions", projectId] });
          onSessionCreated?.(s);
        }
      } catch (e) {
        setError(e);
        return false;
      }
      const localId = `local-${Date.now()}`;
      const abort = new AbortController();
      active.current = { id: localId, abort };
      setRunning(true);
      const now = Date.now();
      let chain: ChainMessage = { ...newChain(now), id: localId };
      const userId = `u-${now}`;
      setItems((list) => [...list, { kind: "user", id: userId, content: text }, { kind: "ai", m: chain }]);
      let accepted = true;
      let finished = false;
      try {
        const res = await fetch(`/agent/sessions/${sid}/messages`, {
          ...buildInit("POST", { content: text }),
          headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
          signal: abort.signal,
        });
        if (!res.ok || !res.body) throw await errorFromResponse(res);
        await readSse(
          res.body,
          (ev) => {
            const prevId = chain.id;
            chain = applyEvent(chain, ev, Date.now());
            if (ev.event === "done" || ev.event === "error") finished = true;
            const next = chain;
            setItems((list) => list.map((it) => (it.kind === "ai" && it.m.id === prevId ? { kind: "ai", m: next } : it)));
          },
          abort.signal,
        );
      } catch (e) {
        if (!abort.signal.aborted) {
          setError(e);
          // Request rejected before streaming (409 SESSION_BUSY, 503 MODEL_NOT_CONFIGURED…): drop the placeholder.
          if (chain.id === localId) {
            accepted = false;
            setItems((list) => list.filter((it) => !(it.kind === "ai" && it.m.id === localId) && !(it.kind === "user" && it.id === userId)));
          } else {
            setItems((list) => list.map((it) => (it.kind === "ai" && it.m.id === chain.id && it.m.status === "running" ? { kind: "ai", m: { ...it.m, status: "error" } } : it)));
          }
          finished = true;
        }
      } finally {
        active.current = null;
        setRunning(false);
        qc.invalidateQueries({ queryKey: ["agent-sessions", projectId] });
        // Stream dropped without a final event: reload the session and follow it while it runs.
        if (!finished && current.current === sid) {
          setRemoteRunning(true);
          qc.invalidateQueries({ queryKey: ["agent-session", sid] });
        } else {
          qc.invalidateQueries({ queryKey: ["agent-session", sid] });
        }
      }
      return accepted;
    },
    [projectId, scope, qc, onSessionCreated],
  );

  const stop = useCallback(async () => {
    const sid = current.current;
    const a = active.current;
    if (a) {
      setItems((list) => list.map((it) => (it.kind === "ai" && it.m.status === "running" ? { kind: "ai", m: markStopped(it.m, Date.now()) } : it)));
    }
    if (sid) {
      try {
        await agentApi.post(`/sessions/${sid}/cancel`);
      } catch (e) {
        setError(e);
      }
    }
    // The server ends the stream with a normal `done`; the remote poll picks up a detached run.
    if (!a) qc.invalidateQueries({ queryKey: ["agent-session", sid] });
  }, [qc]);

  return {
    items,
    running: running || remoteRunning,
    streaming: running,
    error,
    loading: !!sessionId && detail.isPending,
    loadError: detail.error,
    send,
    stop,
  };
}
