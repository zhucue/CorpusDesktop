import type { CorpusMeta } from "../../api";

export const metaLabels: [keyof CorpusMeta, string][] = [
  ["license", "许可"],
  ["attribution", "署名"],
  ["source_url", "来源链接"],
  ["version", "版本"],
];

/** Filled source and license fields, in display order. */
export function metaEntries(
  meta: CorpusMeta | undefined,
): [keyof CorpusMeta, string, string][] {
  return metaLabels.flatMap(([k, label]) => {
    const v = meta?.[k]?.trim();
    return v ? [[k, label, v] as [keyof CorpusMeta, string, string]] : [];
  });
}

const isHttp = (v: string) => /^https?:\/\//i.test(v);

export function MetaValue({
  field,
  value,
}: {
  field: keyof CorpusMeta;
  value: string;
}) {
  if (field === "source_url" && isHttp(value))
    return (
      <a
        href={value}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
      >
        {value}
      </a>
    );
  return <>{value}</>;
}

/** Source and license block for the corpus drawer; nothing when the corpus has none. */
export function CorpusMetaList({ meta }: { meta: CorpusMeta | undefined }) {
  const rows = metaEntries(meta);
  if (!rows.length) return null;
  return (
    <dl className="kv corp-meta" aria-label="来源与许可">
      {rows.map(([k, label, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd className={k === "version" ? "mono" : undefined}>
            <MetaValue field={k} value={v} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Form values → `meta` body (only filled fields); undefined when all are empty. */
export function metaFromForm(
  v: Partial<Record<keyof CorpusMeta, string>>,
): CorpusMeta | undefined {
  const out: CorpusMeta = {};
  for (const [k] of metaLabels) {
    const s = v[k]?.trim();
    if (s) out[k] = s;
  }
  return Object.keys(out).length ? out : undefined;
}
