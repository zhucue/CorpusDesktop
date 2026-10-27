import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Popover, Select } from "antd";
import { useState } from "react";
import { api, errorText, type Hit, type Term } from "../../api";
import { Icon } from "../../components/Icon";
import { useDebounced } from "../../lib/useDebounced";
import { useTerms } from "./data";

/** KWIC row action: pick a term and add the hit as one of its corpus examples. */
export default function TermExampleButton({ projectId, hit, source }: { projectId: string; hit: Hit; source: string }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [termId, setTermId] = useState<string | undefined>();
  const dq = useDebounced(q.trim(), 250);
  const terms = useTerms(projectId, { q: dq, page_size: 20 }, open);
  const add = useMutation({
    mutationFn: async (id: string) => {
      // The example is the hit's sentence; the KWIC character context can run into neighbouring sentences.
      const ctx = await api
        .get<{ sentences: { index: number; text: string }[] }>("/search/context", { document_id: hit.document_id, sentence_index: hit.sentence_index, before: 0, after: 0 })
        .catch(() => null);
      const sentence = ctx?.sentences.find((s) => s.index === hit.sentence_index)?.text;
      return api.post<Term>(`/kb/terms/${id}/examples`, {
        hit_id: hit.hit_id,
        document_id: hit.document_id,
        start_cp: hit.start_cp,
        end_cp: hit.end_cp,
        text: sentence || `${hit.left}${hit.match}${hit.right}`,
        source,
      });
    },
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ["kb-terms"] });
      message.success(`已加入术语「${t.term}」的例句`);
      setOpen(false);
      setTermId(undefined);
    },
    onError: (e) => message.error(errorText(e)),
  });
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomRight"
      content={
        <div className="row" style={{ width: 300 }} onClick={(e) => e.stopPropagation()}>
          <Select
            className="grow"
            size="small"
            showSearch
            filterOption={false}
            onSearch={setQ}
            placeholder="选择术语"
            loading={terms.isFetching}
            value={termId}
            onChange={setTermId}
            notFoundContent={terms.isSuccess ? "没有匹配的术语" : null}
            options={(terms.data?.items ?? []).map((t) => ({ value: t.id, label: `${t.term}${t.translations?.[0] ? ` / ${t.translations[0].text}` : ""}` }))}
            aria-label="术语"
          />
          <button className="btn xs p" type="button" disabled={!termId || add.isPending} onClick={() => termId && add.mutate(termId)}>
            加入
          </button>
        </div>
      }
    >
      <button
        className="pin-btn"
        type="button"
        aria-label="加入术语例句"
        title="加入术语例句"
        onClick={(e) => e.stopPropagation()}
      >
        <Icon name="term" size={14} />
      </button>
    </Popover>
  );
}
