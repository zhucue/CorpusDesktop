---
name: synonym-comparison
description: 近义词辨析。用户要比较两个近义词（如 big 和 large、提高和提升）的用法、搭配、语域或频率差异时使用；用 Word Sketch、Sketch Diff 与例句。
---

# 近义词辨析

## 适用问题

- “比较 big 和 large 的用法。”
- “提高和提升有什么区别？”
- “这两个词分别常和什么名词搭配？”

## 步骤

1. 确认两个词与词性。用户没说词性时按常见词性（如 big / large 为 ADJ）传 pos，并在正文写明。
2. 比较频率：stats_compare，items 为两项 `{label: "big", query: "{lemma=big}"}`、`{label: "large", query: "{lemma=large}"}`，不带 by；得到两者的每百万词与 LL。需要看体裁或年代差异时再加 by（如 genre、year）。
3. 搭配差异：stats_sketch_diff，lemma_a、lemma_b、pos；min_freq 默认 2。看 sides 的 a（偏 A）、common（共同）、b（偏 B）。
4. 需要单个词的完整画像时，再对它做 stats_word_sketch。
5. 看例句：从偏 A、偏 B 各挑 1–2 个最典型的搭配，用该行的 search_query 调用 corpus_search 取例句；search_query 为 null 的行不取例句。
6. 中文或其他没有依存的语料返回 NO_DEPENDENCIES 时，告诉用户需要先在标注页建依存层；这时只做第 2 步频率比较和搭配统计（stats_collocations）。

## 工具与参数

- stats_compare：items（2 项）、by（可选）。
- stats_sketch_diff：lemma_a、lemma_b、pos、min_freq、top。
- stats_word_sketch：lemma、pos。
- corpus_search：query（行的 search_query）。

## 呈现

- 频率：FreqChart（value 为每百万词）；带 by 时 CompareChart。
- 搭配差异：SketchDiff 三列卡。
- 单词画像：WordSketch 分栏卡，只放用户关心的栏。
- 例句：KwicTable。
- 正文按关系（宾语、修饰等）概括差异，只写工具给出的搭配与数值；搭配总数与各组数量照抄 side_totals（total、a、common、b），不自己数行或相加。

## 口径与局限

- logDice 衡量搭配强度，不是频次；diff 为两词在同一关系中的 logDice 差。
- 依存分析有错误，尤其是长句与介词短语挂靠；少量搭配可能是分析错误，提醒用户看例句核对。
- 按词元统计会合并词形（larger、largest 归入 large）。
- 多义词的不同义项混在一起，例句才能区分义项。
- 不替用户下“A 用于正式语境”之类结论；可以说明数据显示的倾向，由用户判断。
