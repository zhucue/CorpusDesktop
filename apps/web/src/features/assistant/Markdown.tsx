import type { ReactNode } from "react";

/**
 * Small Markdown renderer for assistant prose: headings, paragraphs, lists, tables, quotes, rules, fenced code;
 * inline `code`, **bold**, *italic*, [text](url) and [n] citations. No HTML passthrough.
 */

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: number; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "table"; head: string[]; align: ("left" | "right" | "center" | undefined)[]; rows: string[][] }
  | { kind: "quote"; lines: string[] }
  | { kind: "code"; text: string }
  | { kind: "hr" };

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split(/(?<!\\)\|/)
    .map((c) => c.trim().replace(/\\\|/g, "|"));
const isSep = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const UL = /^\s*[-*+]\s+(.*)$/;
const OL = /^\s*\d+[.、)]\s+(.*)$/;

export function parseBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^\s*```/.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const h = /^\s*(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      out.push({ kind: "h", level: h[1].length, text: h[2].replace(/\s+#+\s*$/, "") });
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.push({ kind: "hr" });
      i++;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
      const head = cells(line);
      const align = cells(lines[i + 1]).map((c) => (c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : undefined));
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push({ kind: "table", head, align, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push({ kind: "quote", lines: body });
      continue;
    }
    const list = UL.test(line) ? "ul" : OL.test(line) ? "ol" : null;
    if (list) {
      const re = list === "ul" ? UL : OL;
      const items: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        const m = re.exec(lines[i]);
        if (m) items.push(m[1]);
        else if (items.length && /^\s{2,}\S/.test(lines[i])) items[items.length - 1] += " " + lines[i].trim();
        else break;
        i++;
      }
      out.push({ kind: list, items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,6}\s|>)/.test(lines[i]) && !UL.test(lines[i]) && !OL.test(lines[i])) {
      if (lines[i].includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) break;
      para.push(lines[i++]);
    }
    if (!para.length) para.push(lines[i++]);
    out.push({ kind: "p", lines: para });
  }
  return out;
}

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\s][^*\n]*\*|\[[^\]\n]+\]\((?:https?:\/\/|\/)[^)\s]+\)|\[\d+\])/g;

/** Inline formatting: `code`, **bold**, *italic*, [text](url) and [n] citations. */
export function Inline({ text }: { text: string }) {
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return p;
        if (p.startsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
        if (p.startsWith("**") || p.startsWith("__")) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (/^\[\d+\]$/.test(p))
          return (
            <span key={i} className="cite">
              {p.slice(1, -1)}
            </span>
          );
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(p);
        if (link)
          return (
            <a key={i} href={link[2]} target={link[2].startsWith("/") ? undefined : "_blank"} rel="noreferrer">
              {link[1]}
            </a>
          );
        return <em key={i}>{p.slice(1, -1)}</em>;
      })}
    </>
  );
}

function withCaret(node: ReactNode, caret: ReactNode) {
  return (
    <>
      {node}
      {caret}
    </>
  );
}

export function Markdown({ text, caret }: { text: string; caret?: ReactNode }) {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((b, i) => {
        const end = i === blocks.length - 1 ? caret : null;
        switch (b.kind) {
          case "h": {
            const Tag = (b.level <= 2 ? "h3" : "h4") as "h3" | "h4";
            return <Tag key={i} className="md-h">{withCaret(<Inline text={b.text} />, end)}</Tag>;
          }
          case "hr":
            return <hr key={i} className="md-hr" />;
          case "code":
            return (
              <pre key={i} className="md-pre">
                <code>{b.text}</code>
              </pre>
            );
          case "quote":
            return (
              <blockquote key={i} className="md-quote">
                {withCaret(<Inline text={b.lines.join("\n")} />, end)}
              </blockquote>
            );
          case "ul":
          case "ol": {
            const Tag = b.kind;
            return (
              <Tag key={i} className="md-list">
                {b.items.map((it, j) => (
                  <li key={j}>{withCaret(<Inline text={it} />, j === b.items.length - 1 ? end : null)}</li>
                ))}
              </Tag>
            );
          }
          case "table":
            return (
              <div key={i} className="md-table-wrap">
                <table className="md-table">
                  <thead>
                    <tr>
                      {b.head.map((c, j) => (
                        <th key={j} style={{ textAlign: b.align[j] }}>
                          <Inline text={c} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, k) => (
                      <tr key={k}>
                        {b.head.map((_, j) => (
                          <td key={j} style={{ textAlign: b.align[j] }}>
                            <Inline text={r[j] ?? ""} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {end}
              </div>
            );
          default:
            return <p key={i}>{withCaret(<Inline text={b.lines.join("\n")} />, end)}</p>;
        }
      })}
      {blocks.length === 0 && caret}
    </>
  );
}
