import type { MetadataField } from "../../api";

/** Chinese names of common document metadata fields (QA Q26 / Q34); other fields keep their own name. */
const LABELS: Record<string, string> = {
  position: "文档位置",
  year: "年份",
  date: "日期",
  pub_date: "发布日期",
  publish_date: "发布日期",
  revision_time: "修订时间",
  decade: "年代",
  period: "时期",
  genre: "体裁",
  type: "类型",
  category: "类别",
  topic: "主题",
  register: "语域",
  source: "来源",
  author: "作者",
  level: "水平",
  grade: "年级",
  gender: "性别",
  native_language: "母语",
  l1: "母语",
  score: "分数",
  split: "数据划分",
  lang: "语言",
  language: "语言",
  tatoeba_lang: "语言",
  url: "链接",
  page_title: "页面标题",
  title: "标题",
  matched_terms: "匹配词",
};

export const fieldLabel = (field: string) => LABELS[field] ?? field;

/** Bookkeeping fields with no research value: ids, keys, hashes, import parts, dump names. */
export function internalField(field: string): boolean {
  return /(^|_)(id|ids|key|hash|uuid)$/i.test(field) || ["part", "dump", "tatoeba_lang", "record_key"].includes(field);
}

/** Time-like fields first, then genre-like, then the rest. */
function rank(field: string): number {
  if (/year|年|date|日期|decade|period|time|时期/i.test(field)) return 0;
  if (/genre|体裁|type|类型|category|类别|topic|主题|register|level|grade/i.test(field)) return 1;
  return 2;
}

/** Distribution fields: numbers and enumerable strings with more than one value, ordered time / genre first;
 * ids, links, titles and single-valued fields are left out; 文档位置 last. */
export function distributionFields(fields: MetadataField[]): string[] {
  const usable = fields.filter((f) => {
    if (internalField(f.field) || ["url", "title", "page_title"].includes(f.field)) return false;
    if (f.values) return f.values.length > 1;
    return f.type === "number";
  });
  return [...usable.map((f) => f.field).sort((a, b) => rank(a) - rank(b)), "position"];
}
