import type { EvidenceKind, JobKind, JobState, KbKind, LayerKind, StatMethod } from "../api";
import { Icon, type IconName } from "./Icon";

/** Domain → icon maps shared by pages, the task tray, the command palette and OpenUI cards. */

export const pageIcon: Record<string, IconName> = {
  corpora: "library",
  search: "textsearch",
  stats: "barchart",
  annotate: "highlighter",
  knowledge: "bookopen",
  assistant: "sparkles",
  jobs: "listchecks",
  settings: "settings",
};

export const jobKindIcon: Record<JobKind, IconName> = {
  import: "fileup",
  index: "databasezap",
  export: "filedown",
  stats: "barchart",
  preannotate: "wand",
  kb_import: "bookopen",
  kb_summarize: "sparkles",
  kb_extract: "booka",
};

export const jobStateIcon: Record<JobState, IconName> = {
  queued: "hourglass",
  running: "loader",
  succeeded: "circlecheck",
  failed: "circlex",
  cancelled: "ban",
};

export const statIcon: Record<StatMethod, IconName> = {
  frequency: "chartbar",
  ngrams: "listordered",
  collocations: "chartnetwork",
  keywords: "chartscatter",
  distribution: "barchart",
};

export const layerIcon: Record<LayerKind, IconName> = {
  pos: "tag",
  dep: "listtree",
  span: "squaredashed",
  relation: "waypoints",
  alignment: "languages",
};

/** Knowledge-base documents; `term` is the glossary, `pdf`/`docx`/`md`/`txt` refine literature by file type. */
export const kbIcon: Record<KbKind | "term" | "pdf" | "docx" | "md" | "txt", IconName> = {
  literature: "bookopentext",
  guideline: "scrolltext",
  note: "notebookpen",
  url: "globe",
  term: "booka",
  pdf: "filepdf",
  docx: "filetype",
  md: "filecode",
  txt: "filetext",
};

export const evidenceIcon: Record<EvidenceKind, IconName> = {
  hit: "textquote",
  stat_row: "chartbar",
  text: "quote",
};

const FORMAT_ICON: Record<string, IconName> = {
  txt: "filetext",
  text: "filetext",
  docx: "filetype",
  doc: "filetype",
  pdf: "filepdf",
  md: "filecode",
  csv: "filespreadsheet",
  tsv: "filespreadsheet",
  xlsx: "filespreadsheet",
  tmx: "filecode",
  xml: "filecode",
  conllu: "filebraces",
  conll: "filebraces",
  json: "filebraces",
  jsonl: "filebraces",
  zip: "archive",
};

/** Icon for a corpus or document format (`txt`, `docx`, `csv`, `tmx`, `conllu`…) or a file name. */
export function iconForFormat(formatOrName: string | null | undefined): IconName {
  const s = (formatOrName ?? "").toLowerCase();
  const ext = s.includes(".") ? s.slice(s.lastIndexOf(".") + 1) : s;
  return FORMAT_ICON[ext] ?? "file";
}

/** File icon with the format as its accessible name. */
export function FileTypeIcon({ format, size = 16, className }: { format: string | null | undefined; size?: 12 | 14 | 16 | 18 | 20; className?: string }) {
  const s = (format ?? "").toLowerCase();
  const ext = s.includes(".") ? s.slice(s.lastIndexOf(".") + 1) : s;
  return <Icon name={iconForFormat(format)} size={size} className={["ft-ic", className ?? ""].filter(Boolean).join(" ")} label={ext ? ext.toUpperCase() : "文件"} />;
}

/** KB document icon: literature refined by the file extension of its source or title. */
export function kbDocIcon(kind: KbKind | string, source?: string | null, title?: string | null): IconName {
  if (kind === "literature") {
    for (const s of [source, title]) {
      const m = (s ?? "").toLowerCase().match(/\.(pdf|docx|md|txt)(?:$|[?#])/);
      if (m) return kbIcon[m[1] as "pdf" | "docx" | "md" | "txt"];
    }
  }
  return kbIcon[kind as KbKind] ?? "file";
}
