import { useQuery } from "@tanstack/react-query";
import { Select, Table } from "antd";
import { useEffect, useState } from "react";
import { api, type TableMapping, type TablePreview } from "../../api";
import { ErrorAlert } from "../../components/common";

/** Matches PREVIEW_BYTES in services/api/corpora.py: only the head of a large CSV/TSV/JSONL is sent; an XLSX is sent whole. */
const PREVIEW_BYTES = 256 * 1024;

export const isTable = (f: File) => /\.(csv|tsv|xlsx|jsonl)$/i.test(f.name);
const isXlsx = (f: File) => /\.xlsx$/i.test(f.name);

/** Field mapping of an upload batch: CSV/TSV/XLSX columns or JSONL fields; `sheet` for XLSX (null = first sheet). */
export type ImportMapping = TableMapping & { sheet?: string | null };
type ImportPreview = Omit<TablePreview, "defaults"> & { defaults: ImportMapping; sheets?: string[] };

/**
 * Field mapping for the CSV/TSV/XLSX/JSONL files of one upload batch: preview of the first such file (XLSX: of
 * the chosen sheet) and the mapping state (reset to the detected defaults when the file or sheet changes).
 * `ready` is false while the preview loads or no text column is chosen. Batches without tables return mapping null.
 */
export function useTableMapping(files: File[]) {
  const tables = files.filter(isTable);
  const first = tables[0];
  const [sheet, setSheet] = useState<string | null>(null);
  const key = first ? `${first.name}:${first.size}:${first.lastModified}` : "";
  useEffect(() => setSheet(null), [key]);
  const preview = useQuery({
    queryKey: ["table-preview", key, sheet],
    enabled: !!first,
    retry: false,
    staleTime: Infinity,
    queryFn: () => {
      const body = new FormData();
      body.append("file", !isXlsx(first) && first.size > PREVIEW_BYTES ? first.slice(0, PREVIEW_BYTES) : first, first.name);
      if (sheet) body.append("sheet", sheet);
      return api.post<ImportPreview>("/imports/preview", body);
    },
  });
  const [mapping, setMapping] = useState<ImportMapping | null>(null);
  const defaults = preview.data?.defaults;
  useEffect(() => setMapping(defaults ?? null), [defaults]);
  return {
    tables,
    preview,
    mapping: first ? mapping : null,
    setMapping,
    setSheet,
    ready: !first || (!!mapping && mapping.text.length > 0),
  };
}

export function TableMappingFields({ state }: { state: ReturnType<typeof useTableMapping> }) {
  const { tables, preview, mapping, setMapping, setSheet } = state;
  if (tables.length === 0) return null;
  if (preview.error) return <ErrorAlert error={preview.error} style={{ marginBottom: 12 }} />;
  if (!preview.data || !mapping) return <div className="small muted" style={{ marginBottom: 12 }}>读取 {tables[0].name} 的列…</div>;
  const { columns, rows, sheets } = preview.data;
  const options = columns.map((c) => ({ value: c, label: c }));
  const used = new Set([...mapping.text, mapping.title, mapping.language]);
  const rest = columns.filter((c) => !used.has(c));
  const meta = mapping.metadata === null ? rest : mapping.metadata.filter((c) => !used.has(c));
  const set = (patch: Partial<ImportMapping>) => setMapping({ ...mapping, ...patch });
  return (
    <div className="table-map">
      <div className="table-map-head">
        <b>列映射</b>
        <span className="small muted">
          {tables[0].name}
          {tables.length > 1 && ` 等 ${tables.length} 个文件，共用此映射`}
        </span>
      </div>
      <div className="table-map-grid">
        {sheets && (
          <>
            <label>工作表</label>
            <Select size="small" value={mapping.sheet ?? sheets[0]} options={sheets.map((s) => ({ value: s, label: s }))} onChange={(s: string) => setSheet(s)} aria-label="工作表" />
          </>
        )}
        <label>正文列</label>
        <Select
          mode="multiple"
          maxCount={2}
          size="small"
          value={mapping.text}
          options={options}
          status={mapping.text.length ? undefined : "error"}
          placeholder="选择 1–2 列，按表格列序以空行连接"
          onChange={(text: string[]) => set({ text: columns.filter((c) => text.includes(c)) })}
        />
        <label>标题列</label>
        <Select size="small" allowClear value={mapping.title} options={options} placeholder="行号" onChange={(title) => set({ title: title ?? null })} />
        <label>语言列</label>
        <Select size="small" allowClear value={mapping.language} options={options} placeholder="使用上方语言" onChange={(language) => set({ language: language ?? null })} />
        <label>元数据列</label>
        <Select
          mode="multiple"
          size="small"
          value={meta}
          options={rest.map((c) => ({ value: c, label: c }))}
          maxTagCount="responsive"
          placeholder="不导入元数据"
          onChange={(metadata: string[]) => set({ metadata })}
        />
      </div>
      <Table<{ key: number; cells: string[] }>
        size="small"
        className="table-map-preview"
        pagination={false}
        scroll={{ x: "max-content" }}
        dataSource={rows.map((cells, key) => ({ key, cells }))}
        locale={{ emptyText: "没有数据行" }}
        columns={columns.map((c, i) => ({
          title: c,
          key: c,
          className: mapping.text.includes(c) ? "map-text" : undefined,
          render: (_: unknown, r: { cells: string[] }) => <span className="cell-clip">{r.cells[i]}</span>,
        }))}
      />
    </div>
  );
}
