import pytest

from engine.query import Atom, Gap, QueryError, attrs, compile, compile_filter, parse


def test_parse_structure():
    ast = parse('语言|语法 $2-5 文化/n +研究 -"经济"')
    assert ast.anchor.text == "语言|语法 $2-5 文化/n"
    alts, gap, last = ast.anchor.items
    assert [a.text for a in alts] == ["语言", "语法"] and all(a.cjk for a in alts)
    assert gap == Gap(2, 5)
    assert last == [Atom("string", "文化", ("NOUN", "PROPN"))] and not last[0].cjk
    assert [(c.op, c.query.text) for c in ast.conditions] == [
        ("+", "研究"),
        ("-", '"经济"'),
    ]
    assert ast.conditions[1].query.items == [[Atom("exact", "经济")]]
    assert [t.kind for t in ast.tokens] == [
        "word",
        "or",
        "word",
        "gap",
        "word",
        "cond",
        "word",
        "cond",
        "exact",
    ]


def test_parse_atoms():
    assert parse("a $3 b").anchor.items[1] == Gap(0, 3)
    assert parse("/v").anchor.items == [[Atom("any", "", ("VERB",))]]
    assert parse("* of").anchor.items[0] == [Atom("any")]
    assert parse("/PROPN").anchor.items[0][0].pos == ("PROPN",)
    assert parse("e-mail").anchor.items == [
        [Atom("string", "e-mail")]
    ]  # '-' inside a word is literal
    assert parse('"(" x').anchor.items[0] == [Atom("exact", "(")]


@pytest.mark.parametrize(
    "q, pos, msg",
    [
        ("", 0, "查询为空"),
        ("+语言", 0, "缺少主查询"),
        ("{dep=nsubj", 0, "缺少 }"),
        ("{deprel=nsubj}", 1, "属性写作"),
        ("{dep=nsubj,dep=obj}", 11, "重复"),
        ("{pos=}", 1, "取值为空"),
        ("a{pos=n}|b", 9, "|"),
        ("a|b{pos=n}", 2, "|"),
        ("语言 +{dep=nsubj}", 4, "主查询"),
        ("[偏误:时态] 语言", 0, "暂不支持"),
        ("(语言 | 文化) 研究", 0, "括号"),
        ("$3 语言", 0, "间隔"),
        ("语言 $3", 3, "间隔"),
        ("语言 |", 3, "|"),
        ("语言/zz", 3, "未知词性"),
        ('"语言', 0, "引号"),
        ("语言 +", 3, "缺少条件"),
        ("一二三四五六七八九", 0, "最长"),
    ],
)
def test_parse_errors(q, pos, msg):
    with pytest.raises(QueryError) as e:
        parse(q)
    assert e.value.position == pos and msg in e.value.message


def test_compile_tokens():
    assert compile(parse("the")) == '[word="the" %c]'
    assert compile(parse('"The"/det')) == '[word="The" & pos="DET"]'
    assert compile(parse("th?n* $1-2 /v")) == '[word="th.n.*" %c] []{1,2} [pos="VERB"]'
    assert compile(parse("a|b *")) == '([word="a" %c] | [word="b" %c]) []'
    assert compile(parse('"a.b"')) == r'[word="a\.b"]'
    assert compile(parse("语言/n")) == '[word="语言" & pos="NOUN|PROPN"]'


def test_compile_cjk_cross_boundary():
    lines = compile(parse("语言")).split("\n")
    assert lines[0] == '([word=".*语言.*"] | [word=".*语"] [word="言.*"])'
    assert lines[1] == "#span 语言"
    cqp = compile(parse("语?言"))
    alts = cqp.split("\n")[0].strip("()").split(" | ")
    assert len(alts) == 4 and '[word=".*语"] [word="."] [word="言.*"]' in alts


def test_compile_conditions_and_edges():
    lines = compile(parse("语言 $2 the +文化 -/v")).split("\n")
    assert lines[1] == '+([word=".*文化.*"] | [word=".*文"] [word="化.*"])'
    assert lines[2] == '-[pos="VERB"]'
    assert lines[3] == "#lead 语言" and len(lines) == 4


def test_compile_filter():
    f = compile_filter(
        {"year": {"gte": 1990, "lte": 2000}, "genre": ["news", "a.b"], "年份": 2005},
        {"year": "number", "genre": "string", "年份": "number"},
    )
    assert f == (
        '(match.doc_meta_year != "" & int(match.doc_meta_year) >= 1990 & int(match.doc_meta_year) <= 2000)'
        ' & (match.doc_meta_genre = "news" | match.doc_meta_genre = "a\\.b")'
        ' & (match.doc_meta__e5b9b4e4bbbd = "000000002005")'
    )
    assert compile_filter({}, {}) == ""
    with pytest.raises(ValueError):
        compile_filter({"x": 1}, {})
    with pytest.raises(ValueError):
        compile_filter({"genre": {"gte": 1}}, {"genre": "string"})


def test_pos_tagsets():
    from engine.query import JIEBA_ALIASES, infer_tagset, resolve_pos

    assert resolve_pos("n") == ("NOUN", "PROPN")
    n = resolve_pos("n", "jieba")
    assert set(n) == {"n", "ng", "nr", "nrfg", "nrt", "ns", "nt", "nz"}
    assert set(resolve_pos("v", "jieba")) == {"v", "vd", "vg", "vi", "vn", "vq"}
    assert set(resolve_pos("a", "jieba")) == {"a", "ad", "ag", "an"}
    assert set(resolve_pos("u", "jieba")) >= {"u", "uj", "ul", "uz"}
    assert "eng" not in JIEBA_ALIASES["e"]
    for tag in ("p", "c", "w", "x", "q", "m", "r", "d"):
        assert resolve_pos(tag, "jieba")[0] == tag
    assert resolve_pos("nr", "jieba") == ("nr",)
    assert resolve_pos("VERB", "jieba") == resolve_pos("v", "jieba")
    assert "nr" not in resolve_pos("NOUN", "jieba")
    assert resolve_pos("PROPN", "jieba") == ("nr", "nrfg", "nrt", "ns", "nt", "nz")
    assert resolve_pos("n", "mixed") == ("NOUN", "PROPN", *n)
    assert resolve_pos("x") == ("X",)
    with pytest.raises(QueryError):
        resolve_pos("nr")  # jieba tag on a UPOS corpus
    with pytest.raises(QueryError):
        resolve_pos("DET", "jieba")
    with pytest.raises(QueryError):
        resolve_pos("zz", "mixed")
    assert infer_tagset(["NOUN", None, "PUNCT"]) == "upos"
    assert infer_tagset(["n", "uj", "eng", "w"]) == "jieba"
    assert infer_tagset(["NOUN", "n"]) == "mixed" and infer_tagset([]) == "mixed"


def test_compile_jieba_pos():
    assert (
        compile(parse("语言/n", "jieba"))
        == '[word="语言" & pos="n|ng|nr|nrfg|nrt|ns|nt|nz"]'
    )
    assert compile(parse("/nr 的/uj", "jieba")) == '[pos="nr"] [word="的" & pos="uj"]'
    assert compile(parse("翻译/v", "jieba")) == '[word="翻译" & pos="v|vd|vg|vi|vn|vq"]'
    with pytest.raises(QueryError) as e:
        parse("语言/zz", "jieba")
    assert e.value.position == 3 and "jieba" in e.value.message


def test_attributes_parse_and_compile():
    ast = parse("{dep=nsubj}")
    assert ast.anchor.items == [[Atom("any", attrs={"dep": ("nsubj",)})]]
    assert [(t.kind, t.text) for t in ast.tokens] == [("attr", "{dep=nsubj}")]
    assert compile(ast).split("\n") == ["[]", "#attr 0 dep=nsubj", "#target 0 @[]"]

    ast = parse(
        '学生{dep=nsubj} "run"{pos=v} /d{ dep = advmod|amod , lemma=Go }', "jieba"
    )
    a, b, c = (item[0] for item in ast.anchor.items)
    assert (a.kind, a.text, a.attrs, a.cjk) == (
        "string",
        "学生",
        {"dep": ("nsubj",)},
        False,
    )
    assert b.attrs == {"pos": ("v", "vd", "vg", "vi", "vn", "vq")}
    assert c.kind == "any" and c.pos == ("d", "df", "dg")
    assert c.attrs == {"dep": ("advmod", "amod"), "lemma": ("Go",)}
    assert [t.kind for t in ast.tokens] == [
        "word",
        "attr",
        "exact",
        "attr",
        "pos",
        "attr",
    ]
    lines = compile(ast).split("\n")
    # attributes make a CJK string one whole token, as /pos does
    assert lines[0] == '[word="学生"] [word="run"] [pos="d|df|dg"]'
    assert attrs(compile(ast)) == {
        0: {"dep": ("nsubj",)},
        1: {"pos": ("v", "vd", "vg", "vi", "vn", "vq")},
        2: {"dep": ("advmod", "amod"), "lemma": ("Go",)},
    }
    targets = [ln for ln in lines if ln.startswith("#target")]
    assert targets == [
        '#target 0 @[word="学生"] [word="run"] [pos="d|df|dg"]',
        '#target 1 [word="学生"] @[word="run"] [pos="d|df|dg"]',
        '#target 2 [word="学生"] [word="run"] @[pos="d|df|dg"]',
    ]
    # pos values resolve like /pos on the corpus tagset; unknown labels stay literal (project label sets)
    assert parse("{pos=n}").anchor.items[0][0].attrs == {"pos": ("NOUN", "PROPN")}
    assert parse("{pos=VERB|myTag}").anchor.items[0][0].attrs == {
        "pos": ("VERB", "myTag")
    }
    gap = compile(parse("the $2 {pos=DET}")).split("\n")
    assert gap[-1] == '#target 1 [word="the" %c] []{0,2} @[]'
