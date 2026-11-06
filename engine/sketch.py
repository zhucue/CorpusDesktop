"""Word Sketch and sketch diff over UD dependencies (contracts/p10.md §五). Pure computation over documents
(engine.metrics.Doc, tokens (form, pos, lemma, head, deprel)); the worker reads them from the index (system
dependencies) or from a dependency layer in PostgreSQL.

Relations, read from every dependency d → head h (deprel base = the part before ":"); node = the side whose
lemma is looked up, collocate = the other side:
  subject      nsubj (nsubj:pass …): node = h, collocate = d
  subject_of   nsubj: node = d, collocate = h                       (作主语的谓词)
  object       obj, iobj: node = h, collocate = d
  amod / advmod / nmod / compound: node = h, collocate = d          (修饰语)
  amod_of …    the same deprels: node = d, collocate = h            (所修饰的词)
  conj         conj, both directions
  pp:<case>    obl / nmod dependent d with a `case` child p: node = h, collocate = d, one column per p's lemma
               (`with + N`)
Lemmas: the token lemma, else its form; the node matches case-insensitively (and its POS, when given, is one of
the resolved tags). Collocates made only of punctuation, symbols and digits are left out.
  f(n,r,c) = instances of relation r between node n and collocate c; f(n,r,*) = Σc; f(*,r,c) = instances of r with
  collocate c and any node; logDice = 14 + log₂(2 f(n,r,c) / (f(n,r,*) + f(*,r,c)))   (Rychlý 2008, per relation)
Rows: per relation the collocates with f(n,r,c) ≥ min_freq, the `top` best by logDice (then frequency, lemma).
search_query (same-sentence approximation, may find more than the row's count): the dependent token with its
  deprel (`"form"{dep=obj}` when one form was seen, else `{lemma=x,dep=obj}`) plus `+` conditions for the head's
  seen forms (and the preposition's for pp); conj rows seen in both directions add search_query_reverse.
Sketch diff: per relation, collocates with f ≥ min_freq for either lemma; diff = logdice_a − logdice_b (a
  missing logDice counts as 0); group a (only A reaches min_freq), b (only B), common (both); per relation the
  `top` rows of each group, a and common by diff desc, b by diff asc (most B-leaning first), shown a, common, b.
"""

import math
from collections import Counter, defaultdict

from engine.stats import Table, _col, _rank, _row, is_punct

MODIFIERS = ("amod", "advmod", "nmod", "compound")
FIXED = (
    ("subject", "主语"),
    ("object", "宾语"),
    *(
        x
        for m in MODIFIERS
        for x in ((m, f"修饰语（{m}）"), (f"{m}_of", f"所修饰的词（{m}）"))
    ),
    ("conj", "并列"),
)
LAST = (("subject_of", "作主语的谓词"),)
_UNSAFE = set(' ,{}[]|=/"')


def label(rel) -> str:
    if rel.startswith("pp:"):
        return f"{rel[3:]} + N"
    return dict(FIXED + LAST).get(rel, rel)


def _lemma(tok):
    return tok[2] or tok[0]


def instances(sent):
    """(relation, node index, collocate index, dependent index, case index or None) of a sentence (0-based)."""
    children = defaultdict(list)
    for i, tok in enumerate(sent):
        if tok[3]:
            children[tok[3] - 1].append(i)
    for d, tok in enumerate(sent):
        h, dep = (tok[3] or 0) - 1, tok[4]
        if h < 0 or h >= len(sent) or not dep:
            continue
        base = dep.split(":")[0]
        if base == "nsubj":
            yield "subject", h, d, d, None
            yield "subject_of", d, h, d, None
        elif base in ("obj", "iobj"):
            yield "object", h, d, d, None
        elif base == "conj":
            yield "conj", h, d, d, None
            yield "conj", d, h, d, None
        if base in MODIFIERS:
            yield base, h, d, d, None
            yield f"{base}_of", d, h, d, None
        if base in ("obl", "nmod"):
            for c in children.get(d, ()):
                cdep = sent[c][4] or ""
                if cdep.split(":")[0] == "case":
                    p = _lemma(sent[c]).lower()
                    if p and not is_punct(p):
                        yield f"pp:{p}", h, d, d, c


class _Seen:
    __slots__ = ("case_forms", "coll_forms", "dep_side", "deprels", "node_forms")

    def __init__(self):
        self.node_forms, self.coll_forms = set(), set()
        self.dep_side, self.deprels, self.case_forms = set(), set(), set()


def collect(docs, lemmas, pos_tags=None, check=None):
    """One pass: per looked-up lemma (lower-cased) node frequency and f(n,r,c) with what each row saw; f(*,r,c)."""
    targets = {lm.lower(): lm for lm in lemmas}
    node_freq = Counter()
    pairs = {lm: defaultdict(Counter) for lm in targets}  # lemma → rel → coll → f
    seen = {lm: {} for lm in targets}  # lemma → (rel, coll) → _Seen
    background = defaultdict(Counter)  # rel → coll → f(*,r,c)
    for doc in docs:
        if check:
            check()
        for sent in doc.sentences:
            keys = [_lemma(t) for t in sent]
            for i, tok in enumerate(sent):
                k = keys[i].lower()
                if k in targets and (not pos_tags or tok[1] in pos_tags):
                    node_freq[k] += 1
            for rel, n, c, d, case in instances(sent):
                coll = keys[c]
                if is_punct(coll):
                    continue
                background[rel][coll] += 1
                k = keys[n].lower()
                if k not in targets or (pos_tags and sent[n][1] not in pos_tags):
                    continue
                pairs[k][rel][coll] += 1
                s = seen[k].setdefault((rel, coll), _Seen())
                s.node_forms.add(sent[n][0])
                s.coll_forms.add(sent[c][0])
                s.dep_side.add("node" if d == n else "coll")
                s.deprels.add(sent[d][4])
                if case is not None:
                    s.case_forms.add(sent[case][0])
    return node_freq, pairs, seen, background


def _alts(forms):
    if not forms or any('"' in f for f in forms):
        return None
    return "|".join(f'"{f}"' for f in sorted(forms))


def _query(dep_lemma, dep_forms, deprels, head_forms, case_forms=()):
    if any(ch in _UNSAFE for v in deprels for ch in v):
        return None
    d = "|".join(sorted(deprels))
    if len(dep_forms) == 1 and '"' not in next(iter(dep_forms)):
        slot = f'"{next(iter(dep_forms))}"{{dep={d}}}'
    elif dep_lemma and not any(ch in _UNSAFE for ch in dep_lemma):
        slot = f"{{lemma={dep_lemma},dep={d}}}"
    else:
        return None
    heads = _alts(head_forms)
    if heads is None:
        return None
    q = f"{slot} +{heads}"
    if case_forms:
        cases = _alts(case_forms)
        if cases is None:
            return None
        q += f" +{cases}"
    return q


def row_queries(node_lemma, coll, s: _Seen, rel):
    """(search_query, search_query_reverse) of a row."""
    case = s.case_forms if rel.startswith("pp:") else ()
    out = []
    for side in ("coll", "node"):
        if side not in s.dep_side:
            out.append(None)
            continue
        if side == "coll":
            out.append(_query(coll, s.coll_forms, s.deprels, s.node_forms, case))
        else:
            out.append(_query(node_lemma, s.node_forms, s.deprels, s.coll_forms, case))
    first, second = out
    return (first, second) if first else (second, None)


def logdice(f, f_node, f_coll):
    return 14 + math.log2(2 * f / (f_node + f_coll))


def _order(rels):
    fixed = [r for r, _ in FIXED if r in rels]
    pp = sorted((r for r in rels if r.startswith("pp:")), key=lambda r: (-rels[r], r))
    last = [r for r, _ in LAST if r in rels]
    return fixed + pp + last


def _scores(pairs, background, rel):
    total = sum(pairs[rel].values())
    return total, {
        c: logdice(f, total, background[rel][c]) for c, f in pairs[rel].items()
    }


def sketch(
    docs, lemma, pos_tags=None, min_freq=2, top=25, check=None, layer=None
) -> Table:
    node_freq, pairs, seen, background = collect(docs, [lemma], pos_tags, check)
    k = lemma.lower()
    p, sn = pairs[k], seen[k]
    rels = {r: sum(cs.values()) for r, cs in p.items() if cs}
    rows, relations, row_count = [], [], 0
    for rel in _order(rels):
        total, scores = _scores(p, background, rel)
        items = [c for c, f in p[rel].items() if f >= min_freq]
        row_count += len(items)
        items.sort(key=lambda c: (-_rank(scores[c]), -p[rel][c], c))
        relations.append(
            {"key": rel, "label": label(rel), "freq": total, "rows": len(items[:top])}
        )
        for c in items[:top]:
            q, rq = row_queries(lemma, c, sn[(rel, c)], rel)
            extra = {"search_query_reverse": rq} if rq else {}
            if layer:
                extra["search_layers"] = {"dep": layer}
            rows.append(
                _row(
                    f"{rel}\t{c}",
                    {
                        "relation": rel,
                        "relation_label": label(rel),
                        "collocate": c,
                        "freq": p[rel][c],
                        "coll_freq": background[rel][c],
                        "logdice": scores[c],
                    },
                    q,
                    **extra,
                )
            )
    columns = [
        _col("relation_label", "关系", "string"),
        _col("collocate", "搭配词", "string"),
        _col("freq", "共现频次"),
        _col("coll_freq", "该关系中搭配词频次"),
        _col("logdice", "logDice"),
    ]
    totals = {"lemma": lemma, "node_freq": node_freq[k], "relations": relations}
    return Table(columns, rows, row_count, totals)


def diff(
    docs, lemma_a, lemma_b, pos_tags=None, min_freq=2, top=25, check=None, layer=None
) -> Table:
    if lemma_a.lower() == lemma_b.lower():
        raise ValueError("两个词元相同")
    node_freq, pairs, seen, background = collect(
        docs, [lemma_a, lemma_b], pos_tags, check
    )
    ka, kb = lemma_a.lower(), lemma_b.lower()
    pa, pb = pairs[ka], pairs[kb]
    rels = Counter()
    for p in (pa, pb):
        for r, cs in p.items():
            rels[r] += sum(cs.values())
    rows, relations, row_count = [], [], 0
    for rel in _order(rels):
        ta, sa = _scores(pa, background, rel) if rel in pa else (0, {})
        tb, sb = _scores(pb, background, rel) if rel in pb else (0, {})
        groups = {"a": [], "common": [], "b": []}
        for c in set(pa.get(rel, {})) | set(pb.get(rel, {})):
            fa, fb = pa[rel][c] if rel in pa else 0, pb[rel][c] if rel in pb else 0
            in_a, in_b = fa >= min_freq, fb >= min_freq
            if not (in_a or in_b):
                continue
            la, lb = sa.get(c), sb.get(c)
            d = (la or 0.0) - (lb or 0.0)
            g = "common" if in_a and in_b else "a" if in_a else "b"
            groups[g].append((c, fa, fb, la, lb, d))
        n_rel = 0
        for g in ("a", "common", "b"):
            items = groups[g]
            row_count += len(items)
            sign = 1 if g == "b" else -1
            items.sort(key=lambda x: (sign * _rank(x[5]), -(x[1] + x[2]), x[0]))
            shown = items[:top]
            if g == "b":
                shown = shown[
                    ::-1
                ]  # rows of a relation read from most A-leaning to most B-leaning
            for c, fa, fb, la, lb, d in shown:
                qa = row_queries(lemma_a, c, seen[ka][(rel, c)], rel)[0] if fa else None
                qb = row_queries(lemma_b, c, seen[kb][(rel, c)], rel)[0] if fb else None
                extra = {"search_query_b": qb}
                if layer:
                    extra["search_layers"] = {"dep": layer}
                rows.append(
                    _row(
                        f"{rel}\t{c}",
                        {
                            "relation": rel,
                            "relation_label": label(rel),
                            "collocate": c,
                            "freq_a": fa,
                            "freq_b": fb,
                            "logdice_a": la,
                            "logdice_b": lb,
                            "diff": d,
                            "group": g,
                        },
                        qa or qb,
                        **extra,
                    )
                )
                n_rel += 1
        relations.append(
            {"key": rel, "label": label(rel), "freq_a": ta, "freq_b": tb, "rows": n_rel}
        )
    columns = [
        _col("relation_label", "关系", "string"),
        _col("collocate", "搭配词", "string"),
        _col("freq_a", f"{lemma_a} 频次"),
        _col("freq_b", f"{lemma_b} 频次"),
        _col("logdice_a", f"{lemma_a} logDice"),
        _col("logdice_b", f"{lemma_b} logDice"),
        _col("diff", "logDice 差"),
        _col("group", "偏向", "string"),
    ]
    totals = {
        "lemma_a": lemma_a,
        "lemma_b": lemma_b,
        "node_freq_a": node_freq[ka],
        "node_freq_b": node_freq[kb],
        "relations": relations,
    }
    return Table(columns, rows, row_count, totals)
