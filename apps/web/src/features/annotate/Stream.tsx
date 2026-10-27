import { Select } from "antd";
import { useEffect, useRef } from "react";
import type { LayerDocument } from "../../api";
import { Empty, ErrorAlert, Skeleton } from "../../components/common";
import { Icon } from "../../components/Icon";
import { fmt } from "../../lib/format";

export interface StreamItem {
  key: number;
  text: string;
  done: boolean;
}

/** Left column of the span and alignment workspaces: document select, pending/all filter and the sentence (pair) list. */
export function Stream({
  title,
  unit,
  docs,
  docsPending,
  docId,
  onDoc,
  filter,
  onFilter,
  items,
  current,
  onPick,
  loading,
  error,
  hasMore,
  loadingMore,
  onMore,
}: {
  title: string;
  unit: string;
  docs: LayerDocument[];
  docsPending: boolean;
  docId: string | null;
  onDoc: (id: string) => void;
  filter?: "pending" | "all";
  onFilter?: (f: "pending" | "all") => void;
  items: StreamItem[];
  current: number | null;
  onPick: (key: number) => void;
  loading: boolean;
  error: unknown;
  hasMore: boolean;
  loadingMore: boolean;
  onMore: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const doc = docs.find((d) => d.document_id === docId);
  useEffect(() => {
    ref.current?.querySelector(".sent.on")?.scrollIntoView?.({ block: "nearest" });
  }, [current, docId]);
  return (
    <section className="card stream-card" aria-label={title}>
      <div className="row between" style={{ padding: "2px 6px 8px" }}>
        <h2>{title}</h2>
        {onFilter && (
          <div className="seg-mini" role="tablist" aria-label={`${title}范围`}>
            <button type="button" role="tab" aria-selected={filter === "pending"} onClick={() => onFilter("pending")}>
              待办
            </button>
            <button type="button" role="tab" aria-selected={filter === "all"} onClick={() => onFilter("all")}>
              全部
            </button>
          </div>
        )}
      </div>
      <div style={{ padding: "0 4px 8px" }}>
        <Select
          size="small"
          style={{ width: "100%" }}
          value={docId ?? undefined}
          placeholder="选择文档"
          aria-label="文档"
          loading={docsPending}
          onChange={onDoc}
          showSearch
          optionFilterProp="title"
          options={docs.map((d) => ({
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
      <ErrorAlert error={error} style={{ margin: "0 4px 8px" }} />
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
      <div className="col gap-4 stream" ref={ref}>
        {loading && docId ? (
          <Skeleton rows={5} />
        ) : items.length === 0 && docId ? (
          <Empty icon="check" text={filter === "pending" ? `本文档没有待办${unit}` : `没有${unit}`}>
            {filter === "pending" && onFilter && (
              <button className="btn s" type="button" onClick={() => onFilter("all")}>
                显示全部
              </button>
            )}
          </Empty>
        ) : (
          items.map((it) => {
            const on = it.key === current;
            return (
              <button
                key={it.key}
                className={`sent ${on ? "on" : ""} ${it.done ? "done" : ""}`}
                type="button"
                aria-current={on ? "true" : undefined}
                onClick={() => onPick(it.key)}
              >
                <span className="n">{it.key + 1}</span>
                <span className="grow">{it.text}</span>
                {it.done ? <Icon name="check" size={14} className="st" /> : on ? <span className="dot pulse" /> : null}
              </button>
            );
          })
        )}
        {hasMore && (
          <button className="btn s ghost" type="button" disabled={loadingMore} onClick={onMore}>
            {loadingMore ? <span className="spin" /> : null}
            加载更多
          </button>
        )}
      </div>
    </section>
  );
}

/** The editor ignores single-key shortcuts while typing or inside overlays. */
export function typingTarget(t: EventTarget | null): boolean {
  return t instanceof Element && !!t.closest("input, textarea, select, [contenteditable='true'], .ant-modal-wrap, .ant-select-dropdown, .ant-popover");
}
