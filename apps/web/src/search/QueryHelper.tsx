import { Button, Input, InputNumber, Select, Space, Table, Typography } from "antd";
import { useState } from "react";

const posOptions = [
  { value: "n", label: "/n 名词" },
  { value: "v", label: "/v 动词" },
  { value: "a", label: "/a 形容词" },
  { value: "d", label: "/d 副词" },
  { value: "p", label: "/p 介词" },
  { value: "r", label: "/r 代词" },
];

export const syntaxRows = [
  { syntax: "语言", meaning: "字串，中文按字符匹配，可跨分词边界" },
  { syntax: "语言/n", meaning: "词 + 词性；/v 表示任意动词" },
  { syntax: "语言 文化", meaning: "两词相邻" },
  { syntax: "语言 $3 文化", meaning: "中间最多 3 个词；$2-5 表示 2 到 5 个" },
  { syntax: "语言|语法", meaning: "或" },
  { syntax: "语言 +文化", meaning: "同句须出现「文化」，以「语言」为锚点计数" },
  { syntax: "语言 -文化", meaning: "同句不出现「文化」" },
  { syntax: '"语言"', meaning: "精确词形，不做字串扩展" },
  { syntax: "*、?", meaning: "任意词、任意单字" },
];

/** Append a snippet to the query; "|" alternatives attach without a space. */
export function appendSnippet(query: string, snippet: string): string {
  const q = query.trimEnd();
  if (!q || snippet.startsWith("|")) return q + snippet;
  return `${q} ${snippet}`;
}

export default function QueryHelper({ onInsert }: { onInsert: (snippet: string) => void }) {
  const [word, setWord] = useState("");
  const [pos, setPos] = useState<string>();
  const [gapMin, setGapMin] = useState<number | null>(null);
  const [gapMax, setGapMax] = useState<number | null>(3);
  const w = word.trim();
  const withPos = pos ? `${w}/${pos}` : w;
  const gap = gapMin != null && gapMax != null ? `$${gapMin}-${gapMax}` : gapMax != null ? `$${gapMax}` : null;

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Space wrap>
        <Input placeholder="词" value={word} onChange={(e) => setWord(e.target.value)} style={{ width: 140 }} />
        <Select
          placeholder="词性"
          allowClear
          value={pos}
          onChange={setPos}
          options={posOptions}
          style={{ width: 120 }}
        />
        <Button disabled={!w && !pos} onClick={() => onInsert(w ? withPos : `/${pos}`)}>
          插入词
        </Button>
        <Button disabled={!w} onClick={() => onInsert(`"${w}"`)}>
          精确 ""
        </Button>
        <Button disabled={!w} onClick={() => onInsert(`|${withPos}`)}>
          或 |
        </Button>
        <Button disabled={!w} onClick={() => onInsert(`+${withPos}`)}>
          同句出现 +
        </Button>
        <Button disabled={!w} onClick={() => onInsert(`-${withPos}`)}>
          同句不出现 -
        </Button>
      </Space>
      <Space wrap>
        <span>间隔</span>
        <InputNumber min={0} placeholder="最少" value={gapMin} onChange={setGapMin} style={{ width: 80 }} />
        至
        <InputNumber min={1} placeholder="最多" value={gapMax} onChange={setGapMax} style={{ width: 80 }} />
        <Button disabled={!gap} onClick={() => gap && onInsert(gap)}>
          插入 $N
        </Button>
        <Button onClick={() => onInsert("*")}>任意词 *</Button>
        <Button onClick={() => onInsert("?")}>任意单字 ?</Button>
      </Space>
      <Table
        size="small"
        rowKey="syntax"
        pagination={false}
        dataSource={syntaxRows}
        columns={[
          {
            title: "写法",
            dataIndex: "syntax",
            width: 160,
            render: (s: string) => <Typography.Text code>{s}</Typography.Text>,
          },
          { title: "含义", dataIndex: "meaning" },
        ]}
      />
    </Space>
  );
}
