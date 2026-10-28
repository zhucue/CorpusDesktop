/** Names for the POS tags a corpus index carries (插入 → 词性, QA Q21). */
const UPOS: Record<string, string> = {
  ADJ: "形容词",
  ADP: "介词",
  ADV: "副词",
  AUX: "助动词",
  CCONJ: "并列连词",
  DET: "限定词",
  INTJ: "叹词",
  NOUN: "名词",
  NUM: "数词",
  PART: "小品词",
  PRON: "代词",
  PROPN: "专有名词",
  PUNCT: "标点",
  SCONJ: "从属连词",
  SYM: "符号",
  VERB: "动词",
  X: "其他",
};

const JIEBA: Record<string, string> = {
  a: "形容词",
  ad: "副形词",
  ag: "形语素",
  an: "名形词",
  b: "区别词",
  c: "连词",
  d: "副词",
  df: "副词（不）",
  dg: "副语素",
  e: "叹词",
  eng: "英文",
  f: "方位词",
  g: "语素",
  h: "前缀",
  i: "成语",
  j: "简称",
  k: "后缀",
  l: "习用语",
  m: "数词",
  mg: "数语素",
  mq: "数量词",
  n: "名词",
  ng: "名语素",
  nr: "人名",
  nrfg: "人名",
  nrt: "音译人名",
  ns: "地名",
  nt: "机构名",
  nz: "其他专名",
  o: "拟声词",
  p: "介词",
  q: "量词",
  r: "代词",
  rg: "代语素",
  rr: "人称代词",
  rz: "指示代词",
  s: "处所词",
  t: "时间词",
  tg: "时语素",
  u: "助词",
  ud: "助词（得）",
  ug: "助词（过）",
  uj: "助词（的）",
  ul: "助词（了）",
  uv: "助词（地）",
  uz: "助词（着）",
  v: "动词",
  vd: "副动词",
  vg: "动语素",
  vi: "不及物动词",
  vn: "名动词",
  vq: "动词（趋向）",
  w: "标点",
  x: "非语素字",
  y: "语气词",
  z: "状态词",
  zg: "状态语素",
};

export function posName(tag: string): string {
  return UPOS[tag] ?? JIEBA[tag] ?? "";
}

/** One-letter jieba groups that cover their longer tags (n → nr, ns …), shown first. */
export function posGroups(tags: string[]): { tag: string; name: string }[] {
  const set = new Set(tags);
  const groups = tags.filter((t) => /^[a-z]$/.test(t));
  const rest = tags.filter((t) => !groups.includes(t));
  return [...groups, ...rest].filter((t) => set.has(t)).map((tag) => ({ tag, name: posName(tag) }));
}
