"""Engine data model (contracts/p1.md §三). Offsets are Unicode code points into Document.text, [start, end)."""

from dataclasses import dataclass, field


@dataclass
class Token:
    start: int
    end: int
    form: str
    pos: str | None = None
    lemma: str | None = None
    head: int | None = None  # 1-based token number within the sentence, 0 = root
    deprel: str | None = None


@dataclass
class Sentence:
    start: int
    end: int
    tokens: list[Token]
    # parallel formats: target of Alignment ids (Tatoeba id, TMX tu)
    external_id: str | None = None


@dataclass
class Document:
    title: str
    language: str
    text: str
    metadata: dict
    sentences: list[Sentence]
    external_id: str | None = None


@dataclass
class Alignment:
    """Sentence-level alignment between Sentence.external_id values."""

    src_external_id: str
    tgt_external_id: str


@dataclass
class IndexInfo:
    tokens: int
    sentences: int
    documents: int
    index_version: str
    tagset: str = (
        "upos"  # POS tag set of the index: upos | jieba | mixed (engine.query.TAGSETS)
    )


@dataclass
class Context:
    unit: str = "char"  # char | sentence | paragraph
    size: int = 40  # code points, only for unit=char
    # parallel corpora: context never leaves the hit's sentence (neighbouring sentences are unrelated pairs)
    sentence_only: bool = False


@dataclass
class Hit:
    hit_id: str  # "<doc_id>:<start_cp>-<end_cp>", stable for one index content
    doc_id: str
    sentence_index: int  # 0-based within the document
    start_cp: int
    end_cp: int
    left: str
    match: str
    right: str


@dataclass
class Counts:
    hits: int | None
    sentences: int | None
    documents: int | None
    complete: bool


@dataclass
class SearchResult:
    counts: Counts
    items: list[Hit] = field(default_factory=list)
    page: int = 1
    page_size: int = 50
