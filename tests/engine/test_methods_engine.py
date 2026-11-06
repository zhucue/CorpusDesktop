"""engine.methods: method appendix text and references from collected facts."""

import pytest

from engine import methods

CORPUS = {
    "name": "Tatoeba 中英",
    "language": "zh",
    "documents": 2,
    "sentences": 1200,
    "tokens": 15342,
    "index_version": "v7",
    "meta": {
        "license": "CC BY 2.0 FR",
        "attribution": "Tatoeba 贡献者",
        "source_url": "https://tatoeba.org",
        "version": "2026-10-01",
    },
    "builtin": True,
    "subcorpora": [
        {
            "name": "新闻",
            "filter": {"genre": "news"},
            "documents": 1,
            "sentences": 600,
            "tokens": 7000,
        }
    ],
}
TOOLS = {
    "platform": "1.4.0",
    "jieba": "0.42.1",
    "stanza": "1.10.1",
    "cwb": "3.5.0",
    "zh": True,
    "en": False,
}
KEYWORDS = {
    "method": "keywords",
    "params": {
        "target": {"corpus_id": "x"},
        "reference": {"corpus_id": "y"},
        "unit": "word",
        "measure": "log_ratio",
        "direction": "negative",
        "min_freq": 3,
        "top": 200,
        "exclude_punct": True,
    },
    "scope": "学习者作文",
    "reference": "Tatoeba 中英",
    "totals": {"tokens": 1000, "reference": {"tokens": 15342}},
    "columns": [
        "word",
        "target_freq",
        "ref_freq",
        "target_pm",
        "ref_pm",
        "ll",
        "log_ratio",
        "pct_diff",
        "log_ratio_ci_low",
        "log_ratio_ci_high",
        "bonferroni",
    ],
    "index_version": "v3",
    "created_at": "2026-11-05 10:00 UTC",
}
FREQUENCY = {
    "method": "frequency",
    "params": {"unit": "lemma", "parts": "segments", "dispersion": True},
    "scope": "学习者作文",
    "totals": {"tokens": 1000, "parts": 10},
    "columns": [
        "item",
        "freq",
        "per_million",
        "range",
        "range_pct",
        "dp",
        "dp_norm",
        "juilland_d",
    ],
}
LAYER = {
    "name": "抽样：了",
    "kind": "span",
    "label_set": "体标记",
    "labels": 3,
    "mode": "single",
    "annotators": 1,
    "items": 20,
    "sample": {
        "query": '"了"',
        "scope": "Tatoeba 中英",
        "n": 20,
        "seed": 42,
        "total_hits": 512,
    },
    "sample_summary": {
        "total_hits": 512,
        "sampled": 20,
        "coded": 18,
        "rejected": 2,
        "labels": [
            {
                "label": "完成",
                "count": 12,
                "pct": 12 / 18,
                "ci_low": 0.437,
                "ci_high": 0.837,
                "estimate": 341,
            }
        ],
    },
}


def test_sections_and_metric_formulas():
    out = methods.build(
        {
            "corpora": [CORPUS],
            "tools": TOOLS,
            "stats": [KEYWORDS, FREQUENCY],
            "layers": [LAYER],
        },
        "apa",
    )
    md = out["markdown"]
    assert md.startswith("# 方法附录")
    assert (
        "## 1 语料" in md
        and "## 2 处理工具" in md
        and "## 3 统计" in md
        and "## 4 标注" in md
    )
    assert "## 3 检索" not in md  # no searches given: no section
    # corpus size, license, version, index version, subcorpus filter and size
    assert "2 篇文档，1,200 句，15,342 词（含标点）" in md
    assert (
        "许可：CC BY 2.0 FR" in md and "版本：2026-10-01" in md and "索引版本：v7" in md
    )
    assert (
        '子库「新闻」：筛选条件 `{"genre": "news"}`；1 篇文档，600 句，7,000 词' in md
    )
    # tool versions
    assert "jieba 0.42.1" in md and "Stanza 1.10.1 zh-hans" in md and "CWB）3.5.0" in md
    assert "平台：语料检索、分析与标注研究平台 1.4.0" in md
    assert "英文分词" not in md
    # parameters and only the metrics used
    assert "范围：学习者作文；参照：Tatoeba 中英" in md
    assert (
        "排序指标 log ratio" in md and "方向 参照多于目标" in md and "最低频次 3" in md
    )
    assert "规模：词数（含标点） 1,000；参照：词数（含标点） 15,342" in md
    assert "%DIFF" in md and "（Gabrielatos & Marchi 2012）" in md
    assert (
        "Bonferroni 校正" in md
        and "（Hardie 2014）" in md
        and "（Dunning 1993；Rayson & Garside 2000）" in md
    )
    assert "部分 按词数等分 10 段" in md and "部分数 10" in md
    assert (
        "DP = ½ Σ|vᵢ − sᵢ|" in md
        and "（Lijffijt & Gries 2012）" in md
        and "Juilland D" in md
    )
    assert "MI3" not in md and "logDice" not in md
    # sampling layer: method and coding with Wilson intervals
    assert "从全部 512 条命中中按随机种子 42 等概率无放回抽取 20 条" in md
    assert "已编码 18 / 抽样 20，拒绝（不计入）2" in md and "（Wilson 1927）" in md
    assert "比例的 95% Wilson 区间（Wilson 1927）" in md
    assert "| 完成 | 12 | 66.7% | 43.7% – 83.7% | 341 |" in md


def test_references_apa_and_gbt():
    data = {"corpora": [CORPUS], "tools": TOOLS, "stats": [KEYWORDS], "layers": [LAYER]}
    apa = methods.build(data, "apa")["citations"]
    assert (
        "Dunning, T. (1993). Accurate methods for the statistics of surprise and coincidence. Computational "
        "Linguistics, 19(1), 61–74."
    ) in apa
    assert any(c.startswith("Wilson, E. B. (1927).") for c in apa)
    assert any(
        c.startswith("Wilson, E. B. (1927).")
        and c.endswith("https://doi.org/10.1080/01621459.1927.10502953")
        for c in apa
    )
    assert any(
        c.startswith(
            "Hardie, A. (2014, April 28). Log Ratio – an informal introduction"
        )
        for c in apa
    )
    assert not any(c.startswith("Gries") for c in apa)  # dispersion not used
    # literature sorted by author, then the built-in corpus, then the platform
    literature = apa[:-2]
    assert literature == sorted(literature, key=str.lower)
    assert apa[-2].startswith(
        "Tatoeba 中英 (Version 2026-10-01) [Data set]. Tatoeba 贡献者. License: CC BY 2.0 FR."
    )
    assert apa[-1].startswith(
        "语料检索、分析与标注研究平台 (Version 1.4.0) [Computer software]"
    )

    gbt = methods.build(data, "gbt7714")
    cites = gbt["citations"]
    assert (
        "DUNNING T. Accurate methods for the statistics of surprise and coincidence[J]. Computational "
        "Linguistics, 1993, 19(1): 61-74."
    ) in cites
    assert (
        cites[-2]
        == "Tatoeba 贡献者. Tatoeba 中英[DS/OL]. 版本 2026-10-01. 许可 CC BY 2.0 FR. https://tatoeba.org."
    )
    assert any(
        c.startswith("RAYSON P") and c.endswith("DOI: 10.3115/1117729.1117730.")
        for c in cites
    )
    assert cites[-1].startswith("语料检索、分析与标注研究平台[CP/OL]. 版本 1.4.0.")
    assert "（Dunning 1993；Rayson 和 Garside 2000）" in gbt["markdown"]
    assert gbt["markdown"].rstrip().endswith(f"{len(cites)}. {cites[-1]}")


def test_searches_agreement_and_minimal():
    data = {
        "tools": {"platform": "dev", "cwb": "3.5.0", "en": True, "stanza": "1.10.1"},
        "searches": [
            {
                "query": '"翻译"',
                "scope": "Tatoeba 中英",
                "aligned": {"op": "+", "query": '"translate"'},
                "counts": {
                    "hits": 30,
                    "sentences": 28,
                    "documents": 1,
                    "complete": True,
                },
                "searched_at": "2026-11-05 10:00 UTC",
            },
            {"query": "[x", "scope": "作文", "error": "查询式有误"},
        ],
        "layers": [
            {
                "name": "偏误",
                "kind": "span",
                "label_set": "learner-errors",
                "mode": "multi",
                "annotators": 2,
                "items": 40,
                "agreement": {"kappa": 0.7512, "alpha": 0.74, "n": 25},
            }
        ],
    }
    out = methods.build(data, "apa")
    md = out["markdown"]
    assert (
        '1. 查询式 `"翻译"`；范围：Tatoeba 中英；译文条件：含 `"translate"`；命中 30 次，28 句，1 篇文档'
        in md
    )
    assert "2. 查询式 `[x`；范围：作文；计数失败：查询式有误" in md
    assert (
        "Cohen κ（两两平均）0.751" in md
        and "Krippendorff α（名义）0.740" in md
        and "比较单元 25 个" in md
    )
    assert "英文分词、词性（UPOS）、词元与依存：Stanza 1.10.1 en 模型" in md
    assert (
        "## 1 处理工具" in md
        and "## 2 检索" in md
        and "## 3 标注" in md
        and "## 4 参考文献" in md
    )
    assert any(c.startswith("Cohen, J. (1960).") for c in out["citations"])
    assert any(c.startswith("Krippendorff, K. (2004).") for c in out["citations"])


def test_metric_detection_and_bad_style():
    stat = {
        "columns": ["collocate", "freq", "mi3", "delta_p_node", "delta_p_coll", "z"],
        "params": {"measures": ["mi3", "z"]},
    }
    assert methods.stat_metrics(stat) == ["mi3", "z", "delta_p"]
    with pytest.raises(ValueError):
        methods.build({}, "mla")
