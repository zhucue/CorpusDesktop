---
name: learner-error-analysis
description: 学习者偏误分析。用户研究学习者语料中的偏误类型、偏误比例、不同水平学习者的差异或作文的复杂度时使用；用抽样编码、偏误分布与文本指标。
---

# 学习者偏误分析

## 适用问题

- “这批作文里‘了’的偏误有哪些类型，各占多少？”
- “不同水平学习者的冠词误用比例有差别吗？”
- “高年级作文的词汇丰富度是否更高？”

## 步骤

1. 了解语料：corpora_get 读取元数据字段，找出学习者水平、母语、年级等字段。
2. 文本指标基线：stats_text_metrics，group_by 为水平字段，看各组的 STTR、MTLD、平均句长、平均依存距离。
3. 目标结构的分布：先用 corpus_search 确认查询式能找到目标结构并得到总命中数；再用 stats_compare（各水平一个子库或同一查询，by 为水平字段）或 stats_breakdown（by=meta:水平字段）看每百万词的分布。
4. 抽样编码（写操作，用户明确要求时）：sample_create，n 一般 100–200，固定 seed，label_set_name 用项目里的偏误标签集；没有合适的标签集时请用户先在标注页建。确认后由用户在标注页逐条编码。
5. 编码完成后：sample_summary 读取各偏误类型的比例、95% Wilson 区间与估计命中数；多人编码时用 annot_agreement 看一致性。
6. 需要看某句的偏误标注时，用 annot_spans 读取，再用 SpanView 呈现。

## 工具与参数

- stats_text_metrics：scope、group_by。
- corpus_search、stats_compare（items、by）、stats_breakdown（by=meta:<字段>）。
- sample_create：query、n、seed、layer_name、label_set_name。
- sample_summary：layer_id。
- annot_agreement：layer_id。

## 呈现

- 文本指标与分组汇总：短 Markdown 表格（只列用户关心的指标），注明 totals.notes 中为 null 的原因。
- 分布：BreakdownTable 或 CompareChart。
- 抽样汇总：短表格，列偏误类型、条数、比例、区间、估计命中数；estimate 写明“估计”。
- 单句偏误：SpanView。

## 口径与局限

- 抽样只覆盖查询式找得到的命中；查询式漏掉的偏误（如遗漏型偏误）不在样本里，提醒用户查询式的召回问题。
- 比例的分母是已编码且未拒绝的条数；区间宽说明样本不足。
- TTR 受文本长度影响，比较不同长度的作文用 STTR 或 MTLD；词数不足 100 的文档没有 STTR、MTLD。
- 平均依存距离依赖依存分析，学习者文本的分析错误率更高。
- 编码一致性未检验时，比例只是单人判断。
- 不推断偏误成因，由用户判断。
