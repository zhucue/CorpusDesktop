import { Popover } from "antd";
import { useEffect, useRef, useState } from "react";
import type { AgentSession, Scope } from "../../api";
import { Empty, ErrorAlert } from "../../components/common";
import { ScopeSelect } from "../../components/common/ScopeSelect";
import { TOOL_COUNT } from "../../components/global/tools";
import { Icon } from "../../components/Icon";
import { ResultContext } from "../../components/results/cards";
import { reducedMotion } from "../../theme/motion";
import { AiMessage } from "./ChainView";
import { ToolList } from "./ToolList";
import { useAgentChat, useAgentHealth, useSessions, type ChatItem } from "./useAgentChat";
import "./assistant.css";

export function HealthNotice({ compact }: { compact?: boolean }) {
  const health = useAgentHealth();
  if (health.isPending || health.data?.ok) return null;
  if (health.error)
    return (
      <ErrorAlert error={health.error} style={compact ? { margin: "0 0 8px" } : undefined}>
        <span className="small">助手服务不可用</span>
      </ErrorAlert>
    );
  return (
    <div className="alert warn" role="alert" style={compact ? { margin: "0 0 8px" } : undefined}>
      <Icon name="alert" size={14} />
      <span>
        {health.data?.reason === "MODEL_NOT_CONFIGURED" ? "未配置对话模型，助手暂不可用" : "助手暂不可用"}
        {health.data?.reason && <span className="err-code">{health.data.reason}</span>}
      </span>
    </div>
  );
}

/** Conversation + composer, shared by the assistant page and the 420 px drawer. */
export default function AssistantPanel({
  projectId,
  sessionId,
  onSessionCreated,
  scope,
  scopeLabel,
  onScopeChange,
  compact,
  prefill,
  onItems,
}: {
  projectId: string;
  sessionId: string | null;
  onSessionCreated?: (s: AgentSession) => void;
  scope: Scope | null;
  scopeLabel: string;
  onScopeChange?: (s: Scope) => void;
  compact?: boolean;
  prefill?: string;
  onItems?: (items: ChatItem[]) => void;
}) {
  const health = useAgentHealth();
  const chat = useAgentChat({ projectId, sessionId, scope, onSessionCreated });
  const [text, setText] = useState(prefill ?? "");
  const [scopeOpen, setScopeOpen] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const disabled = !health.data?.ok;

  useEffect(() => {
    onItems?.(chat.items);
  }, [chat.items, onItems]);

  // Follow the bottom only while the reader is at (or within 40 px of) it; otherwise offer 回到底部.
  const pinned = useRef(true);
  // Set by 回到底部 until a smooth scroll reaches the bottom, so its intermediate scroll events don't unpin.
  const jumping = useRef(false);
  const [away, setAway] = useState(false);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const follow = () => {
      if (pinned.current) el.scrollTop = el.scrollHeight;
      else setAway(el.scrollHeight - el.clientHeight > 40);
    };
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
      if (jumping.current) {
        if (!atBottom) return;
        jumping.current = false;
      }
      pinned.current = atBottom;
      setAway(!atBottom);
    };
    const obs = new MutationObserver(follow);
    obs.observe(el, { childList: true, subtree: true, characterData: true });
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(follow);
    resize?.observe(el);
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      obs.disconnect();
      resize?.disconnect();
      el.removeEventListener("scroll", onScroll);
    };
  }, []);

  function toBottom(smooth = true) {
    const el = scroller.current;
    if (!el) return;
    pinned.current = true;
    jumping.current = smooth && !reducedMotion();
    setAway(false);
    el.scrollTo({ top: el.scrollHeight, behavior: smooth && !reducedMotion() ? "smooth" : "auto" });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && chat.running && !document.querySelector(".ant-modal-wrap")) void chat.stop();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [chat]);

  async function submit() {
    if (disabled || chat.running || !text.trim()) return;
    const sent = text;
    setText("");
    toBottom(false);
    const ok = await chat.send(sent);
    if (!ok) setText(sent);
  }

  const lastUser = [...chat.items].reverse().find((i) => i.kind === "user");
  const used = new Set(chat.items.flatMap((i) => (i.kind === "ai" ? i.m.tools.map((t) => t.name) : [])));
  const sessions = useSessions(projectId);
  const sessionTitle = sessions.data?.items.find((s) => s.id === sessionId)?.title;
  const firstUser = chat.items.find((i) => i.kind === "user");
  const noteTitle = sessionTitle || (firstUser?.kind === "user" ? firstUser.content.replace(/\s+/g, " ").slice(0, 40) : "") || "助手回答";

  return (
    <ResultContext.Provider value={{ projectId, scope }}>
      <div className={`chat ${compact ? "compact" : ""}`}>
        <div className="chat-body">
          <div className="chat-scroll" ref={scroller}>
            <div className="chat-log" aria-live="polite">
              {chat.loading && <span className="skel h20" style={{ width: "60%" }} />}
              <ErrorAlert error={chat.loadError} />
              {chat.items.length === 0 && !chat.loading && !compact && (
                <div style={{ paddingTop: 44 }}>
                  <Empty icon="sparkles" text={`针对「${scopeLabel || "当前范围"}」提问，可检索、统计并生成图表`} />
                </div>
              )}
              {chat.items.map((it, i) =>
                it.kind === "user" ? (
                  <div className="msg-user" key={it.id + i}>
                    {it.content}
                  </div>
                ) : (
                  <AiMessage
                    key={it.m.id || i}
                    m={it.m}
                    noteTitle={noteTitle}
                    onRegenerate={i === chat.items.length - 1 && lastUser?.kind === "user" && !disabled && !chat.running ? () => void chat.regenerate() : undefined}
                    onConfirm={i === chat.items.length - 1 && !disabled && !chat.running ? chat.confirm : undefined}
                  />
                ),
              )}
              <ErrorAlert error={chat.error} />
            </div>
          </div>
          <button className="to-bottom" type="button" data-show={away} tabIndex={away ? 0 : -1} aria-hidden={!away} onClick={() => toBottom()}>
            回到底部
            <Icon name="arrowdown" size={14} />
          </button>
        </div>
        <div className="composer">
          {compact && <HealthNotice compact />}
          <form
            className="composer-box"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label htmlFor={compact ? "ask-mini" : "ask"} className="sr-only">
              向助手提问
            </label>
            <textarea
              id={compact ? "ask-mini" : "ask"}
              rows={2}
              value={text}
              disabled={disabled}
              data-slash={compact ? undefined : true}
              placeholder={disabled ? "助手不可用" : compact ? "针对当前结果提问" : "向助手提问，Enter 发送，Shift+Enter 换行"}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void submit();
                }
              }}
            />
            <div className="row">
              <Popover
                open={scopeOpen && !!onScopeChange}
                onOpenChange={setScopeOpen}
                trigger="click"
                content={
                  <ScopeSelect
                    projectId={projectId}
                    value={scope}
                    onChange={(s) => {
                      onScopeChange?.(s);
                      setScopeOpen(false);
                    }}
                  />
                }
              >
                <button className="pill" type="button" title="范围只影响新消息">
                  <Icon name="db" size={14} />
                  <span>{scopeLabel || "未选择范围"}</span>
                </button>
              </Popover>
              {!compact && (
                <Popover trigger="click" placement="topLeft" content={<ToolList used={used} />} classNames={{ root: "tool-pop" }}>
                  <button className="pill" type="button" aria-haspopup="dialog">
                    <Icon name="tool" size={14} />
                    <span>工具 {TOOL_COUNT}</span>
                  </button>
                </Popover>
              )}
              <div className="grow" />
              {health.data?.model_id && <span className="small muted mono">{health.data.model_id}</span>}
              {chat.running ? (
                <button className="send stop" type="button" aria-label="停止" onClick={() => void chat.stop()}>
                  <Icon name="stop" />
                </button>
              ) : (
                <button className="send" type="submit" aria-label="发送" disabled={disabled || !text.trim()}>
                  <Icon name="send" />
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    </ResultContext.Provider>
  );
}
