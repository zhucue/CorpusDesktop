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
import { answerParts, fmtChars, hasContent, isThinking, pendingCalls, plainText, scrubIds, thinkingChars, thinkingText, type ChainMessage } from "./chain";
import { Markdown } from "./Markdown";

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

/** Chinese names of the arguments shown in the expanded step; IDs and scope objects are never shown. */
const ARG_LABELS: Record<string, string> = {
  query: "查询式",
  q: "检索词",
  node: "节点词",
  window: "窗口",
  unit: "单位",
  n: "n",
  top: "前",
  min_freq: "最低频次",
  measures: "指标",
  measure: "指标",
  pos: "词性",
  pos_pattern: "词性序列",
  field: "字段",
  bins: "区间",
  kind: "类型",
  name: "名称",
  title: "标题",
  format: "格式",
  source: "来源",
  method: "方法",
  label: "标签",
  head: "head",
  document_title: "文档",
  document_ordinal: "第几个文档",
  sentence_index: "句",
  token_index: "词",
  sort: "排序",
};

function argValue(k: string, v: unknown): string {
  if (k === "sentence_index" || k === "src_sentence_index") return `第 ${Number(v) + 1} 句`;
  if (Array.isArray(v) && v.every((x) => typeof x !== "object")) return v.join("、");
  return typeof v === "string" ? v : JSON.stringify(v);
}

function argsText(args: Record<string, unknown>): React.ReactNode[] {
  return Object.entries(args ?? {})
    .filter(([k, v]) => ARG_LABELS[k] && v !== null && v !== undefined && !(typeof v === "object" && !Array.isArray(v)))
    .slice(0, 6)
    .map(([k, v], i) => {
      const text = scrubIds(argValue(k, v));
      const shown = text.length > 60 ? `${text.slice(0, 60)}…` : text;
      return (
        <span key={k}>
          {i > 0 && "　"}
          {ARG_LABELS[k]} {KEY_ARGS.includes(k) ? <b>{shown}</b> : shown}
        </span>
      );
    });
}

const STATE_TEXT: Partial<Record<ToolCall["state"], string>> = {
  running: "运行中",
  cancelled: "已取消",
  needs_confirmation: "待确认",
  confirmed: "已确认",
  declined: "已取消",
};
const STATE_CLASS: Record<ToolCall["state"], string> = {
  running: "active",
  succeeded: "done",
  failed: "failed",
  cancelled: "failed",
  needs_confirmation: "pending",
  confirmed: "done",
  declined: "failed",
};

/** One tool call as a compact row: family icon, title, key argument, result, state dot; `detail` adds the arguments. */
function Step({ call, detail }: { call: ToolCall; detail?: boolean }) {
  const view = TOOL_VIEW[call.name];
  const cls = STATE_CLASS[call.state] ?? "done";
  const res = scrubIds(call.state === "failed" ? call.result_summary || "失败" : (STATE_TEXT[call.state] ?? call.result_summary));
  const key = keyArg(call.args);
  const args = detail ? argsText(call.args) : [];
  return (
    <li className={`step ${cls}`} data-state={call.state}>
      <Icon name={view?.icon ?? "tool"} size={14} className="step-ic" />
      <div className="step-row">
        <span className="step-title">{view?.title ?? call.name}</span>
        {key && <b className="step-key">{scrubIds(key)}</b>}
        <span className="step-res" title={res}>
          {res}
        </span>
        <span className="step-dot" aria-hidden />
      </div>
      {args.length > 0 && <div className="step-args">{args}</div>}
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
  const visible = scrubIds(thinking.slice(0, shownThinking));
  // Two-line ticker: the latest reasoning as one flowing line pair (blank lines would leave a line empty).
  const ticker = visible.replace(/\s+/g, " ").trim().slice(-240);
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
              <span>{ticker}</span>
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
              {/* Tool steps first: a long reasoning text would push them out of the 40vh box. */}
              {m.tools.length > 0 && (
                <ol className="steps">
                  {m.tools.map((t) => (
                    <Step key={t.id} call={t} detail />
                  ))}
                </ol>
              )}
              {visible && <div className="think-text">{visible}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TextPart({ text, streaming }: { text: string; streaming: boolean }) {
  const shown = useTypewriter(text, streaming);
  return <Markdown text={scrubIds(text.slice(0, shown))} caret={streaming ? <span className="caret" aria-hidden /> : null} />;
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

/**
 * Confirm card for the write tools the assistant proposed (contracts/p2.md 第十二节). Buttons only on the latest
 * message (`onConfirm` given); older cards show what happened.
 */
export function ConfirmCard({ m, onConfirm }: { m: ChainMessage; onConfirm?: (ids: string[], action: "execute" | "decline") => Promise<void> }) {
  const [busy, setBusy] = useState<"execute" | "decline" | null>(null);
  const proposals = m.tools.filter((t) => t.confirm && ["needs_confirmation", "confirmed", "declined"].includes(t.state));
  if (!proposals.length) return null;
  const pending = pendingCalls(m);
  const open = pending.length > 0 && !!onConfirm && m.status !== "running";
  const state = pending.length ? (open ? null : "未执行") : proposals.some((t) => t.state === "confirmed") ? "已执行" : "已取消";
  const act = async (action: "execute" | "decline") => {
    setBusy(action);
    try {
      await onConfirm?.(
        pending.map((t) => t.id),
        action,
      );
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="confirm-card" role="group" aria-label="确认操作" data-state={state ?? "pending"}>
      {proposals.map((t) => (
        <div className="cc-item" key={t.id}>
          <Icon name={TOOL_VIEW[t.name]?.icon ?? "tool"} size={14} className="cc-ic" />
          <div className="cc-body">
            <div className="cc-title">{t.confirm!.title}</div>
            {t.confirm!.lines.length > 0 && (
              <ul className="cc-lines">
                {t.confirm!.lines.map((l, i) => (
                  <li key={i}>{scrubIds(l)}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ))}
      <div className="cc-actions">
        {open ? (
          <>
            <button className="btn p s" type="button" disabled={!!busy} onClick={() => void act("execute")}>
              <Icon name={busy === "execute" ? "loader" : "check"} size={14} />
              执行
            </button>
            <button className="btn s" type="button" disabled={!!busy} onClick={() => void act("decline")}>
              取消
            </button>
          </>
        ) : (
          <span className="cc-state">
            <Icon name={state === "已执行" ? "circlecheck" : "circlex"} size={14} />
            {state}
          </span>
        )}
      </div>
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

export function AiMessage({
  m,
  onRegenerate,
  onConfirm,
  noteTitle,
}: {
  m: ChainMessage;
  onRegenerate?: () => void;
  onConfirm?: (ids: string[], action: "execute" | "decline") => Promise<void>;
  noteTitle?: string;
}) {
  const [copied, setCopied] = useState(false);
  const content = hasContent(m);
  const chainShown = m.tools.length > 0 || !!thinkingText(m) || m.status === "running";
  return (
    <div className="msg-ai" data-status={m.status}>
      <ThinkingChain m={m} />
      <Answer m={m} />
      <ConfirmCard m={m} onConfirm={onConfirm} />
      {m.status === "stopped" && !chainShown && (
        <div className="ans-stopped">
          <Icon name="stop" size={14} />
          已停止
        </div>
      )}
      {m.status !== "running" && (content || onRegenerate) && (
        <div className="ans-actions">
          {content && (
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
          )}
          {onRegenerate && (
            <button className="btn xs" type="button" onClick={onRegenerate}>
              <Icon name="retry" size={14} />
              重新生成
            </button>
          )}
          {m.status === "done" && content && noteTitle != null && <NoteActions m={m} noteTitle={noteTitle} />}
        </div>
      )}
    </div>
  );
}
