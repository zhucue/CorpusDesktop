---
name: keyword-analysis
description: 关键词分析。用户要找一个语料或子库相对另一个语料显著多用 / 少用的词，比较两类文本（如译文与原创、学习者与母语者、两个年代）的用词特点时使用。
---

# 关键词分析

## 适用问题

- “译文和原创文本相比，哪些词用得特别多？”
- “这个子库的特征词是什么？”
- “A、B 两组作文用词有什么差别？”

## 步骤

1. 确定目标库与参照库。用户没说参照库时先问清楚，或用 corpora_list、subcorpora_list 列出可选项让用户选；不要自己挑参照库。
2. 计算关键词：stats_keywords，target 为目标范围，reference 为参照范围；measure 默认 ll，direction 用 both（同时看多用和少用）；min_freq 默认 3。用户点名指标（log ratio、%DIFF）时改 measure。
3. 检查分布：对排名靠前、用户关心的关键词，用 stats_frequency（目标范围，parts=document，dispersion=true）看 DP 和 range。DP 很高（集中在少数文档）的词要在回答中指出。
4. 看例句：对最值得讨论的 2–3 个关键词，用 corpus_search 取例句（查询式用 "词" 限定词形）。
5. 只比较几个指定词时，用 stats_keywords 的 items 参数，不跑全表。

## 工具与参数

- stats_keywords：target、reference、unit（word / lemma）、measure、direction、min_freq、items。
- stats_frequency：parts=document、dispersion=true。
- corpus_search：query、scope。

## 呈现

- KeywordTable：前 20 行，measure 与工具参数一致。
- 需要时 KwicTable 展示例句。
- 正文说明：目标库与参照库的名称和规模、排序指标、显著性校正方式（Bonferroni）。

## 口径与局限

- LL 表示差异是否显著，log ratio 表示差异大小；两者都来自工具，不自己换算。显著但 log ratio 很小的词差异不大。
- 两库规模差别很大时，低频词的 LL 不稳定，提醒用户关注 min_freq。
- 关键词集中在少数文档时可能只反映个别文本的话题，不代表整类文本。
- 结果依赖分词与词元化；中文分词错误会产生伪关键词。
- 只说明统计结果显示了什么，为什么多用由用户判断。
