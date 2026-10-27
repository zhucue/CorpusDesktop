import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { ToolCall } from "../../api";
import { Icon } from "../../components/Icon";
import { TOOL_VIEW } from "../../components/global/tools";
import { reducedMotion } from "../../theme/motion";
import { answerParts, plainText, thinkingText, type ChainMessage } from "./chain";

const UiBlock = lazy(() => import("../../openui/UiBlock"));

/** Reveal `text` 2–3 characters every 16–32 ms while `active`; jumps to the end otherwise. */
export function useTypewriter(text: string, active: boolean): number {
  const [shown, setShown] = useState(active ? 0 : text.length);
  const target = useRef(text.length);
  target.current = text.length;
  useEffect(() => {
    if (!active || reducedMotion()) {
      setShown(text.length);
      return;
    }
    let t: ReturnType<typeof setTimeout>;
    const step = () => {
      setShown((n) => {
        if (n >= target.current) return n;
        return Math.min(target.current, n + (Math.random() < 0.3 ? 3 : 2));
      });
      t = setTimeout(step, 16 + Math.random() * 16);
    };
    t = setTimeout(step, 16);
    return () => clearTimeout(t);
  }, [active, text.length]);
  return active ? Math.min(shown, text.length) : text.length;
}

function argsText(args: Record<string, unknown>): React.ReactNode[] {
  return Object.entries(args ?? {})
    .slice(0, 5)
    .map(([k, v], i) => {
      const s = typeof v === "string" ? `"${v}"` : JSON.stringify(v);
      const short = s && s.length > 60 ? `${s.slice(0, 60)}…` : s;
      return (
        <span key={k}>
          {i > 0 && " "}
          {k}=
          {k === "query" || k === "node" || k === "q" ? <b>{short}</b> : short}
        </span>
      );
    });
}

function Step({ call }: { call: ToolCall }) {
  const view = TOOL_VIEW[call.name];
  const cls = call.state === "running" ? "active" : call.state === "succeeded" ? "done" : "failed";
  const res =
    call.state === "running" ? "运行中" : call.state === "cancelled" ? "已取消" : call.state === "failed" ? call.result_summary || "失败" : call.result_summary;
  return (
    <li className={`step ${cls}`} data-state={call.state}>
      <span className="step-node">
        {call.state === "succeeded" ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path className="chk" pathLength={1} d="M20 6 9 17l-5-5" />
          </svg>
        ) : call.state === "failed" || call.state === "cancelled" ? (
          <Icon name="x" />
        ) : (
          <Icon name={view?.icon ?? "tool"} />
        )}
      </span>
      <div className="step-card">
        <div className="step-top">
          <span className="step-tool">{call.name}</span>
          <span className="step-title">{view?.title ?? ""}</span>
          <span className="step-res" title={res}>
            {res}
          </span>
        </div>
        {Object.keys(call.args ?? {}).length > 0 && <div className="step-args">{argsText(call.args)}</div>}
      </div>
    </li>
  );
}

export function chainLabel(m: ChainMessage, now: number): { text: string; shimmer: boolean } {
  const n = m.tools.length;
  if (m.status === "stopped") return { text: `已停止 · ${n} 次工具调用`, shimmer: false };
  if (m.status === "error") return { text: `出错 · ${n} 次工具调用`, shimmer: false };
  const running = m.tools.find((t) => t.state === "running");
  if (m.status === "running" && (running || m.answerAt == null)) {
    if (running) return { text: TOOL_VIEW[running.name]?.label ?? `正在调用 ${running.name}…`, shimmer: true };
    return { text: "正在思考…", shimmer: true };
  }
  // Live messages: time until the answer started. Stored messages: the recorded duration.
  const ms = m.answerAt != null ? m.answerAt - m.startedAt : (m.durationMs ?? now - m.startedAt);
  const secs = Math.max(0, ms / 1000);
  return { text: `已思考 ${secs.toFixed(1)} 秒 · ${n} 次工具调用`, shimmer: false };
}

/** Thinking chain: shimmer header → tool timeline → collapses to "已思考 N 秒 · N 次工具调用". */
export function ThinkingChain({ m }: { m: ChainMessage }) {
  const thinking = thinkingText(m);
  const live = m.status === "running" && (m.answerAt == null || m.tools.some((t) => t.state === "running"));
  const [override, setOverride] = useState<boolean | null>(null);
  useEffect(() => setOverride(null), [live]);
  const open = override ?? live;
  const label = chainLabel(m, Date.now());
  const shownThinking = useTypewriter(thinking, m.status === "running");
  if (!m.tools.length && !thinking && m.status !== "running") return null;
  return (
    <div className={`think ${live ? "running" : ""}`} data-open={open ? "true" : "false"}>
      <button className="think-head" type="button" aria-expanded={open} onClick={() => setOverride(!open)}>
        <Icon name="spark" className="spark-ic" />
        <span key={label.text} className={`think-label swap ${label.shimmer ? "shimmer-text" : ""}`}>
          {label.text}
        </span>
        <Icon name="down" className="chev" />
      </button>
      <div className="think-body">
        <div className="think-inner">
          <div className="think-flow">
            {thinking && <div className="think-text">{thinking.slice(0, shownThinking)}</div>}
            {m.tools.length > 0 && (
              <ol className="steps">
                {m.tools.map((t) => (
                  <Step key={t.id} call={t} />
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Inline formatting for answer text: `code` and [n] citations. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`\n]+`|\[\d+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("`") && p.endsWith("`") && p.length > 1 ? (
          <code key={i}>{p.slice(1, -1)}</code>
        ) : /^\[\d+\]$/.test(p) ? (
          <span key={i} className="cite">
            {p.slice(1, -1)}
          </span>
        ) : (
          p
        ),
      )}
    </>
  );
}

function TextPart({ text, streaming }: { text: string; streaming: boolean }) {
  const shown = useTypewriter(text, streaming);
  const visible = text.slice(0, shown);
  const paras = visible.split(/\n{2,}/);
  return (
    <>
      {paras.map((p, i) => (
        <p key={i}>
          <Inline text={p.replace(/^\s*[-*]\s+/gm, "· ").replace(/\*\*([^*]+)\*\*/g, "$1")} />
          {streaming && i === paras.length - 1 && <span className="caret" aria-hidden />}
        </p>
      ))}
    </>
  );
}

export function Answer({ m }: { m: ChainMessage }) {
  const parts = answerParts(m);
  const streaming = m.status === "running";
  let ui = 0;
  return (
    <div className="answer">
      {parts.map((p, i) => {
        const last = i === parts.length - 1;
        if (p.type === "text") return p.text.trim() ? <TextPart key={i} text={p.text} streaming={streaming && last} /> : null;
        if (p.type === "ui")
          return (
            <Suspense key={i} fallback={<span className="skel h28" />}>
              <UiBlock lang={p.lang} streaming={streaming && last} index={ui++} />
            </Suspense>
          );
        return null;
      })}
      {streaming && parts.length === 0 && m.answerAt != null && <span className="caret" aria-hidden />}
      {m.error && (
        <div className="alert err" role="alert">
          <Icon name="alert" size={14} />
          <span>
            {m.error.message || "运行失败"}
            <span className="err-code">{m.error.code}</span>
          </span>
        </div>
      )}
    </div>
  );
}

export function AiMessage({ m, onRegenerate }: { m: ChainMessage; onRegenerate?: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="msg-ai" data-status={m.status}>
      <ThinkingChain m={m} />
      <Answer m={m} />
      {m.status !== "running" && (
        <div className="ans-actions">
          <button
            className="btn xs"
            type="button"
            onClick={() => {
              void navigator.clipboard?.writeText(plainText(m)).then(() => setCopied(true));
            }}
          >
            <Icon name={copied ? "check" : "copy"} size={14} />
            {copied ? "已复制" : "复制"}
          </button>
          {onRegenerate && (
            <button className="btn xs" type="button" onClick={onRegenerate}>
              <Icon name="retry" size={14} />
              重新生成
            </button>
          )}
        </div>
      )}
    </div>
  );
}
