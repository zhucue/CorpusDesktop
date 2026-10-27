import { useQueryClient } from "@tanstack/react-query";
import { Select, Tabs } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import type { Alignment, Layer, SentencePair } from "../../api";
import { toggleLink, type LinkGroup } from "../../components/annot/align";
import { AlignGraph } from "../../components/annot/AlignGraph";
import { Empty, Skeleton } from "../../components/common";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { useCorpora } from "../../lib/data";
import { fmt } from "../../lib/format";
import { AgreementTab } from "./Agreement";
import { AlignmentStatsCard } from "./AlignStats";
import { useLayerDocs } from "./data";
import { useAlignActions, useAlignPairs, useAnnotatorView } from "./spanData";
import { fmtScore, isSuggested, pairDone, tokenForms } from "./spanModel";
import { Stream, typingTarget } from "./Stream";
import { StatsTab } from "./Tabs";
import { sourceText, statusView } from "./Workspace";

type Tab = "edit" | "stats" | "agreement";

const groupsOf = (alignments: Alignment[]): LinkGroup[] =>
  alignments.filter((a) => a.level !== "sentence").map((a) => ({ id: a.id, src: a.src_tokens ?? [], tgt: a.tgt_tokens ?? [], status: a.status }));

/** Bilingual alignment review: source and target columns, word links toggled by clicking, sentence target select. */
export default function AlignWorkspace({
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
  const docs = useLayerDocs(layer.id);
  const seenStatus = useRef(layer.status);
  useEffect(() => {
    if (seenStatus.current === layer.status) return;
    seenStatus.current = layer.status;
    qc.invalidateQueries({ queryKey: ["layer-docs", layer.id] });
    qc.invalidateQueries({ queryKey: ["align-pairs", layer.id] });
  }, [layer.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const corpora = useCorpora(projectId);
  const cname = (id: string | null | undefined) => corpora.data?.items.find((c) => c.id === id)?.name ?? "";
  const word = layer.level !== "sentence";
  const docList = docs.data ?? [];
  const docParam = params.get("doc");
  const docId =
    docParam && (!docs.data || docList.some((d) => d.document_id === docParam))
      ? docParam
      : ((docList.find((d) => d.pending > 0) ?? docList[0])?.document_id ?? null);
  const doc = docList.find((d) => d.document_id === docId);

  const list = useAlignPairs(layer.id, docId);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sParam = params.get("s");
  const sIdx = sParam != null && sParam !== "" && docParam === docId ? Number(sParam) : (items[0]?.src.sentence_index ?? null);
  const annot = useAnnotatorView(layer, canManage, projectId);
  // A source sentence can have several targets (one pair each) or none (tgt null).
  const pairs = useMemo(() => items.filter((p) => p.src.sentence_index === sIdx), [items, sIdx]);
  const srcRows = useMemo(() => {
    const m = new Map<number, SentencePair[]>();
    for (const p of items) m.set(p.src.sentence_index, [...(m.get(p.src.sentence_index) ?? []), p]);
    return [...m.values()];
  }, [items]);
  const mine = (p: SentencePair) => p.alignments.filter(annot.keep);
  const here = pairs.flatMap(mine);
  const suggested = here.filter(isSuggested).length;
  const remaining = docList.reduce((n, d) => n + d.pending, 0);
  const fallbackTgtDoc = items.find((p) => p.tgt)?.tgt?.document_id;
  const act = useAlignActions(layer.id, projectId);
  const [tab, setTab] = useState<Tab>(() => (["stats", "agreement"].includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "edit"));

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

  async function movePair(delta: 1 | -1) {
    const keys = srcRows.map((r) => r[0].src.sentence_index);
    const i = keys.indexOf(sIdx ?? -1);
    if (delta > 0 && i === keys.length - 1 && list.hasNextPage) {
      const r = await list.fetchNextPage();
      const n = (r.data?.pages.flatMap((p) => p.items) ?? []).find((p) => p.src.sentence_index > (sIdx ?? -1));
      if (n) go(docId, n.src.sentence_index);
      return;
    }
    if (delta > 0 && i === keys.length - 1) {
      const k = docList.findIndex((d) => d.document_id === docId);
      const next = docList.slice(k + 1).find((d) => d.pending > 0) ?? docList[k + 1];
      if (next) go(next.document_id, null);
      return;
    }
    const n = keys[i < 0 ? 0 : Math.max(0, Math.min(keys.length - 1, i + delta))];
    if (n != null && n !== sIdx) go(docId, n);
  }

  /** Word links: optimistic groups, then the API operations in order. */
  function toggle(p: SentencePair, i: number, j: number) {
    if (!canAnnotate) return;
    const groups = groupsOf(mine(p));
    const { ops, next } = toggleLink(groups, i, j);
    const keepOthers = p.alignments.filter((a) => !groups.some((g) => g.id === a.id));
    const asAlign = (g: LinkGroup): Alignment => {
      const old = p.alignments.find((a) => a.id === g.id);
      return old
        ? { ...old, src_tokens: g.src, tgt_tokens: g.tgt, status: g.status }
        : { id: g.id, level: "word", src_tokens: g.src, tgt_tokens: g.tgt, score: null, source: "human", status: "confirmed", revision: 0, annotator_id: annot.value };
    };
    act.setAlignments(p, [...keepOthers, ...next.map(asAlign)]);
    let tmp = 0;
    void act.run(
      ops.map((op) => () => {
        if (op.op === "create") return act.create(p, `tmp:${tmp++}`, { src_tokens: op.src, tgt_tokens: op.tgt });
        const a = p.alignments.find((x) => x.id === op.id)!;
        return op.op === "reject" ? act.patchOne(p, a, { action: "reject" }) : act.patchOne(p, a, { action: "modify", src_tokens: op.src, tgt_tokens: op.tgt });
      }),
    );
  }

  function setAll(status: "confirmed" | "rejected") {
    if (!canAnnotate) return;
    const steps: (() => Promise<unknown>)[] = [];
    for (const p of pairs) {
      const todo = mine(p).filter((a) => (status === "confirmed" ? a.status === "suggested" : a.status !== "rejected"));
      if (!todo.length) continue;
      act.setAlignments(p, p.alignments.map((a) => (todo.includes(a) ? { ...a, status } : a)));
      for (const a of todo) steps.push(() => act.patchOne(p, a, { action: status === "confirmed" ? "confirm" : "reject" }));
    }
    if (steps.length) void act.run(steps);
  }

  function changeTarget(p: SentencePair, tgtIdx: number) {
    if (!canAnnotate) return;
    const sentAl = mine(p).find((a) => a.level === "sentence");
    const reload = (ok: boolean) => {
      if (ok) void qc.invalidateQueries({ queryKey: ["align-pairs", layer.id, docId] });
    };
    if (sentAl) void act.run([() => act.patchOne(p, sentAl, { action: "modify", tgt_sentence_index: tgtIdx })]).then(reload);
    else {
      const tgtDoc = p.tgt?.document_id ?? fallbackTgtDoc;
      if (tgtDoc) void act.run([() => act.create(p, "tmp:s", { tgt_document_id: tgtDoc, tgt_sentence_index: tgtIdx })]).then(reload);
    }
  }

  const runRef = useRef({ setAll, movePair });
  runRef.current = { setAll, movePair };
  useEffect(() => {
    if (tab !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || typingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if ((e.key === "Enter" || e.key === " ") && e.target instanceof Element && e.target.closest("button, a, [role='button'], [role='tab'], [role='switch']")) return;
      const k = e.key.toLowerCase();
      if (e.key === "Enter") {
        runRef.current.setAll("confirmed");
        void runRef.current.movePair(1);
      } else if (e.key === "Delete" || e.key === "Backspace") runRef.current.setAll("rejected");
      else if (k === "j") void runRef.current.movePair(1);
      else if (k === "k") void runRef.current.movePair(-1);
      else return;
      e.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [tab]);

  /** Target sentence choices: target sentences of the loaded pairs in that target document. */
  function targetOptions(tgtDoc: string | undefined) {
    const seen = new Map<number, string>();
    for (const p of items) if (p.tgt && p.tgt.document_id === tgtDoc) seen.set(p.tgt.sentence_index, p.tgt.text);
    return [...seen.entries()].sort((a, b) => a[0] - b[0]).map(([i, t]) => ({ value: i, label: `句 ${i + 1} · ${t}` }));
  }

  const stream = (
    <Stream
      title="句对"
      unit="句对"
      docs={docList}
      docsPending={docs.isPending}
      docId={docId}
      onDoc={(v) => go(v, null)}
      items={srcRows.map((r) => ({ key: r[0].src.sentence_index, text: r[0].src.text, done: r.every((p) => pairDone(mine(p))) }))}
      current={sIdx}
      onPick={(k) => go(docId, k)}
      loading={list.isPending}
      error={docs.error ?? list.error}
      hasMore={list.hasNextPage}
      loadingMore={list.isFetchingNextPage}
      onMore={() => list.fetchNextPage()}
    />
  );

  const pairHead = (p: SentencePair) => {
    const al = mine(p);
    const sent = al.find((a) => a.level === "sentence");
    const score = sent?.score ?? (al.length === 1 ? al[0].score : null);
    return (
      <div className="row small bi-head">
        <span className="mono muted grow ellipsis">{p.tgt ? `句 ${p.src.sentence_index + 1} ↔ 句 ${p.tgt.sentence_index + 1}` : `句 ${p.src.sentence_index + 1}`}</span>
        {sent && <span className={`tag ${statusView[sent.status].cls}`}>{statusView[sent.status].label}</span>}
        {sent && <span className="mono muted">{sourceText(sent.source, layer.source_model)}</span>}
        <span className="muted">
          候选分数 <b className="mono">{fmtScore(score)}</b>
        </span>
      </div>
    );
  };

  const editor = (
    <section className="card" aria-label="双语对照">
      <div className="card-head">
        <h2>{word ? "词对齐" : "句对齐"}</h2>
        {sIdx != null && (
          <span className="mono small muted ellipsis" style={{ maxWidth: 240 }}>
            {doc?.title ?? docId} · 句 {sIdx + 1}
          </span>
        )}
        {pairs.length > 0 && <span className={`tag ${suggested ? "t-run" : "t-ok"}`}>{suggested ? `${suggested} 条建议` : "已确认"}</span>}
        <div className="grow" />
        <span className="remain-head">
          剩余 <b className="num">{fmt(remaining)}</b> 句
        </span>
        {annot.options.length > 0 && (
          <Select size="small" style={{ width: 150 }} aria-label="标注者" value={annot.value ?? ""} options={annot.options} onChange={(v: string) => annot.setValue(v || null)} />
        )}
        <div className="legend">
          <span>
            <span className="lg-s" />
            建议
          </span>
          <span>
            <span className="lg-c" />
            已确认
          </span>
        </div>
        {pairs[0] && (
          <PinButton
            input={{ kind: "text", ref: { document_id: pairs[0].src.document_id }, text: `${pairs[0].src.text} ↔ ${pairs.map((p) => p.tgt?.text ?? "").join(" ")}`, source: `${layer.name} · 句 ${pairs[0].src.sentence_index + 1}` }}
          />
        )}
      </div>
      <div className="col">
        {!docId ? (
          <Empty icon="file" text={docs.isPending ? "加载中" : "该层没有文档"} />
        ) : pairs.length === 0 ? (
          list.isPending ? <Skeleton rows={4} /> : <Empty icon="columns" text="选择句对" />
        ) : (
          pairs.map((p) => (
            <div className="bi-pair" key={`${p.tgt?.document_id}:${p.tgt?.sentence_index}`}>
              {pairHead(p)}
              {word && p.tgt ? (
                <>
                  <div className="row small muted">
                    <span className="grow ellipsis">{cname(layer.src_corpus_id) || "原文"}</span>
                    <span className="grow ellipsis" style={{ textAlign: "right" }}>
                      {cname(layer.tgt_corpus_id) || "译文"}
                    </span>
                  </div>
                  <AlignGraph
                    key={`${docId}:${sIdx}:${p.tgt.sentence_index}`}
                    src={tokenForms(p.src.tokens)}
                    tgt={tokenForms(p.tgt.tokens)}
                    links={groupsOf(mine(p)).map((g) => ({ key: String(g.id), src: g.src, tgt: g.tgt, status: g.status }))}
                    onToggle={canAnnotate ? (i, j) => toggle(p, i, j) : undefined}
                  />
                </>
              ) : (
                <div className="sent-pair">
                  <div className="sp-src">{p.src.text}</div>
                  <div className={`sp-link ${mine(p).find((a) => a.level === "sentence")?.status ?? "none"}`} aria-hidden />
                  <div className="sp-tgt">{p.tgt ? p.tgt.text : <span className="muted">未对齐</span>}</div>
                </div>
              )}
              {!word && (
                <div className="row small" style={{ gap: 8 }}>
                  <span className="muted">目标句</span>
                  <Select
                    size="small"
                    style={{ flex: 1, minWidth: 0 }}
                    aria-label="目标句"
                    placeholder="选择目标句"
                    disabled={!canAnnotate}
                    value={p.tgt?.sentence_index}
                    options={targetOptions(p.tgt?.document_id ?? fallbackTgtDoc)}
                    onChange={(v: number) => changeTarget(p, v)}
                  />
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  );

  const right = (
    <aside className="col gap-16" aria-label="当前句对">
      <section className="card card-pad col gap-12 cur-card" aria-label="当前">
        <div className="row between">
          <h2>当前</h2>
          {pairs.length > 0 && <span className={`tag ${suggested ? "t-run" : "t-ok"}`}>{suggested ? "待确认" : "已完成"}</span>}
        </div>
        {pairs.length ? (
          <>
            <dl className="kv" style={{ gridTemplateColumns: "64px 1fr", margin: 0 }}>
              <dt>目标句</dt>
              <dd className="num">{fmt(pairs.filter((p) => p.tgt).length)}</dd>
              {word && (
                <>
                  <dt>词对</dt>
                  <dd className="num">{fmt(groupsOf(here).filter((g) => g.status !== "rejected").reduce((n, g) => n + g.src.length * g.tgt.length, 0))}</dd>
                </>
              )}
            </dl>
            <div className="act two">
              <button
                className="btn ok"
                type="button"
                disabled={!canAnnotate}
                onClick={() => {
                  setAll("confirmed");
                  void movePair(1);
                }}
              >
                <Icon name="check" size={14} />
                确认<span className="kbd">Enter</span>
              </button>
              <button className="btn danger" type="button" disabled={!canAnnotate} onClick={() => setAll("rejected")}>
                <Icon name="x" size={14} />
                拒绝<span className="kbd">Del</span>
              </button>
            </div>
            <div className="remain">
              <span className="small muted">本句</span>
              <span className="num">{suggested}</span>
              <span className="small muted">条待确认</span>
            </div>
          </>
        ) : (
          <span className="small muted">选择句对</span>
        )}
        {!canAnnotate && <div className="small muted">查看者只读</div>}
      </section>
      <section className="card card-pad" aria-label="快捷键">
        <div className="row" style={{ marginBottom: 10 }}>
          <Icon name="keyboard" size={14} className="muted" />
          <h2>快捷键</h2>
        </div>
        <div className="keys">
          {word && (
            <>
              <span>加 / 删连线</span>
              <span className="small">点原词，再点译词</span>
            </>
          )}
          <span>确认 / 拒绝</span>
          <span>
            <span className="kbd">Enter</span> <span className="kbd">Del</span>
          </span>
          <span>上一句 / 下一句</span>
          <span>
            <span className="kbd">K</span> <span className="kbd">J</span>
          </span>
        </div>
      </section>
    </aside>
  );

  const tabs = [
    { key: "edit", label: <span className="row" style={{ gap: 6 }}><Icon name="columns" size={14} />双语对照</span> },
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
          ) : tab === "stats" ? (
            <div className="col gap-20">
              <AlignmentStatsCard projectId={projectId} layers={layers.filter((l) => l.id === layer.id)} initial={layer.id} />
              <StatsTab layer={layer} />
            </div>
          ) : (
            <AgreementTab layer={layer} labels={[]} canAdjudicate={canManage} />
          )}
        </div>
      </div>
      {tab === "edit" && right}
    </div>
  );
}

