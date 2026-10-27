import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Drawer, InputNumber, Space, Spin } from "antd";
import { useState } from "react";
import { api, errorText, type ContextResult, type Hit } from "../api";
import { metadataText } from "../corpora";

function Sentence({ text, highlight }: { text: string; highlight: [number, number] | null }) {
  if (!highlight) return <>{text}</>;
  // highlight offsets are code points; Array.from splits by code point
  const chars = Array.from(text);
  const [s, e] = highlight;
  return (
    <>
      {chars.slice(0, s).join("")}
      <strong style={{ background: "#fff1b8" }}>{chars.slice(s, e).join("")}</strong>
      {chars.slice(e).join("")}
    </>
  );
}

export default function ContextDrawer({ hit, onClose }: { hit: Hit | null; onClose: () => void }) {
  const [before, setBefore] = useState(2);
  const [after, setAfter] = useState(2);
  const ctx = useQuery({
    queryKey: ["context", hit?.hit_id, before, after],
    queryFn: () =>
      api.get<ContextResult>("/search/context", {
        document_id: hit!.document_id,
        sentence_index: hit!.sentence_index,
        start_cp: hit!.start_cp,
        end_cp: hit!.end_cp,
        before,
        after,
      }),
    enabled: !!hit,
    placeholderData: keepPreviousData,
  });

  return (
    <Drawer title={hit?.document_title} open={!!hit} onClose={onClose} width={640}>
      <Space style={{ marginBottom: 16 }}>
        前
        <InputNumber min={0} max={20} value={before} onChange={(v) => setBefore(v ?? 0)} style={{ width: 64 }} />
        句，后
        <InputNumber min={0} max={20} value={after} onChange={(v) => setAfter(v ?? 0)} style={{ width: 64 }} />
        句
        {ctx.isFetching && <Spin size="small" />}
      </Space>
      {ctx.error && <Alert type="error" showIcon message={errorText(ctx.error)} />}
      {ctx.data && (
        <>
          <div style={{ lineHeight: 1.9, fontSize: 15 }}>
            {ctx.data.sentences.map((s) => (
              <p key={s.index} style={{ margin: "0 0 8px" }}>
                <Sentence text={s.text} highlight={s.highlight} />
              </p>
            ))}
          </div>
          {hit && hit.aligned.length > 0 && (
            <Descriptions size="small" column={1} title="对齐句" style={{ marginTop: 16 }}>
              {hit.aligned.map((a, i) => (
                <Descriptions.Item key={i} label={a.language}>
                  {a.text}
                </Descriptions.Item>
              ))}
            </Descriptions>
          )}
          <Descriptions size="small" column={1} style={{ marginTop: 16 }}>
            <Descriptions.Item label="句序号">{hit?.sentence_index}</Descriptions.Item>
            <Descriptions.Item label="码点">
              {hit?.start_cp}–{hit?.end_cp}
            </Descriptions.Item>
            <Descriptions.Item label="元数据">{metadataText(ctx.data.document.metadata)}</Descriptions.Item>
          </Descriptions>
        </>
      )}
    </Drawer>
  );
}
