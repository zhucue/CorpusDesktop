import type { ReactNode } from "react";

export interface Part {
  t: string;
  m: boolean;
}

const stripTags = (s: string) => s.replace(/<[^>]*>/g, "");

/** Query words for client-side marking: split on spaces and punctuation; Latin words need 2+ letters. */
export function queryWords(q: string): string[] {
  return q
    .split(/[\s,，、。；;：:!?！？"'“”‘’()（）[\]【】《》<>]+/)
    .map((w) => w.trim())
    .filter((w) => w && (/[^\x00-\x7f]/.test(w) || w.length > 1));
}

export function markWords(text: string, words: string[]): Part[] {
  const ws = [...new Set(words.filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!ws.length || !text) return [{ t: text, m: false }];
  const re = new RegExp(`(${ws.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text
    .split(re)
    .filter((p) => p !== "")
    .map((p) => ({ t: p, m: ws.some((w) => w.toLowerCase() === p.toLowerCase()) }));
}

/**
 * Snippet parts for a hit: the server's `highlight` when it delimits matches with <mark> or <b>
 * (ts_headline style); otherwise the highlight or chunk text with the query words marked here.
 */
export function snippetParts(text: string, highlight: string | null | undefined, words: string[]): Part[] {
  const hl = highlight ?? "";
  if (/<(mark|b)>/i.test(hl)) {
    const out: Part[] = [];
    const re = /<(mark|b)>([\s\S]*?)<\/\1>/gi;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(hl))) {
      if (m.index > last) out.push({ t: stripTags(hl.slice(last, m.index)), m: false });
      out.push({ t: stripTags(m[2]), m: true });
      last = re.lastIndex;
    }
    if (last < hl.length) out.push({ t: stripTags(hl.slice(last)), m: false });
    return out.filter((p) => p.t);
  }
  return markWords(stripTags(hl) || text, words);
}

export function Marked({ parts }: { parts: Part[] }): ReactNode {
  return parts.map((p, i) => (p.m ? <mark key={i}>{p.t}</mark> : <span key={i}>{p.t}</span>));
}
