import { Select } from "antd";
import type { Scope } from "../../api";
import { scopeFromKey, scopeKey, useCorpora, useSubcorpora } from "../../lib/data";

/** Corpus / subcorpus picker; only ready (or stale) corpora are selectable. */
export function ScopeSelect({
  projectId,
  value,
  onChange,
  width = 220,
  size,
}: {
  projectId: string;
  value: Scope | null | undefined;
  onChange: (s: Scope) => void;
  width?: number;
  size?: "small" | "middle";
}) {
  const corpora = useCorpora(projectId);
  const subs = useSubcorpora(projectId);
  return (
    <Select
      size={size}
      style={{ width }}
      value={value ? scopeKey(value) : undefined}
      placeholder="选择范围"
      onChange={(k: string) => onChange(scopeFromKey(k))}
      loading={corpora.isPending || subs.isPending}
      showSearch
      optionFilterProp="label"
      options={[
        {
          label: "语料库",
          options: (corpora.data?.items ?? []).map((c) => ({
            value: `corpus:${c.id}`,
            label: c.project_id === null ? `${c.name}（内置）` : c.name,
            disabled: c.status !== "ready" && c.status !== "stale",
          })),
        },
        { label: "子库", options: (subs.data?.items ?? []).map((s) => ({ value: `subcorpus:${s.id}`, label: `子库「${s.name}」` })) },
      ]}
    />
  );
}
