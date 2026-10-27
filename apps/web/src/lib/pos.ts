/** UPOS → categorical colour index (doc/frontend-design.md 3, palette c1–c8). */
const POS_CAT: Record<string, number> = {
  NOUN: 1, PROPN: 1, VERB: 2, ADJ: 3, ADV: 4, PRON: 5, ADP: 6, AUX: 7, PART: 7,
  DET: 8, NUM: 8, CCONJ: 8, SCONJ: 8, PUNCT: 8, X: 8,
};
export const posCat = (p: string | null | undefined) => (p ? POS_CAT[p.toUpperCase()] ?? 8 : 8);

export const posLegend: [number, string][] = [
  [1, "名词 NOUN"], [2, "动词 VERB"], [3, "形容词 ADJ"], [4, "副词 ADV"],
  [5, "代词 PRON"], [6, "介词 ADP"], [7, "助词 AUX/PART"], [8, "限定·数词 DET/NUM"],
];
