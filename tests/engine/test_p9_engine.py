"""P9 engine: language check at import (contracts/p9.md §九) and cancellable CWB tool runs (§七)."""

import sys
import threading
import time
from pathlib import Path

import pytest

from engine import cwb, nlp, stats
from engine.parsers import parse

IMP = Path(__file__).parents[1] / "fixtures" / "import"


def _text(name):
    return (IMP / name).read_text(encoding="utf-8")


def test_french_text_is_not_english():
    assert nlp.language_problem(_text("fr.txt")) == nlp.NOT_EN
    # the given language skips the function-word test (the import checks the code itself)
    assert nlp.language_problem(_text("fr.txt"), check_english=False) is None


def test_japanese_text_is_neither_chinese_nor_english():
    assert nlp.language_problem(_text("ja.txt")) == nlp.NOT_ZH_EN
    assert nlp.language_problem(_text("ja.txt"), check_english=False) == nlp.NOT_ZH_EN
    assert nlp.language_problem("Привет, как дела? Это русский текст.") == nlp.NOT_ZH_EN


def test_english_and_chinese_pass():
    assert nlp.language_problem(_text("en.txt")) is None
    zh = "社会语言学研究语言与社会的关系，语料库方法为翻译研究提供了新的证据。" * 20
    assert nlp.language_problem(zh) is None
    # Chinese with Latin terms, digits and full-width letters
    assert (
        nlp.language_problem("本文用 logDice（Ｒａｙｓｏｎ 2000）衡量搭配强度。")
        is None
    )
    # short Latin text: too few words for the function-word test
    assert nlp.language_problem("Bonjour tout le monde, merci beaucoup.") is None


def test_tmx_parser_keeps_every_language():
    """The parser reads all languages; the import (services.worker.tasks) rejects fr."""
    docs, _ = parse(IMP / "en-fr.tmx", language=None, metadata={})
    assert sorted(d.language for d in docs) == ["en", "fr", "zh"]


def _sleeper():
    return [sys.executable, "-c", "import time; time.sleep(30)"]


def test_run_stops_when_cancelled():
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(cwb.Cancelled):
        cwb._run(_sleeper(), cancel=cancel)
    assert time.monotonic() - started < 3


def test_run_with_cancel_passes_input_and_errors():
    echo = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write(sys.stdin.read()[::-1])",
    ]
    assert cwb._run(echo, input="abc", cancel=threading.Event()) == "cba"
    fail = [sys.executable, "-c", "import sys; sys.exit(3)"]
    with pytest.raises(cwb.CQPError):
        cwb._run(fail, cancel=threading.Event())


def test_checked_loops_raise_inside_cancellable(monkeypatch):
    monkeypatch.setattr(stats, "CHECK_EVERY", 3)
    cancel = threading.Event()
    seen = []
    with stats.cancellable(cancel):
        assert stats.cancel_event() is cancel
        with pytest.raises(cwb.Cancelled):
            for i in stats._checked(range(100)):
                seen.append(i)
                if i == 4:
                    cancel.set()
    assert seen == [0, 1, 2, 3, 4, 5]  # stopped at the next check (item 6)
    assert stats.cancel_event() is None
    assert list(stats._checked(range(5))) == [0, 1, 2, 3, 4]


@pytest.mark.cwb
def test_stats_stop_when_cancelled(tmp_path):
    docs, _ = parse(IMP.parent / "ud-en-ewt-sample.conllu", language="en", metadata={})
    cwb.build(tmp_path, "p9", docs, [f"d{i}" for i in range(len(docs))])
    scope = stats.Scope(tmp_path, "p9")
    cancel = threading.Event()
    with stats.cancellable(cancel):
        assert stats.frequency(scope, top=3).rows  # not set: runs as usual
        cancel.set()
        with pytest.raises(cwb.Cancelled):
            stats.frequency(scope, top=3)
        with pytest.raises(cwb.Cancelled):
            stats.collocations(scope, '"the"')


REFERENCES = "\n".join(
    f"Smith, J. ({1990 + i}). Corpus Linguistics and Translation Studies, Vol. {i}. "
    "Oxford University Press. Brown, K. Lexical Priming. Routledge."
    for i in range(30)
)
GLOSSARY = "\n".join(
    f"concordance{i}\tcollocation\tlemma\ttoken frequency\tkeyness\tdispersion\tsubcorpus"
    for i in range(60)
)
ZH_TERMS = (
    "本文使用 BERT、RoBERTa 与 GPT-4 模型，在 CoNLL-2003、OntoNotes 5.0、SQuAD v2.0 等 dataset 上"
    "进行 fine-tuning 实验，并对比 precision、recall 与 F1 score。"
) * 40
IPA = "ʃ ʒ ɪ ʊ ə ɛ ɔ æ ŋ θ ð ɹ ɾ ʔ ˈ ː " * 300 + "the words of " * 10


@pytest.mark.parametrize("text", [REFERENCES, GLOSSARY, ZH_TERMS, IPA])
def test_english_lists_terms_and_ipa_pass(text):
    assert nlp.language_problem(text) is None
    assert nlp.language_problem(text, check_english=False) is None


def test_not_english_message_suggests_language():
    assert nlp.NOT_EN.endswith("可指定 zh 或 en 后重试")
