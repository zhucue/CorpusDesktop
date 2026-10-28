import type { Corpus, CorpusMeta as FullMeta } from "../../api";

/** The source and license fields (the index profile in `meta` is shown elsewhere). */
type CorpusMeta = Pick<FullMeta, "license" | "attribution" | "source_url" | "version">;

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

export const tagsetLabels: Record<string, string> = { jieba: "jieba 词性", upos: "UPOS", mixed: "jieba + UPOS" };
export const scriptLabels: Record<string, string> = { simplified: "简体", traditional: "繁体", mixed: "简繁混合" };

/** "zh-en" for corpora whose documents are in several languages (parallel), else the corpus language. */
export function corpusLanguages(c: Corpus): string {
  const langs = c.meta?.languages ?? [];
  if (langs.length > 1) return [c.language, ...langs.filter((l) => l !== c.language)].filter((l) => l && l !== "auto").join("-");
  if (c.language === "auto") return langs[0] ?? "待识别";
  return c.language;
}

/** "zh · 繁体 · UPOS": languages, Chinese script and POS tag set as detected at indexing. */
export function corpusProfile(c: Corpus): string[] {
  const out = [corpusLanguages(c)];
  if (c.meta?.script) out.push(scriptLabels[c.meta.script] ?? c.meta.script);
  if (c.meta?.tagset) out.push(tagsetLabels[c.meta.tagset] ?? c.meta.tagset);
  return out;
}
