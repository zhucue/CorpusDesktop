import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Popconfirm } from "antd";
import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { agentApi, errorText, type AgentSession, type Scope, type ToolCall } from "../../api";
import { ErrorAlert } from "../../components/common";
import { AGENT_TOOLS } from "../../components/global/tools";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/shell/AppShell";
import { useShell } from "../../components/shell/shell";
import { describeScope, useCorpora, useProjectId, useSubcorpora } from "../../lib/data";
import { dayGroup, fmt, fmtShortTime } from "../../lib/format";
import "./assistant.css";
import AssistantPanel, { HealthNotice } from "./AssistantPanel";
import { useSessions, type ChatItem } from "./useAgentChat";

export function refLink(projectId: string, ref: ToolCall["result_ref"]): string | null {
  if (!ref) return null;
  const base = `/p/${projectId}`;
  switch (ref.kind) {
    case "stat":
      return `${base}/stats?stat=${encodeURIComponent(ref.id)}`;
    case "job":
      return `${base}/jobs?job=${encodeURIComponent(ref.id)}`;
    case "layer":
      return `${base}/annotate?layer=${encodeURIComponent(ref.id)}`;
    case "corpus":
      return `${base}/corpora/${ref.id}`;
    case "subcorpus":
    case "evidence":
      return `${base}/corpora`;
    case "query":
    case "search":
      return `${base}/search`;
    case "note":
    case "kb_document":
    case "document":
      return `${base}/knowledge?doc=${encodeURIComponent(ref.id)}`;
    case "term":
      return `${base}/knowledge?tab=terms&term=${encodeURIComponent(ref.id)}`;
    default:
      return null;
  }
}

function SessionList({ projectId, current }: { projectId: string; current: string | null }) {
  const sessions = useSessions(projectId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { message } = App.useApp();
  const del = useMutation({
    mutationFn: (id: string) => agentApi.del(`/sessions/${id}`),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["agent-sessions", projectId] });
      if (id === current) navigate(`/p/${projectId}/assistant`);
    },
    onError: (e) => message.error(errorText(e)),
  });
  const items = [...(sessions.data?.items ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  let group = "";
  return (
    <nav className="convs" aria-label="会话">
      <button className="btn p" type="button" style={{ margin: "0 2px 8px" }} onClick={() => navigate(`/p/${projectId}/assistant`)}>
        <Icon name="plus" size={14} />
        新对话
      </button>
      <ErrorAlert error={sessions.error} />
      {sessions.isSuccess && items.length === 0 && <div className="empty sm">暂无会话</div>}
      {items.map((s) => {
        const g = dayGroup(s.updated_at);
        const head = g !== group ? <div className="conv-group">{(group = g)}</div> : null;
        return (
          <div key={s.id}>
            {head}
            <div className={`list-item conv ${s.id === current ? "on" : ""}`} role="button" tabIndex={0} onClick={() => navigate(`/p/${projectId}/assistant/${s.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/p/${projectId}/assistant/${s.id}`)}>
              <span className="li-title ellipsis">{s.title || "新对话"}</span>
              <span className="li-meta">
                {s.state === "running" ? (
                  <>
                    <span className="dot pulse" style={{ color: "var(--accent)" }} />
                    运行中
                  </>
                ) : (
                  <>
                    {fmtShortTime(s.updated_at)} · {s.message_count} 条消息
                  </>
                )}
              </span>
              <Popconfirm title="删除这个会话？" okText="删除" cancelText="取消" onConfirm={() => del.mutate(s.id)}>
                <button className="btn ghost icon conv-del" type="button" aria-label="删除会话" onClick={(e) => e.stopPropagation()}>
                  <Icon name="trash" size={14} />
                </button>
              </Popconfirm>
            </div>
          </div>
        );
      })}
    </nav>
  );
}

function Rail({ projectId, scope, items }: { projectId: string; scope: Scope | null; items: ChatItem[] }) {
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const info = describeScope(scope, corpora.data?.items ?? [], subs.data?.items ?? []);
  const calls = items.flatMap((i) => (i.kind === "ai" ? i.m.tools : []));
  const used = new Set(calls.map((c) => c.name));
  const cited = calls.filter((c) => c.state === "succeeded" && c.result_ref);
  const stats = info.subcorpus?.stats ?? info.corpus?.stats;
  return (
    <aside className="rail" aria-label="上下文">
      <section>
        <h2>
          <Icon name="db" size={14} />
          当前范围
        </h2>
        {info.corpus ? (
          <dl className="kv" style={{ gridTemplateColumns: "64px 1fr" }}>
            <dt>语料库</dt>
            <dd>{info.corpus.name}</dd>
            <dt>子库</dt>
            <dd>{info.subcorpus?.name ?? "全部"}</dd>
            {stats && (
              <>
                <dt>句</dt>
                <dd className="num">{fmt(stats.sentences)}</dd>
                <dt>词</dt>
                <dd className="num">{fmt(stats.tokens)}</dd>
              </>
            )}
            <dt>索引</dt>
            <dd className="num">{info.corpus.index_version != null ? `v${info.corpus.index_version}` : "—"}</dd>
          </dl>
        ) : (
          <div className="muted sm">未选择</div>
        )}
      </section>
      <section>
        <h2>
          <Icon name="quote" size={14} />
          引用结果
        </h2>
        {cited.length === 0 && <div className="muted sm">暂无</div>}
        {cited.map((c, i) => {
          const href = refLink(projectId, c.result_ref);
          return (
            <div className="ev" key={c.id}>
              <span className="cite">{i + 1}</span>
              <div style={{ minWidth: 0 }}>
                <div className="mono small">{c.name}</div>
                <div className="ellipsis">{href ? <Link to={href}>{c.result_summary || c.result_ref?.id}</Link> : c.result_summary}</div>
              </div>
            </div>
          );
        })}
      </section>
      <section>
        <h2>
          <Icon name="tool" size={14} />
          可用工具
        </h2>
        {AGENT_TOOLS.map((g) => (
          <div key={g.group}>
            <div className="tool-group">{g.group}</div>
            <div className="tool-chips">
              {g.tools.map((t) => (
                <span key={t} className={`chip static ${used.has(t) ? "used" : ""}`}>
                  {t}
                </span>
              ))}
            </div>
          </div>
        ))}
      </section>
    </aside>
  );
}

export default function AssistantPage() {
  const projectId = useProjectId();
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const shell = useShell();
  const qc = useQueryClient();
  const sessions = useSessions(projectId);
  const session: AgentSession | undefined = sessions.data?.items.find((s) => s.id === sessionId);
  const scope = (sessionId ? (session?.scope ?? null) : null) ?? shell.scope;
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  const label = describeScope(scope, corpora.data?.items ?? [], subs.data?.items ?? []).name;
  const [items, setItems] = useState<ChatItem[]>([]);
  const onItems = useCallback((x: ChatItem[]) => setItems(x), []);
  const { message } = App.useApp();

  const changeScope = async (s: Scope) => {
    if (!sessionId) return shell.setScope(s);
    try {
      await agentApi.patch(`/sessions/${sessionId}`, { scope: s });
      qc.invalidateQueries({ queryKey: ["agent-sessions", projectId] });
    } catch (e) {
      message.error(errorText(e));
    }
  };

  const onCreated = useMemo(() => (s: AgentSession) => navigate(`/p/${projectId}/assistant/${s.id}`, { replace: true }), [navigate, projectId]);

  return (
    <div className="asst-page">
      <PageHeader title="助手" />
      <div className="asst">
        <SessionList projectId={projectId} current={sessionId ?? null} />
        <section className="chat-col" aria-label="对话">
          <div style={{ padding: "16px 32px 0", maxWidth: 884, margin: "0 auto", width: "100%" }}>
            <HealthNotice />
          </div>
          <AssistantPanel
            projectId={projectId}
            sessionId={sessionId ?? null}
            onSessionCreated={onCreated}
            scope={scope}
            scopeLabel={label}
            onScopeChange={changeScope}
            onItems={onItems}
          />
        </section>
        <Rail projectId={projectId} scope={scope} items={items} />
      </div>
    </div>
  );
}
