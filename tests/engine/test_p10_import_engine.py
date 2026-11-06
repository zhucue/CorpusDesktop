"""P10 import extensions and languages (contracts/p10.md §七, §八): PDF / XLSX / JSONL parsing, content_hash,
language detection for zh en ja fr de es ru, Stanza pipeline cache, and real samples through NLP and CWB."""

import importlib.util
import re
from pathlib import Path
from typing import ClassVar

import pytest

from engine import cwb, nlp, parsers, query
from engine.model import Context, Document
from engine.parsers import table

IMP = Path(__file__).parents[1] / "fixtures" / "import"
MIGRATION = (
    Path(__file__).parents[2]
    / "services/api/migrations/versions/0011_semantic_search.py"
)


def _text(name):
    return (IMP / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- content hash


def test_content_hash_normalizes_whitespace_and_width():
    h = parsers.content_hash
    assert h("  语料 库\n\t研究  ") == h("语料 库 研究")
    assert h("ＡＢＣ　１２３") == h(
        "ABC 123"
    )  # NFKC: full-width letters, digits, ideographic space
    assert h("a b") != h("ab")
    assert re.fullmatch(r"[0-9a-f]{64}", h("x"))


def test_content_hash_matches_migration_backfill():
    spec = importlib.util.spec_from_file_location("m0011", MIGRATION)
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except ImportError as e:  # alembic / pgvector missing outside the containers
        pytest.skip(f"migration not importable: {e}")
    for text in ("  语料 库\n研究 ", "ＡＢＣ　x", _text("lang-fr.txt")):
        assert m.content_hash(text) == parsers.content_hash(text)


# ---------------------------------------------------------------- PDF


def test_pdf_with_text_layer():
    [doc], links = parsers.parse(
        IMP / "text-layer.pdf", language="en", metadata={"genre": "report"}
    )
    assert links == []
    assert doc.title == "Reading Habits of Graduate Students"
    assert doc.metadata == {"genre": "report", "pages": 2, "author": "P10 test fixture"}
    assert "parallel editions" in doc.text and doc.text.count("\n") >= 2
    assert doc.source == "text-layer.pdf"


def test_pdf_without_text_layer_fails():
    with pytest.raises(parsers.ParseError) as e:
        parsers.parse(IMP / "scanned.pdf", language="en", metadata={})
    assert str(e.value) == "scanned.pdf：PDF 没有文字层（扫描件），暂不支持 OCR"


# ---------------------------------------------------------------- XLSX / JSONL


def test_xlsx_first_sheet_with_detected_columns():
    docs, _ = parsers.parse(IMP / "abstracts.xlsx", language="", metadata={})
    assert [d.title for d in docs] == [
        "语料库与翻译教学",
        "Corpora in the writing classroom",
        "学习者口语中的停顿",
        "语料库与翻译教学",
    ]
    assert [d.language for d in docs] == ["zh", "en", "zh", "zh"]
    assert docs[0].metadata == {"年份": 2021, "类型": "期刊"}  # numbers stay numbers
    assert [d.source for d in docs] == [f"abstracts.xlsx #{i}" for i in range(1, 5)]
    assert parsers.content_hash(docs[0].text) == parsers.content_hash(docs[3].text)


def test_xlsx_chosen_sheet_and_mapping():
    mapping = {
        "text": ["摘要"],
        "title": "标题",
        "language": None,
        "metadata": ["年份"],
        "sheet": "2025",
    }
    docs, _ = parsers.parse(
        IMP / "abstracts.xlsx", language="en", metadata={}, mapping=mapping
    )
    assert [d.title for d in docs] == ["Hedging in student theses", "新闻标题的修辞"]
    assert all(
        d.language == "en" for d in docs
    )  # no language column: the upload language
    assert docs[1].metadata == {"年份": 2025}
    with pytest.raises(parsers.ParseError, match="没有工作表：2026"):
        parsers.parse(
            IMP / "abstracts.xlsx",
            language="en",
            metadata={},
            mapping={**mapping, "sheet": "2026"},
        )


def test_xlsx_preview_lists_sheets():
    data = (IMP / "abstracts.xlsx").read_bytes()
    pv = table.preview(data, "abstracts.xlsx", partial=False)
    assert pv["sheets"] == ["摘要", "2025"]
    assert pv["columns"] == ["标题", "语言", "年份", "类型", "摘要"]
    assert pv["defaults"] == {
        "text": ["摘要"],
        "title": "标题",
        "language": "语言",
        "metadata": None,
        "sheet": "摘要",
    }
    assert pv["rows"][0][2] == "2021"
    assert (
        table.preview(data, "abstracts.xlsx", sheet="2025")["defaults"]["sheet"]
        == "2025"
    )
    with pytest.raises(parsers.ParseError, match="不是有效的 XLSX"):
        table.preview(b"not a zip", "x.xlsx", partial=False)


def test_jsonl_fields_with_nested_metadata():
    docs, _ = parsers.parse(IMP / "abstracts.jsonl", language="", metadata={"src": "j"})
    assert len(docs) == 6
    d = docs[1]
    assert (d.title, d.language) == ("Corpora in the writing classroom", "en")
    assert d.text.startswith("This article reports")
    assert d.metadata == {
        "src": "j",
        "id": 2,
        "meta.year": 2022,
        "meta.genre": "journal",
    }
    assert d.source == "abstracts.jsonl #2"
    mapped, _ = parsers.parse(
        IMP / "abstracts.jsonl",
        language="zh",
        metadata={},
        mapping={
            "text": ["body"],
            "title": None,
            "language": None,
            "metadata": ["meta.year"],
        },
    )
    assert mapped[0].title == "abstracts #1" and mapped[0].language == "zh"
    assert mapped[0].metadata == {"meta.year": 2021}


def test_jsonl_errors_and_partial_preview(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"text": "a"}\n[1, 2]\n', encoding="utf-8")
    with pytest.raises(parsers.ParseError, match="第 2 行不是 JSON 对象"):
        parsers.parse(bad, language="en", metadata={})
    bad.write_text('{"text": "a"}\n{"text": \n', encoding="utf-8")
    with pytest.raises(parsers.ParseError, match="第 2 行不是有效的 JSON"):
        parsers.parse(bad, language="en", metadata={})
    data = (IMP / "abstracts.jsonl").read_bytes()
    pv = table.preview(data[:400], "abstracts.jsonl", partial=True)  # cut mid-line
    assert pv["columns"] == ["id", "title", "lang", "body", "meta.year", "meta.genre"]
    assert pv["defaults"]["text"] == ["body"] and pv["defaults"]["language"] == "lang"


# ---------------------------------------------------------------- language detection

P9_PROBE = {  # tmp/p9_lang_probe.py (P9 review): all must import without a problem
    "zh_trad": ("語料庫語言學是研究語言使用的重要方法，" * 50, "zh"),
    "zh_latin_terms": (
        "本文使用 BERT、RoBERTa 与 GPT-4 模型，在 CoNLL-2003、OntoNotes 5.0、SQuAD v2.0 等 dataset 上进行"
        " fine-tuning 实验，并对比 precision recall F1 score。" * 40,
        "zh",
    ),
    "en_glossary": (
        "\n".join(
            f"corpus{i} concordance collocation lemma token frequency keyness dispersion"
            for i in range(60)
        ),
        "en",
    ),
    "en_code": (
        "def foo(x):\n    return bar(x) + baz(y)\nimport numpy as np\nclass Model(nn.Module):\n"
        * 80,
        "en",
    ),
    "en_refs": (
        "Smith, J. (2010). Corpus Linguistics. Oxford University Press. Brown, K. (2012). Lexical "
        "Priming. Routledge. " * 30,
        "en",
    ),
    "en_normal": (
        "The study of language in use is one of the central concerns of linguistics, and it is in "
        "this area that corpora have been most useful. " * 20,
        "en",
    ),
    "en_title": ("Introduction to Corpus Linguistics", "en"),
    "ipa": ("ʃ ʒ ɪ ʊ ə ɛ ɔ æ ŋ θ ð ɹ ɾ ʔ " * 300 + "the words of " * 10, "en"),
    "zh_with_kana_quotes": (
        "这部作品的日文原名是「ノルウェイの森」，" + "中文译本由林少华翻译，" * 100,
        "zh",
    ),
}


@pytest.mark.parametrize("name", P9_PROBE)
def test_p9_probe_samples_keep_their_language(name):
    text, lang = P9_PROBE[name]
    assert nlp.detect_language(text) == lang
    assert nlp.language_problem(text) is None
    assert nlp.language_problem(text, lang) is None


@pytest.mark.parametrize(
    ("name", "lang"),
    [
        ("lang-fr.txt", "fr"),
        ("lang-de.txt", "de"),
        ("lang-es.txt", "es"),
        ("lang-ru.txt", "ru"),
        ("lang-ja.txt", "ja"),
        ("fr.txt", "fr"),
        ("ja.txt", "ja"),
        ("en.txt", "en"),
    ],
)
def test_real_samples_detected(name, lang):
    text = _text(name)
    assert nlp.detect_language(text) == lang
    assert nlp.language_problem(text) is None


def test_short_texts_and_other_scripts():
    assert nlp.detect_language("Bonjour tout le monde, merci beaucoup.") == "fr"
    assert nlp.detect_language("Привет, как дела? Это русский текст.") == "ru"
    assert nlp.detect_language("社会语言学研究语言。") == "zh"
    assert nlp.detect_language("Language and society, 语言") == "en"
    assert nlp.detect_language("12345 !!!") == "en"
    korean = "한국어 말뭉치는 언어 연구에 널리 쓰인다. " * 20
    assert nlp.language_problem(korean) == nlp.OTHER_SCRIPT
    assert (
        nlp.language_problem(korean, "en") == nlp.OTHER_SCRIPT
    )  # given, but not that script


def test_unrecognized_latin_text_fails():
    finnish = (
        "Tänään sää oli kaunis ja lapset leikkivät pihalla. Äiti keittää kahvia keittiössä. "
        * 20
    )
    assert nlp.language_problem(finnish) == nlp.NOT_DETECTED
    assert nlp.NOT_DETECTED.startswith("未识别语言，请指定")
    assert nlp.language_problem(finnish, "fr") is None  # a given language is trusted


def test_language_codes():
    assert [
        nlp.lang_code(x) for x in ("jpn", "fra", "deu", "spa", "rus", "ja-JP", "pt")
    ] == [
        "ja",
        "fr",
        "de",
        "es",
        "ru",
        "ja",
        "pt",
    ]
    assert set(nlp.SUPPORTED) == {"zh", "en", "ja", "fr", "de", "es", "ru"}
    assert (
        nlp.unsupported_message(["ko"])
        == "暂不支持该语言：ko（支持 zh、en、ja、fr、de、es、ru）"
    )


def test_japanese_string_is_character_mode():
    cqp = query.compile(query.parse("図書館で"))
    assert '[word=".*図書館"] [word="で.*"]' in cqp and "#span" in cqp
    assert query.parse("ｺｰﾊﾟｽ").anchor.items[0][0].cjk


# ---------------------------------------------------------------- pipeline cache


class FakePipeline:
    made: ClassVar[list] = []

    def __init__(self, lang, **kw):
        self.lang = lang
        FakePipeline.made.append(lang)


@pytest.fixture
def fake_stanza(monkeypatch):
    import stanza

    FakePipeline.made = []
    monkeypatch.setattr(stanza, "Pipeline", FakePipeline)
    monkeypatch.setattr(nlp, "_PIPELINES", nlp.collections.OrderedDict())
    monkeypatch.setattr(nlp, "has_models", lambda lang, processors: lang != "es")
    refreshed = []
    monkeypatch.setattr(nlp, "_refresh_resources", refreshed.append)
    return refreshed


def test_pipelines_least_recently_used_dropped(fake_stanza, monkeypatch):
    monkeypatch.setenv("STANZA_MAX_PIPELINES", "2")
    en, fr = nlp.pipeline("en"), nlp.pipeline("fr")
    assert nlp.pipeline("en") is en  # cached; en is now the most recent
    nlp.pipeline("de")  # drops fr
    assert list(nlp._PIPELINES) == ["en", "de"]
    assert nlp.pipeline("fr") is not fr
    assert list(nlp._PIPELINES) == ["de", "fr"]
    assert FakePipeline.made == ["en", "fr", "de", "fr"]
    monkeypatch.setenv("STANZA_MAX_PIPELINES", "1")
    nlp._zh_depparse()
    assert list(nlp._PIPELINES) == ["zh-dep"]


def test_download_is_announced_and_failure_named(fake_stanza, monkeypatch):
    notes = []
    with nlp.notifying(notes.append):
        nlp.pipeline("fr")  # on disk: no notice
        nlp.pipeline("es")
    assert notes == ["下载 es 模型"] and fake_stanza == ["es"]

    def offline(lang, **kw):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(nlp, "_PIPELINES", nlp.collections.OrderedDict())
    import stanza

    monkeypatch.setattr(stanza, "Pipeline", offline)
    with pytest.raises(nlp.ModelError, match=r"^下载 es 模型失败：network unreachable"):
        nlp.pipeline("es")
    with pytest.raises(nlp.ModelError, match=r"^加载 fr 模型失败"):
        nlp.pipeline("fr")


# ---------------------------------------------------------------- real samples through Stanza and CWB

UPOS = set(query.UPOS)
SAMPLES = {  # language: (file, query, expected match)
    "fr": ("lang-fr.txt", "bibliothèque", "bibliothèque"),
    "de": ("lang-de.txt", "Großeltern", "Großeltern"),
    "es": ("lang-es.txt", "mercado", "mercado"),
    "ru": ("lang-ru.txt", "студентов", "студентов"),
    "ja": (
        "lang-ja.txt",
        "図書館で",
        "図書館で",
    ),  # crosses a token boundary (図書館 | で)
}


def _models(lang):
    return nlp.has_models(lang, nlp.STANZA_PROCESSORS[lang])


@pytest.mark.nlp
@pytest.mark.cwb
@pytest.mark.parametrize("lang", SAMPLES)
def test_real_sample_annotated_and_searchable(lang, tmp_path):
    if not _models(lang):
        pytest.skip(f"Stanza {lang} models not downloaded")
    name, q, match = SAMPLES[lang]
    [doc], _ = parsers.parse(IMP / name, language=None, metadata={})
    doc.language = nlp.detect_language(doc.text)
    assert doc.language == lang
    nlp.annotate_many([doc])
    tokens = [t for s in doc.sentences for t in s.tokens]
    assert len(doc.sentences) >= 8 and len(tokens) >= 150
    assert {t.pos for t in tokens} <= UPOS and {"NOUN", "VERB"} <= {
        t.pos for t in tokens
    }
    assert all(t.deprel and t.head is not None for t in tokens)
    info = cwb.build(tmp_path, lang, [doc], ["d1"])
    assert info.tagset == "upos"
    r = cwb.search(
        tmp_path,
        lang,
        query.compile(query.parse(q, tagset=info.tagset)),
        restrict=None,
        sort="position",
        seed=None,
        page=1,
        page_size=50,
        context=Context(),
    )
    assert r.counts.hits == doc.text.count(match) and r.items
    for h in r.items:
        assert h.match == match == doc.text[h.start_cp : h.end_cp]
        assert doc.text[h.start_cp - len(h.left) : h.start_cp] == h.left
    nouns = cwb.search(
        tmp_path,
        lang,
        query.compile(query.parse("/NOUN", tagset=info.tagset)),
        restrict=None,
        sort="position",
        seed=None,
        page=1,
        page_size=5,
        context=Context(),
    )
    assert nouns.counts.hits and nouns.counts.hits == sum(
        t.pos == "NOUN" for t in tokens
    )


@pytest.mark.nlp
def test_three_languages_within_pipeline_limit(monkeypatch):
    langs = [x for x in ("fr", "de", "ja") if _models(x)]
    if len(langs) < 3:
        pytest.skip("Stanza fr / de / ja models not all downloaded")
    monkeypatch.setenv("STANZA_MAX_PIPELINES", "2")
    docs = [
        Document(n, "", _text(n), {}, [])
        for n in ("lang-fr.txt", "lang-de.txt", "lang-ja.txt")
    ]
    nlp.annotate_many(docs)
    assert [d.language for d in docs] == ["fr", "de", "ja"]
    assert all(d.sentences for d in docs)
    assert len(nlp._PIPELINES) <= 2 and "ja" in nlp._PIPELINES


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        (
            "it",
            (
                "La traduzione letteraria è un lavoro difficile, ma anche molto bello. Il traduttore deve "
                "capire il testo e trovare le parole giuste nella sua lingua."
            ),
        ),
        (
            "pt",
            (
                "A tradução literária é um trabalho difícil, mas também muito bonito. O tradutor precisa "
                "entender o texto e encontrar as palavras certas na sua língua."
            ),
        ),
        (
            "nl",
            (
                "Het vertalen van literatuur is een moeilijk werk, maar ook heel mooi. De vertaler moet de "
                "tekst begrijpen en de juiste woorden vinden in zijn taal."
            ),
        ),
    ],
)
def test_italian_portuguese_dutch_fail_instead_of_english(lang, text):
    for t in (text, text * 10):  # short and long
        assert nlp.language_problem(t) == nlp.unsupported_message([lang])
    assert nlp.language_problem(text, "en") is None  # a given language is trusted


def test_download_lock_and_temp_names_shared_volume(tmp_path, monkeypatch):
    monkeypatch.setenv("STANZA_RESOURCES_DIR", str(tmp_path))
    with nlp._file_lock(".download-fr.lock"):
        assert (tmp_path / ".download-fr.lock").exists()
    (tmp_path / "resources.json").write_text('{"en": {"old": 1}, "fr": {"old": 1}}')

    def fake_download(folder, resources_filepath):
        Path(resources_filepath).write_text('{"en": {"new": 1}, "fr": {"new": 2}}')
        assert re.search(r"\.resources-[0-9a-f]{32}\.json$", resources_filepath)

    from stanza.resources import common

    monkeypatch.setattr(common, "download_resources_json", fake_download)
    nlp._refresh_resources("fr")
    import json

    assert json.loads((tmp_path / "resources.json").read_text()) == {
        "en": {"old": 1},
        "fr": {"new": 2},
    }
    assert not list(tmp_path.glob(".resources-*.json"))
