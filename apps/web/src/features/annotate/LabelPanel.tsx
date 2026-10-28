import { forwardRef, useState } from "react";
import type { LabelDef, LabelSet } from "../../api";
import { Tip } from "../../components/common";
import { posCat } from "../../lib/pos";
import { keyHint } from "./model";

/** Labels of the layer's label set; 1–9 then letters pick a label, the search box filters (Enter picks the first match). */
export const LabelPanel = forwardRef<
  HTMLInputElement,
  { set: LabelSet | undefined; current: string | null; disabled: boolean; colorPos: boolean; onPick: (label: LabelDef) => void }
>(function LabelPanel({ set, current, disabled, colorPos, onPick }, ref) {
  const [q, setQ] = useState("");
  const labels = set?.labels ?? [];
  const needle = q.trim().toLowerCase();
  const shown = labels
    .map((l, i) => ({ l, i }))
    .filter(({ l }) => !needle || `${l.id} ${l.name} ${l.description ?? ""}`.toLowerCase().includes(needle));
  return (
    <section className="card lab-card" aria-label="标签">
      <div className="row between" style={{ padding: "2px 4px 8px" }}>
        <h2>{set?.name ?? "标签"}</h2>
        <span className="small muted mono">{labels.length} 个标签</span>
      </div>
      <input
        ref={ref}
        className="input lab-search"
        value={q}
        placeholder="筛选标签"
        aria-label="筛选标签"
        data-slash
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && shown[0] && !disabled) {
            e.preventDefault();
            onPick(shown[0].l);
            setQ("");
            e.currentTarget.blur();
          } else if (e.key === "Escape") {
            setQ("");
            e.currentTarget.blur();
          }
        }}
      />
      <div className="col gap-4 lab-list" role="listbox" aria-label="标签列表">
        {shown.length === 0 && <div className="empty sm">没有匹配的标签</div>}
        {shown.map(({ l, i }) => {
          const hint = keyHint(i);
          // annotations store the label id; the name is shown
          const on = current != null && (current === l.id || current === l.name);
          const btn = (
            <button
              key={l.id ?? l.name}
              className={`lab-opt ${on ? "on" : ""}`}
              type="button"
              role="option"
              aria-selected={on}
              disabled={disabled}
              data-c={colorPos ? posCat(l.name) : undefined}
              tabIndex={-1}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onPick(l)}
            >
              <i style={l.color ? { background: l.color } : undefined} />
              <span className="mono">{l.name}</span>
              {l.id && l.id !== l.name && <span className="mono lab-desc">{l.id}</span>}
              {l.description && <span className="lab-desc ellipsis">{l.description}</span>}
              {hint && <span className="kbd">{hint}</span>}
            </button>
          );
          return l.description ? (
            <Tip key={l.id ?? l.name} title={l.description}>
              {btn}
            </Tip>
          ) : (
            btn
          );
        })}
      </div>
    </section>
  );
});
