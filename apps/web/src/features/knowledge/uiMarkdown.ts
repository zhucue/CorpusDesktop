import { createParser } from "@openuidev/react-lang";
import type { MessagePart } from "../../api";
import { fmtValue } from "../../lib/format";
import { library } from "../../openui/library";
import { parseJsonBlock } from "../../openui/UiBlock";
import { knowledgeHref, locatorText } from "./data";

type Block = { component: string; props: Record<string, unknown> };
type Row = Record<string, unknown>;

let parser: ReturnType<typeof createParser> | null = null;

/** A ui part as `{component, props}`: the JSON fallback, or OpenUI Lang through the library's parser. */
export function uiBlocks(lang: string): Block[] {
  const json = parseJsonBlock(lang);
  if (json) return json;
  try {
    parser ??= createParser(library.toJSONSchema());
    const root = parser.parse(lang).root;
    return root ? [{ component: root.typeName, props: root.props }] : [];
  } catch {
    return [];
  }
}

const cell = (v: unknown) => (v == null ? "" : String(typeof v === "number" ? fmtValue(v) : v)).replace(/\|/g, "\\|").replace(/\n/g, " ");
const rowsOf = (v: unknown): Row[] => (Array.isArray(v) ? v.filter((r): r is Row => !!r && typeof r === "object") : []);
const s = (v: unknown) => (v == null ? "" : String(v));

function table(head: string[], rows: unknown[][]): string {
  if (!rows.length) return "";
  return [`| ${head.join(" | ")} |`, `| ${head.map(() => "---").join(" | ")} |`, ...rows.map((r) => `| ${r.map(cell).join(" | ")} |`)].join("\n");
}

function searchLink(projectId: string, q: string): string {
  return `/p/${projectId}/search?${new URLSearchParams({ q }).toString()}`;
}

/** Text table or link standing in for one result component in a note. */
export function blockMarkdown(b: Block, projectId: string): string {
  const p = b.props ?? {};
  const statLink = p.stat_id ? `\n\n[在统计中打开](/p/${projectId}/stats?stat=${encodeURIComponent(s(p.stat_id))})` : "";
  switch (b.component) {
    case "KwicTable":
      return `**KWIC** \`${s(p.query)}\` · ${s(p.scope_name)}\n\n${table(
        ["左语境", "命中", "右语境", "出处"],
        rowsOf(p.rows).map((r) => [r.left, r.match, r.right, r.source]),
      )}\n\n[打开完整结果](${searchLink(projectId, s(p.query))})`;
    case "FreqChart":
      return `**${s(p.title) || "频次"}**（${s(p.unit)}）\n\n${table(["项", "值", "每百万"], rowsOf(p.rows).map((r) => [r.label, r.value, r.per_million]))}${statLink}`;
    case "CollocationTable":
      return `**搭配** ${s(p.node)} · ±${s(p.window)} · ${s(p.measure)}\n\n${table(["搭配词", "共现", s(p.measure) || "分值"], rowsOf(p.rows).map((r) => [r.collocate, r.freq, r.score]))}${statLink}`;
    case "KeywordTable":
      return `**关键词** ${s(p.target)} 对 ${s(p.reference)}\n\n${table(["词", "目标", "参照", s(p.measure) || "分值"], rowsOf(p.rows).map((r) => [r.word, r.target_freq, r.reference_freq, r.score]))}${statLink}`;
    case "DistributionChart":
      return `**分布** ${s(p.field)}\n\n${table(["区间", "命中", "每百万词"], rowsOf(p.rows).map((r) => [r.bin, r.hits, r.per_million]))}${statLink}`;
    case "EvidenceCard":
      return `> ${s(p.text)}\n>\n> —— ${s(p.source)}`;
    case "JobStatus":
      return `任务 ${s(p.kind)} #${s(p.job_id).slice(0, 8)}：${s(p.state)}（[打开任务](/p/${projectId}/jobs?job=${encodeURIComponent(s(p.job_id))})）`;
    case "Callout":
      return `> ${s(p.text)}`;
    case "DependencyTree":
      return `**依存树** 句 ${Number(p.sentence_index ?? 0) + 1}：${rowsOf(p.tokens)
        .map((t) => `${s(t.form)}/${s(t.pos)}`)
        .join(" ")}\n\n[在标注中打开](/p/${projectId}/annotate?doc=${encodeURIComponent(s(p.document_id))}&s=${s(p.sentence_index)})`;
    case "AnnotationDiff":
      return `**预标差异** 句 ${Number(p.sentence_index ?? 0) + 1}\n\n${table(["词", "模型", "人工", "状态"], rowsOf(p.tokens).map((t) => [t.form, t.model, t.human, t.status]))}`;
    case "TermCard": {
      const tr = rowsOf(p.translations).map((t) => s(t.text)).filter(Boolean).join("、");
      const ex = rowsOf(p.examples).map((x) => `- ${s(x.text)}（${s(x.source)}）`);
      return [`**${s(p.term)}**${tr ? `（${tr}）` : ""}：${s(p.definition)}`, ...ex, `[打开术语](${knowledgeHref(projectId, { tab: "terms", term: s(p.term_id), tq: s(p.term) })})`].join("\n");
    }
    case "KbCitation":
      return rowsOf(p.items)
        .map((x, i) => {
          const loc = locatorText(x.locator as never);
          return `${i + 1}. [${s(x.title)}${loc ? ` · ${loc}` : ""}](${knowledgeHref(projectId, { doc: s(x.document_id), chunk: s(x.chunk_id) })})：${s(x.text)}`;
        })
        .join("\n");
    default:
      return `[${b.component}]`;
  }
}

/** An assistant answer as Markdown: text parts as written, ui parts as tables or links. */
export function messageMarkdown(parts: MessagePart[], projectId: string): string {
  return parts
    .map((p) => {
      if (p.type === "text") return p.text.trim();
      if (p.type === "ui") return uiBlocks(p.lang).map((b) => blockMarkdown(b, projectId)).join("\n\n");
      return "";
    })
    .filter(Boolean)
    .join("\n\n");
}
