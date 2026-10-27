import { useQueryClient } from "@tanstack/react-query";
import { Input, Popconfirm, Popover, Select, Tabs } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import type { LabelDef, Layer, Relation, SentenceSpans, Span } from "../../api";
import { DiffRows, diffCounts, type DiffKind } from "../../components/annot/DiffRows";
import { SpanText, type FlowPiece } from "../../components/annot/SpanText";
import { cpSlice } from "../../components/annot/spans";
import { Empty, ErrorAlert, Skeleton } from "../../components/common";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { fmt } from "../../lib/format";
import { AgreementTab } from "./Agreement";
import { useLabelSets, useLayerDocs } from "./data";
import { LabelPanel } from "./LabelPanel";
import { useAnnotatorView, useSpanActions, useSpanSentence, useSpanSentences, useSpanWindow } from "./spanData";
import { flowRelations, flowSpans, isHumanSource, isSuggested, sortSpans, spanDiffTokens, spanKeyCommand, spanSentenceDone, type SpanCommand } from "./spanModel";
import { Stream, typingTarget } from "./Stream";
import { StatsTab } from "./Tabs";
import { sourceText, statusView } from "./Workspace";

type Tab = "edit" | "diff" | "stats" | "agreement";
type Sel = { kind: "span" | "rel"; id: string } | null;

/** Span / relation review: text flow with spans, label panel, relations between two spans. */
export default function SpanWorkspace({
  layer,
  layers,
  projectId,
  canAnnotate,
  canManage,
  leftTop,
}: {
  layer: Layer;
  layers: Layer[];
  projectId: string;
  canAnnotate: boolean;
  canManage: boolean;
  leftTop?: React.ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const isRel = layer.kind === "relation";
  const spanLayer = isRel ? layers.find((l) => l.id === layer.base_layer_id) : layer;
  const spanLayerId = isRel ? (layer.base_layer_id ?? layer.id) : layer.id;
  const relLayerId = isRel ? layer.id : null;

  const docs = useLayerDocs(layer.id);
  const seenStatus = useRef(layer.status);
  useEffect(() => {
    if (seenStatus.current === layer.status) return;
    seenStatus.current = layer.status;
    qc.invalidateQueries({ queryKey: ["layer-docs", layer.id] });
    qc.invalidateQueries({ queryKey: ["span-sentences", layer.id] });
  }, [layer.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const labelSets = useLabelSets(projectId);
  const spanSet = labelSets.data?.find((s) => s.id === spanLayer?.label_set_id);
  const relSet = isRel ? labelSets.data?.find((s) => s.id === layer.label_set_id) : undefined;
  const spanOrder = useMemo(() => (spanSet?.labels ?? []).map((l) => l.name), [spanSet]);
  const docList = docs.data ?? [];

  const docParam = params.get("doc");
  const docId =
    docParam && (!docs.data || docList.some((d) => d.document_id === docParam))
      ? docParam
      : ((docList.find((d) => d.pending > 0) ?? docList[0])?.document_id ?? null);
  const doc = docList.find((d) => d.document_id === docId);

  const [statusFilter, setStatusFilter] = useState<"pending" | "all">("pending");
  const list = useSpanSentences(layer.id, docId, statusFilter);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sParam = params.get("s");
  const sIdx = sParam != null && sParam !== "" && docParam === docId ? Number(sParam) : (items[0]?.sentence_index ?? null);
  const inList = items.find((x) => x.sentence_index === sIdx);
  const one = useSpanSentence(layer.id, docId, sIdx, !inList && !list.isPending);
  const s: SentenceSpans | undefined = inList ?? one.data ?? undefined;

  const [view, setView] = useState<"sent" | "para">("sent");
  const win = useSpanWindow(layer.id, docId, sIdx, view === "para");
  const annot = useAnnotatorView(layer, canManage, projectId);

  const flowSents = useMemo(() => {
    if (!s) return [];
    if (view !== "para" || !win.data) return [s];
    const around = win.data.items.filter((x) => x.document_id === s.document_id && Math.abs(x.sentence_index - s.sentence_index) <= 2);
    return [...around.filter((x) => x.sentence_index !== s.sentence_index), s].sort((a, b) => a.sentence_index - b.sentence_index);
  }, [s, view, win.data]);
  const spans = useMemo(() => flowSents.flatMap((x) => x.spans).filter(annot.keep), [flowSents, annot.keep]);
  const relations = useMemo(() => flowSents.flatMap((x) => x.relations).filter(annot.keep), [flowSents, annot.keep]);
  const ownSpans = useMemo(() => sortSpans((s?.spans ?? []).filter(annot.keep)), [s, annot.keep]);
  const ownRels = useMemo(() => (s?.relations ?? []).filter(annot.keep), [s, annot.keep]);
  const viewSpans = useMemo(() => flowSpans(spans, spanOrder), [spans, spanOrder]);
  const viewRels = useMemo(() => flowRelations(relations), [relations]);
  const pieces: FlowPiece[] = flowSents.map((x) => ({ key: `${x.sentence_index}`, cp: x.start_cp, text: x.text, dim: x.sentence_index !== s?.sentence_index }));
  const flowText = (a: number, b: number) => {
    const p = flowSents.find((x) => a >= x.start_cp && a < x.end_cp);
    return p ? cpSlice(p.text, a - p.start_cp, b - p.start_cp) : "";
  };

  const sentKey = `${docId}:${sIdx}`;
  const [selState, setSelState] = useState<{ key: string; sel: Sel }>({ key: "", sel: null });
  const [pendingState, setPendingState] = useState<{ key: string; start: number; end: number } | null>(null);
  const [draftState, setDraftState] = useState<{ key: string; from: string; to?: string } | null>(null);
  const sel = selState.key === sentKey ? selState.sel : null;
  const pending = pendingState?.key === sentKey ? pendingState : null;
  const draft = draftState?.key === sentKey ? draftState : null;
  const selSpan = sel?.kind === "span" ? spans.find((x) => x.id === sel.id) : undefined;
  const selRel = sel?.kind === "rel" ? relations.find((x) => x.id === sel.id) : undefined;
  const ownerOf = (spanId: string) => flowSents.find((x) => x.spans.some((y) => y.id === spanId)) ?? s;
  const select = (next: Sel) => {
    setSelState({ key: sentKey, sel: next });
    setPendingState(null);
  };

  const [tab, setTab] = useState<Tab>(() => (["diff", "stats", "agreement"].includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "edit"));
  const searchRef = useRef<HTMLInputElement>(null);
  const act = useSpanActions({ listLayerId: layer.id, spanLayerId, relationLayerId: relLayerId, projectId });

  const pendingHere = ownSpans.filter(isSuggested).length + ownRels.filter(isSuggested).length;
  const remaining = docList.reduce((n, d) => n + d.pending, 0);

  function go(d: string | null, idx: number | null) {
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (d) n.set("doc", d);
        else n.delete("doc");
        if (idx == null) n.delete("s");
        else n.set("s", String(idx));
        return n;
      },
      { replace: true },
    );
  }

  async function moveSentence(delta: 1 | -1) {
    const i = items.findIndex((x) => x.sentence_index === sIdx);
    if (delta > 0 && i === items.length - 1 && list.hasNextPage) {
      const r = await list.fetchNextPage();
      const n = (r.data?.pages.flatMap((p) => p.items) ?? [])[i + 1];
      if (n) go(docId, n.sentence_index);
      return;
    }
    if (delta > 0 && i === items.length - 1) {
      const k = docList.findIndex((d) => d.document_id === docId);
      const next = docList.slice(k + 1).find((d) => d.pending > 0) ?? docList[k + 1];
      if (next) go(next.document_id, null);
      return;
    }
    const j = i < 0 ? 0 : Math.max(0, Math.min(items.length - 1, i + delta));
    const n = items[j];
    if (n && n.sentence_index !== sIdx) go(docId, n.sentence_index);
  }

  /** Next suggestion in this sentence after `fromId` (spans in text order, then relations), wrapping. */
  function advance(fromId: string) {
    const order: Sel[] = [...ownSpans.map((x) => ({ kind: "span" as const, id: x.id })), ...ownRels.map((x) => ({ kind: "rel" as const, id: x.id }))];
    const sugg = new Set([...ownSpans.filter(isSuggested).map((x) => x.id), ...ownRels.filter(isSuggested).map((x) => x.id)]);
    sugg.delete(fromId);
    const k = order.findIndex((o) => o!.id === fromId);
    for (let d = 1; d <= order.length; d++) {
      const o = order[(k + d + order.length) % order.length];
      if (o && sugg.has(o.id)) return select(o);
    }
  }

  function pick(label: LabelDef | string) {
    const name = typeof label === "string" ? label : label.name;
    if (!s || !canAnnotate) return;
    if (draft?.to) {
      const from = draft.from;
      const to = draft.to;
      setDraftState(null);
      void act.createRelation(ownerOf(from)!, from, to, name).then((r) => r && select({ kind: "rel", id: r.id }));
      return;
    }
    if (pending) {
      setPendingState(null);
      void act.createSpan(s, pending.start, pending.end, name).then((r) => r && select({ kind: "span", id: r.id }));
      return;
    }
    if (selSpan) {
      const owner = ownerOf(selSpan.id)!;
      if (selSpan.label === name && selSpan.status !== "rejected") {
        if (selSpan.status === "suggested") void act.patchSpan(owner, selSpan, { action: "confirm" });
      } else void act.patchSpan(owner, selSpan, { action: "modify", label: name });
      advance(selSpan.id);
    } else if (selRel) {
      if (selRel.label === name && selRel.status !== "rejected") {
        if (selRel.status === "suggested") void act.patchRelation(s, selRel, { action: "confirm" });
      } else void act.patchRelation(s, selRel, { action: "modify", label: name });
      advance(selRel.id);
    }
  }

  function confirm() {
    if (!s || !canAnnotate) return;
    if (selSpan) {
      if (selSpan.status !== "confirmed") void act.patchSpan(ownerOf(selSpan.id)!, selSpan, { action: "confirm" });
      advance(selSpan.id);
    } else if (selRel) {
      if (selRel.status !== "confirmed") void act.patchRelation(s, selRel, { action: "confirm" });
      advance(selRel.id);
    } else {
      const first = ownSpans.find(isSuggested) ?? ownSpans[0];
      if (first) select({ kind: "span", id: first.id });
    }
  }

  function reject() {
    if (!s || !canAnnotate) return;
    if (selSpan && selSpan.status !== "rejected") {
      void act.patchSpan(ownerOf(selSpan.id)!, selSpan, { action: "reject" });
      advance(selSpan.id);
    } else if (selRel && selRel.status !== "rejected") {
      void act.patchRelation(s, selRel, { action: "reject" });
      advance(selRel.id);
    }
  }

  function startRelation() {
    if (!relLayerId || !selSpan || !canAnnotate) return;
    setDraftState({ key: sentKey, from: selSpan.id });
  }

  function run(cmd: SpanCommand) {
    switch (cmd.type) {
      case "sentence":
        void moveSentence(cmd.delta);
        return;
      case "span": {
        if (!ownSpans.length) return;
        const i = selSpan ? ownSpans.findIndex((x) => x.id === selSpan.id) : -1;
        const n = ownSpans[i < 0 ? (cmd.delta > 0 ? 0 : ownSpans.length - 1) : (i + cmd.delta + ownSpans.length) % ownSpans.length];
        select({ kind: "span", id: n.id });
        return;
      }
      case "edit":
        searchRef.current?.focus();
        return;
      case "cancel":
        setPendingState(null);
        setDraftState(null);
        select(null);
        return;
      case "relation":
        startRelation();
        return;
      case "confirm":
        confirm();
        return;
      case "reject":
        reject();
        return;
      case "label":
        pick(cmd.label);
    }
  }

  const relMode = !!draft?.to || sel?.kind === "rel";
  const panelSet = relMode ? relSet : spanSet;
  const panelLabels = useMemo(() => panelSet?.labels ?? [], [panelSet]);
  const runRef = useRef(run);
  runRef.current = run;
  useEffect(() => {
    if (tab !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || typingTarget(e.target)) return;
      if ((e.key === "Enter" || e.key === " ") && e.target instanceof Element && e.target.closest("button, a, [role='button'], [role='tab'], [role='switch']")) return;
      const cmd = spanKeyCommand(e, { labels: panelLabels, relations: !!relLayerId });
      if (!cmd) return;
      e.preventDefault();
      runRef.current(cmd);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [tab, panelLabels, relLayerId]);

  function onSelectSpan(id: string | null, e: React.MouseEvent) {
    if (draft && !draft.to) {
      if (id && id !== draft.from) setDraftState({ ...draft, to: id });
      else setDraftState(null);
      return;
    }
    if (id && e.shiftKey && relLayerId && selSpan && id !== selSpan.id && canAnnotate) {
      setDraftState({ key: sentKey, from: selSpan.id, to: id });
      return;
    }
    setDraftState(null);
    select(id ? { kind: "span", id } : null);
  }

  /* ---------- left ---------- */
  const stream = (
    <Stream
      title="句子"
      unit="句子"
      docs={docList}
      docsPending={docs.isPending}
      docId={docId}
      onDoc={(v) => go(v, null)}
      filter={statusFilter}
      onFilter={setStatusFilter}
      items={items.map((it) => ({ key: it.sentence_index, text: it.text, done: spanSentenceDone({ ...it, spans: it.spans.filter(annot.keep), relations: it.relations.filter(annot.keep) }) }))}
      current={sIdx}
      onPick={(k) => go(docId, k)}
      loading={list.isPending}
      error={docs.error ?? list.error}
      hasMore={list.hasNextPage}
      loadingMore={list.isFetchingNextPage}
      onMore={() => list.fetchNextPage()}
    />
  );

  /* ---------- centre ---------- */
  const done = s ? spanSentenceDone({ ...s, spans: ownSpans, relations: ownRels }) : false;
  const editor = (
    <section className="card" aria-label="编辑器">
      <div className="card-head">
        <h2>{isRel ? "片段与关系" : "片段"}</h2>
        {sIdx != null && (
          <span className="mono small muted ellipsis" style={{ maxWidth: 220 }}>
            {doc?.title ?? docId} · 句 {sIdx + 1}
          </span>
        )}
        {s && <span className={`tag ${done ? "t-ok" : "t-run"}`}>{done ? "已完成" : "待校对"}</span>}
        <div className="grow" />
        <span className="remain-head">
          剩余 <b className="num">{fmt(remaining)}</b> 句
        </span>
        {annot.options.length > 0 && (
          <Select size="small" style={{ width: 150 }} aria-label="标注者" value={annot.value ?? ""} options={annot.options} onChange={(v: string) => annot.setValue(v || null)} />
        )}
        <div className="seg-mini" role="tablist" aria-label="文本范围">
          <button type="button" role="tab" aria-selected={view === "sent"} onClick={() => setView("sent")}>
            句
          </button>
          <button type="button" role="tab" aria-selected={view === "para"} onClick={() => setView("para")}>
            段
          </button>
        </div>
        {s && <PinButton input={{ kind: "text", ref: { document_id: s.document_id, start_cp: s.start_cp, end_cp: s.end_cp }, text: s.text, source: `${layer.name} · ${doc?.title ?? s.document_id} · 句 ${s.sentence_index + 1}` }} />}
      </div>
      <div className="card-pad">
        <ErrorAlert error={one.error ?? win.error} />
        {!docId ? (
          <Empty icon="file" text={docs.isPending ? "加载中" : "该层没有文档"} />
        ) : !s ? (
          list.isPending || one.isFetching ? <Skeleton rows={3} /> : <Empty icon="filetext" text="选择句子" />
        ) : (
          <>
            <div className="legend" style={{ justifyContent: "flex-end", marginBottom: 4 }}>
              <span>
                <span className="lg-s" />
                建议
              </span>
              <span>
                <span className="lg-c" />
                已确认
              </span>
            </div>
            <SpanText
              key={sentKey}
              pieces={pieces}
              spans={viewSpans}
              relations={viewRels}
              selected={selSpan?.id ?? null}
              selectedRelation={selRel?.id ?? null}
              relFrom={draft?.from ?? null}
              pending={pending}
              onSelectText={canAnnotate ? (r) => (setDraftState(null), setSelState({ key: sentKey, sel: null }), setPendingState({ key: sentKey, ...r })) : undefined}
              onSelectSpan={onSelectSpan}
              onSelectRelation={(id) => (setDraftState(null), select({ kind: "rel", id }))}
              onBoundary={canAnnotate ? (id, start, end) => {
                const sp = spans.find((x) => x.id === id);
                if (sp) void act.patchSpan(ownerOf(id)!, sp, { action: "modify", start_cp: start, end_cp: end });
              } : undefined}
              label={s.text}
            />
          </>
        )}
      </div>
    </section>
  );

  /* ---------- right ---------- */
  const spanText = (id: string) => spans.find((x) => x.id === id)?.text ?? "?";
  const right = (
    <aside className="col gap-16" aria-label="标签">
      <section className="card card-pad col gap-12 cur-card" aria-label="当前">
        <div className="row between">
          <h2>当前</h2>
          {selSpan && <span className={`tag ${statusView[selSpan.status].cls}`}>{statusView[selSpan.status].label}</span>}
          {selRel && <span className={`tag ${statusView[selRel.status].cls}`}>{statusView[selRel.status].label}</span>}
          {pending && <span className="tag t-gray">新片段</span>}
        </div>
        {draft ? (
          <div className="col gap-8">
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className="cur-form">{spanText(draft.from)}</span>
              <Icon name="right" size={14} />
              <span className="cur-form">{draft.to ? spanText(draft.to) : "…"}</span>
            </div>
            <span className="small muted">{draft.to ? "选择关系标签" : "点击目标片段"}</span>
            <button className="btn s" type="button" onClick={() => setDraftState(null)}>
              取消<span className="kbd">Esc</span>
            </button>
          </div>
        ) : pending ? (
          <div className="col gap-8">
            <span className="cur-form">{flowText(pending.start, pending.end)}</span>
            <span className="small muted">选择标签</span>
            <button className="btn s" type="button" onClick={() => setPendingState(null)}>
              取消<span className="kbd">Esc</span>
            </button>
          </div>
        ) : selSpan ? (
          <SpanCard
            span={selSpan}
            layer={spanLayer ?? layer}
            canAnnotate={canAnnotate}
            canRelate={!!relLayerId}
            annotator={annot.multi && annot.options.length ? annot.email(selSpan.annotator_id ?? "") : null}
            onConfirm={() => run({ type: "confirm" })}
            onReject={() => run({ type: "reject" })}
            onEdit={() => run({ type: "edit" })}
            onRelate={startRelation}
            onDelete={() => void act.deleteSpan(ownerOf(selSpan.id)!, selSpan).then((ok) => ok && select(null))}
            onPatch={(body) => void act.patchSpan(ownerOf(selSpan.id)!, selSpan, body)}
          />
        ) : selRel ? (
          <RelationCard
            rel={selRel}
            from={spanText(selRel.from_span_id)}
            to={spanText(selRel.to_span_id)}
            layer={layer}
            canAnnotate={canAnnotate}
            onConfirm={() => run({ type: "confirm" })}
            onReject={() => run({ type: "reject" })}
            onEdit={() => run({ type: "edit" })}
          />
        ) : (
          <span className="small muted">{canAnnotate ? "拖选文字新建片段，或点击片段" : "点击片段"}</span>
        )}
        <div className="remain">
          <span className="small muted">本句</span>
          <span className="num">{pendingHere}</span>
          <span className="small muted">处待确认</span>
        </div>
        {!canAnnotate && <div className="small muted">查看者只读</div>}
      </section>
      <LabelPanel
        ref={searchRef}
        set={panelSet}
        current={selSpan && selSpan.status !== "rejected" ? selSpan.label : selRel && selRel.status !== "rejected" ? selRel.label : null}
        disabled={!canAnnotate || !(selSpan || selRel || pending || draft?.to)}
        colorPos={false}
        onPick={pick}
      />
      <section className="card card-pad" aria-label="快捷键">
        <div className="row" style={{ marginBottom: 10 }}>
          <Icon name="keyboard" size={14} className="muted" />
          <h2>快捷键</h2>
        </div>
        <div className="keys">
          <span>确认 / 拒绝</span>
          <span>
            <span className="kbd">Enter</span> <span className="kbd">Del</span>
          </span>
          <span>上一句 / 下一句</span>
          <span>
            <span className="kbd">K</span> <span className="kbd">J</span>
          </span>
          <span>选片段</span>
          <span>
            <span className="kbd">←</span> <span className="kbd">→</span>
          </span>
          {relLayerId && (
            <>
              <span>连关系</span>
              <span>
                <span className="kbd">R</span> 或 <span className="kbd">Shift</span>+点击
              </span>
            </>
          )}
          <span>全部快捷键</span>
          <span>
            <span className="kbd">?</span>
          </span>
        </div>
      </section>
    </aside>
  );

  const tabs = [
    { key: "edit", label: <span className="row" style={{ gap: 6 }}><Icon name="pen" size={14} />编辑</span> },
    { key: "diff", label: <span className="row" style={{ gap: 6 }}><Icon name="diff" size={14} />预标差异</span> },
    { key: "stats", label: <span className="row" style={{ gap: 6 }}><Icon name="chart" size={14} />统计</span> },
    ...(layer.mode === "multi" ? [{ key: "agreement", label: <span className="row" style={{ gap: 6 }}><Icon name="users" size={14} />一致性</span> }] : []),
  ];

  return (
    <div className="ws">
      <div className="col gap-16" style={{ minWidth: 0 }}>
        {leftTop}
        {stream}
      </div>
      <div className={`col gap-16 ws-center ${tab !== "edit" ? "wide" : ""}`} style={{ minWidth: 0 }}>
        <Tabs className="stat-tabs" activeKey={tab} onChange={(k) => setTab(k as Tab)} items={tabs} />
        <div className="panel-in" key={tab}>
          {tab === "edit" ? (
            editor
          ) : tab === "diff" ? (
            <SpanDiffTab
              layer={layer}
              docId={docId}
              keep={annot.keep}
              onOpen={(idx) => {
                go(docId, idx);
                setTab("edit");
              }}
            />
          ) : tab === "stats" ? (
            <StatsTab layer={layer} />
          ) : (
            <AgreementTab layer={layer} labels={(isRel ? relSet : spanSet)?.labels ?? []} canAdjudicate={canManage} />
          )}
        </div>
      </div>
      {tab === "edit" && right}
    </div>
  );
}

/* ---------- current span / relation ---------- */

function SpanCard({
  span,
  layer,
  canAnnotate,
  canRelate,
  annotator,
  onConfirm,
  onReject,
  onEdit,
  onRelate,
  onDelete,
  onPatch,
}: {
  span: Span;
  layer: Layer;
  canAnnotate: boolean;
  canRelate: boolean;
  annotator: string | null;
  onConfirm: () => void;
  onReject: () => void;
  onEdit: () => void;
  onRelate: () => void;
  onDelete: () => void;
  onPatch: (body: { action: "modify"; start_cp?: number; end_cp?: number; attrs?: Record<string, string> }) => void;
}) {
  const attrs = span.attrs ?? {};
  const move = (start: number, end: number) => {
    if (start < end && start >= 0) onPatch({ action: "modify", start_cp: start, end_cp: end });
  };
  return (
    <>
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <span className={`cur-form ${span.status === "rejected" ? "struck" : ""}`}>{span.text}</span>
        <span className={`mono sub ${span.status === "rejected" ? "struck" : ""}`}>{span.label}</span>
      </div>
      <dl className="kv" style={{ gridTemplateColumns: "56px 1fr", margin: 0 }}>
        <dt>来源</dt>
        <dd className="mono">{sourceText(span.source, layer.source_model)}</dd>
        {span.model_label && span.model_label !== span.label && (
          <>
            <dt>预标</dt>
            <dd className="mono">{span.model_label}</dd>
          </>
        )}
        {annotator && (
          <>
            <dt>标注者</dt>
            <dd className="ellipsis">{annotator}</dd>
          </>
        )}
        <dt>位置</dt>
        <dd className="mono">
          {span.start_cp}–{span.end_cp}
        </dd>
        <dt>属性</dt>
        <dd>
          <span className="row wrap" style={{ gap: 4 }}>
            {Object.entries(attrs).map(([k, v]) => (
              <span key={k} className="tag t-gray mono">
                {k}={v}
              </span>
            ))}
            {canAnnotate && (
              <Popover trigger="click" placement="left" destroyOnHidden content={<AttrsEditor value={attrs} onSave={(a) => onPatch({ action: "modify", attrs: a })} />}>
                <button className="btn xs ghost" type="button" aria-label="编辑属性">
                  <Icon name="edit" size={14} />
                  {Object.keys(attrs).length ? "" : "添加"}
                </button>
              </Popover>
            )}
          </span>
        </dd>
      </dl>
      {canAnnotate && (
        <div className="bound-row" role="group" aria-label="边界">
          <span className="small muted">起点</span>
          <button className="btn xs" type="button" aria-label="起点左移" onClick={() => move(span.start_cp - 1, span.end_cp)}>
            −1
          </button>
          <button className="btn xs" type="button" aria-label="起点右移" onClick={() => move(span.start_cp + 1, span.end_cp)}>
            +1
          </button>
          <span className="small muted" style={{ marginLeft: 8 }}>
            终点
          </span>
          <button className="btn xs" type="button" aria-label="终点左移" onClick={() => move(span.start_cp, span.end_cp - 1)}>
            −1
          </button>
          <button className="btn xs" type="button" aria-label="终点右移" onClick={() => move(span.start_cp, span.end_cp + 1)}>
            +1
          </button>
        </div>
      )}
      <div className="act">
        <button className="btn ok" type="button" disabled={!canAnnotate} onClick={onConfirm}>
          <Icon name="check" size={14} />
          确认<span className="kbd">Enter</span>
        </button>
        <button className="btn" type="button" disabled={!canAnnotate} onClick={onEdit}>
          <Icon name="edit" size={14} />
          修改<span className="kbd">E</span>
        </button>
        <button className="btn danger" type="button" disabled={!canAnnotate} onClick={onReject}>
          <Icon name="x" size={14} />
          拒绝<span className="kbd">Del</span>
        </button>
      </div>
      {canAnnotate && (canRelate || isHumanSource(span.source)) && (
        <div className="row" style={{ gap: 8 }}>
          {canRelate && (
            <button className="btn s grow" type="button" onClick={onRelate}>
              <Icon name="link" size={14} />
              连关系<span className="kbd">R</span>
            </button>
          )}
          {isHumanSource(span.source) && (
            <Popconfirm title="删除这个片段？" okText="删除" okButtonProps={{ danger: true }} cancelText="取消" onConfirm={onDelete}>
              <button className="btn s ghost" type="button">
                <Icon name="trash" size={14} />
                删除
              </button>
            </Popconfirm>
          )}
        </div>
      )}
    </>
  );
}

function RelationCard({
  rel,
  from,
  to,
  layer,
  canAnnotate,
  onConfirm,
  onReject,
  onEdit,
}: {
  rel: Relation;
  from: string;
  to: string;
  layer: Layer;
  canAnnotate: boolean;
  onConfirm: () => void;
  onReject: () => void;
  onEdit: () => void;
}) {
  return (
    <>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <span className="cur-form">{from}</span>
        <Icon name="right" size={14} />
        <span className="cur-form">{to}</span>
      </div>
      <dl className="kv" style={{ gridTemplateColumns: "56px 1fr", margin: 0 }}>
        <dt>关系</dt>
        <dd className={`mono ${rel.status === "rejected" ? "struck" : ""}`}>{rel.label}</dd>
        <dt>来源</dt>
        <dd className="mono">{sourceText(rel.source, layer.source_model)}</dd>
      </dl>
      <div className="act">
        <button className="btn ok" type="button" disabled={!canAnnotate} onClick={onConfirm}>
          <Icon name="check" size={14} />
          确认<span className="kbd">Enter</span>
        </button>
        <button className="btn" type="button" disabled={!canAnnotate} onClick={onEdit}>
          <Icon name="edit" size={14} />
          修改<span className="kbd">E</span>
        </button>
        <button className="btn danger" type="button" disabled={!canAnnotate} onClick={onReject}>
          <Icon name="x" size={14} />
          拒绝<span className="kbd">Del</span>
        </button>
      </div>
    </>
  );
}

/** Key / value attributes of a span. Empty keys are dropped. */
export function AttrsEditor({ value, onSave }: { value: Record<string, string>; onSave: (attrs: Record<string, string>) => void }) {
  const [rows, setRows] = useState<[string, string][]>(() => (Object.keys(value).length ? Object.entries(value) : [["", ""]]));
  const set = (i: number, k: 0 | 1, v: string) => setRows((r) => r.map((x, j) => (j === i ? ((k === 0 ? [v, x[1]] : [x[0], v]) as [string, string]) : x)));
  return (
    <div className="col gap-8 attrs-ed" style={{ width: 260 }}>
      {rows.map(([k, v], i) => (
        <div className="row" key={i} style={{ gap: 6 }}>
          <Input size="small" value={k} placeholder="属性" aria-label="属性名" onChange={(e) => set(i, 0, e.target.value)} />
          <Input size="small" value={v} placeholder="值" aria-label="属性值" onChange={(e) => set(i, 1, e.target.value)} />
          <button className="btn xs ghost icon" type="button" aria-label="删除属性" onClick={() => setRows((r) => r.filter((_, j) => j !== i))}>
            <Icon name="x" size={14} />
          </button>
        </div>
      ))}
      <div className="row between">
        <button className="btn xs ghost" type="button" onClick={() => setRows((r) => [...r, ["", ""]])}>
          <Icon name="plus" size={14} />
          添加
        </button>
        <button className="btn xs p" type="button" onClick={() => onSave(Object.fromEntries(rows.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v.trim()])))}>
          保存
        </button>
      </div>
    </div>
  );
}

/* ---------- diff ---------- */

const KIND_VIEW: [DiffKind, string, string][] = [
  ["changed", "改动", "var(--warning-solid)"],
  ["confirmed", "确认", "var(--success-solid)"],
  ["rejected", "拒绝", "var(--error-solid)"],
  ["pending", "待办", "var(--text-4)"],
];

/** 预标差异 for spans and relations: model label vs human result per sentence (P3 DiffRows). */
function SpanDiffTab({ layer, docId, keep, onOpen }: { layer: Layer; docId: string | null; keep: (x: { annotator_id: string | null }) => boolean; onOpen: (idx: number) => void }) {
  const q = useSpanSentences(layer.id, docId, "all");
  const [filter, setFilter] = useState<DiffKind | "all">("all");
  const blocks = useMemo(
    () =>
      (q.data?.pages.flatMap((p) => p.items) ?? [])
        .map((s) => {
          const toks = spanDiffTokens({ ...s, spans: s.spans.filter(keep), relations: s.relations.filter(keep) });
          return { s, toks, c: diffCounts(toks) };
        })
        .filter((b) => b.toks.length > 0),
    [q.data, keep],
  );
  const total = blocks.reduce((acc, b) => ({ changed: acc.changed + b.c.changed, confirmed: acc.confirmed + b.c.confirmed, rejected: acc.rejected + b.c.rejected, pending: acc.pending + b.c.pending }), { changed: 0, confirmed: 0, rejected: 0, pending: 0 });
  const shown = filter === "all" ? blocks : blocks.filter((b) => b.c[filter] > 0);
  return (
    <section className="card" aria-label="预标差异">
      <div className="card-head">
        <h2>预标 / 人工</h2>
        <span className="mono small muted">{layer.source_model}</span>
      </div>
      <div className="card-pad" style={{ paddingBottom: 6 }}>
        <div className="diff-sum" role="group" aria-label="差异计数">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
            全部 <b>{fmt(blocks.length)}</b> 句
          </button>
          {KIND_VIEW.map(([k, label, color]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(filter === k ? "all" : k)} data-kind={k}>
              <span className="dot" style={{ color }} />
              {label} <b>{fmt(total[k])}</b>
            </button>
          ))}
        </div>
      </div>
      <ErrorAlert error={q.error} style={{ margin: 16 }} />
      {q.isPending && docId ? (
        <Skeleton rows={4} />
      ) : shown.length === 0 && !q.error ? (
        <Empty icon="diff" text="本文档没有片段" />
      ) : (
        <div className="diff-list">
          {shown.map(({ s, toks, c }, i) => (
            <div className="diff-blk" key={s.sentence_index} style={{ ["--i" as string]: Math.min(i, 12) }}>
              <div className="row">
                <span className="mono small muted grow ellipsis">
                  句 {s.sentence_index + 1} · {s.text}
                </span>
                {c.changed > 0 && <span className="tag t-warn">{c.changed} 处改动</span>}
                {c.rejected > 0 && <span className="tag t-err">{c.rejected} 处拒绝</span>}
                {c.pending > 0 && <span className="tag t-gray">{c.pending} 处待办</span>}
                <button className="btn xs ghost" type="button" onClick={() => onOpen(s.sentence_index)}>
                  <Icon name="edit" size={14} />
                  编辑
                </button>
              </div>
              <DiffRows tokens={toks} modelSource={layer.source_model} />
            </div>
          ))}
        </div>
      )}
      {q.hasNextPage && (
        <div className="card-foot">
          <button className="btn s ghost" type="button" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
            {q.isFetchingNextPage && <span className="spin" />}
            加载更多
          </button>
        </div>
      )}
    </section>
  );
}

