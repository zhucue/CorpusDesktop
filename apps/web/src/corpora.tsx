import { useQuery } from "@tanstack/react-query";
import { Tag, Tooltip, Typography } from "antd";
import { MAX_PAGE_SIZE, api, type Corpus, type CorpusStatus, type Metadata, type Page } from "./api";

export function metadataText(m: Metadata): string {
  return Object.entries(m)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join("；");
}

const statusView: Record<CorpusStatus, { label: string; color: string }> = {
  empty: { label: "空", color: "default" },
  importing: { label: "导入中", color: "processing" },
  indexing: { label: "建索引中", color: "processing" },
  ready: { label: "可检索", color: "success" },
  stale: { label: "需重建索引", color: "warning" },
  failed: { label: "失败", color: "error" },
};

export function CorpusStatusTag({ corpus }: { corpus: Corpus }) {
  const v = statusView[corpus.status] ?? { label: corpus.status, color: "default" };
  return (
    <>
      <Tag color={v.color}>{v.label}</Tag>
      {corpus.status === "failed" && corpus.error && (
        <Tooltip title={corpus.error}>
          <Typography.Text type="danger" ellipsis style={{ maxWidth: 240 }}>
            {corpus.error}
          </Typography.Text>
        </Tooltip>
      )}
    </>
  );
}

const busy = (c: Corpus) => c.status === "importing" || c.status === "indexing";

export function useCorpora(projectId: string) {
  return useQuery({
    queryKey: ["corpora", projectId],
    queryFn: () => api.get<Page<Corpus>>("/corpora", { project_id: projectId, page_size: MAX_PAGE_SIZE }),
    refetchInterval: (q) => (q.state.data?.items.some(busy) ? 3000 : false),
  });
}

export function useCorpus(id: string) {
  return useQuery({
    queryKey: ["corpus", id],
    queryFn: () => api.get<Corpus>(`/corpora/${id}`),
    refetchInterval: (q) => (q.state.data && busy(q.state.data) ? 3000 : false),
  });
}

export const fmt = (n: number | undefined) => (n ?? 0).toLocaleString("zh-CN");
export const fmtTime = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("zh-CN") : "");

export const languageOptions = [
  { value: "zh", label: "中文 zh" },
  { value: "en", label: "英语 en" },
];
