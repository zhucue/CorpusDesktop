import { Input } from "antd";
import type { Metadata } from "../../api";
import { Icon } from "../../components/Icon";

/** Metadata editor state: field/value rows, or raw JSON (advanced; also for nested values). */
export type MetaDraft = { mode: "rows" | "json"; rows: { key: string; value: string }[]; json: string };

export const emptyMeta = (): MetaDraft => ({ mode: "rows", rows: [{ key: "", value: "" }], json: "" });

const NUMBER = /^-?(0|[1-9]\d*)(\.\d+)?$/;

/** "2020" → 2020, "2.5" → 2.5; "007", "1,000" and other text stay strings (as CSV metadata columns). */
export function metaValue(v: string): string | number {
  const s = v.trim();
  return NUMBER.test(s) ? Number(s) : s;
}

const scalar = (v: unknown) => typeof v === "string" || typeof v === "number" || typeof v === "boolean";

export function draftFrom(m: Metadata | undefined): MetaDraft {
  const entries = Object.entries(m ?? {});
  if (!entries.length) return emptyMeta();
  if (entries.every(([, v]) => scalar(v))) return { mode: "rows", rows: entries.map(([key, v]) => ({ key, value: String(v) })), json: "" };
  return { mode: "json", rows: [], json: JSON.stringify(m, null, 2) };
}

/** Draft → metadata object; throws an Error naming the row or the JSON problem. */
export function metadataFromDraft(d: MetaDraft | undefined): Metadata {
  if (!d) return {};
  if (d.mode === "json") {
    if (!d.json.trim()) return {};
    let v: unknown;
    try {
      v = JSON.parse(d.json);
    } catch {
      throw new Error("JSON 格式错误");
    }
    if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("元数据须为 JSON 对象");
    return v as Metadata;
  }
  const out: Metadata = {};
  d.rows.forEach((r, i) => {
    const key = r.key.trim();
    if (!key && !r.value.trim()) return;
    if (!key) throw new Error(`第 ${i + 1} 行缺少字段名`);
    if (key in out) throw new Error(`字段「${key}」重复`);
    out[key] = metaValue(r.value);
  });
  return out;
}

export const metaDraftRule = {
  validator: (_: unknown, v: MetaDraft | undefined) => {
    try {
      metadataFromDraft(v);
      return Promise.resolve();
    } catch (e) {
      return Promise.reject(e);
    }
  },
};

/** Field / value rows with a JSON mode; a controlled antd form control. */
export function MetadataInput({ value, onChange }: { value?: MetaDraft; onChange?: (v: MetaDraft) => void }) {
  const d = value ?? emptyMeta();
  const set = (next: Partial<MetaDraft>) => onChange?.({ ...d, ...next });
  const setRow = (i: number, patch: Partial<{ key: string; value: string }>) => set({ rows: d.rows.map((r, k) => (k === i ? { ...r, ...patch } : r)) });
  const toJson = () => {
    let json = d.json;
    try {
      const m = metadataFromDraft(d);
      json = Object.keys(m).length ? JSON.stringify(m, null, 2) : "";
    } catch {
      /* keep the rows; the field error explains */
      return;
    }
    set({ mode: "json", json });
  };
  const toRows = () => {
    try {
      const next = draftFrom(metadataFromDraft(d));
      if (next.mode === "rows") onChange?.(next);
    } catch {
      /* invalid JSON stays in JSON mode */
    }
  };

  if (d.mode === "json")
    return (
      <div className="col" style={{ gap: 6 }}>
        <Input.TextArea rows={4} value={d.json} onChange={(e) => set({ json: e.target.value })} placeholder='{"year": 2020, "genre": "新闻"}' style={{ fontFamily: "var(--mono)" }} aria-label="元数据 JSON" />
        <span>
          <button className="btn xs ghost" type="button" onClick={toRows}>
            改用字段表
          </button>
        </span>
      </div>
    );
  return (
    <div className="meta-rows">
      {d.rows.map((r, i) => (
        <div className="meta-row" key={i}>
          <Input size="small" value={r.key} placeholder="字段，如 year" aria-label={`第 ${i + 1} 行字段`} onChange={(e) => setRow(i, { key: e.target.value })} />
          <Input size="small" value={r.value} placeholder="值，如 2020" aria-label={`第 ${i + 1} 行值`} onChange={(e) => setRow(i, { value: e.target.value })} />
          <button className="btn ghost icon xs" type="button" aria-label={`删除第 ${i + 1} 行`} title="删除" onClick={() => set({ rows: d.rows.length > 1 ? d.rows.filter((_, k) => k !== i) : [{ key: "", value: "" }] })}>
            <Icon name="x" size={14} />
          </button>
        </div>
      ))}
      <div className="row" style={{ gap: 6 }}>
        <button className="btn xs" type="button" onClick={() => set({ rows: [...d.rows, { key: "", value: "" }] })}>
          <Icon name="plus" size={14} />
          添加字段
        </button>
        <button className="btn xs ghost" type="button" onClick={toJson}>
          JSON
        </button>
      </div>
    </div>
  );
}
