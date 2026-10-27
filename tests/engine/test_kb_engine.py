"""engine.kb: parsers, chunker, keyword text, term candidates (pure and CWB), embedder (nlp)."""

import math
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from engine import cwb, stats
from engine.kb import chunk, parse, terms, text
from engine.parsers import conllu

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# ---- parsers ----


def test_pdf_blocks_per_page():
    blocks, meta = parse.parse(FIXTURES / "kb-sample.pdf", "pdf")
    assert [b["locator"] for b in blocks] == [{"page": 1}, {"page": 2}]
    assert blocks[0]["text"].startswith("Corpus linguistics studies language")
    assert "\n" not in blocks[0]["text"]  # wrapped lines joined
    assert blocks[1]["text"].startswith(
        "语料库语言学以大规模真实文本为基础研究语言使用。"
    )
    assert " " not in blocks[1]["text"]  # no space between CJK lines
    assert meta == {"pages": 2, "title": "Corpus sample", "author": "Test"}


def test_docx_heading_paths():
    blocks, meta = parse.parse(FIXTURES / "kb-sample.docx", "docx")
    assert blocks == [
        {
            "text": "本规范说明词性标注的基本原则。",
            "locator": {"heading_path": ["标注规范"]},
        },
        {
            "text": "表示人、事物、地点或抽象概念的词标为名词。",
            "locator": {"heading_path": ["标注规范", "名词"]},
        },
        {
            "text": "表示动作、行为或状态变化的词标为动词。",
            "locator": {"heading_path": ["标注规范", "动词"]},
        },
    ]
    assert meta["title"] == "标注规范样例"


def test_markdown_paragraphs_lines_and_headings():
    blocks, _ = parse.parse(FIXTURES / "kb-sample.md", "md")
    assert blocks == [
        {
            "text": "Intro paragraph about corpora.",
            "locator": {"heading_path": ["Corpus methods"], "line": 3},
        },
        {
            "text": "logDice measures association.\nSecond line of the same paragraph.",
            "locator": {"heading_path": ["Corpus methods", "Collocation"], "line": 7},
        },
        {
            "text": "搭配分析衡量节点词与搭配词之间的关联强度。",
            "locator": {"heading_path": ["Corpus methods", "搭配"], "line": 12},
        },
    ]
    plain = parse.markdown("first\n\n\nsecond line\n```\n# not a heading\n\ncode\n```")
    assert [b["locator"] for b in plain] == [{"line": 1}, {"line": 4}]
    assert "# not a heading" in plain[1]["text"]


def test_html_main_text_keeps_headings():
    page = (
        "<html><head><title>Corpus page</title></head><body><nav>menu</nav><article>"
        "<h1>Corpus linguistics</h1><p>Corpus linguistics studies language through large collections"
        " of authentic texts.</p><h2>搭配</h2><p>搭配分析衡量节点词与搭配词之间的关联强度，常用的度量包括互信息。</p>"
        "</article><footer>copyright</footer></body></html>"
    )
    blocks, meta = parse.html(page, "https://example.org/a")
    assert blocks[-1]["locator"]["heading_path"][-1] == "搭配"
    assert blocks[-1]["text"].startswith("搭配分析")
    assert not any("menu" in b["text"] for b in blocks)
    assert meta["title"] == "Corpus linguistics"  # trafilatura prefers the h1


def test_url_checks():
    with pytest.raises(parse.ParseError):
        parse.check_url("ftp://example.org")
    with pytest.raises(parse.ParseError):
        parse.fetch("http://127.0.0.1:1/")  # private address refused before connecting
    assert parse.kind_of("A.PDF") == "pdf" and parse.kind_of("x.doc") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost:8000/x",
        "http://10.1.2.3/",
        "http://172.20.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.1.1/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_request_time_url_check_rejects_internal(url):
    with pytest.raises(parse.ParseError):
        parse.check_public_url(url)


def test_request_time_url_check_allows_public_and_unresolved():
    assert parse.check_public_url(" https://8.8.8.8/x ") == "https://8.8.8.8/x"
    assert parse.check_public_url("http://198.18.0.7/") == "http://198.18.0.7/"
    # a name that does not resolve here is left to the worker's check at fetch time
    assert parse.check_public_url("https://no-such-host.invalid/a")


def test_normalize_url():
    n = parse.normalize_url
    assert n("HTTPS://Example.ORG:443/a/b/#frag") == "https://example.org/a/b"
    assert n("https://example.org/a/b?x=1") == "https://example.org/a/b?x=1"
    assert n("http://example.org:8080/") == "http://example.org:8080"
    assert n("https://example.org/a") != n("https://example.org/b")


# ---- chunker ----


def test_chunks_size_overlap_and_sections():
    para = " ".join(f"Sentence number {i} talks about corpora." for i in range(40))
    blocks = [
        {"text": para, "locator": {"heading_path": ["A"], "line": 1}},
        {"text": "Short tail.", "locator": {"heading_path": ["A"], "line": 3}},
        {"text": "其他章节。" * 150, "locator": {"heading_path": ["B"], "line": 5}},
    ]
    out = chunk.chunk(blocks, size=500, overlap=80)
    a = [c for c in out if c["locator"]["heading_path"] == ["A"]]
    b = [c for c in out if c["locator"]["heading_path"] == ["B"]]
    assert all(len(c["text"]) <= 500 for c in out)
    assert not any("其他" in c["text"] for c in a) and not any(
        "Sentence" in c["text"] for c in b
    )
    assert a[-1]["text"].endswith("Short tail.")
    for x, y in pairwise(a):  # consecutive chunks overlap and cut at sentence ends
        assert x["text"].endswith(".")
        assert y["text"].split()[0] in x["text"][-90:]
    assert {c["locator"]["line"] for c in a} == {1}
    joined = "".join(c["text"] for c in b)
    assert joined.count("其他章节。") >= 150


def test_chunk_locator_is_start_block():
    blocks = [
        {"text": "x" * 300, "locator": {"line": 1}},
        {"text": "y" * 300, "locator": {"line": 9}},
    ]
    out = chunk.chunk(blocks, size=400, overlap=50)
    assert out[0]["locator"] == {"line": 1}
    assert out[-1]["locator"] == {"line": 9}


# ---- keyword text ----


def test_tsv_text_and_query_words():
    tsv = text.tsv_text("语料库语言学研究BERT模型 and logDice.").split()
    assert {"语料库", "语料", "语言学", "BERT", "模型", "logDice."} <= set(tsv)
    assert text.query_words("什么是语料库的搭配分析？ What is logDice?") == [
        "语料库",
        "搭配",
        "分析",
        "logdice",
    ]
    assert text.tsquery(["语料库", "can't"]) == "'语料库' | 'can''t'"
    assert text.tsquery([]) is None


def test_highlight_escapes_and_marks():
    out = text.highlight("<b>搭配</b> 分析的强度", ["搭配", "强度"])
    assert out == "&lt;b&gt;<mark>搭配</mark>&lt;/b&gt; 分析的<mark>强度</mark>"
    assert text.highlight("nothing here", ["corpus"]) is None


# ---- term candidates ----


def _sentences(name, language):
    docs = conllu.parse(FIXTURES / name, language, {})
    return [
        (d.language, [(t.form, t.pos, t.lemma) for t in s.tokens])
        for d in docs
        for s in d.sentences
    ]


def _reference(sents, first, second):
    """Independent count of ADJ/NOUN + NOUN pairs as lower-cased form + lemma, and the logDice inputs."""
    pairs, fx, fy = Counter(), Counter(), Counter()
    for _, toks in sents:
        for f, _, lemma in toks:
            fx[f.lower()] += 1
            fy[(lemma if lemma not in (None, "_") else f).lower()] += 1
        for (f1, p1, _), (f2, p2, l2) in pairwise(toks):
            if (p1, p2) in (("ADJ", "NOUN"), ("NOUN", "NOUN")):
                pairs[(f1.lower(), (l2 or f2).lower())] += 1
    n = pairs[(first, second)]
    return n, 14 + math.log2(2 * n / (fx[first] + fy[second]))


def test_terms_english_patterns_reference():
    sents = _sentences("ud-en-ewt-sample.conllu", "en")
    cands = terms.from_sentences(sents, top=10, min_freq=2)
    assert [c.term for c in cands[:2]] == ["iranian government", "islamic fascist"]
    assert all(c.language == "en" and c.pattern in ("a+n", "n+n") for c in cands)
    assert [c.freq for c in cands] == sorted((c.freq for c in cands), reverse=True)
    by_term = {c.term: c for c in cands}
    for term in ("iranian government", "nuclear weapon", "air space"):
        freq, logdice = _reference(sents, *term.split())
        assert by_term[term].freq == freq
        assert by_term[term].logdice == pytest.approx(logdice)
    assert by_term["air space"].pattern == "n+n"


def test_terms_chinese_patterns():
    cands = terms.from_sentences(_sentences("zh-sample.conllu", "zh"), min_freq=1)
    found = {c.term: c.pattern for c in cands}
    assert found["社会语言学"] == "n+n"
    assert found["研究语言"] == "v+n"
    assert all(c.language == "zh" for c in cands)
    jieba = [
        ("zh", [("统计", "vn", "统计"), ("方法", "n", "方法"), ("张三", "nr", "张三")])
    ]
    assert [c.term for c in terms.from_sentences(jieba, min_freq=1)] == ["统计方法"]
    assert terms.pos_class("nr") is None and terms.pos_class("PROPN") is None


def test_terms_chinese_light_verbs_excluded():
    sents = [
        (
            "zh",
            [
                ("是", "v", "是"),
                ("语言", "n", "语言"),
                ("进行", "v", "进行"),
                ("研究", "vn", "研究"),
                ("做", "v", "做"),
                ("实验", "n", "实验"),
                ("学", "v", "学"),
                ("汉语", "nz", "汉语"),
                ("分析", "v", "分析"),
                ("语料", "n", "语料"),
            ],
        )
    ]
    found = {c.term: c.pattern for c in terms.from_sentences(sents, min_freq=1)}
    assert found == {"分析语料": "v+n"}
    assert "进行研究" not in terms.units("zh", sents[0][1])


def test_translations_by_cooccurrence():
    zh = lambda *w: ("zh", [(x, "n", x) for x in w])
    en = lambda *w: ("en", [(x, "NOUN", x) for x in w])
    pairs = [
        (zh("机器", "翻译"), en("machine", "translation")),
        (zh("机器", "翻译", "质量"), en("machine", "translation", "quality")),
        (zh("人工", "翻译"), en("human", "translation")),
        (zh("翻译", "质量"), en("translation", "quality")),
    ]
    aligned = [((a[0], a[1], i), (b[0], b[1], -i)) for i, (a, b) in enumerate(pairs)]
    cands = terms.from_sentences(
        [zh_ for zh_, _ in pairs], min_freq=1, languages=["zh"]
    )
    terms.translate(cands, aligned)
    got = {
        c.term: (c.translations[0]["text"] if c.translations else None, c.example)
        for c in cands
    }
    assert got["机器翻译"] == ("machine translation", 0)
    assert got["翻译质量"][0] == "translation quality"


@pytest.fixture(scope="module")
def ud_index(tmp_path_factory):
    d = tmp_path_factory.mktemp("kbterms")
    docs = conllu.parse(FIXTURES / "ud-en-ewt-sample.conllu", "en", {})
    cwb.build(d, "ud_terms", docs, [f"d{i}" for i in range(len(docs))])
    return d


@pytest.mark.cwb
def test_terms_from_cwb_scope_match_pure(ud_index):
    scope = stats.Scope(ud_index, "ud_terms")
    got = terms.rank(*terms.scan_scope(scope), top=30, min_freq=2)
    want = terms.from_sentences(
        _sentences("ud-en-ewt-sample.conllu", "en"), top=30, min_freq=2
    )
    assert [(c.term, c.freq, round(c.logdice, 9)) for c in got] == [
        (c.term, c.freq, round(c.logdice, 9)) for c in want
    ]


# ---- embeddings (downloads the model into MODELS_DIR) ----


@pytest.mark.nlp
def test_local_embeddings():
    from engine.kb import embed

    vecs = embed.embed(["语料库", "corpus", "香蕉很好吃"])
    assert all(len(v) == embed.DIM for v in vecs)
    assert all(abs(sum(x * x for x in v) - 1) < 1e-4 for v in vecs)
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(vecs[0], vecs[1]) > dot(vecs[0], vecs[2])
    assert embed.model_name() == embed.DEFAULT_MODEL
