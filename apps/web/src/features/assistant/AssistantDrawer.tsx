import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import type { Scope } from "../../api";
import { Icon } from "../../components/Icon";
import { Tip } from "../../components/common";
import { useShell } from "../../components/shell/shell";
import { describeScope, useCorpora, useSubcorpora } from "../../lib/data";
import { readJson, writeJson } from "../../lib/storage";
import "./assistant.css";
import AssistantPanel from "./AssistantPanel";
import { useSessions, type AgentPageContext } from "./useAgentChat";

const CONTEXT_PAGES: AgentPageContext["page"][] = ["search", "stats", "annotate", "knowledge", "corpora"];
const MAX_HITS = 20;

const scopeKey = (s: Scope | null | undefined) => (!s ? "" : "subcorpus_id" in s ? `s:${s.subcorpus_id}` : `c:${s.corpus_id}`);

/**
 * 420 px side panel without mask. Each question carries the page context (page, label, scope; on the search page
 * also the query, search_id and selected hits); a session keeps its own scope, and a mismatch with the page is shown.
 */
export default function AssistantDrawer({ onClose }: { onClose: () => void }) {
  const shell = useShell();
  const navigate = useNavigate();
  const pageId = useLocation().pathname.split("/")[3]; // /p/{project}/{page}
  const key = `drawer-session:${shell.projectId}`;
  const [sessionId, setSessionId] = useState<string | null>(() => readJson<string | null>(key, null));
  const corpora = useCorpora(shell.projectId);
  const subs = useSubcorpora(shell.projectId);
  const sessions = useSessions(shell.projectId);
  const ctx = shell.assistantContext;
  const scope = ctx?.scope ?? shell.scope;
  const label = ctx?.label ?? shell.scopeInfo.name;
  const nameOf = (s: Scope | null) => describeScope(s, corpora.data?.items ?? [], subs.data?.items ?? []).name || "未选择范围";

  const page = CONTEXT_PAGES.find((p) => p === pageId);
  const context = useMemo<AgentPageContext | null>(() => {
    if (!page) return null;
    const base: AgentPageContext = { page, label: label || nameOf(scope), scope };
    if (page !== "search" || !ctx?.query) return base;
    return {
      ...base,
      query: ctx.query,
      ...(ctx.search_id ? { search_id: ctx.search_id } : {}),
      ...(ctx.hit_ids?.length ? { hit_ids: ctx.hit_ids.slice(0, MAX_HITS) } : {}),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, label, scope, ctx, corpora.data, subs.data]);

  const session = sessionId ? sessions.data?.items.find((s) => s.id === sessionId) : undefined;
  const mismatch = !!session && scopeKey(session.scope) !== scopeKey(scope);
  const newSession = () => {
    setSessionId(null);
    writeJson(key, null);
  };

  return (
    <aside className="asst-drawer" aria-label="助手">
      <div className="drawer-head">
        <Icon name="spark" />
        <h2 className="grow">助手</h2>
        <Tip title="新对话">
          <button className="btn ghost icon" type="button" aria-label="新对话" onClick={newSession}>
            <Icon name="plus" />
          </button>
        </Tip>
        <Tip title="在助手页打开">
          <button className="btn ghost icon" type="button" aria-label="在助手页打开" onClick={() => navigate(`/p/${shell.projectId}/assistant${sessionId ? `/${sessionId}` : ""}`)}>
            <Icon name="external" />
          </button>
        </Tip>
        <Tip title="关闭">
          <button className="btn ghost icon" type="button" aria-label="关闭助手" onClick={onClose}>
            <Icon name="x" />
          </button>
        </Tip>
      </div>
      {mismatch && (
        <div className="alert warn" role="status" style={{ margin: "0 12px 8px" }}>
          <Icon name="alert" size={14} />
          <span className="grow sm">
            会话范围：{nameOf(session.scope)}；当前页面：{nameOf(scope)}
          </span>
          <button className="btn xs" type="button" onClick={newSession}>
            按当前范围新对话
          </button>
        </div>
      )}
      <AssistantPanel
        compact
        projectId={shell.projectId}
        sessionId={sessionId}
        onSessionCreated={(s) => {
          setSessionId(s.id);
          writeJson(key, s.id);
        }}
        scope={scope}
        scopeLabel={session ? nameOf(session.scope) : label}
        context={context}
      />
    </aside>
  );
}
