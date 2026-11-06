---
name: translation-study
description: 译法研究。用户在平行语料中研究某个词或结构怎么译、有哪些译法、各译法占多少、译法随译者或年代如何变化时使用。
---

# 译法研究

## 适用问题

- “‘翻译’在英文译本里一般怎么译？”
- “这个词有几种译法，各占多少？”
- “不同译者的译法有什么差别？”

## 步骤

1. 确认是平行语料：corpora_list 中 parallel 为 true。不是平行语料时说明译法统计需要平行语料，停止。
2. 统计译法：stats_translations，query 为源语言一侧的查询式，scope 用源语言一侧；measure 默认 dice，min_freq 默认 2。记下 totals 中的 hit_sentences、aligned_sentences、unaligned。
3. 核对主要译法：对前 3–5 个译法，用 corpus_search 加 aligned 译文条件（`{op: "+", query: "\"translate\""}`）取例句并计数；需要时用 `op: "-"` 看不含该译法的句子（含与不含之和等于无条件计数）。
4. 看分布：用户关心译者、年代或体裁时，用 stats_distribution，field 为该元数据字段，加该译法的 aligned 条件，每种译法一次。
5. 需要命中词形本身的分解时，用 stats_breakdown（by=word 或 lemma）。

## 工具与参数

- stats_translations：query、unit、target_language、measure、min_freq。
- corpus_search：query、aligned。
- stats_distribution：query、field、aligned。
- stats_breakdown：query、by。

## 呈现

- TranslationTable：行的 search_query、search_aligned 原样复制，点击打开含该译法的例句。
- KwicTable：带 aligned 的例句。
- DistributionChart：各译法的分布。
- 正文写明命中句数、有对齐的句数与无对齐的句数。

## 口径与局限

- 统计单位是句对：译文句中出现某词，不等于它就是源词的译文；Dice 高只说明共现集中。看例句核对。
- 无对齐译文的命中句不进入统计。
- 零翻译、意译和结构转换无法由单词共现发现，需要抽样人工编码（sample_create，写操作需用户确认）。
- 只描述译法的数量与分布，翻译策略的解释由用户判断。
