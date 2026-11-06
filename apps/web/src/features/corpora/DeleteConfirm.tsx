import { useQuery } from "@tanstack/react-query";
import { Checkbox, Modal, Spin } from "antd";
import { useState } from "react";
import { api } from "../../api";
import { ErrorAlert } from "../../components/common";
import { fmt } from "../../lib/format";

/** GET /corpora/{id}/delete-impact · /documents/{id}/delete-impact (contracts/p7.md §二). */
type DeleteImpact = {
  documents: number;
  sentences: number;
  layers: { id: string; name: string; kind: string; human: number }[];
  human_annotations: number;
  evidence: number;
  kb_refs: number;
};

const KIND_LABELS: Record<string, string> = { pos: "词性", dep: "依存", span: "片段", relation: "关系", alignment: "对齐" };

export type DeleteTarget = { kind: "corpus" | "document"; id: string; name: string };

/** Delete confirmation listing what goes with the corpus / document; human annotations need a checkbox. */
export function DeleteConfirm({ target, pending, onConfirm, onClose }: { target: DeleteTarget | null; pending?: boolean; onConfirm: () => void; onClose: () => void }) {
  const [ack, setAck] = useState(false);
  const impact = useQuery({
    queryKey: ["delete-impact", target?.kind, target?.id],
    queryFn: () => api.get<DeleteImpact>(target!.kind === "corpus" ? `/corpora/${target!.id}/delete-impact` : `/documents/${target!.id}/delete-impact`),
    enabled: !!target,
    staleTime: 0,
    gcTime: 0,
  });
  const d = impact.data;
  const isCorpus = target?.kind === "corpus";
  const affects = !!d && (d.layers.length > 0 || d.evidence > 0 || d.kb_refs > 0);
  const needAck = !!d && d.human_annotations > 0;
  const close = () => {
    setAck(false);
    onClose();
  };

  return (
    <Modal
      title={target && `删除${isCorpus ? "语料库" : "文档"}「${target.name}」？`}
      open={!!target}
      onCancel={close}
      okText="删除"
      cancelText="取消"
      okButtonProps={{ danger: true, loading: pending, disabled: !d || (needAck && !ack) }}
      onOk={() => {
        setAck(false);
        onConfirm();
      }}
      destroyOnHidden
      width={460}
    >
      <div className="col" style={{ gap: 12 }}>
        {impact.isFetching && <Spin />}
        {impact.isError && !impact.isFetching && (
          // deleting stays disabled until the impact is known
          <div className="col" style={{ gap: 8 }}>
            <span className="sm">无法读取删除影响，暂不能删除。</span>
            <ErrorAlert error={impact.error} />
            <div>
              <button className="btn xs" type="button" onClick={() => void impact.refetch()}>
                重试
              </button>
            </div>
          </div>
        )}
        {d && !affects && <span className="sm">{isCorpus ? `${fmt(d.documents)} 个文档、${fmt(d.sentences)} 句一并删除。` : "删除后需重建索引。"}</span>}
        {d && affects && (
          <>
            <span className="sm">以下内容会一并删除，不可恢复：</span>
            <table className="tbl mid">
              <tbody>
                <tr>
                  <td className="sm">文档</td>
                  <td className="r num">
                    {fmt(d.documents)} 个 · {fmt(d.sentences)} 句
                  </td>
                </tr>
                {d.layers.map((l) => (
                  <tr key={l.id}>
                    <td className="sm">
                      标注层「{l.name}」<span className="muted">{KIND_LABELS[l.kind] ?? l.kind}</span>
                    </td>
                    <td className="r num">人工 {fmt(l.human)} 条</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(d.evidence > 0 || d.kb_refs > 0) && (
              <span className="sm num">
                引用这些句子的证据 {fmt(d.evidence)} 条、笔记引用 {fmt(d.kb_refs)} 条，删除后无法回到原句
              </span>
            )}
            {!isCorpus && <span className="sm">删除后需重建索引。</span>}
            {needAck && (
              <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)}>
                我确认删除这些人工标注（{fmt(d.human_annotations)} 条）
              </Checkbox>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
