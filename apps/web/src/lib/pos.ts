/** UPOS → categorical colour index (doc/frontend-design.md 3, palette c1–c8). */
const POS_CAT: Record<string, number> = {
  NOUN: 1, PROPN: 1, VERB: 2, ADJ: 3, ADV: 4, PRON: 5, ADP: 6, AUX: 7, PART: 7,
  DET: 8, NUM: 8, CCONJ: 8, SCONJ: 8, PUNCT: 8, X: 8,
};

/** jieba / ICTCLAS tags group by their first letter (n, nr, ns… → noun). */
const JIEBA_CAT: Record<string, number> = { n: 1, v: 2, a: 3, d: 4, r: 5, p: 6, u: 7, c: 8, m: 8, w: 8 };

export function posCat(p: string | null | undefined): number {
  if (!p) return 8;
  const upos = POS_CAT[p];
  if (upos) return upos;
  // Lower-case tags are jieba; upper-case unknowns fall back to the UPOS table case-insensitively.
  if (/^[a-z]/.test(p)) return JIEBA_CAT[p[0]] ?? 8;
  return POS_CAT[p.toUpperCase()] ?? 8;
}

/** Punctuation and unknown tokens are not coloured in KWIC. */
export function isPunctPos(p: string | null | undefined): boolean {
  if (!p) return true;
  return p === "PUNCT" || p === "X" || p === "x" || p === "w" || /^w[a-z]*$/.test(p);
}

export const posLegend: [number, string][] = [
  [1, "名词 NOUN · n"], [2, "动词 VERB · v"], [3, "形容词 ADJ · a"], [4, "副词 ADV · d"],
  [5, "代词 PRON · r"], [6, "介词 ADP · p"], [7, "助词 AUX/PART · u"], [8, "其他 DET/NUM/c/m/w"],
];
