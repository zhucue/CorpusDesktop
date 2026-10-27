import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Markdown → sanitized HTML (GFM tables, line breaks). */
export function markdownHtml(text: string): string {
  const html = marked.parse(text ?? "", { async: false, gfm: true, breaks: true });
  return DOMPurify.sanitize(html);
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => markdownHtml(text), [text]);
  return <div className={`md ${className ?? ""}`} dangerouslySetInnerHTML={{ __html: html }} />;
}
