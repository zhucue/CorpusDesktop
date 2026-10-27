import { useQueryClient } from "@tanstack/react-query";
import { Popconfirm, Select, Tabs } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import type { AnnotStatus, LabelDef, Layer } from "../../api";
import { DepGraph } from "../../components/annot/DepGraph";
import { Empty, ErrorAlert, Skeleton, Tip } from "../../components/common";
import { PinButton } from "../../components/global/evidence";
import { Icon } from "../../components/Icon";
import { fmt } from "../../lib/format";
import { posCat } from "../../lib/pos";
import { useAnnotActions, useLabelSets, useLayerDocs, useSentence, useSentenceList } from "./data";
import { LabelPanel } from "./LabelPanel";
import { graphOf, isPending, keyCommand, nextPending, tokenViews, type Command, type TokView } from "./model";
import { DiffTab, StatsTab } from "./Tabs";

export const statusView: Record<AnnotStatus, { label: string; cls: string }> = {
  suggested: { label: "建议", cls: "t-run" },
  confirmed: { label: "已确认", cls: "t-ok" },
  modified: { label: "已修改", cls: "t-warn" },
  rejected: { label: "已拒绝", cls: "t-err" },
};

export function sourceText(source: string, model: string): string {
  if (source === "system") return model || "系统层";
  if (source.startsWith("model:")) return source.slice(6);
  if (source.startsWith("human:")) return "人工";
  return source;
}

type Tab = "edit" | "diff" | "stats";

function typingTarget(t: EventTarget | null): boolean {
  return t instanceof Element && !!t.closest("input, textarea, select, [contenteditable='true'], .ant-modal-wrap, .ant-select-dropdown, .ant-popover");
}

/** Three-column review workspace for one layer: document and sentence stream, editor (tabs), current item and labels. */
export default function Workspace({
  layer,
  projectId,
  canAnnotate,
  readOnlyNote = "查看者只读",
  leftTop,
}: {
  layer: Layer;
  projectId: string;
  canAnnotate: boolean;
  readOnlyNote?: string;
  leftTop?: React.ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const docs = useLayerDocs(layer.id);
  // Documents and sentences read while the layer was still preannotating are empty; reload them when it settles.
  const seenStatus = useRef(layer.status);
  useEffect(() => {
    if (seenStatus.current === layer.status) return;
    seenStatus.current = layer.status;
    qc.invalidateQueries({ queryKey: ["layer-docs", layer.id] });
    qc.invalidateQueries({ queryKey: ["annot-sentences", layer.id] });
  }, [layer.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const labelSets = useLabelSets(projectId);
  const set = labelSets.data?.find((s) => s.id === layer.label_set_id);
  const labels = useMemo(() => set?.labels ?? [], [set]);
  const docList = docs.data ?? [];

  const docParam = params.get("doc");
  const docId =
    docParam && (!docs.data || docList.some((d) => d.document_id === docParam))
      ? docParam
      : ((docList.find((d) => d.pending > 0) ?? docList[0])?.document_id ?? null);
  const doc = docList.find((d) => d.document_id === docId);

  const [statusFilter, setStatusFilter] = useState<"pending" | "all">("pending");
  const list = useSentenceList(layer.id, docId, statusFilter);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const sParam = params.get("s");
  const sIdx = sParam != null && sParam !== "" && docParam === docId ? Number(sParam) : (items[0]?.sentence_index ?? null);
  const seed = items.find((x) => x.sentence_index === sIdx);
  const sent = useSentence(layer.id, docId, sIdx, seed);
  const s = sent.data;
  const views = useMemo(() => (s ? tokenViews(s, layer.kind) : []), [s, layer.kind]);

  const sentKey = `${docId}:${sIdx}`;
  const [tok, setTok] = useState<{ key: string; index: number } | null>(null);
  const curTok = tok?.key === sentKey && views.some((v) => v.index === tok.index) ? tok.index : (views.find(isPending)?.index ?? views[0]?.index ?? null);
  const cur = views.find((v) => v.index === curTok) ?? null;
  const select = (index: number) => setTok({ key: sentKey, index });

  const [tab, setTab] = useState<Tab>(() => (["diff", "stats"].includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "edit"));
  const [posColor, setPosColor] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);
  const { act, confirmSentence, resetSentence } = useAnnotActions(layer, projectId);

  const pendingHere = views.filter(isPending).length;
  const remaining = docList.reduce((n, d) => n + d.pending, 0);

  function go(doc: string | null, idx: number | null) {
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (doc) n.set("doc", doc);
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
      const all = r.data?.pages.flatMap((p) => p.items) ?? [];
      const n = all[i + 1];
      if (n) go(docId, n.sentence_index);
      return;
    }
    if (delta > 0 && i === items.length - 1) {
      // End of this document: continue with the next document that still has work, so the keyboard flow never stops.
      const k = docList.findIndex((d) => d.document_id === docId);
      const next = docList.slice(k + 1).find((d) => d.pending > 0) ?? docList[k + 1];
      if (next) go(next.document_id, null);
      return;
    }
    const j = i < 0 ? 0 : Math.max(0, Math.min(items.length - 1, i + delta));
    const n = items[j];
    if (n && n.sentence_index !== sIdx) go(docId, n.sentence_index);
  }

  /** After an action on `from`, move to the next token still to review. */
  function advance(from: number) {
    const rest = views.map((v) => (v.index === from ? { ...v, status: "confirmed" as AnnotStatus } : v));
    const n = nextPending(rest, from);
    if (n != null) select(n);
  }

  function pick(label: LabelDef | string) {
    const name = typeof label === "string" ? label : label.name;
    if (!s || !cur || !canAnnotate) return;
    if (cur.label === name && cur.status !== "rejected") void act(s, { token_index: cur.index, action: "confirm" });
    else void act(s, { token_index: cur.index, action: "modify", label: name });
    advance(cur.index);
  }

  function changeHead(dep: number, head: number) {
    if (!s || !canAnnotate) return;
    select(dep);
    const v = views.find((x) => x.index === dep);
    // The same head is no modification: confirm a suggestion, leave a reviewed token as it is.
    if (v && v.head === head && v.status !== "rejected") {
      if (v.status === "suggested") void act(s, { token_index: dep, action: "confirm" });
      return;
    }
    void act(s, { token_index: dep, action: "modify", head });
  }

  function run(cmd: Command) {
    switch (cmd.type) {
      case "token": {
        const i = views.findIndex((v) => v.index === curTok);
        const n = views[Math.max(0, Math.min(views.length - 1, i + cmd.delta))];
        if (n) select(n.index);
        return;
      }
      case "sentence":
        void moveSentence(cmd.delta);
        return;
      case "posColor":
        setPosColor((v) => !v);
        return;
      case "edit":
        searchRef.current?.focus();
        return;
    }
    if (!s || !cur || !canAnnotate) return;
    if (cmd.type === "confirm") {
      void act(s, { token_index: cur.index, action: "confirm" });
      advance(cur.index);
    } else if (cmd.type === "reject") {
      if (layer.kind !== "pos") return;
      void act(s, { token_index: cur.index, action: "reject" });
      advance(cur.index);
    } else if (cmd.type === "label") pick(cmd.label);
    else if (cmd.type === "confirmSentence") {
      void confirmSentence(s);
      void moveSentence(1);
    }
  }

  const runRef = useRef(run);
  runRef.current = run;
  useEffect(() => {
    if (tab !== "edit") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || typingTarget(e.target)) return;
      if ((e.key === "Enter" || e.key === " ") && e.target instanceof Element && e.target.closest("button, a, [role='button'], [role='tab'], [role='switch']")) return;
      const cmd = keyCommand(e, { kind: layer.kind, labels });
      if (!cmd) return;
      e.preventDefault();
      runRef.current(cmd);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [tab, layer.kind, labels]);

  useEffect(() => {
    streamRef.current?.querySelector(".sent.on")?.scrollIntoView?.({ block: "nearest" });
  }, [sentKey]);

  const graph = useMemo(() => graphOf(views), [views]);
  const headOptions = useMemo(
    () => [{ value: 0, label: "0 · root" }, ...views.filter((v) => v.index !== curTok).map((v) => ({ value: v.index, label: `${v.index} · ${v.form}` }))],
    [views, curTok],
  );
  const headForm = (h: number | null) => (h == null ? "—" : h === 0 ? "root" : (views.find((v) => v.index === h)?.form ?? String(h)));

  /* ---------- left: documents and sentences ---------- */
  const stream = (
    <section className="card stream-card" aria-label="句子">
      <div className="row between" style={{ padding: "2px 6px 8px" }}>
        <h2>句子</h2>
        <div className="seg-mini" role="tablist" aria-label="句子范围">
          <button type="button" role="tab" aria-selected={statusFilter === "pending"} onClick={() => setStatusFilter("pending")}>
            待办
          </button>
          <button type="button" role="tab" aria-selected={statusFilter === "all"} onClick={() => setStatusFilter("all")}>
            全部
          </button>
        </div>
      </div>
      <div style={{ padding: "0 4px 8px" }}>
        <Select
          size="small"
          style={{ width: "100%" }}
          value={docId ?? undefined}
          placeholder="选择文档"
          aria-label="文档"
          loading={docs.isPending}
          onChange={(v: string) => go(v, null)}
          showSearch
          optionFilterProp="title"
          options={docList.map((d) => ({
            value: d.document_id,
            title: d.title,
            label: (
              <span className="row between" style={{ gap: 8 }}>
                <span className="ellipsis">{d.title}</span>
                <span className="mono small muted">
                  {fmt(d.done)} / {fmt(d.sentences)}
                </span>
              </span>
            ),
          }))}
        />
      </div>
      <ErrorAlert error={docs.error ?? list.error} style={{ margin: "0 4px 8px" }} />
      {doc && (
        <div className="row small muted doc-counts">
          <span>
            已完成 <b className="num">{fmt(doc.done)}</b>
          </span>
          <span>
            待办 <b className="num">{fmt(doc.pending)}</b>
          </span>
        </div>
      )}
      <div className="col gap-4 stream" ref={streamRef}>
        {list.isPending && docId ? (
          <Skeleton rows={5} />
        ) : items.length === 0 && docId ? (
          <Empty icon="check" text={statusFilter === "pending" ? "本文档没有待办句子" : "没有句子"}>
            {statusFilter === "pending" && (
              <button className="btn s" type="button" onClick={() => setStatusFilter("all")}>
                显示全部
              </button>
            )}
          </Empty>
        ) : (
          items.map((it) => {
            const on = it.sentence_index === sIdx;
            return (
              <button
                key={it.sentence_index}
                className={`sent ${on ? "on" : ""} ${it.status === "done" ? "done" : ""}`}
                type="button"
                aria-current={on ? "true" : undefined}
                onClick={() => go(docId, it.sentence_index)}
              >
                <span className="n">{it.sentence_index + 1}</span>
                <span className="grow">{it.text}</span>
                {it.status === "done" ? <Icon name="check" size={14} className="st" /> : on ? <span className="dot pulse" /> : null}
              </button>
            );
          })
        )}
        {list.hasNextPage && (
          <button className="btn s ghost" type="button" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
            {list.isFetchingNextPage ? <span className="spin" /> : null}
            加载更多
          </button>
        )}
      </div>
    </section>
  );

  /* ---------- centre: editor ---------- */
  const editor = (
    <section className="card" aria-label="编辑器">
      <div className="card-head">
        <h2>{layer.kind === "pos" ? "词性" : "依存"}</h2>
        {sIdx != null && (
          <span className="mono small muted ellipsis" style={{ maxWidth: 240 }}>
            {doc?.title ?? docId} · 句 {sIdx + 1}
          </span>
        )}
        {s && <span className={`tag ${s.status === "done" ? "t-ok" : "t-run"}`}>{s.status === "done" ? "已完成" : "待校对"}</span>}
        <div className="grow" />
        <span className="remain-head">
          剩余 <b className="num">{fmt(remaining)}</b> 句
        </span>
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
        <span className="pos-toggle">
          <Tip title="词性着色（P）">
            <button className="switch" type="button" role="switch" aria-checked={posColor} aria-label="词性着色" onClick={() => setPosColor((v) => !v)} />
          </Tip>
          <span className="small muted">词性着色</span>
        </span>
        {s && <PinButton input={{ kind: "text", ref: { document_id: s.document_id }, text: s.text, source: `${layer.name} · ${doc?.title ?? s.document_id} · 句 ${s.sentence_index + 1}` }} />}
      </div>
      <div className="card-pad">
        <ErrorAlert error={sent.error} />
        {!docId ? (
          <Empty icon="file" text={docs.isPending ? "加载中" : "该层没有文档"} />
        ) : !s ? (
          sent.isFetching || list.isPending ? <Skeleton rows={3} /> : <Empty icon="filetext" text="选择句子" />
        ) : layer.kind === "pos" ? (
          <PosRow views={views} selected={curTok} onSelect={select} posColor={posColor} />
        ) : (
          <div className="depwrap">
            <DepGraph
              key={sentKey}
              tokens={graph.tokens}
              arcs={graph.arcs}
              selected={curTok}
              onSelectToken={select}
              onSelectArc={select}
              onHeadChange={canAnnotate ? changeHead : undefined}
              posColor={posColor}
            />
          </div>
        )}
      </div>
    </section>
  );

  /* ---------- right: current item and labels ---------- */
  const right = (
    <aside className="col gap-16" aria-label="标签">
      <section className="card card-pad col gap-12 cur-card" aria-label="当前">
        <div className="row between">
          <h2>当前</h2>
          {cur && <span className={`tag ${statusView[cur.status].cls}`}>{statusView[cur.status].label}</span>}
        </div>
        {cur ? (
          <>
            <div className="row" style={{ gap: 10 }}>
              <span className="cur-form">{cur.form}</span>
              <span className={`mono sub ${cur.status === "rejected" ? "struck" : ""}`}>{cur.label ?? "—"}</span>
            </div>
            <dl className="kv" style={{ gridTemplateColumns: "56px 1fr", margin: 0 }}>
              <dt>来源</dt>
              <dd className="mono">{sourceText(cur.source, layer.source_model)}</dd>
              {layer.kind === "pos" && cur.ann?.model_label && cur.ann.model_label !== cur.label && (
                <>
                  <dt>预标</dt>
                  <dd className="mono">{cur.ann.model_label}</dd>
                </>
              )}
              {layer.kind === "dep" && (
                <>
                  <dt>依存</dt>
                  <dd className="mono">
                    {cur.label ?? "—"} → {headForm(cur.head)}
                  </dd>
                  <dt>中心词</dt>
                  <dd>
                    <Select
                      size="small"
                      style={{ width: "100%" }}
                      value={cur.head ?? undefined}
                      disabled={!canAnnotate}
                      aria-label="中心词"
                      options={headOptions}
                      onChange={(h: number) => changeHead(cur.index, h)}
                    />
                  </dd>
                </>
              )}
            </dl>
            <div className={`act ${layer.kind === "dep" ? "two" : ""}`}>
              <button className="btn ok" type="button" disabled={!canAnnotate} onClick={() => run({ type: "confirm" })}>
                <Icon name="check" size={14} />
                确认<span className="kbd">Enter</span>
              </button>
              <button className="btn" type="button" disabled={!canAnnotate} onClick={() => run({ type: "edit" })}>
                <Icon name="edit" size={14} />
                修改<span className="kbd">E</span>
              </button>
              {layer.kind === "pos" && (
                <button className="btn danger" type="button" disabled={!canAnnotate} onClick={() => run({ type: "reject" })}>
                  <Icon name="x" size={14} />
                  拒绝<span className="kbd">Del</span>
                </button>
              )}
            </div>
            <div className="remain">
              <span className="small muted">本句</span>
              <span className="num">{pendingHere}</span>
              <span className="small muted">处待确认</span>
              <div className="grow" />
              <Tip title="整句确认（Shift+Enter）">
                <button className="btn xs" type="button" disabled={!canAnnotate || pendingHere === 0} onClick={() => run({ type: "confirmSentence" })}>
                  整句确认
                </button>
              </Tip>
              <Popconfirm title="本句回到预标值？" okText="重置" cancelText="取消" onConfirm={() => s && resetSentence(s)} disabled={!canAnnotate}>
                <button className="btn xs ghost" type="button" disabled={!canAnnotate}>
                  重置
                </button>
              </Popconfirm>
            </div>
            {!canAnnotate && <div className="small muted">{readOnlyNote}</div>}
          </>
        ) : (
          <span className="small muted">选择一个词</span>
        )}
      </section>
      <LabelPanel ref={searchRef} set={set} current={cur?.status === "rejected" ? null : (cur?.label ?? null)} disabled={!canAnnotate || !cur} colorPos={layer.kind === "pos" && posColor} onPick={pick} />
      <section className="card card-pad" aria-label="快捷键">
        <div className="row" style={{ marginBottom: 10 }}>
          <Icon name="keyboard" size={14} className="muted" />
          <h2>快捷键</h2>
        </div>
        <div className="keys">
          <span>上一句 / 下一句</span>
          <span>
            <span className="kbd">K</span> <span className="kbd">J</span>
          </span>
          <span>选词</span>
          <span>
            <span className="kbd">←</span> <span className="kbd">→</span>
          </span>
          <span>整句确认</span>
          <span>
            <span className="kbd">Shift</span> <span className="kbd">Enter</span>
          </span>
          <span>全部快捷键</span>
          <span>
            <span className="kbd">?</span>
          </span>
        </div>
      </section>
    </aside>
  );

  return (
    <div className="ws">
      <div className="col gap-16" style={{ minWidth: 0 }}>
        {leftTop}
        {stream}
      </div>
      <div className={`col gap-16 ws-center ${tab !== "edit" ? "wide" : ""}`} style={{ minWidth: 0 }}>
        <Tabs
          className="stat-tabs"
          activeKey={tab}
          onChange={(k) => setTab(k as Tab)}
          items={[
            { key: "edit", label: <span className="row" style={{ gap: 6 }}><Icon name="pen" size={14} />编辑</span> },
            { key: "diff", label: <span className="row" style={{ gap: 6 }}><Icon name="diff" size={14} />预标差异</span> },
            { key: "stats", label: <span className="row" style={{ gap: 6 }}><Icon name="chart" size={14} />统计</span> },
          ]}
        />
        <div className="panel-in" key={tab}>
          {tab === "edit" ? (
            editor
          ) : tab === "diff" ? (
            <DiffTab
              layer={layer}
              docId={docId}
              onOpen={(idx) => {
                go(docId, idx);
                setTab("edit");
              }}
            />
          ) : (
            <StatsTab layer={layer} />
          )}
        </div>
      </div>
      {tab === "edit" && right}
    </div>
  );
}

/** pos layer: token row, each with its tag chip (suggested dashed, confirmed solid, modified solid + dot, rejected struck). */
export function PosRow({ views, selected, onSelect, posColor }: { views: TokView[]; selected: number | null; onSelect: (i: number) => void; posColor: boolean }) {
  return (
    <div className={`tokrow ${posColor ? "poscolor" : ""}`} role="listbox" aria-label="词">
      {views.map((v) => (
        <button
          key={v.index}
          type="button"
          role="option"
          aria-selected={v.index === selected}
          tabIndex={-1}
          className={`tk ${v.index === selected ? "sel" : ""}`}
          data-index={v.index}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => onSelect(v.index)}
        >
          <span className="tk-form">{v.form}</span>
          <span key={`${v.status}:${v.label}`} className={`pchip ${v.status}`} data-c={posCat(v.label)} data-status={v.status}>
            {v.label ?? "—"}
            {v.status === "modified" && <i className="mod-dot" aria-label="已修改" />}
          </span>
        </button>
      ))}
    </div>
  );
}

