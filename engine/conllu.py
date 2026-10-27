"""CoNLL-U writer for annotated documents (contracts/p3.md §四). The caller passes effective annotations in
the tokens (pos, lemma, head, deprel); nothing is read from a database here.

Columns: ID = token number in the sentence; FORM; LEMMA; UPOS = pos when it is a UPOS tag, otherwise the
jieba tag mapped to UPOS (X when unknown) with the original tag in XPOS; FEATS = _; HEAD, DEPREL (`_` when
empty); DEPS = _; MISC = SpaceAfter=No when the next token starts where this one ends. Comments: `# newdoc id`
(Document.external_id or title) before each document, then `# sent_id = <doc id>-<n>` (n from 1) and
`# text`. Multiword-token ranges are not written; each stored token is one word line.
"""

from collections.abc import Iterable

from engine.model import Document
from engine.nlp import jieba_upos
from engine.query import UPOS


def _field(value) -> str:
    if value is None:
        return "_"
    text = " ".join(str(value).split()) if isinstance(value, str) else str(value)
    return text or "_"


def write_conllu(documents: Iterable[Document]) -> str:
    out = []
    for doc in documents:
        doc_id = _field(doc.external_id or doc.title)
        out.append(f"# newdoc id = {doc_id}")
        n = 0
        for s in doc.sentences:
            if not s.tokens:
                continue
            n += 1
            out.append(f"# sent_id = {doc_id}-{n}")
            out.append(f"# text = {' '.join(doc.text[s.start : s.end].split())}")
            for i, t in enumerate(s.tokens):
                if t.pos in UPOS or t.pos is None:
                    upos, xpos = t.pos, None
                else:
                    upos, xpos = jieba_upos(t.pos), t.pos
                nxt = s.tokens[i + 1] if i + 1 < len(s.tokens) else None
                misc = "SpaceAfter=No" if nxt and nxt.start <= t.end else None
                out.append(
                    "\t".join(
                        [
                            str(i + 1),
                            _field(t.form),
                            _field(t.lemma),
                            _field(upos),
                            _field(xpos),
                            "_",
                            _field(t.head),
                            _field(t.deprel),
                            "_",
                            _field(misc),
                        ]
                    )
                )
            out.append("")
    return "\n".join(out) + ("\n" if out else "")
