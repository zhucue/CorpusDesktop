"""Bilingual alignment candidates (contracts/p5.md §三).

Sentence level, for document pairs without stored sentence alignments: every source / target sentence pair in a
band around the diagonal with embedding cosine ≥ THRESHOLD is a candidate scored
0.8 · cosine + 0.2 · length similarity, where length similarity = min(r, 1/r) for r = (len(tgt) / len(src)) / R
and R = total target length / total source length of the two documents (code points). Candidates are taken
greedily by score, one-to-one (each sentence used once). Vectors are unit length (engine.kb.embed), so cosine =
dot product.

Word level: model answers [{src: [i…], tgt: [j…]}] with 1-based token numbers are checked by clean_links.
"""

THRESHOLD = 0.5
COSINE_WEIGHT = 0.8


def _dot(u, v) -> float:
    return sum(a * b for a, b in zip(u, v))


def length_similarity(src_len: int, tgt_len: int, ratio: float) -> float:
    if src_len <= 0 or tgt_len <= 0 or ratio <= 0:
        return 0.0
    r = tgt_len / src_len / ratio
    return min(r, 1 / r)


def band(n: int, m: int) -> int:
    """Half-width (in target sentences) of the diagonal band searched for each source sentence."""
    return max(10, (max(n, m) + 4) // 5)


def match_sentences(
    src: list[str], tgt: list[str], src_vectors, tgt_vectors, threshold=THRESHOLD
) -> list[tuple[int, int, float]]:
    """Greedy one-to-one sentence matches → [(source index, target index, score)] in source order."""
    n, m = len(src), len(tgt)
    if not n or not m:
        return []
    ratio = (sum(len(t) for t in tgt) or 1) / (sum(len(s) for s in src) or 1)
    width = band(n, m)
    candidates = []
    for i in range(n):
        center = i * m / n
        for j in range(max(0, int(center) - width), min(m, int(center) + width + 1)):
            cos = _dot(src_vectors[i], tgt_vectors[j])
            if cos < threshold:
                continue
            score = COSINE_WEIGHT * cos + (1 - COSINE_WEIGHT) * length_similarity(
                len(src[i]), len(tgt[j]), ratio
            )
            candidates.append((-score, abs(j - center), i, j))
    candidates.sort()
    used_src, used_tgt, out = set(), set(), []
    for neg, _, i, j in candidates:
        if i in used_src or j in used_tgt:
            continue
        used_src.add(i)
        used_tgt.add(j)
        out.append((i, j, round(-neg, 4)))
    return sorted(out)


def clean_links(links, n_src: int, n_tgt: int) -> list[tuple[tuple, tuple]]:
    """Valid, de-duplicated links: each side a non-empty list of distinct ints in 1..n; others are dropped."""
    out, seen = [], set()
    for link in links if isinstance(links, list) else []:
        if not isinstance(link, dict):
            continue
        sides = []
        for key, n in (("src", n_src), ("tgt", n_tgt)):
            value = link.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                value = [value]
            if not isinstance(value, list) or not value:
                break
            if not all(
                isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= n
                for x in value
            ):
                break
            sides.append(tuple(sorted(set(value))))
        if len(sides) != 2:
            continue
        key = (sides[0], sides[1])
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def word_pairs(links) -> set[tuple[int, int]]:
    """Links [(src tuple, tgt tuple)] → the set of (i, j) word pairs they connect."""
    return {(i, j) for s, t in links for i in s for j in t}
