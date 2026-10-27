import { Table, Typography, type TablePaginationConfig } from "antd";
import type { Hit } from "../api";
import { metadataText } from "../corpora";

const clip: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden" };

export default function KwicTable({
  items,
  offset,
  loading,
  pagination,
  onOpen,
}: {
  items: Hit[];
  offset: number;
  loading?: boolean;
  pagination: TablePaginationConfig | false;
  onOpen: (hit: Hit) => void;
}) {
  const alignedKeys = items.filter((h) => h.aligned.length > 0).map((h) => h.hit_id);
  return (
    <Table<Hit>
      rowKey="hit_id"
      size="small"
      loading={loading}
      dataSource={items}
      pagination={pagination}
      tableLayout="fixed"
      locale={{ emptyText: "无命中" }}
      onRow={(hit) => ({ onClick: () => onOpen(hit), style: { cursor: "pointer" } })}
      expandable={{
        showExpandColumn: false,
        expandedRowKeys: alignedKeys,
        expandedRowRender: (hit) =>
          hit.aligned.map((a, i) => (
            <div key={i} style={{ color: "rgba(0,0,0,0.65)" }}>
              <Typography.Text type="secondary">{a.language}</Typography.Text> {a.text}
            </div>
          )),
      }}
      columns={[
        { title: "#", width: 56, render: (_, __, i) => offset + i + 1 },
        {
          title: "左语境",
          dataIndex: "left",
          // rtl container keeps the text next to the match visible when it overflows
          render: (s: string) => (
            <div style={{ ...clip, direction: "rtl", textAlign: "right" }}>
              <span style={{ direction: "ltr", unicodeBidi: "embed" }}>{s}</span>
            </div>
          ),
        },
        {
          title: "命中",
          dataIndex: "match",
          width: 140,
          align: "center",
          render: (s: string) => <strong data-testid="kwic-match">{s}</strong>,
        },
        {
          title: "右语境",
          dataIndex: "right",
          render: (s: string) => <div style={clip}>{s}</div>,
        },
        { title: "出处", dataIndex: "document_title", width: 160, ellipsis: true },
        { title: "元数据", width: 180, ellipsis: true, render: (_, h) => metadataText(h.metadata) },
      ]}
    />
  );
}
