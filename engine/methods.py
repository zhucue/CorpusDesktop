"""Method appendix and references (contracts/p8.md §六). Pure functions: the API collects the facts.

build(data, style) → {"markdown", "citations"}; only the parts present in `data` are written.

data = {
  "corpora": [{name, language, documents, sentences, tokens, index_version, meta: {license, attribution,
               source_url, version}, builtin: bool, subcorpora: [{name, filter, documents, sentences, tokens}]}],
  "tools": {platform, jieba?, stanza?, cwb?, zh: bool, en: bool, ud: bool},
  "searches": [{query, scope, aligned?: {op, query}, counts?: {hits, sentences, documents, complete},
                searched_at?, error?}],
  "stats": [{method, params, scope, reference?, totals, columns: [key], index_version, created_at}],
  "layers": [{name, kind, label_set, labels, mode, annotators, items,
              agreement?: {kappa, alpha, n}, sample?: {query, scope, aligned, n, seed, total_hits, created_at},
              sample_summary?: {total_hits, sampled, coded, rejected, labels: [{label, count, pct, ci_low,
              ci_high, estimate}]}}],
}
Scopes are display names (the API resolves them). Unknown parameters and totals are written as key=value.

Reference entries are a static table (no lookups); fields not known for certain are left out.
"""

import json

STYLES = ("gbt7714", "apa")
PLATFORM_NAME = "语料检索、分析与标注研究平台"
PLATFORM_URL = "https://github.com/zhucue/CorpusDesktop"

# key: (sort key, in-text label, GB/T 7714-2015, APA 7th)
REFERENCES = {
    "church1990": (
        "Church 1990",
        "Church & Hanks 1990",
        (
            "CHURCH K W, HANKS P. Word association norms, mutual information, and lexicography[J]. "
            "Computational Linguistics, 1990, 16(1): 22-29."
        ),
        (
            "Church, K. W., & Hanks, P. (1990). Word association norms, mutual information, and lexicography. "
            "Computational Linguistics, 16(1), 22–29."
        ),
    ),
    "church1991": (
        "Church 1991",
        "Church et al. 1991",
        (
            "CHURCH K, GALE W, HANKS P, et al. Using statistics in lexical analysis[M]//ZERNIK U. Lexical "
            "acquisition: exploiting on-line resources to build a lexicon. Hillsdale: Lawrence Erlbaum Associates, "
            "1991: 115-164."
        ),
        (
            "Church, K., Gale, W., Hanks, P., & Hindle, D. (1991). Using statistics in lexical analysis. In U. Zernik "
            "(Ed.), Lexical acquisition: Exploiting on-line resources to build a lexicon (pp. 115–164). Lawrence "
            "Erlbaum Associates."
        ),
    ),
    "dunning1993": (
        "Dunning 1993",
        "Dunning 1993",
        (
            "DUNNING T. Accurate methods for the statistics of surprise and coincidence[J]. Computational "
            "Linguistics, 1993, 19(1): 61-74."
        ),
        (
            "Dunning, T. (1993). Accurate methods for the statistics of surprise and coincidence. Computational "
            "Linguistics, 19(1), 61–74."
        ),
    ),
    "rayson2000": (
        "Rayson 2000",
        "Rayson & Garside 2000",
        (
            "RAYSON P, GARSIDE R. Comparing corpora using frequency profiling[C]//Proceedings of the Workshop on "
            "Comparing Corpora. Hong Kong: Association for Computational Linguistics, 2000: 1-6."
        ),
        (
            "Rayson, P., & Garside, R. (2000). Comparing corpora using frequency profiling. In Proceedings of the "
            "Workshop on Comparing Corpora (pp. 1–6). Association for Computational Linguistics."
        ),
    ),
    "rychly2008": (
        "Rychly 2008",
        "Rychlý 2008",
        (
            "RYCHLÝ P. A lexicographer-friendly association score[C]//SOJKA P, HORÁK A. Proceedings of Recent "
            "Advances in Slavonic Natural Language Processing, RASLAN 2008. Brno: Masaryk University, 2008: 6-9."
        ),
        (
            "Rychlý, P. (2008). A lexicographer-friendly association score. In P. Sojka & A. Horák (Eds.), "
            "Proceedings of Recent Advances in Slavonic Natural Language Processing, RASLAN 2008 (pp. 6–9). "
            "Masaryk University."
        ),
    ),
    "oakes1998": (
        "Oakes 1998",
        "Oakes 1998",
        "OAKES M P. Statistics for corpus linguistics[M]. Edinburgh: Edinburgh University Press, 1998.",
        "Oakes, M. P. (1998). Statistics for corpus linguistics. Edinburgh University Press.",
    ),
    "gries2013": (
        "Gries 2013",
        "Gries 2013",
        (
            "GRIES S T. 50-something years of work on collocations: what is or should be next ...[J]. "
            "International Journal of Corpus Linguistics, 2013, 18(1): 137-166."
        ),
        (
            "Gries, S. Th. (2013). 50-something years of work on collocations: What is or should be next …. "
            "International Journal of Corpus Linguistics, 18(1), 137–166."
        ),
    ),
    "evert2005": (
        "Evert 2005",
        "Evert 2005",
        (
            "EVERT S. The statistics of word cooccurrences: word pairs and collocations[D]. Stuttgart: "
            "Universität Stuttgart, 2005."
        ),
        (
            "Evert, S. (2005). The statistics of word cooccurrences: Word pairs and collocations [Doctoral "
            "dissertation, Universität Stuttgart]."
        ),
    ),
    "hardie2014": (
        "Hardie 2014",
        "Hardie 2014",
        (
            "HARDIE A. Log Ratio – an informal introduction[EB/OL]. ESRC Centre for Corpus Approaches to Social "
            "Science (CASS), (2014-04-28). https://cass.lancs.ac.uk/log-ratio-an-informal-introduction/."
        ),
        (
            "Hardie, A. (2014, April 28). Log Ratio – an informal introduction. ESRC Centre for Corpus Approaches "
            "to Social Science (CASS). https://cass.lancs.ac.uk/log-ratio-an-informal-introduction/"
        ),
    ),
    "gabrielatos2012": (
        "Gabrielatos 2012",
        "Gabrielatos & Marchi 2012",
        (
            "GABRIELATOS C, MARCHI A. Keyness: appropriate metrics and practical issues[C]. CADS International "
            "Conference 2012. Bologna: University of Bologna, 2012."
        ),
        (
            "Gabrielatos, C., & Marchi, A. (2012). Keyness: Appropriate metrics and practical issues [Conference "
            "presentation]. CADS International Conference 2012, University of Bologna, Italy."
        ),
    ),
    "gries2008": (
        "Gries 2008",
        "Gries 2008",
        (
            "GRIES S T. Dispersions and adjusted frequencies in corpora[J]. International Journal of Corpus "
            "Linguistics, 2008, 13(4): 403-437."
        ),
        (
            "Gries, S. Th. (2008). Dispersions and adjusted frequencies in corpora. International Journal of "
            "Corpus Linguistics, 13(4), 403–437."
        ),
    ),
    "lijffijt2012": (
        "Lijffijt 2012",
        "Lijffijt & Gries 2012",
        (
            'LIJFFIJT J, GRIES S T. Correction to Stefan Th. Gries, "Dispersions and adjusted frequencies in '
            'corpora"[J]. International Journal of Corpus Linguistics, 2012, 17(1): 147-149.'
        ),
        (
            'Lijffijt, J., & Gries, S. Th. (2012). Correction to Stefan Th. Gries, "Dispersions and adjusted '
            'frequencies in corpora". International Journal of Corpus Linguistics, 17(1), 147–149.'
        ),
    ),
    "juilland1964": (
        "Juilland 1964",
        "Juilland & Chang-Rodríguez 1964",
        "JUILLAND A, CHANG-RODRÍGUEZ E. Frequency dictionary of Spanish words[M]. The Hague: Mouton, 1964.",
        "Juilland, A., & Chang-Rodríguez, E. (1964). Frequency dictionary of Spanish words. Mouton.",
    ),
    "bonferroni1936": (
        "Bonferroni 1936",
        "Bonferroni 1936",
        (
            "BONFERRONI C E. Teoria statistica delle classi e calcolo delle probabilità[J]. Pubblicazioni del R "
            "Istituto Superiore di Scienze Economiche e Commerciali di Firenze, 1936, 8: 1-62."
        ),
        (
            "Bonferroni, C. E. (1936). Teoria statistica delle classi e calcolo delle probabilità. Pubblicazioni "
            "del R Istituto Superiore di Scienze Economiche e Commerciali di Firenze, 8, 1–62."
        ),
    ),
    "wilson1927": (
        "Wilson 1927",
        "Wilson 1927",
        (
            "WILSON E B. Probable inference, the law of succession, and statistical inference[J]. Journal of the "
            "American Statistical Association, 1927, 22(158): 209-212."
        ),
        (
            "Wilson, E. B. (1927). Probable inference, the law of succession, and statistical inference. Journal "
            "of the American Statistical Association, 22(158), 209–212."
        ),
    ),
    "dice1945": (
        "Dice 1945",
        "Dice 1945",
        (
            "DICE L R. Measures of the amount of ecologic association between species[J]. Ecology, 1945, 26(3): "
            "297-302."
        ),
        (
            "Dice, L. R. (1945). Measures of the amount of ecologic association between species. Ecology, 26(3), "
            "297–302."
        ),
    ),
    "cohen1960": (
        "Cohen 1960",
        "Cohen 1960",
        (
            "COHEN J. A coefficient of agreement for nominal scales[J]. Educational and Psychological Measurement, "
            "1960, 20(1): 37-46."
        ),
        (
            "Cohen, J. (1960). A coefficient of agreement for nominal scales. Educational and Psychological "
            "Measurement, 20(1), 37–46."
        ),
    ),
    "krippendorff2004": (
        "Krippendorff 2004",
        "Krippendorff 2004",
        (
            "KRIPPENDORFF K. Content analysis: an introduction to its methodology[M]. 2nd ed. Thousand Oaks: Sage, "
            "2004."
        ),
        "Krippendorff, K. (2004). Content analysis: An introduction to its methodology (2nd ed.). Sage.",
    ),
    "evert2011": (
        "Evert 2011",
        "Evert & Hardie 2011",
        (
            "EVERT S, HARDIE A. Twenty-first century Corpus Workbench: updating a query architecture for the new "
            "millennium[C]//Proceedings of the Corpus Linguistics 2011 Conference. Birmingham: University of "
            "Birmingham, 2011."
        ),
        (
            "Evert, S., & Hardie, A. (2011). Twenty-first century Corpus Workbench: Updating a query architecture "
            "for the new millennium. In Proceedings of the Corpus Linguistics 2011 Conference. University of "
            "Birmingham."
        ),
    ),
    "qi2020": (
        "Qi 2020",
        "Qi et al. 2020",
        (
            "QI P, ZHANG Y, ZHANG Y, et al. Stanza: a Python natural language processing toolkit for many human "
            "languages[C]//Proceedings of the 58th Annual Meeting of the Association for Computational "
            "Linguistics: System Demonstrations. Association for Computational Linguistics, 2020: 101-108."
        ),
        (
            "Qi, P., Zhang, Y., Zhang, Y., Bolton, J., & Manning, C. D. (2020). Stanza: A Python natural language "
            "processing toolkit for many human languages. In Proceedings of the 58th Annual Meeting of the "
            "Association for Computational Linguistics: System Demonstrations (pp. 101–108). Association for "
            "Computational Linguistics."
        ),
    ),
    # P10 (contracts/p10.md §一~§五)
    "mccarthy2010": (
        "McCarthy 2010",
        "McCarthy & Jarvis 2010",
        (
            "MCCARTHY P M, JARVIS S. MTLD, vocd-D, and HD-D: a validation study of sophisticated approaches to "
            "lexical diversity assessment[J]. Behavior Research Methods, 2010, 42(2): 381-392."
        ),
        (
            "McCarthy, P. M., & Jarvis, S. (2010). MTLD, vocd-D, and HD-D: A validation study of sophisticated "
            "approaches to lexical diversity assessment. Behavior Research Methods, 42(2), 381–392."
        ),
    ),
    "ure1971": (
        "Ure 1971",
        "Ure 1971",
        (
            "URE J. Lexical density and register differentiation[M]//PERREN G E, TRIM J L M. Applications of "
            "linguistics: selected papers of the Second International Congress of Applied Linguistics, Cambridge "
            "1969. Cambridge: Cambridge University Press, 1971: 443-452."
        ),
        (
            "Ure, J. (1971). Lexical density and register differentiation. In G. E. Perren & J. L. M. Trim (Eds.), "
            "Applications of linguistics: Selected papers of the Second International Congress of Applied "
            "Linguistics, Cambridge 1969 (pp. 443–452). Cambridge University Press."
        ),
    ),
    "liu2008": (
        "Liu 2008",
        "Liu 2008",
        (
            "LIU H. Dependency distance as a metric of language comprehension difficulty[J]. Journal of "
            "Cognitive Science, 2008, 9(2): 159-191."
        ),
        (
            "Liu, H. (2008). Dependency distance as a metric of language comprehension difficulty. Journal of "
            "Cognitive Science, 9(2), 159–191."
        ),
    ),
    "flesch1948": (
        "Flesch 1948",
        "Flesch 1948",
        "FLESCH R. A new readability yardstick[J]. Journal of Applied Psychology, 1948, 32(3): 221-233.",
        "Flesch, R. (1948). A new readability yardstick. Journal of Applied Psychology, 32(3), 221–233.",
    ),
    "kincaid1975": (
        "Kincaid 1975",
        "Kincaid et al. 1975",
        (
            "KINCAID J P, FISHBURNE R P, ROGERS R L, et al. Derivation of new readability formulas (Automated "
            "Readability Index, Fog Count and Flesch Reading Ease Formula) for Navy enlisted personnel: Research "
            "Branch Report 8-75[R]. Millington, TN: Chief of Naval Technical Training, Naval Air Station Memphis, "
            "1975. https://apps.dtic.mil/sti/pdfs/ADA006655.pdf."
        ),
        (
            "Kincaid, J. P., Fishburne, R. P., Jr., Rogers, R. L., & Chissom, B. S. (1975). Derivation of new "
            "readability formulas (Automated Readability Index, Fog Count and Flesch Reading Ease Formula) for "
            "Navy enlisted personnel (Research Branch Report 8-75). Chief of Naval Technical Training, Naval Air "
            "Station Memphis. https://apps.dtic.mil/sti/pdfs/ADA006655.pdf"
        ),
    ),
    "mann1947": (
        "Mann 1947",
        "Mann & Whitney 1947",
        (
            "MANN H B, WHITNEY D R. On a test of whether one of two random variables is stochastically larger "
            "than the other[J]. The Annals of Mathematical Statistics, 1947, 18(1): 50-60."
        ),
        (
            "Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random variables is "
            "stochastically larger than the other. The Annals of Mathematical Statistics, 18(1), 50–60."
        ),
    ),
    "spearman1904": (
        "Spearman 1904",
        "Spearman 1904",
        (
            "SPEARMAN C. The proof and measurement of association between two things[J]. The American Journal "
            "of Psychology, 1904, 15(1): 72-101."
        ),
        (
            "Spearman, C. (1904). The proof and measurement of association between two things. The American "
            "Journal of Psychology, 15(1), 72–101."
        ),
    ),
    "kilgarriff2004": (
        "Kilgarriff 2004",
        "Kilgarriff et al. 2004",
        (
            "KILGARRIFF A, RYCHLÝ P, SMRŽ P, et al. The Sketch Engine[C]//WILLIAMS G, VESSIER S. Proceedings of "
            "the 11th EURALEX International Congress. Lorient: Université de Bretagne-Sud, 2004: 105-116. "
            "https://euralex.org/publications/the-sketch-engine/."
        ),
        (
            "Kilgarriff, A., Rychlý, P., Smrž, P., & Tugwell, D. (2004). The Sketch Engine. In G. Williams & S. "
            "Vessier (Eds.), Proceedings of the 11th EURALEX International Congress (pp. 105–116). Université de "
            "Bretagne-Sud. https://euralex.org/publications/the-sketch-engine/"
        ),
    ),
    "kilgarriff2014": (
        "Kilgarriff 2014",
        "Kilgarriff et al. 2014",
        (
            "KILGARRIFF A, BAISA V, BUŠTA J, et al. The Sketch Engine: ten years on[J]. Lexicography, 2014, "
            "1(1): 7-36."
        ),
        (
            "Kilgarriff, A., Baisa, V., Bušta, J., Jakubíček, M., Kovář, V., Michelfeit, J., Rychlý, P., & "
            "Suchomel, V. (2014). The Sketch Engine: Ten years on. Lexicography, 1(1), 7–36."
        ),
    ),
    "browne2023": (
        "Browne 2023",
        "Browne, Culligan & Phillips 2023",
        (
            "BROWNE C, CULLIGAN B, PHILLIPS J. The New General Service List: version 1.2[EB/OL]. (2023-04)"
            "[2026-11-06]. https://www.newgeneralservicelist.com/new-general-service-list."
        ),
        (
            "Browne, C., Culligan, B., & Phillips, J. (2023). The New General Service List (Version 1.2) [Word "
            "list]. https://www.newgeneralservicelist.com/new-general-service-list"
        ),
    ),
}

# DOIs, appended as "DOI: …" (GB/T 7714) or "https://doi.org/…" (APA)
DOIS = {
    "rayson2000": "10.3115/1117729.1117730",
    "gries2008": "10.1075/ijcl.13.4.02gri",
    "gries2013": "10.1075/ijcl.18.1.09gri",
    "lijffijt2012": "10.1075/ijcl.17.1.08lij",
    "wilson1927": "10.1080/01621459.1927.10502953",
    "dice1945": "10.2307/1932409",
    "cohen1960": "10.1177/001316446002000104",
    "qi2020": "10.18653/v1/2020.acl-demos.14",
    "mccarthy2010": "10.3758/BRM.42.2.381",
    "liu2008": "10.17791/jcs.2008.9.2.159",
    "flesch1948": "10.1037/h0057532",
    "mann1947": "10.1214/aoms/1177730491",
    "spearman1904": "10.2307/1412159",
    "kilgarriff2014": "10.1007/s40607-014-0009-9",
}


def reference(key, style):
    entry = REFERENCES[key][3 if style == "apa" else 2]
    doi = DOIS.get(key)
    if not doi:
        return entry
    return (
        f"{entry} https://doi.org/{doi}" if style == "apa" else f"{entry} DOI: {doi}."
    )


# metric key: (name, one-line formula, reference keys); order = order in the appendix
METRICS = {
    "per_million": ("每百万词", "f / N × 10⁶，N 为范围词数（含标点）", ()),
    "range": ("range", "出现该项的部分数（range_pct 为占部分总数的百分比）", ()),
    "dp": (
        "DP",
        "DP = ½ Σ|vᵢ − sᵢ|，vᵢ = fᵢ / f，sᵢ = 部分词数 / 范围词数；0 表示均匀，越大越集中",
        ("gries2008",),
    ),
    "dp_norm": ("DPnorm", "DPnorm = DP / (1 − min sᵢ)", ("lijffijt2012",)),
    "juilland_d": (
        "Juilland D",
        "D = 1 − CV / √(n − 1)，CV 为各部分相对频率 pᵢ = fᵢ / 部分词数 的变异系数，n 为部分数",
        ("juilland1964",),
    ),
    "mi": ("MI", "MI = log₂(O / E)，O 为窗口内共现频次，E 为期望频次", ("church1990",)),
    "mi3": ("MI3", "MI3 = log₂(O³ / E)", ("oakes1998",)),
    "t": ("t", "t = (O − E) / √O", ("church1991",)),
    "z": ("z", "z = (O − E) / √E", ("evert2005",)),
    "logdice": (
        "logDice",
        "logDice = 14 + log₂(2O / (f节点 + f搭配词))",
        ("rychly2008",),
    ),
    "delta_p": (
        "ΔP",
        "ΔP节点 = P(搭配词 | 节点) − P(搭配词 | 非节点)；ΔP搭配词 交换节点与搭配词的位置",
        ("gries2013",),
    ),
    "ll": (
        "LL",
        "对数似然比 G² = 2 Σ O ln(O / E)，2×2 列联表",
        ("dunning1993", "rayson2000"),
    ),
    "log_ratio": (
        "log ratio",
        "log ratio = log₂((a / c) / (b / d))，a、b 为目标与参照频次，c、d 为两库词数，0 次按 0.5 计",
        ("hardie2014",),
    ),
    "log_ratio_ci": (
        "log ratio 95% 置信区间",
        "log₂ 尺度，SE = √(1/a + 1/b)，0 次按 0.5 平滑",
        ("hardie2014",),
    ),
    "pct_diff": (
        "%DIFF",
        "%DIFF = (目标每百万 − 参照每百万) / 参照每百万 × 100，参照为 0 时按 0.5 次平滑",
        ("gabrielatos2012",),
    ),
    "odds_ratio": ("odds ratio", "OR = (a / (c − a)) / (b / (d − b))", ()),
    "significance": (
        "显著性",
        "LL ≥ 3.84 / 6.63 / 10.83 对应 p < 0.05 / 0.01 / 0.001（自由度 1）",
        (),
    ),
    "bonferroni": (
        "Bonferroni 校正",
        "显著性阈值除以检验的词型数 m（p < 0.05 / m、0.01 / m、0.001 / m）",
        ("bonferroni1936",),
    ),
    "dice": (
        "Dice",
        "Dice = 2a / (n + b)，a 为共现句数，n 为命中句数，b 为该词在目标侧的句数",
        ("dice1945",),
    ),
    # P10 text metrics (words = tokens with a letter or CJK character; types = lower-cased forms)
    "ttr": ("TTR", "TTR = 词种 / 词数（词不含标点、符号与纯数字）", ()),
    "sttr": (
        "STTR",
        "每 n 词（STTR 窗口）一段的 TTR 均值，末尾不足一段不计；词数少于 100 的文档不计",
        (),
    ),
    "mtld": (
        "MTLD",
        (
            "顺读、倒读各一遍：累计 TTR 降到 0.72 记一个因子并重新累计，剩余部分记 (1 − TTR) / (1 − 0.72) 个因子；"
            "MTLD = 词数 / 因子数，取两遍均值；词数少于 100 的文档不计"
        ),
        ("mccarthy2010",),
    ),
    "lexical_density": (
        "词汇密度",
        "实词数 / 词数；实词为 UPOS NOUN、PROPN、VERB、ADJ、ADV，或 jieba 词性以 n、v、a、d 开头",
        ("ure1971",),
    ),
    "mean_sentence_length": ("平均句长", "词数 / 句数", ()),
    "mean_dependency_distance": (
        "平均依存距离",
        "MDD = Σ|中心词序号 − 从属词序号| / 依存数，不含根，标点计入",
        ("liu2008",),
    ),
    "flesch_reading_ease": (
        "Flesch 易读度",
        "206.835 − 1.015 × 词数 / 句数 − 84.6 × 音节数 / 词数（英文；音节按元音组估计）",
        ("flesch1948",),
    ),
    "flesch_kincaid_grade": (
        "Flesch-Kincaid 年级",
        "0.39 × 词数 / 句数 + 11.8 × 音节数 / 词数 − 15.59（英文）",
        ("kincaid1975",),
    ),
    "coverage": (
        "词次覆盖率",
        "该等级的词次 / 词数 × 100；英文按小写词元、中文按词形匹配词表，未匹配的词计入表外",
        (),
    ),
    "ngsl": (
        "NGSL 1.2",
        "New General Service List 1.2（CC BY-SA 4.0），等级为 SFI 排名段 1–1000、1001–2000、2001–2809",
        ("browne2023",),
    ),
    "mann_whitney": (
        "Mann-Whitney U",
        "每篇文档的每百万词为一个观测，比较两项；正态近似，含结校正与连续性校正；效应量 r = z / √n",
        ("mann1947",),
    ),
    "spearman": (
        "Spearman ρ",
        "每篇文档的字段值与每百万词的秩相关；p 值按 t 分布（自由度 n − 2），双侧",
        ("spearman1904",),
    ),
    "word_sketch": (
        "Word Sketch",
        "按 UD 依存关系（主语、宾语、修饰、并列、介词短语等）分栏列出搭配词元，logDice 在各关系内计算",
        ("kilgarriff2004", "kilgarriff2014"),
    ),
    "logdice_diff": (
        "logDice 差",
        "logDice(A) − logDice(B)，一方没有该搭配时其 logDice 记 0",
        (),
    ),
}

# column / parameter value → metric key
COLUMN_METRIC = {
    "range_pct": "range",
    "delta_p_node": "delta_p",
    "delta_p_coll": "delta_p",
    "log_ratio_ci_low": "log_ratio_ci",
    "log_ratio_ci_high": "log_ratio_ci",
    "target_pm": "per_million",
    "ref_pm": "per_million",
    "logdice_a": "logdice",
    "logdice_b": "logdice",
    "diff": "logdice_diff",
}

METHODS = {
    "frequency": "频次",
    "ngrams": "n-gram",
    "collocations": "搭配",
    "keywords": "关键词",
    "distribution": "分布",
    "breakdown": "命中频次分解",
    "translations": "译法",
    "text_metrics": "文本指标",
    "vocab_profile": "词汇等级画像",
    "compare": "多项对比",
    "word_sketch": "Word Sketch",
    "sketch_diff": "近义词对比（sketch diff）",
}
UNITS = {
    "word": "词形",
    "lemma": "词元",
    "pos": "词性",
    "deprel": "依存关系",
    "span_label": "片段标签",
    "relation_label": "关系标签",
}
BY = {
    "word": "词形",
    "lemma": "词元",
    "pos": "词性",
    "left1": "左一词",
    "right1": "右一词",
}
PARTS = {"document": "每篇文档", "segments": "按词数等分 10 段"}
DIRECTIONS = {"positive": "目标多于参照", "negative": "参照多于目标", "both": "双向"}
LAYER_KINDS = {
    "pos": "词性",
    "dep": "依存",
    "span": "片段",
    "relation": "关系",
    "alignment": "对齐",
}
TOTALS = {
    "tokens": "词数（含标点）",
    "sentences": "句数",
    "documents": "文档数",
    "excluded_tokens": "未列出的标点与数字词数",
    "parts": "部分数",
    "hits": "命中数",
    "node_hits": "节点命中数",
    "window_tokens": "窗口词数",
    "hit_sentences": "命中句数",
    "aligned_sentences": "有对齐的命中句数",
    "unaligned": "无对齐的命中句数",
    "words": "词数（不含标点）",
    "node_freq": "节点词频次",
    "node_freq_a": "词元 A 频次",
    "node_freq_b": "词元 B 频次",
    "items": "对比项数",
    "notes": "说明",
}
SKIP_PARAMS = {"method", "project_id", "scope", "target", "reference", "layers"}
SKIP_PARAMS |= {
    "list_id",
    "query_layers",
    "item_scopes",
}  # P10: written through other keys
TESTS = {"mann_whitney": "Mann-Whitney U 检验", "spearman": "Spearman 秩相关"}
VOCAB_BY = {"corpus": "全部范围", "document": "每篇文档"}


def _n(v):
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:,.0f}"
    if v is None:
        return "—"
    return str(v)


def as_json(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def _aligned(a):
    if not a:
        return ""
    return f"{'含' if a.get('op') == '+' else '不含'} `{a.get('query', '')}`"


def _p10_param(key, v, method):
    """P10 parameters whose wording depends on the method; None when the key is not one of them."""
    if method == "vocab_profile" and key == "by":
        return "按 " + VOCAB_BY.get(v, f"字段 {v}")
    if method == "compare" and key == "by":
        return f"按字段 {v}"
    if method == "compare" and key == "items":
        return "对比项 " + "；".join(
            f"{i.get('label')}：`{i.get('query')}`" for i in v if isinstance(i, dict)
        )
    if key == "metrics" and isinstance(v, list):
        return "指标 " + "、".join(METRICS.get(m, (m,))[0] for m in v)
    if key == "group_by":
        return f"按字段 {v} 分组汇总"
    if key == "sttr_window":
        return f"STTR 窗口 {v} 词"
    if key == "vocab_list" and isinstance(v, dict):
        extra = "；".join(x for x in (v.get("source"), v.get("license")) if x)
        return f"词表 {v.get('name', '')}" + (f"（{extra}）" if extra else "")
    if key == "test":
        return f"检验 {TESTS[v]}" if v in TESTS else None
    if key in ("lemma", "lemma_a", "lemma_b"):
        names = {"lemma": "词元", "lemma_a": "词元 A", "lemma_b": "词元 B"}
        return f"{names[key]} {v}"
    if key == "queries":
        return "查询式 " + "；".join(f"`{q}`" for q in v) if v else None
    return None


def _param(key, v, method=None):
    """One parameter as Chinese text, or None to leave it out."""
    if v is None or key in SKIP_PARAMS:
        return None
    if (text := _p10_param(key, v, method)) is not None:
        return text
    if key == "unit":
        return f"单位 {UNITS.get(v, v)}"
    if key == "n":
        return f"n = {v}"
    if key == "pos":
        return f"词性 {v}"
    if key == "pos_pattern":
        return "词性模式 " + " ".join(t or "*" for t in v)
    if key == "contains":
        return f"包含词 {v}"
    if key == "node":
        return f"节点 `{v}`"
    if key == "window":
        return f"窗口 ±{v}"
    if key == "measures":
        return "指标 " + "、".join(METRICS.get(m, (m,))[0] for m in v)
    if key == "measure":
        return f"排序指标 {METRICS.get(v, (v,))[0]}"
    if key == "min_freq":
        return f"最低频次 {v}"
    if key == "top":
        return f"显示前 {v}"
    if key == "exclude_punct":
        return "排除只由标点、符号、数字组成的项" if v else "保留标点与数字项"
    if key == "field":
        return "按文档位置" if v == "position" else f"字段 {v}"
    if key == "bins":
        return f"区间数 {v}"
    if key == "query":
        return f"查询式 `{v}`"
    if key == "by":
        return "分解方式 " + (
            f"元数据 {v[5:]}" if str(v).startswith("meta:") else BY.get(v, v)
        )
    if key == "parts":
        return "部分 " + (
            f"字段 {v[6:]} 的每个值" if str(v).startswith("field:") else PARTS.get(v, v)
        )
    if key == "dispersion":
        return "计算离散度" if v else "不计算离散度"
    if key == "direction":
        return f"方向 {DIRECTIONS.get(v, v)}"
    if key == "items":
        return "指定词 " + "、".join(v)
    if key == "target_language":
        return f"目标语言 {v}"
    if key == "aligned":
        return f"译文条件 {_aligned(v)}" if v else None
    return f"{key} = {as_json(v) if isinstance(v, (dict, list)) else v}"


def stat_metrics(stat) -> list[str]:
    """Metric keys a statistics result uses: its columns, then measure parameters."""
    found = []
    keys = list(stat.get("columns") or [])
    p = stat.get("params") or {}
    keys += list(p.get("measures") or [])
    if p.get("measure"):
        keys.append(p["measure"])
    method = stat.get("method")
    keys = ["per_million" if k.startswith("per_million_") else k for k in keys]
    if method == "vocab_profile":
        keys.append("coverage")
        if (p.get("vocab_list") or {}).get("builtin"):
            keys.append("ngsl")
    if method == "compare":
        if len(p.get("items") or []) == 2 and not p.get("by"):
            keys += ["ll", "log_ratio"]
        if p.get("test") in TESTS:
            keys.append(p["test"])
    if method in ("word_sketch", "sketch_diff"):
        keys += ["word_sketch", "logdice"]
    for k in keys:
        m = COLUMN_METRIC.get(k, k)
        if m in METRICS and m not in found:
            found.append(m)
    return [m for m in METRICS if m in found]


class _Refs:
    def __init__(self, style):
        self.style = style
        self.keys = []

    def cite(self, *keys):
        """In-text citation（作者 年；…）, registering the references."""
        out = []
        for k in keys:
            if k not in self.keys:
                self.keys.append(k)
            out.append(
                REFERENCES[k][1].replace(" & ", " 和 ")
                if self.style == "gbt7714"
                else REFERENCES[k][1]
            )
        return "；".join(out)


def _corpus_lines(c):
    meta = c.get("meta") or {}
    size = f"{_n(c.get('documents', 0))} 篇文档，{_n(c.get('sentences', 0))} 句，{_n(c.get('tokens', 0))} 词（含标点）"
    parts = [f"**{c['name']}**（语言 {c.get('language') or '—'}）：{size}"]
    for key, label in (
        ("attribution", "来源"),
        ("source_url", "链接"),
        ("license", "许可"),
        ("version", "版本"),
    ):
        if meta.get(key):
            parts.append(f"{label}：{meta[key]}")
    parts.append(f"索引版本：{c.get('index_version') or '—'}")
    lines = ["- " + "；".join(parts)]
    for s in c.get("subcorpora") or []:
        size = f"{_n(s.get('documents', 0))} 篇文档，{_n(s.get('sentences', 0))} 句，{_n(s.get('tokens', 0))} 词"
        lines.append(
            f"  - 子库「{s['name']}」：筛选条件 `{as_json(s.get('filter') or {})}`；{size}"
        )
    return lines


def _tool_lines(t, refs):
    lines = []
    if t.get("ud"):
        lines.append(
            "- Universal Dependencies 语料沿用其人工分词、词性、词元与依存标注"
        )
    if t.get("zh"):
        lines.append(
            f"- 中文分词与词性：jieba {t.get('jieba') or '—'}（默认词典，关闭 HMM 新词发现）"
        )
        lines.append(
            f"- 中文依存预标注：Stanza {t.get('stanza') or '—'} zh-hans 模型，在 jieba 分词结果上分析"
            f"（{refs.cite('qi2020')}）"
        )
    if t.get("en"):
        lines.append(
            f"- 英文分词、词性（UPOS）、词元与依存：Stanza {t.get('stanza') or '—'} en 模型（{refs.cite('qi2020')}）"
        )
    if t.get("cwb"):
        lines.append(
            f"- 检索与统计索引：IMS Open Corpus Workbench（CWB）{t['cwb']}（{refs.cite('evert2011')}）"
        )
    lines.append(f"- 平台：{PLATFORM_NAME} {t.get('platform') or 'dev'}")
    return lines


def _search_line(i, s):
    parts = [f"{i}. 查询式 `{s['query']}`；范围：{s.get('scope') or '—'}"]
    if s.get("aligned"):
        parts.append(f"译文条件：{_aligned(s['aligned'])}")
    c = s.get("counts")
    if s.get("error"):
        parts.append(f"计数失败：{s['error']}")
    elif c and c.get("complete"):
        parts.append(
            f"命中 {_n(c.get('hits'))} 次，{_n(c.get('sentences'))} 句，{_n(c.get('documents'))} 篇文档"
        )
    elif c:
        parts.append("计数未完成")
    if s.get("searched_at"):
        parts.append(f"检索时间：{s['searched_at']}")
    return "；".join(parts)


def _totals(totals):
    """Scalars and one level of dicts; lists (P10 groups, relations, notes …) are left out except notes."""
    out = []
    for k, v in (totals or {}).items():
        if isinstance(v, dict):
            inner = "，".join(
                f"{TOTALS.get(a, a)} {_n(b)}"
                for a, b in v.items()
                if not isinstance(b, dict | list)
            )
            if inner:
                out.append(f"{'参照' if k == 'reference' else k}：{inner}")
        elif isinstance(v, list):
            if k == "notes" and v:
                out.append(f"{TOTALS[k]}：{'，'.join(map(str, v))}")
        else:
            out.append(f"{TOTALS.get(k, k)} {_n(v)}")
    return "；".join(out)


def _stat_lines(sec, i, s, refs):
    method = s.get("method", "")
    p = s.get("params") or {}
    head = f"### {sec}.{i} {METHODS.get(method, method)}"
    lines = [head, ""]
    scope = f"- 范围：{s.get('scope') or '—'}"
    if s.get("reference"):
        scope += f"；参照：{s['reference']}"
    lines.append(scope)
    params = [x for k, v in p.items() if (x := _param(k, v, method))]
    if params:
        lines.append("- 参数：" + "；".join(params))
    if s.get("totals"):
        lines.append("- 规模：" + _totals(s["totals"]))
    metrics = stat_metrics(s)
    if metrics:
        lines.append("- 指标：")
        for m in metrics:
            name, formula, keys = METRICS[m]
            cite = f"（{refs.cite(*keys)}）" if keys else ""
            text = formula if formula.startswith(name) else f"{name}：{formula}"
            lines.append(f"  - {text}{cite}")
    lines.append(
        f"- 索引版本：{s.get('index_version') or '—'}；计算时间：{s.get('created_at') or '—'}"
    )
    lines.append("")
    return lines


def _pct(v):
    """Proportions of the sample summary are fractions (0–1)."""
    return "—" if v is None else f"{v * 100:.1f}%"


def _layer_lines(sec, i, layer, refs):
    kind = LAYER_KINDS.get(layer.get("kind"), layer.get("kind"))
    lines = [f"### {sec}.{i} {layer['name']}（{kind}层）", ""]
    if layer.get("label_set"):
        labels = (
            f"，{layer['labels']} 个标签" if layer.get("labels") is not None else ""
        )
        lines.append(f"- 标签集：{layer['label_set']}{labels}")
    mode = "多人独立标注" if layer.get("mode") == "multi" else "单人标注"
    lines.append(
        f"- 标注方式：{mode}，标注人数 {layer.get('annotators', 1)}；条目数 {_n(layer.get('items', 0))}"
    )
    ag = layer.get("agreement")
    if ag and (ag.get("kappa") is not None or ag.get("alpha") is not None):
        parts = []
        if ag.get("kappa") is not None:
            parts.append(
                f"Cohen κ（两两平均）{ag['kappa']:.3f}（{refs.cite('cohen1960')}）"
            )
        if ag.get("alpha") is not None:
            parts.append(
                f"Krippendorff α（名义）{ag['alpha']:.3f}（{refs.cite('krippendorff2004')}）"
            )
        lines.append(
            f"- 一致性：{'；'.join(parts)}；比较单元 {_n(ag.get('n', 0))} 个（各标注者均已完成的单元）"
        )
    sample = layer.get("sample")
    if sample:
        text = (
            f"- 抽样：查询式 `{sample.get('query', '')}`，范围 {sample.get('scope') or '—'}"
            + (
                f"，译文条件 {_aligned(sample['aligned'])}"
                if sample.get("aligned")
                else ""
            )
            + f"；从全部 {_n(sample.get('total_hits'))} 条命中中按随机种子 {sample.get('seed')} 等概率无放回抽取"
            f" {_n(sample.get('n'))} 条"
            + (f"；抽样时间 {sample['created_at']}" if sample.get("created_at") else "")
        )
        lines.append(text)
        summary = layer.get("sample_summary")
        if summary:
            lines.append(
                f"- 编码：已编码 {_n(summary.get('coded'))} / 抽样 {_n(summary.get('sampled'))}，"
                f"拒绝（不计入）{_n(summary.get('rejected'))}；比例以已编码条目为分母，"
                f"比例的 95% Wilson 区间（{refs.cite('wilson1927')}）；估计命中数 = 比例 × 全部命中数"
            )
            rows = summary.get("labels") or []
            if rows:
                lines += [
                    "",
                    "| 标签 | 条数 | 比例 | 95% 区间 | 估计命中数 |",
                    "| --- | --- | --- | --- | --- |",
                ]
                for r in rows:
                    lines.append(
                        f"| {r.get('label')} | {_n(r.get('count'))} | {_pct(r.get('pct'))} | "
                        f"{_pct(r.get('ci_low'))} – {_pct(r.get('ci_high'))} | {_n(r.get('estimate'))} |"
                    )
    lines.append("")
    return lines


def _corpus_citation(c, style):
    """Built-in corpus entry from Corpus.meta; None when it has no attribution or license."""
    meta = c.get("meta") or {}
    if not (meta.get("attribution") or meta.get("license")):
        return None
    name, version = c["name"], meta.get("version")
    if style == "gbt7714":
        out = f"{meta.get('attribution') or name}. {name}[DS/OL]"
        if version:
            out += f". 版本 {version}"
        if meta.get("license"):
            out += f". 许可 {meta['license']}"
        if meta.get("source_url"):
            out += f". {meta['source_url']}"
        return out + "."
    out = f"{name}" + (f" (Version {version})" if version else "") + " [Data set]."
    if meta.get("attribution"):
        out += f" {meta['attribution']}."
    if meta.get("license"):
        out += f" License: {meta['license']}."
    if meta.get("source_url"):
        out += f" {meta['source_url']}"
    return out


def _platform_citation(version, style):
    v = version or "dev"
    if style == "gbt7714":
        return f"{PLATFORM_NAME}[CP/OL]. 版本 {v}. {PLATFORM_URL}."
    return f"{PLATFORM_NAME} (Version {v}) [Computer software]. {PLATFORM_URL}"


def build(data: dict, style: str = "gbt7714") -> dict:
    if style not in STYLES:
        raise ValueError(f"未知引用格式：{style}")
    refs = _Refs(style)
    md = ["# 方法附录", ""]
    section = 0

    corpora = data.get("corpora") or []
    if corpora:
        section += 1
        md += [f"## {section} 语料", ""]
        for c in corpora:
            md += _corpus_lines(c)
        md.append("")

    tools = data.get("tools") or {}
    section += 1
    md += [f"## {section} 处理工具", "", *_tool_lines(tools, refs), ""]

    searches = data.get("searches") or []
    if searches:
        section += 1
        md += [f"## {section} 检索", ""]
        md += [_search_line(i, s) for i, s in enumerate(searches, 1)]
        md.append("")

    stats = data.get("stats") or []
    if stats:
        section += 1
        md += [f"## {section} 统计", ""]
        for i, s in enumerate(stats, 1):
            md += _stat_lines(section, i, s, refs)

    layers = data.get("layers") or []
    if layers:
        section += 1
        md += [f"## {section} 标注", ""]
        for i, layer in enumerate(layers, 1):
            md += _layer_lines(section, i, layer, refs)

    keys = sorted(refs.keys, key=lambda k: REFERENCES[k][0].lower())
    citations = [reference(k, style) for k in keys]
    citations += [
        x for c in corpora if c.get("builtin") and (x := _corpus_citation(c, style))
    ]
    citations.append(_platform_citation(tools.get("platform"), style))
    section += 1
    md += [f"## {section} 参考文献", ""]
    md += [f"{i}. {c}" for i, c in enumerate(citations, 1)]
    return {"markdown": "\n".join(md).rstrip() + "\n", "citations": citations}
