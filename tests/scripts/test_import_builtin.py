"""scripts/import_builtin.py: Tatoeba partition keeps every link inside one part; wiki cleaning."""

import bz2
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "import_builtin", ROOT / "scripts" / "import_builtin.py"
)
ib = importlib.util.module_from_spec(spec)
sys.modules["import_builtin"] = ib
spec.loader.exec_module(ib)


def _write(src, name, lines):
    path = src / name
    path.write_bytes(bz2.compress("".join(lines).encode()))
    path.with_name(name + ".json").write_text(
        json.dumps({"last_modified": "2026-10-24"}), encoding="utf-8"
    )


def test_tatoeba_parts_keep_links_together(tmp_path):
    cmn = [f"{i}\tcmn\t句子{i}\tu\t\\N\t\\N\n" for i in (1, 2, 3, 10)]
    eng = [f"{i}\teng\tSentence {i}\tu\t\\N\t\\N\n" for i in (4, 5, 6, 7, 8, 9)]
    # 1–9 linked across the id range; 2–5 and 5–3 form one component {2, 3, 5}; 10 unlinked
    links = ["1\t9\n", "9\t1\n", "2\t5\n", "5\t3\n", "1\t99\n"]
    _write(tmp_path, "cmn_sentences_detailed.tsv.bz2", cmn)
    _write(tmp_path, "eng_sentences_detailed.tsv.bz2", eng)
    _write(tmp_path, "cmn-eng_links.tsv.bz2", links)
    out, info = ib.tatoeba_prepare(tmp_path, 3)
    assert (
        info["sentences"] == 10
        and info["links"] == 3
        and info["version"] == "2026-10-24"
    )
    where = {}
    for d in sorted(out.glob("part-*")):
        for name in ("cmn_sentences.tsv", "eng_sentences.tsv"):
            for line in (d / name).read_text(encoding="utf-8").splitlines():
                sid, lang, _ = line.split("\t")
                assert lang == name[:3]
                where[int(sid)] = d.name
        for line in (d / "cmn-eng_links.tsv").read_text(encoding="utf-8").splitlines():
            a, b = map(int, line.split("\t"))
            assert where[a] == where[b] == d.name
    assert sorted(where) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert where[1] == where[9] and where[2] == where[3] == where[5]
    assert sum(p["cmn"] + p["eng"] for p in info["parts"]) == 10


def test_clean_wikitext():
    pytest.importorskip("mwparserfromhell")
    text = (
        "{{Infobox person|name=X}}\n'''Alan Turing''' (born 1912) was an English "
        "[[mathematician]] and [[Computer science|computer scientist]].<ref>Cite</ref> "
        "[[File:Turing.jpg|thumb|A photo]]\n"
        "{| class=wikitable\n|-\n| cell || cell\n|}\n"
        "== Early life ==\nHe was born in [[Maida Vale]], London, in a nursing home.\n"
        "== References ==\nThis reference section text is dropped entirely here.\n"
        "[[Category:1912 births]]"
    )
    assert ib.clean_wikitext(text, "en") == (
        "Alan Turing (born 1912) was an English mathematician and computer scientist.\n"
        "He was born in Maida Vale, London, in a nursing home."
    )
    zh = "'''图灵'''是-{zh-hans:计算机;zh-hant:電腦}-科学家。<!-- 注释 -->{{Citation needed}}\n== 参考文献 ==\n来源"
    assert ib.clean_wikitext(zh, "zh") == "图灵是计算机科学家。"
