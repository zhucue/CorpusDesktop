export const fmt = (n: number | null | undefined, digits = 0) =>
  n == null || Number.isNaN(n) ? "" : Number(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Integers print with separators; other numbers keep up to `digits` decimals. */
export function fmtValue(v: unknown, digits = 2): string {
  if (v == null || v === "") return "";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return fmt(v);
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: Math.min(digits, 1) });
}

export const fmtTime = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("zh-CN", { hour12: false }) : "");

export function fmtShortTime(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  if (d.toDateString() === now.toDateString()) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtDuration(ms: number): string {
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} 秒`;
  const m = Math.floor(s / 60);
  return `${m} 分 ${Math.round(s - m * 60)} 秒`;
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** 今天 / 本周 / 更早, for session lists. */
export function dayGroup(s: string): "今天" | "本周" | "更早" {
  const d = new Date(s);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "今天";
  const weekStart = new Date(now);
  weekStart.setHours(0, 0, 0, 0);
  weekStart.setDate(weekStart.getDate() - ((weekStart.getDay() + 6) % 7));
  return d >= weekStart ? "本周" : "更早";
}

export function metadataText(m: Record<string, unknown>): string {
  return Object.entries(m)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join("；");
}
