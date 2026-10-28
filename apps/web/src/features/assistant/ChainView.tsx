import { App } from "antd";
import { lazy, Suspense, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { errorText, type ToolCall } from "../../api";
import { ResultContext } from "../../components/results/cards";
import { knowledgeHref } from "../knowledge/data";
import { NotePicker, writeToNote, type NoteTarget } from "../knowledge/NotePicker";
import { Icon } from "../../components/Icon";
import { TOOL_VIEW } from "../../components/global/tools";
import { reducedMotion } from "../../theme/motion";
import { answerParts, fmtChars, isThinking, plainText, thinkingChars, thinkingText, type ChainMessage } from "./chain";

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

function argText(v: unknown): string {
  const s = typeof v === "string" ? `"${v}"` : JSON.stringify(v);
  return s && s.length > 60 ? `${s.slice(0, 60)}…` : (s ?? "");
}

const KEY_ARGS = ["query", "q", "node", "term", "text", "title", "word"];

/** The argument shown in bold on the step row (query, node word, term…). */
function keyArg(args: Record<string, unknown>): string | null {
  for (const k of KEY_ARGS) {
    const v = args?.[k];
    if (typeof v === "string" && v.trim()) return argText(v);
  }
  return null;
}

function argsText(args: Record<string, unknown>): React.ReactNode[] {
  return Object.entries(args ?? {})
    .slice(0, 5)
    .map(([k, v], i) => (
      <span key={k}>
        {i > 0 && " "}
        {k}={KEY_ARGS.includes(k) ? <b>{argText(v)}</b> : argText(v)}
      </span>
    ));
}

/** One tool call as a compact row: family icon, title, key argument, result, state dot; `detail` adds the raw call. */
function Step({ call, detail }: { call: ToolCall; detail?: boolean }) {
  const view = TOOL_VIEW[call.name];
  const cls = call.state === "running" ? "active" : call.state === "succeeded" ? "done" : "failed";
  const res =
    call.state === "running" ? "运行中" : call.state === "cancelled" ? "已取消" : call.state === "failed" ? call.result_summary || "失败" : call.result_summary;
  const key = keyArg(call.args);
  return (
    <li className={`step ${cls}`} data-state={call.state}>
      <Icon name={view?.icon ?? "tool"} size={14} className="step-ic" />
      <div className="step-row">
        <span className="step-title" title={call.name}>
          {view?.title ?? call.name}
        </span>
        {key && <b className="step-key">{key}</b>}
        <span className="step-res" title={res}>
          {res}
        </span>
        <span className="step-dot" aria-hidden />
      </div>
      {detail && (
        <div className="step-args">
          <span className="step-tool">{call.name}</span>
          {Object.keys(call.args ?? {}).length > 0 && <> {argsText(call.args)}</>}
        </div>
      )}
    </li>
  );
}

/** Header text: live "思考中 · 3.2 秒 · 1.2k 字 · 正在检索语料…"; afterwards one trace line. */
export function chainLabel(m: ChainMessage, now: number): { text: string; live: boolean; meta: string; tool: string | null } {
  const n = m.tools.length;
  const chars = thinkingChars(m);
  const charText = chars ? ` · ${fmtChars(chars)}` : "";
  if (m.status === "stopped") return { text: `已停止 · ${n} 次工具调用`, live: false, meta: "", tool: null };
  if (m.status === "error") return { text: `出错 · ${n} 次工具调用`, live: false, meta: "", tool: null };
  if (isThinking(m)) {
    const running = m.tools.find((t) => t.state === "running");
    const secs = Math.max(0, (now - m.startedAt) / 1000);
    const tool = running ? (TOOL_VIEW[running.name]?.label ?? `正在调用 ${running.name}…`) : null;
    return { text: "思考中", live: true, meta: `${secs.toFixed(1)} 秒${charText}`, tool };
  }
  // Live messages: time until the answer started. Stored messages: the recorded duration.
  const ms = m.answerAt != null ? m.answerAt - m.startedAt : (m.durationMs ?? now - m.startedAt);
  const secs = Math.max(0, ms / 1000);
  return { text: `已思考 ${secs.toFixed(1)} 秒 · ${n} 次工具调用${charText}`, live: false, meta: "", tool: null };
}

/** Re-render every `ms` while `active`; returns the current time. */
function useNow(active: boolean, ms = 100): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [active, ms]);
  return active ? now : Date.now();
}

/** While `active`, keep a scroll box pinned to the bottom as `dep` changes, unless the reader scrolled up in it. */
function useStickToBottom<T extends HTMLElement>(dep: unknown, active: boolean, threshold = 24) {
  const ref = useRef<T>(null);
  const stick = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && active && stick.current) el.scrollTop = el.scrollHeight;
  }, [dep, active]);
  const onScroll = () => {
    const el = ref.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
  };
  return { ref, onScroll };
}

/**
 * Thinking chain after Kimi CLI's compact indicator. While thinking: one header line (思考中 + dots, seconds,
 * characters, current tool), a two-line ticker of the latest reasoning and the latest tool row — the chat does
 * not grow. Click → full reasoning and tool timeline in a 40vh scroll box. When the answer starts it settles
 * into the trace line "已思考 N 秒 · N 次工具调用 · N 字"; a manual expand is kept.
 */
export function ThinkingChain({ m }: { m: ChainMessage }) {
  const thinking = thinkingText(m);
  const live = isThinking(m);
  const [expanded, setExpanded] = useState<boolean | null>(null);
  const open = expanded ?? false;
  const now = useNow(live);
  const label = chainLabel(m, now);
  const shownThinking = useTypewriter(thinking, m.status === "running");
  const visible = thinking.slice(0, shownThinking);
  const full = useStickToBottom<HTMLDivElement>(`${visible.length}:${m.tools.length}:${open}`, m.status === "running");
  const bodyId = useId();
  if (!m.tools.length && !thinking && m.status !== "running") return null;
  const latest = m.tools.find((t) => t.state === "running") ?? m.tools.at(-1);
  return (
    <div className={`think ${live ? "running" : ""}`} data-open={open ? "true" : "false"}>
      <button className="think-head" type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setExpanded(!open)}>
        <Icon name="spark" className="spark-ic" />
        <span key={label.live ? "live" : label.text} className="think-label swap">
          {label.text}
          {label.live && (
            <span className="dots" aria-hidden>
              <i />
              <i />
              <i />
            </span>
          )}
        </span>
        {label.meta && <span className="think-meta">{label.meta}</span>}
        {label.tool && (
          <span key={label.tool} className="think-tool swap">
            {label.tool}
          </span>
        )}
        <Icon name="down" size={14} className="chev" />
      </button>
      {live && !open && (thinking || latest) && (
        <div className="think-peek">
          {thinking && (
            <div className="think-ticker" aria-hidden>
              <span>{visible.slice(-400)}</span>
            </div>
          )}
          {latest && (
            <ol className="steps">
              <Step key={latest.id} call={latest} />
            </ol>
          )}
        </div>
      )}
      <div className="think-body" id={bodyId}>
        <div className="think-inner">
          {open && (
            <div className="think-scroll" ref={full.ref} onScroll={full.onScroll}>
              {visible && <div className="think-text">{visible}</div>}
              {m.tools.length > 0 && (
                <ol className="steps">
                  {m.tools.map((t) => (
                    <Step key={t.id} call={t} detail />
                  ))}
                </ol>
              )}
            </div>
          )}
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

/** 保存为笔记 / 插入到笔记: the answer as Markdown (ui parts become tables or links). */
function NoteActions({ m, noteTitle }: { m: ChainMessage; noteTitle: string }) {
  const { projectId } = useContext(ResultContext);
  const { message } = App.useApp();
  const [picking, setPicking] = useState(false);
  const [saving, setSaving] = useState(false);
  if (!projectId) return null;

  async function write(t: NoteTarget) {
    const { messageMarkdown } = await import("../knowledge/uiMarkdown");
    const note = await writeToNote(projectId, t, messageMarkdown(m.parts, projectId));
    message.success(
      <span>
        {"noteId" in t ? "已插入到笔记" : "已保存为笔记"}「{note.title}」，<Link to={knowledgeHref(projectId, { tab: "notes", doc: note.id })}>打开笔记</Link>
      </span>,
    );
  }

  return (
    <>
      <button
        className="btn xs"
        type="button"
        disabled={saving}
        onClick={async () => {
          setSaving(true);
          try {
            await write({ newTitle: noteTitle });
          } catch (e) {
            message.error(errorText(e));
          } finally {
            setSaving(false);
          }
        }}
      >
        <Icon name="note" size={14} />
        保存为笔记
      </button>
      <button className="btn xs" type="button" onClick={() => setPicking(true)}>
        <Icon name="plus" size={14} />
        插入到笔记
      </button>
      <NotePicker open={picking} projectId={projectId} title="插入到笔记" defaultTitle={noteTitle} onClose={() => setPicking(false)} onPick={write} />
    </>
  );
}

export function AiMessage({ m, onRegenerate, noteTitle }: { m: ChainMessage; onRegenerate?: () => void; noteTitle?: string }) {
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
          {m.status === "done" && noteTitle != null && <NoteActions m={m} noteTitle={noteTitle} />}
        </div>
      )}
    </div>
  );
}
