# 语料检索、分析与标注研究平台重构设计

2026 年 10 月 27 日。本文件是平台重构后的设计基线，替代此前围绕"研究助手工作台"的方案。旧方案的问题见第二节，旧文档迁入 `doc/history/` 后仅供参考。

## 一 定位

面向高校外语、翻译和语言学研究生的网页平台，三块核心能力共用同一套语料数据：

| 能力 | 一句话说明 |
| --- | --- |
| 语料检索 | 参照 CCL 的用法：选语料库，输入查询式，直接看 KWIC 结果；也可输入一句话找语义相近的句子 |
| 统计分析 | 词频、n-gram、搭配、关键词、分布、文本指标、词汇等级、多项对比、Word Sketch，图表展示，可从数字回到例句 |
| 标注平台 | Agent 预标，人工在可视化界面校对；词性、依存、自定义片段、双语对齐 |
| 知识库 | 文献、术语表、标注规范和研究笔记的导入、整理与检索，供人和 Agent 使用 |
| Agent | 对话调用以上全部能力，回复中直接渲染表格、图表、句法树等组件 |

Agent 基于 Pi SDK，是系统内置能力，不以 Pi 产品形态出现。手动操作和 Agent 调用使用同一套后端接口。

## 二 对现有实现的审查结论

| 问题 | 事实 | 处理 |
| --- | --- | --- |
| 研究功能缺失 | 统计分析、双语对齐、标注没有任何生产代码；两条首版研究流程都走不通 | 重构后作为第一优先级 |
| 基础设施过重 | 14 个迁移约 52 张表，任务系统重复 4 套；Pi 宿主叠加租约 epoch、私有检查点、WAITING_JOB 接续、continuation_intent、143 项动作登记 | 全部去掉，见第十节 |
| 用户链路过长 | 查一个词要经过同步 → 索引 → 核准 → 发布 → 挂载 → 快照 → 首屏任务 → 完整任务 | 用户只接触"语料库"和"子库"两个概念 |
| 前端无设计 | `apps/web` 约 1400 行，67 行 CSS；设计文档描述的是 `tmp/ui-v5/` 静态原型，从未落地 | 前端重写，设计文档只描述真实页面 |
| 文档失衡 | README 和开发计划堆满验证数字；产品、技术文档各上千行并反复同步 Word | 新文档一份为主，README 压缩为说明与启动 |
| 仓库卫生 | 无任何提交；`tmp/` 482 项；根目录有误生成文件 | 先做初始提交存档，再清理 |

可复用的旧资产：Tatoeba 解析、CWB 建索引经验、`pipelines/alignment/` 对齐实验、登录与项目权限思路。作为参考，不直接沿用代码。

## 三 功能范围

### 首版

| 模块 | 内容 |
| --- | --- |
| 语料库 | 内置 Tatoeba 中英、UD 中英树库、维基中英子集；用户上传 TXT、DOCX、PDF（文字层）、CSV/TSV/XLSX/JSONL（列映射）、CoNLL-U、TMX，导入时按正文去重，规则见第四节"语料导入"；自动标注语言 zh、en、ja、fr、de、es、ru；文档级元数据（标题、语言、体裁、年代、来源、自定义字段）；按元数据筛出子库并保存 |
| 检索 | 类 CCL 查询式（第五节）；平行语料译文条件；KWIC 结果；上下文展开；排序、结果内筛选、随机抽样；保存查询；导出；从结果发起命中分解、译法统计与抽样编码；语义检索（输入一句话返回相近句，需先建语义索引） |
| 统计 | 频次与标准化频率、离散度（range、DP、DPnorm、Juilland D）、n-gram、搭配（含 MI3、z、ΔP）、关键词比较（含 %DIFF、odds ratio、log ratio 置信区间、Bonferroni）、命中频次分解、平行语料译法、元数据分布；文本指标（TTR、STTR、MTLD、词汇密度、平均句长、平均依存距离、Flesch）、词汇等级画像（内置 NGSL，可上传词表）、多项对比与历时（Mann-Whitney、Spearman）、Word Sketch 与近义词对比；整洁数据导出（每篇一行，带 codebook）；图表；点击任一数字回到例句；方法附录与参考文献 |
| 标注 | 分词与词性、依存句法、自定义片段与关系、双语句级和词级对齐；Agent 预标；人工校对；检索结果抽样编码（比例与 95% 区间）；按标注检索与统计 |
| 知识库 | 导入 PDF、DOCX、Markdown、TXT、网页；术语表；标注规范；研究笔记；混合检索；Agent 引用 |
| Agent | 对话调用全部工具；OpenUI 渲染结果组件；五个研究流程（Pi Skills：关键词分析、近义词辨析、译法研究、学习者偏误分析、方法章节）；会话按项目保存 |
| 成果 | 检索结果、统计表、图、标注数据、知识条目、整洁数据的导出：CSV、XLSX、JSON、CoNLL-U、SVG/PNG、DOCX |
| 账号与项目 | 邮箱登录；修改密码；项目成员角色；平台管理员维护内置语料并管理账号（新建、重置密码、停用 / 启用、设管理员）；设置页说明数据存放与发送到外部模型的操作；多人运营：模型用量记录与每人月度 token 上限、管理员跨项目视图（项目、任务、用量、审计、反馈、系统）、敏感操作审计、删除项目 7 天内可恢复、过期导出自动清理、站内反馈（第十节） |
| 全局交互 | 证据篮（任意页面钉住命中或数字，拖入笔记或导出）；命令面板 Ctrl+K（跳页面、切语料库、重跑保存查询、调用助手工具）；查询历史；全局任务托盘；快捷键提示浮层；深色模式；首次登录引导页；空态直接给"导入示例语料"等动作 |

### 二期

命名实体、句子与文档分类、更多内置语料、实时多人协作。

已提前完成：学习者偏误与翻译策略标签集模板、多人标注一致性与仲裁（P5）；语义检索（P10）。

### 不做

OCR、音视频、实时多人协同编辑、完整 CQL 语法暴露给用户、任意脚本执行。

## 四 核心概念与数据模型

用户只需要理解：**语料库**、**子库**、**标注层**、**知识库**、**项目**。

```text
项目
 ├─ 语料库（内置或上传）
 │    └─ 文档 ─ 句子 ─ 词
 │         └─ 标注层（系统 / 自动 / 人工）
 ├─ 子库（语料库 + 元数据筛选条件）
 ├─ 知识库
 │    └─ 文献 / 术语 / 规范 / 笔记 → 片段与向量
 ├─ 保存的查询、统计结果、图表
 └─ Agent 会话
```

| 表 | 关键字段 |
| --- | --- |
| users, projects, project_members | 角色 owner / editor / annotator / viewer |
| corpora | project_id（内置为空）、名称、语言、可见性、状态、索引版本、语义索引状态 `semantic` JSONB |
| documents | corpus_id、标题、语言、元数据 JSONB、正文对象路径、字数、正文哈希 `content_hash`（去重） |
| sentence_embeddings | sentence_id、corpus_id、384 维向量（HNSW，cosine）；语义检索，见第五节 |
| vocab_lists, vocab_entries | 词表（project_id 为空即内置、名称、语言、等级顺序、来源、许可）与词条（词、等级）；见第六节 |
| sentences | document_id、序号、起止码点 |
| tokens | sentence_id、序号、起止码点、词形 |
| subcorpora | project_id、corpus_id、筛选条件 JSONB、名称 |
| annotation_layers | project_id、corpus_id、类型（token / span / relation / alignment）、label_set_id |
| label_sets, labels | 标签名、颜色、说明、父标签 |
| annotations | layer_id、document_id、目标（token_id 或起止码点或两端 annotation_id 或双语两侧跨度）、label_id、属性 JSONB、source（system / model:名称 / human:user_id）、status（suggested / confirmed / modified / rejected）、revision、updated_by、updated_at |
| knowledge_bases, kb_documents, kb_chunks, kb_terms | 见第八节 |
| saved_queries, stat_results | 参数 JSONB、结果对象路径、subcorpus_id、索引版本 |
| agent_sessions, agent_messages | project_id、owner_id、Pi 会话文件路径、消息投影 |
| jobs | 唯一任务表：类型、参数、状态、进度、结果、错误、owner、project_id |
| llm_usage, audit_logs, feedback | 模型用量、审计日志、站内反馈；projects 另有 deleted_at（软删除）；见第十节 |

正文、索引、结果文件、Pi 会话文件存本地文件系统，数据库只保存路径。坐标统一使用正文 Unicode 码点，左闭右开。

### 语料导入

| 格式 | 一个文件产生 | 规则 |
| --- | --- | --- |
| TXT | 1 篇文档 | 编码自动识别：UTF-8（含或不含 BOM）、UTF-16（BOM 或按零字节判断）、GB18030 / GBK；CRLF、CR 统一为换行；空行去掉；不按分隔线拆分 |
| DOCX | 1 篇文档 | 正文段落（含标题）与表格单元格按文档顺序取文字，合并单元格只取一次；文本框、脚注、页眉页脚、图片不读；文档标题依次取第一个"标题"（Title）样式段落、文档属性标题、第一个"标题 1–9"段落，都没有时用文件名 |
| PDF | 1 篇文档 | 读文字层（与知识库同一解析），页之间换行；元数据加 `pages`，文件带作者时加 `author`；标题依次取 PDF 标题、第 1 页像标题的首行、文件名；没有文字层的扫描件失败"PDF 没有文字层（扫描件），暂不支持 OCR" |
| CSV / TSV | 每行 1 篇文档 | 上传时选择列映射（见下）；正文为空的行跳过；编码规则同 TXT |
| XLSX | 每行 1 篇文档 | 列映射同 CSV，另可选工作表（默认第一个）；表头为第一个非空行 |
| JSONL | 每行一个对象 = 1 篇文档 | 字段映射同 CSV；嵌套对象展开为点号键（如 `meta.year`），数组存为 JSON 文本 |
| CoNLL-U | 1 篇，或每个 `# newdoc` 1 篇 | 保留词形、词元、UPOS、HEAD、依存关系；多词符号按表层形式定位、空节点跳过、注释行忽略；自带分词，导入时不再自动标注，任何语言均可 |
| TMX | 每种语言 1 篇，句对对齐 | 语言取 `xml:lang`（1.4）或 `lang`（1.1），只取主代码；`<bpt>` `<ept>` `<ph>` `<it>` `<ut>` 去掉，其他行内标签保留文字 |
| Tatoeba | sentences / links 三件 TSV | 一次上传识别为平行语料 |

CSV / TSV / XLSX / JSONL 列映射：选择表格文件后显示前 5 行预览（CSV、TSV、JSONL 读取文件前 256 KB；XLSX 读整个文件，不超过 50 MB，超过时 413"XLSX 预览不超过 50 MB，可另存为 CSV 后上传"；XLSX 另显示工作表下拉，映射随工作表重置），设置正文列（必选，1–2 列；两列按表格列序以空行连接，如标题 + 摘要）、标题列、语言列和元数据列（默认其余全部列）。日期、年份等列作为普通元数据。默认值：正文取名为 text / content / body / sentence / abstract / 正文 / 内容 / 句子 的列（不区分大小写），没有则取前 200 行平均长度最长的列；标题取 title / headline / 标题；语言取 language / lang / 语言。映射对本批全部表格文件生效，存入导入任务参数，重试沿用；不经页面（API、Agent）上传时按默认值导入。

语言（2026 年 11 月 6 日，P10 起；契约 [contracts/p10.md](../contracts/p10.md) 第八节）：自动分词与标注支持 zh、en、ja、fr、de、es、ru。中文用 jieba；其他语言用 Stanza（tokenize、mwt（en、fr、de、es）、pos、lemma、depparse），标签集 UPOS + UD 依存。

| 情况 | 结果 |
| --- | --- |
| 上传时指定语言（或"自动"时语料语言）不在七种之内 | 422 `LANGUAGE_UNSUPPORTED`"暂不支持该语言：it（支持 zh、en、ja、fr、de、es、ru）"；全部为 CoNLL-U 文件时不拦（自带分词与标注，任何语言均可）；建语料库不拦 |
| TMX 或其他格式的文档语言不在七种之内 | 导入失败，列出语言码 |
| 自动识别（每篇取前 5 万字符，只看字母）：假名 > 5% → ja；西里尔 > 50% → ru；其他文字（韩文、阿拉伯文等；IPA 算拉丁）> 30% 失败；汉字 > 10% → zh（中文夹英文术语仍判 zh） | — |
| 拉丁文本：en、fr、de、es 各 30 个高频虚词，占词数比例最高者；最高的是 it、pt、nl | 导入失败"暂不支持该语言：it（…）" |
| 拉丁文本最高占比 < 3%，词数 ≥ 200，且变音字母 > 1% | 导入失败"未识别语言，请指定（支持 zh、en、ja、fr、de、es、ru）"；变音字母不超过 1% 时按 en（英文术语表、参考文献、音标等虚词少，沿用 P9 的处理） |

以上错误在任务详情与上传结果中显示（任务错误码 `LANGUAGE_UNSUPPORTED`）。

Stanza 模型首次用到某语言时下载到 `stanza` 卷，进度显示"下载 fr 模型"；下载或加载失败时导入失败 `MODEL_UNAVAILABLE`。下载前只刷新该语言在 `resources.json` 中的条目（Stanza 同一版本内会替换模型），临时文件用唯一名，并以文件锁防止多个容器同时写。每个 worker 同时最多保留 `STANZA_MAX_PIPELINES`（默认 2）个语言管线，中文依存算一个，按最近使用淘汰并释放内存；体积与内存见部署手册。

检索、统计、标注（词性、依存预标与校对）、KWIC 对七种语言可用；日文字串查询与中文相同（可跨分词边界）。术语抽取的词性模式只有 zh、en，语料含其他语言时抽取报错（可指定 zh 或 en 只抽取该语言）。

去重（P10）：导入时对每篇正文规范化（去首尾空白、连续空白合并为一个空格、NFKC）后取 sha256，存入 `documents.content_hash`。同一语料中已有相同哈希的文档、本批中重复出现的文档跳过；平行格式（TMX、Tatoeba）中同一对齐组的各语言文档全部重复才跳过，否则全组导入，不丢对齐。写入事务内锁定语料行，并发导入不会写入重复文档。任务结果记 `skipped_duplicates` 与前 20 个重复来源（文件名或"文件 #行号"）；全部重复且语料已有索引时不重建索引。存量文档的哈希由迁移 `0011` 补算。

解压上限（P11，`engine/parsers/limits.py`，语料导入与知识库共用）：DOCX / XLSX 解析前检查 zip 内声明的解压后总大小不超过 `MAX_UNPACKED_BYTES`（默认 500 MB）、文件数不超过 `MAX_UNPACKED_FILES`（默认 10,000）；Tatoeba 的 `.bz2` 边读边计解压字节，同一上限；PDF 不超过 `MAX_PDF_PAGES`（默认 5,000）页、抽出文字不超过 `MAX_UNPACKED_BYTES`。超过时失败"x.docx 文件解压后过大（超过 500 MB）"。

导入失败显示 `PARSE_ERROR` 和含文件名的原因（如"x.csv 缺少列：body""a.txt 无法识别编码"），语料列表与任务页均可重试；语料列表的重试重新执行该语料最近一次失败的导入或索引任务。

上传对话框（2026 年 10 月 28 日）：

| 项 | 规则 |
| --- | --- |
| 导入到 | 默认"新建语料库"并要求填写名称；选已有语料库时在下方显示"追加到「名称」· 已有 N 篇"与其状态 |
| 文件 | 关闭对话框（Esc、取消、上传完成）即清空已选文件；同名且同大小的文件再次选择时跳过并提示 |
| 语言 | 默认"自动（按内容识别）"：每篇文档（表格每行）按上方自动识别规则判定；也可指定七种语言之一。新建语料库选"自动"时，语料语言在导入完成后取文本量最大的语言 |
| 元数据 | 字段 + 值逐行填写（纯数字的值存为数值，如 2020；007、1,000 保留文本），缺字段名、字段重复时在该项下提示；"JSON"切换为 JSON 输入，嵌套值只能用 JSON |
| 完成提示 | 导入成功后提示"导入完成：N 篇，跳过重复 M 篇（a.csv #4、b.txt 等）"，最多列 3 个来源；没有重复时只写篇数 |
| 来源与许可（P11） | 可填许可、署名、来源链接（各有长度上限 200 / 2000 / 1000 字），写入语料 `meta`，语料页显示，导出来源行使用。新建语料随建库提交；追加到已有语料时作为上传表单字段 `source`（JSON `{license, attribution, source_url, version}`，填写的项写入、清空的项删除），格式不对 422 `INVALID_SOURCE` |
| 上传进度（P11） | 显示真实上传进度"已上传 x / y MB"，传完后"上传完成，正在创建导入任务"；上传中"取消上传"中止请求。取消或失败时，若语料库是本次新建的则删除这个空语料库 |

语料详情抽屉的上传页签、文档编辑使用同样的语言与元数据控件。

语料画像（建索引时写入语料 `meta`，旧语料由一次性回填或下一次重建索引补齐）：

| 字段 | 取值 | 用途 |
| --- | --- | --- |
| `tagset` | `upos` / `jieba` / `mixed` | 与检索引擎解析词性所用一致；语料列表"语言 · 词性"列与详情显示为 UPOS / jieba 词性 / jieba + UPOS；助手据此提示词性写法 |
| `script` | `simplified` / `traditional` / `mixed` | 只对中文文档抽样判定（约 3,000 句，按句 id 等距取自全库；只取前几千句时 Tatoeba 中英被误标为简体，复测 2026-10-28），按 69 组常用简繁对照字中繁体字形占比（≥ 85% 繁体，≤ 15% 简体，其余混合；对照字少于 5 个不记）；列表显示简体 / 繁体 / 简繁混合 |
| `languages` | 语言代码数组，按文本量从多到少 | 多语言（平行）语料显示为 zh-en（语料语言在前） |
| `indexed_at` | ISO 时间 | 列表"索引更新"列、详情"索引更新"显示相对时间，索引版本哈希只在悬停提示中出现 |

平行语料另记 `stats.pairs`（句对数），列表"文档"列与详情显示"N 句对"，悬停说明文档数（每种语言一个文档）。

语料列表：项目和内置语料都没有时才显示整块空态；有内置语料时不显示。删除按钮为图标，`aria-label` 为"删除语料库「名称」"，悬停提示"删除语料库"；文档表的编辑、删除图标同样带名称与提示。

文档详情：在语料详情的文档表点一行打开文档窗口，显示语言、句数与词数、全部元数据，以及按导入分句结果逐句列出的正文（每页 50 句，带句号）；平行语料每句下显示对齐的译文句。

更新中的语料（2026 年 10 月 28 日）：已有索引（状态为可检索或索引过期）的语料再导入或重建索引时，状态保持不变并显示"更新中"，旧索引继续服务检索、统计和范围选择（不置灰）；新索引建好后原子替换（CWB 注册文件 `os.replace`），状态回到可检索。更新失败时：导入失败语料不变，显示"上次更新失败：原因"并可重试；建索引失败或被取消则转为索引过期。没有索引的语料仍按 importing → indexing → ready。

## 五 检索

### 查询语法

参照 CCL 的使用习惯定义，后端编译为 CQP，用户输入不直接进入 CQP。

| 写法 | 含义 |
| --- | --- |
| `语言` | 字串，中文、日文按字符匹配，可跨分词边界；其他语言按整词 |
| `语言/n` | 词 + 词性；`/v` 表示任意动词 |
| `语言 文化` | 两词相邻 |
| `语言 $3 文化` | 中间最多 3 个词；`$2-5` 表示 2 到 5 个 |
| `语言\|语法` | 或 |
| `语言 +文化` | 同句须出现 `文化`，以 `语言` 为锚点计数 |
| `语言 -文化` | 同句不出现 `文化` |
| `"语言"` | 精确词形，不做字串扩展 |
| `*`、`?` | 任意词、任意单字 |
| `{dep=nsubj}` | 依存关系（有标注层时） |
| `[偏误:时态]` | 自定义标签片段（有标注层时） |

布尔只支持"主查询 + 同句条件"，不支持任意嵌套；界面显示"主查询 / 条件"。前端提供点选式辅助面板，生成同一查询式。

- `词/标签` 按当前语料的词性体系解析：UD 等 CoNLL-U 语料用 UPOS（`中國/PROPN`、`/n` 展开为 NOUN|PROPN），中文自动标注用 jieba（`/n` 覆盖 nr、ns 等，`/PROPN` 映射到专名标记）。插入面板的"词性"按钮列出该语料索引里实际出现的标签，并标明体系。Stanza 自动标注的语料（en、ja、fr、de、es、ru）与 CoNLL-U 语料一样用 UPOS，短标签按同一映射展开。
- 解析接口带上检索范围时（`POST /search/parse {query, scope}`），同时检查所需标注层：语料没有依存层时 `{dep=}`、没有片段层时 `[标签]`、没有词元时 `{lemma=}` 在解析行直接报错，检索按钮不可用；`POST /search` 对同样情况返回 422 `INVALID_LAYER`，不返回静默的 0 命中。
- 简繁通查（P11）：`POST /search` 的 `script_variants`（不传时按语料：语料语言或索引画像 `languages` 含 zh 即开启）。开启时查询式（主查询、`+` / `-` 条件与译文条件）中每个含汉字的词后面并列它的其他写法（OpenCC s2t、s2tw、t2s，`|` 并列、去重，如 `语言/n` → `语言/n|語言/n`）；引号中的精确词形、紧跟 `{…}` 或 `[…]` 的词不展开；展开后解析不通过时按原式检索。响应带 `script_variants` 与实际检索式 `searched_query`，分解、统计译法、抽样、导出沿用同一开关。转换库为 opencc-python-reimplemented（纯 Python，Apache-2.0）。
- 0 命中且查询含汉字、简繁通查关闭时，页面按简繁对照换写后再计数；对方写法有命中则提示"该库为繁体，试试「為」（n 次）"。语料的简繁取导入时记录的 `meta.script`。

### 结果

- 返回命中数、命中句数、命中文档数；总数未算完时显示"计算中"，不用已返回行数冒充总数。平行语料第三张计数卡显示"句对"而不是文档数（每种语言一个文档，文档数没有意义）；统计结果头同样写句对数。计数下方显示按年代或体裁的分布条，点击一段即筛选。
- KWIC 默认左右各 40 字符，可切换为整句、整段。左右语境等宽；40 字模式左侧被截处用省略号，不显示半个字形；英文等空格分词文本按整词截断（引擎端去掉窗口边缘的半个词，界面按词裁切）。整句、整段模式完整显示并换行，对齐译文同样换行。
- 平行语料（`corpus.parallel`）的语境只取命中所在句：相邻句子是互不相干的句对，40 字和整段模式都不越过本句；出处显示文档名与句号（"Tatoeba cmn · 句 747"），没有对齐译文的命中标"无对齐译文"；上下文面板默认只显示本句，前后句按需展开。
- 排序：出处、左语境、右语境、随机。
- 结果内筛选（P11）：输入的词作为同句条件追加到查询式（"含"为 `+词`，"不含"为 `-词`），对全部命中重新检索，查询式栏同步显示；清空后恢复原查询式。计数与直接输入同一查询式一致。
- 片段层高亮：KWIC 每页一次 `POST /search/span-marks {layer_id, sentences (≤ 200)}` 取本页各句的片段，不再每行一个请求。
- 双语语料的命中默认附带对齐句；上下文面板提供中英对照视图，词级对齐连线悬停高亮。
- KWIC 可开启词性着色，使用 8 色低饱和色板并附图例。
- 导出 CSV / XLSX，含出处、码点、元数据。导出在后台执行：点击后提示"已开始导出"，完成后自动下载并在提示中给出"下载"链接。P11 起导出读该检索已算好的结果集，只在没有结果集或索引版本已变时重算一次，不再每 1000 条重跑；文件开头一行写查询式、简繁通查后的检索式（与原式不同时）、范围（含临时筛选）、译文条件、命中 / 句 / 文档三项计数、排序（随机写种子）、导出时间（UTC）、索引版本，其后是来源与许可行；"句序"从 1 起，与界面"句 n"一致。
- 证据篮中的命中按句保存：服务端（`POST /projects/{id}/evidence`，手动钉住与 Pi 共用）根据文档与码点取命中所在句，`text` 为本句（命中词以 `**…**` 加粗）加每条对齐译文一行，`ref` 记录 `sentence_index`、`sentence`、`match`（句内码点区间）、`aligned`、`document_title`，出处为"文档 · 句 n · 语料库"；只给 `hit_id` 时从中解析文档与码点。同一命中（同一文档与码点区间，等价于同一 `hit_id`）或同一统计行（`stat_id` + `row_key`）在项目证据篮中只存一条：再次提交（检索页钉住、助手 `evidence.add`）返回已有条目并带 `existing: true`，页面显示“已钉”并提示“已在证据篮中”，助手说明“证据篮里已有”（复测 2026-10-28）。P11 起由数据库保证（迁移 `0013` 部分唯一索引：命中为项目 + 文档 + 起止码点，统计行为项目 + `stat_id` + `md5(row_key)`；写入 `ON CONFLICT DO NOTHING`），并发钉住同一命中只留一条。迁移先合并存量重复：保留最早一条，各条备注按时间拼接，指向被删条目的笔记引用改指保留的一条。证据篮、笔记引用和导出都用这份句子，不再保存 KWIC 窗口；DOCX 中命中词加粗，CSV / XLSX 列为原文、命中、译文、出处、查询式、备注。统计行证据显示为"「项」 方法 数值"。
- 证据篮清空（2026 年 11 月 5 日）："清空我钉的"只删除当前用户钉住的条目（`DELETE /projects/{id}/evidence?mine=true`，一次请求）；删除他人条目仍按单条删除权限（owner / editor）。超过 200 条时显示"显示 200 / 共 N"与"加载更多"。

计数、翻页与排序（2026 年 11 月 5 日）：

- 首次检索在 `SEARCH_COUNT_TIMEOUT`（20 秒）内完成时，返回首页与完整计数，并把过滤、排序后的完整命中行存为该 `search_id` 的结果集（`DATA_DIR/search-cache/`）；带 `search_id` 的翻页从结果集切片，不重跑 CQP。
- 超时时返回语料顺序的首页、`counts.complete=false`，并为该 `search_id` 启动唯一一次后台完整计数（`SEARCH_FULL_TIMEOUT`，默认 300 秒）；轮询只读状态。全进程最多 2 个后台计数同时运行，其余排队；同一用户同一认证方式同时 1 个，新的取消旧的；助手令牌（Bearer）与浏览器会话互不取消。
- 计数完成前 `sort=left|right|random` 按语料顺序返回并带 `sort_applied:false`，页面显示"排序在计数完成后生效"，完成后自动按所选排序重取当前页；`sort=position` 未完成时的切片与完成后一致。页面持续轮询到完成或失败，没有"继续计数"按钮和时长上限。
- 后台计数失败时 `counts.failed=true`，`message` 为固定文案之一：计数超时（300 秒）、命中过多（超过 `SEARCH_MAX_HITS`，默认 200 万）、计数失败请重试，以及同一用户同一登录方式发起新检索时的"计数已取消：已开始新的检索"；不显示内部错误。页面停止轮询并显示该文案。
- 结果集总字节上限 `SEARCH_CACHE_MAX_BYTES`（默认 2 GB），与条目上限（2000 条）一起按最近最少使用淘汰；api 启动时清空 `search-cache`。索引版本变化后旧 `search_id` 返回 409 `SEARCH_EXPIRED`。
- 契约见 [contracts/p7.md](../contracts/p7.md) 第一节。
- 纯属性与纯片段查询（P11，[contracts/p11.md](../contracts/p11.md) 第一节）：从 PostgreSQL 取完整命中行（文档码点），与 CWB 结果同样存为结果集、翻页切片、超时转后台计数；SQL 在 `statement_timeout`（同步阶段 `SEARCH_COUNT_TIMEOUT`，后台 `SEARCH_FULL_TIMEOUT`）下执行。后台计数期间纯属性查询的首页按语料顺序取（最多 5 秒），纯片段查询的首页等计数完成。KWIC 语境从当前索引的正文与句界读取（`cwb.DocText`），只读本页命中所在句及所需前后句，不读整篇；索引之后新增的文档才从正文文件读取。平行语料语境限在本句，与 CWB 路径一致。实测：Tatoeba 整库 `{pos=NOUN}` 380,100 命中完整计数 4.45–6.06 秒、中文侧 42,036 命中 0.39–0.44 秒，UD 中文 GSD 3 万命中 0.52 秒，翻页 0.03 秒；"说话"简繁通查 178 条、关闭 74 条。

译文条件（2026 年 11 月 6 日）：

- 平行语料可加"译文条件"：`POST /search` 的 `aligned: {op: "+" | "-", query}` 只保留对齐句（两个方向都取）中含（`+`）或不含（`-`）`query` 命中的命中。`query` 用同一查询式语法，按目标侧语言的标签集编译，只在目标语言一侧检索。
- 非平行语料返回 422 `NOT_PARALLEL`；译文条件解析错误返回 422 `QUERY_INVALID`，文案为"译文条件第 N 个字符：…"，页面定位到译文条件输入框；译文条件所需标注层缺失（422 `INVALID_LAYER`）同样以"译文条件第 N 个字符"开头。
- 计数、翻页、后台计数与结果集缓存同上，缓存键含 `aligned`；纯属性与纯片段查询（PostgreSQL 路径）也支持。译文条件查询的命中有上限，超出时返回固定文案"译文条件命中过多，请加条件"。
- 检索导出、分布统计接受同一 `aligned`。同一查询"含"与"不含"两次计数之和等于无条件计数。
- 页面地址参数 `aligned=<JSON {op, query}>`；统计译法行与助手链接用它打开带条件的检索。

结果栏工具（2026 年 11 月 6 日）：

| 入口 | 动作 |
| --- | --- |
| 分解 | 下拉：按词形 / 词元 / 词性 / 左一词 / 右一词 / 元数据字段；以当前查询与范围提交 `POST /stats/breakdown`，完成后跳到统计页结果（第六节）。分解不接受译文条件，有译文条件时按钮禁用，悬停"含译文条件时不可用" |
| 统计译法 | 仅平行语料；以当前查询与范围提交 `POST /stats/translations`（词形、Dice），完成后跳到统计页结果；有译文条件时同样禁用 |
| 抽样编码 | 计数完成后可用；选条数、随机种子、片段标签集（可新建）、层名，连同译文条件提交 `POST /projects/{id}/samples`，完成后跳到该层的抽样模式（第七节） |
| 导出整洁数据 | 下拉 CSV / XLSX；以当前范围与查询式提交 `POST /stats/tidy_export`（第六节），每篇文档一行 |

契约见 [contracts/p8.md](../contracts/p8.md) 第一、四、五节与第十节实现说明。

### 语义检索

2026 年 11 月 6 日，契约 [contracts/p10.md](../contracts/p10.md) 第六节，差异见其第十二节。检索页"查询式 / 语义"两种模式；语义模式输入一句话（≤ 500 字），返回范围内余弦相似度最高的句子（默认 50 句），命中范围为整句。

| 项 | 规则 |
| --- | --- |
| 向量 | 与知识库同一向量模型（本地 MiniLM 或远程，384 维）；`sentence_embeddings` 每句一行，HNSW 索引（cosine）。迁移 `0011` |
| 建索引 | `POST /corpora/{id}/semantic-index {language?}` → 任务 `embed_corpus`（长任务道），每批 512 句，进度按句，可取消；项目 owner / editor 可建，内置语料仅平台管理员，助手令牌不可建。可只建一种语言（如平行语料的中文侧）。句数上限 `SEMANTIC_MAX_SENTENCES`（默认 300,000），超过 422 `TOO_LARGE`；建立中再提交 409 `JOB_IN_PROGRESS` |
| 状态 | `GET /corpora/{id}/semantic-index`：未建 / 建立中 / 已建 / 已过期 / 失败，带已建句数、各语言句数、预计耗时（按上次实测速度，没有时按每秒 200 句）、是否可建 |
| 过期 | 建索引期间语料变化，或建完后重建语料索引时句数变化（文档增删），标记过期；改元数据不过期（范围筛选读实时元数据）；向量模型更换后也视为过期。过期索引仍可检索，页面提示重建 |
| 重建 | 重建期间旧索引继续服务；重建失败保留旧索引，显示"上次重建失败：原因"；没有可用旧索引时为失败 |
| 检索 | `POST /search/semantic {scope, text, top}` → `{items: [Hit + score]}`，范围筛选在 SQL 中；范围内已建向量 ≤ 5 万句时精确排序，更大时用 HNSW 迭代扫描（范围筛选后仍能取满 top）。未建 409 `SEMANTIC_NOT_READY`，模型已换 409 `SEMANTIC_MODEL_CHANGED`，向量模型不可用 503 `EMBED_UNAVAILABLE` |
| 结果 | 复用 KWIC 表（整句、出处带"相似度 0.83"），可看上下文、钉证据。切换范围后清空旧结果与上下文，输入的句子保留，重新检索才显示新范围结果（B03） |

实测（Tatoeba 中英第 1 批，16 核）：中文 45,703 句、英文 220,395 句，约 250–280 句 / 秒；只建中文侧约 3–5 分钟、约 160 MB，整库约 20–25 分钟、约 0.9 GB。

### 子库

子库是"语料库 + 元数据筛选条件"，保存后可直接选用。检索和统计都接受语料库或子库作为范围。两个子库可以做关键词比较。

## 六 统计分析

| 方法 | 内容 | 展示 |
| --- | --- | --- |
| 频次 | 原始频次、每百万词、文档频率；离散度 range、DP、DPnorm、Juilland D；按词形或词性 | 表 + 柱状图 |
| n-gram | 2 至 4 元，支持词性模式；可填“包含词”（`contains`，词形或词元等于该词的某一位置）只列含该词的组合 | 表 |
| 搭配 | 节点词 ±5 窗口，MI、logDice、t 值、LL、MI3、z、ΔP；可限定词性 | 表 + 搭配网络图（节点词居中，边粗为强度，点击进入检索） |
| 关键词 | 目标库对参照库，LL、log ratio 及 95% 区间、%DIFF、odds ratio、显著性与 Bonferroni 校正；正向 / 负向 / 双向；指定词对比；参照库可选内置或子库 | 表 + 散点 |
| 命中分解 | 一个查询的命中按词形、词元、词性、左一词、右一词或元数据字段分组计数 | 表 + 前 10 横向柱 |
| 译法 | 平行语料中命中句对齐译文里的词，共现句数、Dice、LL | 表 + 前 10 横向柱 |
| 分布 | 按元数据字段（年代、体裁、来源）或文档位置；平行语料可加译文条件 | 折线 / 柱状 |
| 标注统计 | 标签频次、标签共现、标注者进度与一致性 | 表 + 图 |
| 文本指标 | 每篇文档词数、句数、TTR、STTR、MTLD、词汇密度、平均句长、平均依存距离、Flesch 易读度与年级（英文）；可按元数据分组汇总 | 表 + 分组均值 ± SD + 箱线图 |
| 词汇等级 | 按词表等级统计词次、词种、覆盖率与表外词；整体、每篇或按元数据字段 | 表 + 堆叠柱 + 表外词表 |
| 对比 | 2–10 项（标签 + 范围 + 查询式）的命中与每百万词；可按元数据字段（年份、体裁）展开；Mann-Whitney、Spearman 检验 | 表 + 柱状 / 折线 |
| 词汇画像 | Word Sketch：节点词元按依存关系分栏列搭配词与 logDice | 分栏卡 |
| 近义词对比 | 两个词元在各关系栏的偏 A / 共同 / 偏 B 搭配 | 三列分栏 |

每个结果保存参数和索引版本；点击数字打开对应检索。图表用 ECharts，导出 SVG / PNG。文本指标、词汇等级、对比、词汇画像、近义词对比的接口与口径见下方"研究指标与口径 P1"。

统计口径与导出（2026 年 10 月 28 日）：

| 项 | 规则 |
| --- | --- |
| 标点与数字 | 频次、n-gram、搭配、关键词的 `exclude_punct` 默认开启（页面“排除标点和数字”默认勾选，接口与助手调用默认相同）：只由标点、符号、空白和数字组成的项（`，` `(` `1990` `3.5%`）不列出；n-gram 任一位置是这类项即不列出。总词数 N（`totals.tokens`）与每百万词、MI、LL 等指标仍按全部词计算，页面与导出写“N 词（含标点）”；频次另记 `totals.excluded_tokens`（被排除的词数） |
| 大小写（P11） | 频次、n-gram、搭配、关键词、命中分解、译法的词形与词元默认合并大小写（`case_sensitive` 默认 false，与检索不加引号时不区分大小写一致）：按小写比较，行显示范围内最常见的写法（同频时取小写），回到例句的查询式为各写法并列（`"The"\|"the"`），点回计数与该行一致；`case_sensitive: true` 时每种写法一行。统计页"区分大小写"开关；词性、中文与元数据不受影响。文本指标、词汇等级、Word Sketch 本就按小写，对比按检索口径计数 |
| 关键词参照 | 参照不能与目标相同（接口返回 422“参照与目标相同”）；目标与参照语料的 `meta.script` 一个简体、一个繁体时页面警告简繁字形会进入关键词前列。简繁归一未做 |
| 分布 | 页面要求填写查询式（接口仍允许不填，用于只看各区间词数）。回到例句：字段行的 `search_scope` 为 `{corpus_id, filter}`（原范围筛选加该字段值）；文档位置行另带 `position: {bin, bins}`，检索只保留落在各文档该等分区间内的命中，计数与该行一致，临时筛选标签显示"文档位置 10–20%"，可清除（B06）。`position` 只用于检索、解析和导出（导出表头写明区间），其他接口带它返回 422 `VALIDATION_ERROR`"文档位置区间只用于检索例句，请先清除临时筛选"；检索页带区间时分解、统计译法、抽样编码、导出整洁数据、计算分布与语义检索禁用，悬停说明"文档位置区间仅用于查看例句"。带区间的检索转后台计数时，计数完成前首页为空，完成后按区间命中分页（[contracts/p2.md](../contracts/p2.md) 第三节） |
| 范围 | 统计各标签页用项目共享范围（见前端设计第二节范围规则） |
| 导出 | CSV / XLSX 文件名“统计-方法-时间”；表格前依次写：统计方法与参数（n、单位、节点词、窗口、查询式、词性、包含词、排序指标、最低频次、显示前 N、是否排除标点和数字，词形 / 词元单位另写"区分大小写：是 / 否"）、范围与总词数（含标点）、参照与其总词数、索引版本与计算时间（UTC），然后是语料来源与许可行；小数保留 2 位 |
| 图表导出 | SVG 为合法 XML 文档，固定浅色主题、白底，与页面深浅色无关；PNG 由该 SVG 以 2 倍分辨率绘制 |

研究指标与口径（2026 年 11 月 6 日，契约 [contracts/p8.md](../contracts/p8.md) 第一至四节，差异见其第十节）：

命中分解 `POST /stats/breakdown {scope, query, by, top, min_freq, layers?}`：

| 项 | 规则 |
| --- | --- |
| by | `word` / `lemma` / `pos`（命中本身，多词以空格连接）、`left1` / `right1`（左右第一个词的词形，句首、句末记"（句首）""（句末）"）、`meta:<字段>`（无该字段记"（无）"） |
| 列 | 项、命中数 `hits`、占比 `pct`（占全部命中 %）、每百万词 `per_million`（以范围词数为分母）；`totals.hits` 为全部命中数 |
| 命中 | 取自与检索相同的路径，受 `SEARCH_MAX_HITS` 限制；全部命中数等于同一查询在同一范围的 `counts.hits` |
| 查询 | 单独一个 `{…}` 或 `[…]` 的查询返回 422；不接受译文条件 |
| 回到例句 | 词形行为精确词形序列（查询带词性时点回检索的计数可能大于该行）；词元行单槽且无条件时为 `{lemma=x}`，多词或带同句条件时用该词元在范围内各词形的选项式；词性行为 `/tag` 序列；左一词 / 右一词行为 `"左词" 原查询` / `原查询 "右词"`，计数与该行一致；元数据行同分布，用 `search_scope` 临时筛选 |

离散度（频次 `parts`、`dispersion`，默认 `document`、true）：

| 项 | 规则 |
| --- | --- |
| 部分 | `document` 每篇文档一部分；`segments` 按范围内语料顺序以词数等分 10 段；`field:<字段>` 每个字段值一部分，缺该字段的文档同时排除出 f 与部分词数（频次列仍计全范围） |
| 公式 | sᵢ = 部分词数 / 各部分词数之和；vᵢ = fᵢ / f；DP = ½ Σ\|vᵢ − sᵢ\|（Gries 2008），0 为均匀，越大越集中；DPnorm = DP / (1 − min sᵢ)（Lijffijt & Gries 2012）；Juilland D = 1 − CV / √(n − 1)，CV 为各部分相对频率 pᵢ = fᵢ / 部分词数的总体标准差 / 均值；range 为 fᵢ > 0 的部分数，range_pct = range / 部分总数 × 100 |
| 范围 | 只对显示的前 top 行计算；部分数 < 2 时这些列为 null；`totals.parts` 为部分数；PostgreSQL 统计单位（deprel、片段标签、关系标签）不支持离散度 |

效应量（关键词；a、b 为目标、参照频次，c、d 为两库词数）：

| 指标 | 公式 |
| --- | --- |
| %DIFF | (a/c − b′/d) / (b′/d) × 100（Gabrielatos & Marchi 2012） |
| odds ratio | (a′/(c − a′)) / (b′/(d − b′)) |
| log ratio 95% 区间 | log₂((a′/c)/(b′/d)) ± 1.96 × √(1/a′ + 1/b′) / ln 2（自然对数尺度的 SE 换到 log₂ 尺度；Hardie 2014） |
| Bonferroni | p = P(χ²₁ ≥ LL) × m，m = 目标与参照词型并集（`totals.types_compared`）；p < 0.05 / 0.01 / 0.001 记 `*` / `**` / `***` |
| 平滑 | 频次为 0 时 a′、b′ 取 0.5，行带 `values.smoothed`，页面在 %DIFF、odds ratio 旁标"平滑" |

- `direction`：positive（默认，目标多于参照，min_freq 作用于 a）、negative（参照多于目标，min_freq 作用于 b）、both。
- `items`（≤ 50）：只返回这些词，按给定顺序，忽略 min_freq 与 direction，用于单项两库对比。
- 排序按所选指标的绝对值（odds ratio 用 |ln OR|），positive 下与原排序一致；`measure` 可选 ll、log_ratio、pct_diff、odds_ratio。
- 搭配新增 MI3 = log₂(O³/E)（Oakes 1998）、z = (O − E)/√E、ΔP（Gries 2013）：`delta_p_node` = O/R − (C − O)/(N − R)，`delta_p_coll` = O/C − (R − O)/(N − C)；选 ΔP 时两列都输出，排序按 `delta_p_node`。

译法 `POST /stats/translations {scope, query, unit, target_language?, measure: dice|ll, top: 100, min_freq: 2, exclude_punct}`：

| 项 | 规则 |
| --- | --- |
| 适用 | 只用于平行语料，否则 422 `NOT_PARALLEL`；`target_language` 缺省为与命中句语言不同的一侧，语料没有该语言时 422 |
| 单位 | 以源侧句为单位：n = 命中句中有目标语言对齐句的句数；a = 其中对齐译文含该词的句数；N = 范围内有目标语言对齐句的源句数；b = 其中对齐译文含该词的句数。对齐取两个方向 |
| 指标 | Dice = 2a / (n + b)；LL 为 a、n − a、b − a、N − n − b + a 的 2×2 列联表；只列 a/n > b/N 的词 |
| 列 | 译文词 `item`、共现句数 `cooc`（= a）、占命中句 % `pct`、目标侧句数 `target_freq`（= b）、Dice、LL |
| totals | `hits`、`hit_sentences`、`aligned_sentences`（有对齐的命中句）、`unaligned`、`target_language`、`scope_aligned_sentences`（= N） |
| 回到例句 | 行带 `search_query` = 原查询与 `search_aligned: {op: "+", query: "\"译文词\""}`（词元单位为 `{lemma=…}`），点击打开带该译文条件的检索，命中句数等于该行共现句数 |

以源侧句计数的原因：Tatoeba 一句对多句，按目标侧句计时 2×2 表不自洽，点回检索的计数也对不上。

导出：统计导出另支持 DOCX（接口 `format: docx`）；DP、DPnorm、Juilland D、ΔP、Dice 保留 4 位小数，其余 2 位；译法行导出带译文条件。所有新指标与 `tests/golden/` 中的独立参考实现比对，误差 < 1e-6。

方法附录 `POST /projects/{id}/method-appendix {stat_ids?, searches?, layer_ids?, evidence?, style: gbt7714|apa}` → `{markdown, citations}`，`?format=docx` 返回 DOCX（宋体标题，无底色）：

- 只写实际用到的部分：语料（名称、语言、规模、来源、许可、版本、索引版本，子库写筛选条件与规模）；处理工具（jieba、Stanza 包版本、CWB 3.5.0、平台 `APP_VERSION`）；检索（查询式、范围、译文条件、三项计数、检索时间）；统计（方法、参数、指标公式与文献、totals）；标注与抽样（层、标签集、人数、条目数、一致性、抽样 n / seed / 总命中与编码结果，95% Wilson 区间）；参考文献。
- 参考文献为 `engine/methods.py` 中的静态表，GB/T 7714 或 APA，含 DOI，已联网核对，生成时不联网。
- `evidence: true` 时从证据篮收集统计行与命中的来源查询；文本条目忽略。
- 权限：项目 viewer 起可生成，助手令牌（Bearer）可用；引用其他项目的统计、层或范围返回 404，不写入附录。

研究指标与口径 P1（2026 年 11 月 6 日，契约 [contracts/p10.md](../contracts/p10.md) 第一至五节，差异见其第十二节）：

文本指标 `POST /stats/text_metrics {scope, metrics?, group_by?, sttr_window: 1000}`，每篇文档一行（列键 `words`、`sentences`、`ttr`、`sttr`、`mtld`、`lexical_density`、`mean_sentence_length`、`mean_dependency_distance`、`flesch_reading_ease`、`flesch_kincaid_grade`）：

| 项 | 规则 |
| --- | --- |
| 词 | 含字母或汉字的词；标点、符号、纯数字不算。词种按小写词形 |
| TTR / STTR | TTR = 词种 / 词数；STTR = 每 `sttr_window` 词一段的 TTR 均值，最后不足一段不计 |
| MTLD | McCarthy & Jarvis 2010，阈值 0.72，正反两遍取平均；剩余部分按 (1 − TTR) / (1 − 0.72) 计为部分因子 |
| 短文档 | 词数 < 100 的文档 STTR、MTLD 为 null；词数小于窗口时 STTR 为 null；`totals.notes` 写明篇数 |
| 词汇密度 | 实词 / 词数；实词为 UPOS NOUN、PROPN、VERB、ADJ、ADV，或 jieba 标签首字母 n、v、a、d（Ure 1971） |
| 平均句长 | 词数 / 句数 |
| 平均依存距离 | 全文所有有中心词的词 \|head − i\| 之和 / 依存数，不含根，标点计入；没有依存为 null（Liu 2008） |
| Flesch | 仅英文：易读度 = 206.835 − 1.015 × 词 / 句 − 84.6 × 音节 / 词（Flesch 1948）；年级 = 0.39 × 词 / 句 + 11.8 × 音节 / 词 − 15.59（Kincaid et al. 1975）。音节为小写词中元音组 [aeiouy]+ 的个数，多于一组且以 e 结尾时减 1（le 结尾不减），至少 1 |
| 分组 | `group_by` 时 `totals.groups` 为每个指标的 `[{value, documents, mean, sd}]`（样本标准差，不足 2 篇为 null），缺字段记"（无）" |

页面固定请求 `words`、`sentences` 两列，再加所选指标。

词汇等级 `POST /stats/vocab_profile {scope, list_id, by: corpus | document | <字段>}`：

| 项 | 规则 |
| --- | --- |
| 内置词表 | NGSL 1.2（Browne, Culligan & Phillips 2023，CC BY-SA 4.0，2,809 词，`engine/data/ngsl.csv`）。NGSL 没有官方分级，等级是本平台按 SFI 频率排名分的三段："频率排名 1–1000 / 1001–2000 / 2001–2809"。HSK、AWL 许可不明，不内置，由用户上传 |
| 上传 | `POST /projects/{id}/vocab-lists`（multipart：file、name、language，可选 source、license），项目 owner / editor，浏览器会话；文件为 UTF-8 CSV / TXT，每行 `词,等级`（也可用制表符），空行和 `#` 开头的行跳过，首行等级列为 level / 等级 / grade 时作表头；同一词重复时保留第一个等级。等级名都含数字时按自然顺序（HSK 1 … HSK 9），否则按出现顺序。`GET /projects/{id}/vocab-lists` 含内置；`DELETE /vocab-lists/{id}` 不能删内置（403）。迁移 `0012` |
| 匹配 | 英文等字母语言按小写词元（无词元用词形）；中文、日文按词形；NFC 规范化 |
| 列 | 每个等级与"表外"：词次、词种、词次覆盖率 %（词次 / 词数）；`by=document` 或字段时每行为各等级覆盖率与词数 |
| 回到例句 | 等级行为该等级在范围内出现的词形选项式（`"a"\|"b"`），超过 200 个词形或超过 1000 字时为 null；`totals.off_list` 为表外词前 100 个，各带查询 |
| 校验 | 词表语言与语料语言不一致时 422"词表语言与语料不一致" |

整洁数据导出 `POST /stats/tidy_export {scope, queries? (≤ 10), metrics?, format: csv | xlsx}` → 导出任务（`kind = export`、`source = tidy`）：

- 每篇文档一行，列为 `document_id`、`title`、`language`、`meta_<字段>`（蛇形命名，每字段一列）、`tokens`（含标点，每百万词的分母）、`sentences`，每个查询 `q{n}_hits`、`q{n}_pm`，`metrics=true` 时再加文本指标列。查询计数与检索相同（纯属性、纯片段查询走 PostgreSQL）。
- csv：zip，内含 `tidy_data.csv`（UTF-8 无 BOM，便于 R / pandas）、`tidy_data.codebook.csv`（column、description、unit、query）、语料有许可时 `source.txt`；xlsx：`data`、`codebook` 两个工作表（有许可时另加 `source`），标题宋体、无底色。
- 入口：统计页工具栏、检索页结果栏。

导出防公式注入：检索、统计、证据、整洁数据、标注层 XLSX 导出中，以 `=` `+` `-` `@`、制表符或回车开头的字符串前加 `'`。

对比 `POST /stats/compare {items: [{label, scope, query}] (2–10), by?, test: none | mann_whitney | spearman}`：

| 项 | 规则 |
| --- | --- |
| 不带 by | 每项一行：项、范围、查询式、命中数、词数（含标点）、每百万词、文档数、文档频率 %；恰两项时 `totals.comparison` 给 LL、log ratio 与显著性（同关键词公式） |
| 带 by | 行为字段值（缺字段的文档不计），列 `value`、各项 `hits_i`、`per_million_i`（该值的文档合并计）；行的 `searches` 为各项带字段筛选的检索 |
| 检验 | 每篇文档的每百万词为一个观测。Mann-Whitney（恰两项）：U、z、p、效应量 r = z / √n，正态近似，含结校正与连续性校正，同 SciPy `mannwhitneyu(method="asymptotic")`；Spearman（by 为数值字段）：每项 ρ、p、n，n < 3 或常量时为 null，同 SciPy `spearmanr`。纯 Python 实现，测试中与 SciPy 比对误差 < 1e-9 |
| 计数 | 与检索相同：纯属性查询（如 `{lemma=big}`）、纯片段查询走 PostgreSQL，其余走 CWB；超过 `SEARCH_MAX_HITS` 失败 |
| 范围 | 各项范围须在同一项目内（内置语料可与任何项目搭配），否则 422 |

Word Sketch `POST /stats/word_sketch {scope, lemma, pos?, layers?, min_freq: 2, top: 25}` 与近义词对比 `POST /stats/sketch_diff {scope, lemma_a, lemma_b, …}`：

| 项 | 规则 |
| --- | --- |
| 关系栏 | 主语（nsubj 类，节点为中心词）、宾语（obj、iobj）、修饰语与所修饰的词（amod、advmod、nmod、compound，两个方向各一栏）、并列（conj）、介词短语（obl / nmod 带 case 词，栏名如"with + N"）、作主语的谓词；`totals.relations` 列栏名 |
| 指标 | 每栏：搭配词、共现频次、该关系中搭配词频次、logDice = 14 + log₂(2 f(n,r,c) / (f(n,r,·) + f(·,r,c)))，· 为任意词，按关系计（Rychlý 2008）；`top` 为每栏条数 |
| 依存来源 | 依次取 `layers.dep`、索引中的系统依存（英文等 Stanza 导入，或中文依存预标时回填到系统层的依存）、该语料最近完成的依存预标层；都没有时 422 `NO_DEPENDENCIES`"该语料没有依存标注，请先在标注页建依存层"；统计页中文语料可选依存层 |
| 近义词对比 | 每栏两词元的搭配，列 `freq_a`、`freq_b`、`logdice_a`、`logdice_b`、`diff`（logDice 差，缺一方按 0）、`group`：a（只有 A 达到最低频次）、common（都达到）、b；按 a、common、b 显示，各组按差异最明显排序（a、common 按 diff 降序，b 按升序）。助手工具 `stats.sketch_diff` 给模型每组前 15 行并带 `side_totals`（各组全部行数）；对话中的 SketchDiff 卡按 `stat_id` 读正式结果显示全部行，偏 B 行回到 B 的例句；结果已删除、只能显示模型给的行时，少于 `side_totals` 合计则标"显示 n / 共 N"（B14） |
| 回到例句 | 从属词带依存关系（`"form"{dep=obj}` 或 `{lemma=x,dep=obj}`）加中心词词形的同句条件；这是同句近似，点回检索的计数可能多于该行 |

方法附录写入以上指标的公式（TTR、STTR、平均句长只写公式），文献补充 MTLD（McCarthy & Jarvis 2010）、词汇密度（Ure 1971）、依存距离（Liu 2008）、Flesch 1948、Kincaid et al. 1975、Mann & Whitney 1947、Spearman 1904、Word Sketch（Kilgarriff et al. 2004、2014）与 NGSL 2023，已联网核对。

## 七 标注平台

### 标注类型与可视化

| 类型 | 预标方式 | 校对界面 |
| --- | --- | --- |
| 分词 / 词性 | 中文 jieba（ICTCLAS 词性），英文 Stanza | 词下方标签，点选修改；可合并拆分词 |
| 依存句法 | Stanza（中文按 jieba 分词结果预分词后解析） | 弧线图，拖动弧线改 head，点击改关系 |
| 自定义片段与关系 | LLM 按标签集与规范预标 | 文本高亮，拖选新建，片段间连线建关系 |
| 双语对齐 | 句级：长度与向量相似度；词级：模型 | 左右两栏连线图，点线修改 |

### 流程

1. 建标注层：选类型、标签集、范围（语料库 / 子库 / 文档）。
2. 预标：后台任务；进度实时显示；结果 status = suggested。
3. 校对：按文档逐句进行；确认、修改、拒绝；键盘快捷键；显示剩余数量。Enter 只确认当前项、Shift+Enter 只整句确认；鼠标点过且仍保留焦点的那个按钮（如片段边界按钮）不接收 Enter / 空格，避免误改人工边界；用 Tab 或方向键移到的按钮、对话框关闭后焦点回到的按钮照常接收（B10）。
4. 完成：确认后的标注进入检索与统计；可导出 CoNLL-U、JSON、brat standoff、TMX。

### 规则

- 系统层（原始分词词性）、自动层、人工层分开存储；人工修改不覆盖自动结果，便于比较。
- 人工确认必须有具体用户和时间；Agent 不能把自己的输出标为 confirmed。
- 一个标注层可以有多个标注者；二期计算 Cohen's kappa 和 Krippendorff's alpha，并做仲裁。
- 标注规范存在知识库，预标时作为提示词的一部分。
- 标注层列表显示进度环；多人标注层显示一致性仪表（kappa）。
- 提供"AI 与人工差异视图"：同一句上下两行对比预标与人工结果，改动处高亮，并统计改动、确认、拒绝数。
- 多人层新建时默认不预标；勾选预标或对多人层点“预标注”时提示：每位标注者得到同一份模型建议，会影响独立标注和一致性。
- 片段 / 关系层的句子完成（2026 年 10 月 28 日复测）：一句对某位标注者算完成，须该人“整句确认”过（`sentence_reviews`），或该人在句中有行且没有一条仍是建议。未动过的句子不算完成，预标没给建议的句子也一样，需整句确认（未动过的句子也可点“整句确认”或 Shift+Enter）。多人层只看自己时按本人计；负责人 / 编辑不在标注者名单里时看全部，须名单上每位标注者都完成。句子列表“待办”、句子 `done` 和文档进度（`done` / `pending` = 未完成句数）用同一规则（`services/api/spans.py` `_open`）。原因：多人片段层建好未标注时句子全部显示“已完成”、待办 0（复测 R 其他发现）。
- 新建层与进度（P11，[contracts/p11.md](../contracts/p11.md) 第二节）：

| 项 | 规则 |
| --- | --- |
| 文档范围 | 全部文档 / 子库 / 指定文档。子库在建层时展开为文档（按语料顺序，上限 10,000 篇，超过 422 `TOO_MANY_DOCUMENTS`；子库为空 422 `EMPTY_SUBCORPUS`），层 `meta.subcorpus` 记子库 id 与名称；指定文档时按标题远程搜索，每次取 50 篇，滚动加载更多 |
| 模型调用估算 | `POST /projects/{id}/layers/estimate {kind, corpus_id, document_ids?, subcorpus_id?, …}` → `{documents, sentences, units, batch_size, model_calls, basis}`：片段层按句数、关系层按含两个以上基础片段的句数、词级对齐按源语句数，每批 10 句，`model_calls` = ⌈units / 10⌉；词性、依存与句级对齐不调用对话模型，为 0。估算不含失败批次的重试（失败批次再问一次，最多约两倍） |
| 对齐目标句 | `GET /layers/{id}/target-sentences?document_id=&start=&page_size=&q=`：按句序从 `start` 起分页（`page_size` ≤ 200，默认 100），返回 `{items, total, next_start}`；`q` 为数字时从该句号（从 1 起）开始列，为文字时只列含该文字的句子。不再只列前 5000 句 |
| 层进度 | 校对写入时增量更新 `layer.progress`（`Progress`，持层行锁），不再每次全表聚合；预标进行中每 20 批全量重算一次，预标结束、失败、取消时再全量重算。中文依存预标按块报进度，任务进度单位为句 |

- 一致性（2026 年 10 月 28 日）：严格 κ / α 以片段范围为单位（某人在该范围无片段记 ∅，页面写“未标注”）；重叠宽松版先按范围成组，再把与其他标注者片段重叠、且没有共同标注者的组合并（同标签优先，其次重叠最长，`engine.agreement.overlap_units`），同一标注者的嵌套片段不合并，因此范围完全一致时宽松值等于严格值，只有边界不同才被宽容。原实现把同一人嵌套的片段串成“主谓一致+时态”一个单位，QA 数据上宽松 κ 0.57 反而低于严格 0.61，已改。κ 校正机会一致，合并会改变边际分布，个别数据上宽松值仍可能略低于严格值，属正常。按标签 κ 附 n（至少一人给出该标签的单位数）。分歧接口另给 `target_text`（争议词）与 `marks`（句内码点区间）。

### 抽样编码

从检索结果随机抽取命中逐条人工编码，估计各类用法的比例（2026 年 11 月 6 日，契约 [contracts/p8.md](../contracts/p8.md) 第五节）。

| 项 | 规则 |
| --- | --- |
| 创建 | `POST /projects/{id}/samples {scope, query, aligned?, layers?, n: 1–500, seed?, layer: {name, label_set_id}}` → `{layer_id, sampled, total, seed}`，同步执行。按 `seed`（缺省随机生成并记录）从完整命中中等概率无放回抽 n 条，n 大于命中数时全取 |
| 完整命中 | 计数已完成时用后台结果集；未完成时同步计数，20 秒内算不完或命中过多返回 409 `SEARCH_INCOMPLETE`；零命中 422 `NO_HITS`；标签集须为片段标签集 |
| 层 | 新建单人片段层，`annotation_layers.meta.sample` 记录查询、范围、译文条件、n、seed、总命中与时间（迁移 0009）；每条抽中的命中建一个片段，`label = ""`（未编码），状态 suggested |
| 编码 | 选标签后确认或修改；拒绝表示不计入。未编码片段直接确认返回 422 `LABEL_REQUIRED`，修改后标签仍为空同样 422；整句确认跳过未编码片段。抽样片段只能拒绝不能删除；抽样层不能运行模型建议（422 `SAMPLE_LAYER`） |
| 不计入 | `label = ""` 的片段不进入标注统计、一致性、导出与 `[标签]` 检索 |
| 汇总 | `GET /layers/{id}/sample-summary` → `{total_hits, sampled, coded, rejected, seed, labels: [{label, name, count, pct, ci_low, ci_high, estimate}]}`；比例以已编码（不含拒绝）为分母，比例与区间为 0–1 小数；95% Wilson 区间（Wilson 1927）；`estimate` = 比例 × 总命中（四舍五入），页面与助手写明"估计" |
| 条目 | `GET /layers/{id}/sample-items` 按抽样顺序返回片段、文档名与所在句，供抽样模式使用 |
| 权限 | 创建同建标注层：owner / editor，助手令牌可创建并走写操作确认；annotator、viewer 403 |

### 标注导出

导出只含所选层（2026 年 10 月 28 日起）。菜单和文件内写明口径：

| 层 | 内容 | 格式 |
| --- | --- | --- |
| 词性 / 依存 | 已确认、已修改的词取人工值；未校对的词取系统层自动值（语料自带，或预标时写入的 jieba / Stanza 结果） | CoNLL-U：文件开头 `# 导出口径：…`；`# newdoc id` 为文档外部 id（UD 来源）或文档名，`# sent_id = 文档名-句号`（句号从 1 起，与页面“句 n”一致，空白写作 `_`，重名文档加 -2、-3）。JSON：同口径，词序号从 1 起 |
| 片段 | 已确认、已修改的片段；多人层为各标注者一致或已仲裁的片段 | brat standoff（只含片段，码点偏移，`annotation.conf` 首行写口径）、JSON、XLSX 统计 |
| 关系 | 已确认、已修改的关系，连同基础片段层的有效片段；端点片段本身未确认时随关系一并导出，brat 中加 `AnnotatorNotes`“端点片段未确认，仅作为已确认关系的端点导出”，JSON 中端点带 `"effective": false` 与其状态；关系不因端点未确认被丢弃 | brat standoff、JSON（关系的 from / to 内含片段范围与标签） |
| 对齐 | 已确认、已修改的对齐和未校对的导入句对；多人层为一致或已仲裁的结果 | TMX：`<header>` 内 `prop x-scope`（口径）、`x-source-format`（`x-source` / `x-target` 为“文档 id:句序号”，句序号从 0 起）、词级层 `x-word-alignment-format`（`i-j` 为源 / 目标词序号，从 1 起，与 CoNLL-U ID 一致；Pharaoh 从 0 起，换用时各减 1）。JSON |

JSON 顶层带 `scope`（口径行）、`offsets: "code points"`、`sentence_index_base: 0`，`layers` 只有所选层一项。多人层可选“另附各标注者原始标注”（`POST /layers/{id}/export {"format": "json", "annotators": true}`）：该层加 `annotators: [{annotator_id, email, rows}]`，rows 为每位标注者自己的全部行（含建议、拒绝、修改，以及 source、model_label），用于复核一致性和论文数据复现。

### 索引

词级层（词形、词性、词元、依存关系、head 偏移）写入 CWB 位置属性，确认批次后按需重建索引。片段和关系层存 PostgreSQL，按标签检索时先定位片段再和 CWB 结果取交集。

## 八 知识库

### 内容类型

| 类型 | 来源 | 结构 |
| --- | --- | --- |
| 文献 | PDF、DOCX、Markdown、TXT、网页 URL | 解析为段落片段，保留页码或标题路径 |
| 术语表 | 手工录入、从双语语料抽取、从文献抽取 | 术语、译名、定义、领域、例句（链接到语料证据） |
| 标注规范 | Markdown 编辑或上传 | 与标签集关联 |
| 研究笔记 | 页面编辑；Agent 草稿经人工保存 | 正文、引用的检索与统计结果 |

### 建设

- 导入：上传或粘贴链接，后台解析、分段、向量化；显示进度和失败原因。
- 自动整理：Agent 可从语料库抽取候选术语、为文献生成摘要、按主题归类；结果均为草稿，人工确认后入库。
- 关联：术语例句直接引用语料命中；笔记引用统计结果；规范关联标签集。
- 范围：知识库属于项目或个人；内置参考资料由管理员维护，对全体可见。

### 检索与使用

- 混合检索：pgvector 向量相似度 + PostgreSQL 关键词匹配，结果合并后返回片段及出处。
- 向量模型通过 OpenAI 兼容 `/embeddings` 接口配置，和对话模型同一配置方式。
- Agent 工具 `kb.search` 回答时引用知识片段，前端显示出处；`kb.save` 把当前结论写成笔记草稿。
- 术语表可导出 CSV / XLSX / TBX。

补充规则（2026 年 10 月 28 日，用户试用 QA）：

- 文献标题：上传时先用文件名，解析后若标题仍是文件名（网页仍是网址），改用文档自带标题：PDF 元数据标题（忽略 `about:blank`、`Untitled`、以 `.docx` 等结尾的占位值），否则第 1 页首段短标题；DOCX 核心属性标题，否则正文前的 Title / 标题样式段落；Markdown 首行标题。PDF 按行宽断段：短行（不足最宽行一半）或以句末标点结束且明显短于最宽行的行后另起一段。文献详情可编辑标题、作者、年份（`meta.author`、`meta.year`），供引用。
- 网页抓取：先用带联系地址的爬虫 User-Agent（维基等站点要求），返回 403 时换浏览器 User-Agent 重试一次；带 `Accept`、`Accept-Language`。
- 网页抓取安全（P11）：只接受 http(s)；每一跳只解析一次域名，全部地址不得是私网、回环、链路本地、CGNAT 或组播地址，然后直接连接检查过的 IP（保留 Host 头与 TLS SNI、证书校验按域名），DNS 重绑定拿不到第二个答案；重定向手动跟随（最多 5 次），每跳同样检查；不读取环境变量代理（`trust_env=False`），需要经代理出网的部署不能用网页导入；响应不超过 10 MB。
- 规范：新建规范先填名称（可选标签集）再创建；已导入的 Markdown / TXT 文献可"设为规范"（`PATCH {kind: "guideline"}`，正文取自原文件，片段不变）；多文件上传带 `kind=guideline` 时只收 Markdown / TXT，正文取自文件。
- 检索结果按相关度显示"高 / 中 / 低"，不显示原始分（RRF、ts_rank 跨模式不可比）：查询词全部出现或向量余弦相似度 ≥ 0.6 为高，部分出现或相似度 ≥ 0.45 为中，其余为低；低相关结果默认折叠为"另有 n 条低相关结果"。
- 笔记引用证据：`POST /kb/documents/{id}/refs` 是证据引用块的唯一写入方，每条证据一个块，格式固定为引文 + `—— 出处；查询式：…`。证据篮"加入笔记"只建空笔记（或选已有笔记）再逐条加引用，正文块数与"引用"数一致。同一笔记已引用的证据（同 `evidence_id`；没有时同引文与出处）不再建引用，接口返回已有引用并带 `existing: true`；正文仍含该证据块时不追加，正文已无该块（手动删去或编辑器插入尚未保存）时只补追加正文块（`appended: true`）。页面提示"已加入笔记「…」n 条，k 条已在笔记中，已跳过"，全部已在笔记中时提示"均已在笔记「…」中"。打开中的笔记没有未保存修改时，服务端版本更新（证据篮或助手追加）后编辑器直接换成新版本，不需刷新；有未保存修改时按下方版本冲突处理（B12）。编辑器内"插入证据"或从证据篮拖入单条证据时，页面把同格式的块放在光标或落点处，引用以 `append: false` 只记录不追加。
- 长文献（P11）：文献摘要与文献术语抽取把正文按约 1.2 万字分段（在段尾附近的换行处断开），最多读 20 段。摘要先逐段写要点，再合并为一段整体摘要（map-reduce）；结果写"按 N 段摘要"，超过 20 段时写"（全文 M 段约 x 字，只读取前 20 段约 y 字）"，不静默截断。术语抽取同样分段，结果记段数，超出 20 段时同样写明只读取了前 20 段。
- 笔记保存（P11）：笔记与规范正文修改后，向量重建在最后一次修改 30 秒后执行：已有排队的重建只把执行时间（任务参数 `not_before`）后移，不另排；worker 领取任务时跳过未到时间的。手动"重新导入"立即执行。保存（`PATCH /kb/documents/{id}`）带 `base_updated_at`（编辑器所依据的版本）；版本不符返回 409 `NOTE_CONFLICT`"笔记已被更新（他人编辑或助手 / 证据篮追加），请载入最新版本后合并"，不写入。不带版本号的追加（助手、证据篮加引用）不检查。冲突时页面暂停自动保存，提供"复制本地内容"与"载入最新版本"。
- 术语抽取：结果说明跳过原因（术语表中已有的词，列出前几条）与候选池大小（范围内没有出现 2 次及以上的词性模式组合时直接说明）；对话模型整理时术语原文优先用语料主语言的候选；抽取出的术语附 1 条范围内的语料例句（平行语料用对齐句，其余按术语文本查句，最多查 100 条）。TBX 定义放在所写语言的 langSec；CSV / XLSX 列为 术语、语言、译名、译名语言、定义、领域、例句、来源、状态，来源写"手工 / 语料 / 文献 / 模型"。

## 九 Agent 与 OpenUI

### 架构

```text
浏览器 ──SSE──▶ agent 服务（Node + Pi SDK） ──HTTP + 用户令牌──▶ api（FastAPI）
                        │
                        └──▶ 模型服务（OpenAI 兼容）
```

- 浏览器经同源 `/agent/` 访问 agent 服务。FastAPI 为登录用户签发短期令牌，agent 服务用它调用业务接口，权限仍由 api 判断。
- 会话属于项目；Pi SessionManager 持久化会话文件，数据库保存索引和消息投影。
- 运行状态只有 queued、running、succeeded、failed、cancelled。
- 长任务：工具提交后台任务并在限定时间内等待；超时则返回任务编号，由用户在任务面板查看。不做跨进程自动接续。
- 模型请求重试（P11）：用 Pi 自带的重试，最多 2 次，覆盖 429、408、409、5xx 与连接错误，等待服务端 Retry-After（超过 60 秒直接失败并写明等待时间），否则按 Pi 退避（0.5 秒、1 秒）。Pi 只在拿到响应头之前重试，流式输出中途断开不重试，前端不会收到重复文本；Pi 不能对超时关闭重试，一条消息最坏等待 3 × `MODEL_TIMEOUT_MS`。用量按实际作答的那次请求记一次。
- `corpus.parse` 不带范围时按会话范围的语料解析（词性体系、可用标注层），与检索一致。
- 页面上下文（2026 年 11 月 5 日）：助手抽屉发出的每条消息带 `context`（page、label、scope；检索页另带查询式、`search_id` 与选中的 `hit_ids`，最多 20 个）。agent 把它写成一行"[当前页面：…]"附在本轮用户消息前，模型可见、界面不显示，另存入该消息的 `context` 字段；重新生成沿用原上下文。会话范围与页面范围不同时，抽屉顶部显示"会话范围：A；当前页面：B"与"按当前范围新对话"，不自动切换。输入框提示"针对当前结果提问"只在带查询式时显示，否则为"针对「范围名」提问"。

### 工具

共 53 个，界面按能力分组、显示中文名（`apps/web/src/components/global/tools.ts`）；带 * 的是写操作。

| 分组 | 工具 |
| --- | --- |
| 语料与检索 | corpora.list、corpora.get、corpora.documents、subcorpora.list、subcorpora.create*、corpus.parse、corpus.search、corpus.context、corpus.sentence、search.semantic |
| 统计 | stats.frequency、stats.ngrams、stats.collocations、stats.keywords、stats.distribution、stats.breakdown、stats.translations |
| 研究统计 | stats.text_metrics、vocab.lists、stats.vocab_profile、stats.compare、stats.word_sketch、stats.sketch_diff |
| 词性与依存标注 | annot.layers、annot.create_layer*、annot.sentence、annot.diff、annot.stats、annot.suggest*、annot.export* |
| 片段与对齐 | annot.spans、annot.suggest_spans*、align.pairs、align.suggest*、annot.agreement、sample.create*、sample.summary |
| 知识库 | kb.search、kb.terms、kb.documents、kb.save*、kb.extract_terms*、kb.summarize* |
| 证据与导出 | evidence.add*、evidence.list、queries.save*、queries.list、export.create*、export.tidy*、methods.appendix |
| 研究流程 | skills.read |
| 任务 | jobs.get、jobs.cancel* |

每个工具对应一个 api 接口，用 Pi `customTools` 注册；新增业务能力时同步注册工具。

研究能力工具（2026 年 11 月 6 日，契约 [contracts/p8.md](../contracts/p8.md) 第七节）：stats.breakdown（命中分解）、stats.translations（译法）、methods.appendix（方法附录，返回 markdown，不生成文件）、sample.create（抽样编码，写操作确认）、sample.summary（抽样汇总）；stats.frequency 接受 `parts` 与 `dispersion`，stats.keywords 接受 `direction`、`items` 与新排序指标，stats.collocations 接受 mi3、z、delta_p，stats.distribution 与 corpus.search 接受 `aligned`。系统提示增加"统计与方法"：整范围词表与离散度用 stats.frequency，一个查询的命中构成用 stats.breakdown，译法用 stats.translations，某种译法的例句用 corpus.search 加译文条件；效应量、区间、离散度、比例与估计命中数只取工具结果，不自行换算，估计值注明"估计"；只说明统计结果显示了什么，不代写研究结论，方法部分给出 methods.appendix 原文。

研究能力工具 P1（2026 年 11 月 6 日，契约 [contracts/p10.md](../contracts/p10.md) 第九节）：stats.text_metrics（文本指标）、vocab.lists（列出项目可用词表，含内置）、stats.vocab_profile（词汇等级）、stats.compare（多项对比与检验）、stats.word_sketch、stats.sketch_diff（近义词对比）、search.semantic（语义检索，语料须已建语义索引）、export.tidy（整洁数据导出，写操作确认）。工具描述写明适用问题。

研究流程（Pi Skills）：`services/agent/skills/` 下五个 Markdown 文件，每个写适用问题、步骤、调用的工具与参数、结果呈现与口径局限。

| 流程 | 用途 |
| --- | --- |
| keyword-analysis | 关键词分析：两类文本的显著多用 / 少用词 |
| synonym-comparison | 近义词辨析：Word Sketch + 近义词对比 + 例句 |
| translation-study | 译法研究：译法统计 + 译文条件 + 分布 |
| learner-error-analysis | 学习者偏误分析：抽样编码 + 偏误分布 + 文本指标 |
| methods-section | 方法章节：方法附录 + 结果描述草稿，数字只来自工具，不写结论 |

agent 用 Pi `loadSkillsFromDir` 加载，Pi 在系统提示中列出流程名称与说明；模型用 `skills.read`（以 Pi `read` 工具名注册，覆盖 Pi 自带的读文件工具）按名称读取流程，只能读这五个已加载的文件。agent 镜像复制 `services/agent/skills`。

### 写操作确认

- 用户只要求查看、检索、统计、展示时，助手只用读取类工具；写操作只在用户明确要求该动作时提出，范围只覆盖用户所说（“这篇文档”只传这篇）。原因：试用中只读请求“用依存树展示 UD 中文 GSD 的第 1 句”触发在整库上建依存层并预标 111,279 个词，“给我看三条例句”自行加入证据篮（QA Q65、Q19）。
- 写操作一律先确认：模型调用写工具时不执行，返回 `NEEDS_CONFIRMATION` 与说明（标题 + 若干行：语料库、文档数、规模、标签集等），界面显示确认卡片“执行 / 取消”；用户点执行后由 agent 服务按卡片上的参数原样执行，再请模型简述结果。取消后下一条消息告诉模型，除非用户再次要求不再提出。协议见 [contracts/p2.md](../contracts/p2.md) 第十二节。
- 助手不在内置语料上建标注层（提出前即报 `BUILTIN_CORPUS`）；用户可在标注页自己建层。只读的依存或词性展示先用项目里已有的 dep 层（`annot.sentence`，含人工校对）；没有层时用 `corpus.sentence` 读取语料自带的系统标注（`GET /corpora/{id}/documents/{doc}/sentences/{n}`，返回每个词的 index、form、pos、lemma、head、deprel，不需要层），再用 DependencyTree 呈现；系统标注也没有依存时才说明。原因：复测中“用依存树展示 UD 中文 GSD 的第 1 句”答“该语料没有依存标注层”，而 UD 自带依存。
- 建议类写入（标注、片段、对齐建议）确认后仍是待人工确认的 suggested，确认权在标注页。

### 内部 ID

- 回答正文和思考中不写内部 ID（search_id、stat_id、hit_id、job_id、layer_id、document_id、chunk_id、term_id、corpus_id 等、任何 UUID）；ID 只出现在工具参数与组件参数里，正文用语料库名、文档标题、“第 N 句”、统计方法与节点词、层名。
- 工具结果摘要（步骤行、右栏引用）用中文方法名与状态，不含 ID；前端对正文、思考与步骤再做一次过滤（`scrubIds`），去掉漏出的“xxx_id: …”、UUID 和长十六进制串。
- 思考要求用中文、围绕研究问题、不引用规则，提到工具只用能力名称；推理模型仍可能写出工具名，前端把思考中的工具名（`corpora_list`、`stats.collocations` 等）换成中文能力名（`toolNamesToTitles`），过滤只保证不露 ID 与工具名。

### OpenUI

- 前端注册组件库（19 个）：KwicTable、FreqChart、CollocationTable、KeywordTable、DistributionChart、EvidenceCard、JobStatus、Callout、DependencyTree、AnnotationDiff、TermCard、KbCitation、SpanView、AlignmentGraph、BreakdownTable、TranslationTable、WordSketch、SketchDiff、CompareChart。BreakdownTable 显示项、命中数、占比、每百万词；TranslationTable 显示译文词、共现句数、占命中句 %、所选指标，行点击带 `search_aligned` 打开检索。WordSketch 按关系分栏列搭配词、频次、logDice；SketchDiff 为偏 A / 共同 / 偏 B 三列；CompareChart 为对比带 by 时的多系列折线或分组柱（每百万词）；KwicTable 增加 `mode: semantic`，行带相似度 `score`。行点击均回到检索。
- 组件说明自动生成后写入 Pi 系统提示词；模型回复输出 OpenUI Lang，agent 服务流式转发，前端用 OpenUI React 渲染器绘制。
- 模型只能使用已注册组件，不执行生成代码。组件内的"打开完整结果""保存为笔记"等操作调用普通接口。

### 扩展方式

新增能力：注册新工具；新增可视化：在组件库加组件；新增研究方法：加 Pi Skills 或提示词。三者都不改架构。

## 十 技术架构

| 服务 | 技术 | 职责 |
| --- | --- | --- |
| web | React + TypeScript + Vite，Ant Design，ECharts，OpenUI React | 页面与交互 |
| api | FastAPI + SQLAlchemy + Alembic | 权限、业务接口、查询编译、统计计算、任务入队 |
| worker | Python；PostgreSQL 队列（`FOR UPDATE SKIP LOCKED`） | 导入解析、CWB 建索引、预标注、向量化、导出 |
| agent | Node.js + Pi SDK | 会话、工具调用、OpenUI 流 |
| postgres | PostgreSQL 16 + pgvector | 全部结构化数据与向量 |
| 模型服务 | 外部 OpenAI 兼容接口 | 对话、预标、向量 |

去掉 RabbitMQ、Celery、S3 对象存储和多套任务账本。文件存本地卷。Docker Compose 一键启动，单机部署。

NLP：中文分词与词性用 jieba（固定词典、关闭 HMM），英、日、法、德、西、俄文分词词性依存与中文依存用 Stanza（包版本随 worker 镜像固定，模型首次使用时下载到 `stanza` 卷，见第四节"语料导入"）。CWB 安装在 api 与 worker 镜像。

### 权限

| 角色 | 权限 |
| --- | --- |
| owner | 项目全部权限，管理成员 |
| editor | 上传语料、建子库、建标注层、编辑知识库、上传词表、建语义索引 |
| annotator | 标注校对、检索、统计 |
| viewer | 检索、统计、查看标注与知识库 |
| 平台管理员 | 维护内置语料与参考资料；管理账号，可见全部账号及各账号项目数；可见全部项目（名称、负责人、成员与语料等数量、占用空间，含已删除）、全部任务、模型用量、审计、反馈与系统状态；可改派项目负责人、恢复已删除项目、取消任何任务；不读取项目私有内容。管理接口 `/admin/*` 只接受管理员的浏览器会话，助手令牌 403 |

内置语料记录许可和署名；导出时带署名。

项目（2026 年 10 月 28 日）：负责人可改名（`PATCH /projects/{id}`）和删除项目（`DELETE /projects/{id}`，仅浏览器会话）；删除前确认框列出将一并删除的语料库、标注层、笔记、文献与规范、术语和成员数（`GET /projects/{id}/usage`），并写明"7 天内可由负责人或管理员恢复"；删除与清除规则见下方"项目删除与恢复"。任何成员可从项目设置"新建项目"进入引导创建新项目。被移出或项目已删除时（项目接口 404），整个项目界面换成"你已不是该项目成员"页，列出用户的其他项目和"新建项目"入口，不再显示各页的 NOT_FOUND 报错。

删除语料与文档（2026 年 11 月 5 日）：确认框先取 `GET /corpora/{id}/delete-impact` 或 `GET /documents/{id}/delete-impact`（权限同删除），列出将删除的文档数与句数、各标注层的人工条目数、引用这些句子的证据条数与笔记引用条数。人工条目指 status 为 confirmed、modified、rejected 的条目，词性依存校对、片段、关系、对齐都计。有人工条目时须勾选"我确认删除这些人工标注"才能删除。证据与笔记引用不级联删除，删除后无法回到原句；其余级联行为不变。

账号（2026 年 11 月 5 日）：

- 平台管理员在设置页"用户"标签管理账号（`/admin/users`，仅管理员的浏览器会话，助手令牌 403）：按邮箱或姓名搜索；新建账号返回一次性 16 位临时密码；重置密码；停用 / 启用；设为 / 取消管理员。不能停用自己；不能停用或撤销最后一个可用管理员（409 `LAST_ADMIN`）。命令行 `scripts/create_account.py --reset` 同样可重置。
- 新建与重置后 `must_change_password=true`：登录后只进入改密页；后端除 `/auth/me`、`/auth/password`、`/auth/logout` 外返回 403 `PASSWORD_CHANGE_REQUIRED`，agent 服务同样拒绝。重置与停用吊销该用户全部会话与助手令牌。
- 停用账号登录返回 403 `ACCOUNT_DISABLED`（"账号已停用，请联系管理员"），已有会话下一次请求 401。登录成功记录 `last_login_at`。
- 修改密码 `POST /auth/password`：新密码 12–1024 字符且不同于原密码；成功后吊销本人其他会话与助手令牌，保留当前会话；助手令牌（Bearer）调用拒绝；与登录共用 nginx 限流。
- 数据：迁移 `0008_account_lifecycle` 给 `users` 加 `disabled_at`、`must_change_password`、`last_login_at`。
- 查找账号（P11，加成员用）：`GET /users?email=&project_id=` 必须带 `project_id`，只有该项目负责人的浏览器会话可调用（助手令牌 403）；每人每分钟最多 20 次，超出 429 `RATE_LIMITED`"查找过于频繁，请一分钟后再试"；只做精确匹配（去首尾空白、小写），不存在时返回空列表 `{items: []}`，存在时 `{items: [{id, email, display_name}]}`，不返回 `is_admin`。

数据去向（2026 年 11 月 5 日）：设置页"数据与隐私"列出数据存放（本机 PostgreSQL 与 Docker 数据卷）、管理员可见范围（2026 年 11 月 6 日起：全部用户、项目名称与负责人、各项目磁盘占用、全局任务、模型用量、审计记录与反馈；不通过界面读取他人项目内的语料、标注与知识库内容）、会把文本发给外部模型的操作（助手对话、LLM 片段与关系预标、对齐候选（选用模型时）、文献摘要、术语抽取）与当前模型主机、知识库向量化在本机还是远程、版本号；备份由部署方决定。LLM 预标、文献摘要、术语抽取的确认处各写一行"将把所选句子 / 文献文本 / 候选术语列表发送到 {host}"。模型只在 `deploy/.env` 配置，界面经 `GET /system/info` 只读显示（版本、模型主机与模型名、向量模式与主机），不做在线配置。

用量与限额（2026 年 11 月 6 日）：

- 记录：每次调用对话模型写一行 `llm_usage`（用户、项目、来源、模型、提示 / 生成 / 总 token、任务或会话）；重试时只在成功作答后记一次。agent 服务每轮模型调用记一行（`source=agent`）；worker 的模型调用按任务类型记（预标、对齐、文献摘要、术语抽取），用户为任务发起人。token 取模型响应的 `usage`，没有时按字符数 / 2 估算，来源后加 `:estimated`。Pi 自动压缩上下文时的摘要调用不计入。
- 限额：`LLM_MONTHLY_TOKENS_PER_USER`（0 为不限）。用户当月总 token 达到上限后，以下操作在发起时返回 429 `LLM_QUOTA_EXCEEDED`"本月模型用量已达上限（N token），请联系管理员"：助手新消息、重新生成、确认执行写操作；LLM 片段 / 关系预标、模型词级对齐预标；文献摘要；文献或模型术语抽取；以及这些任务的重试。已在运行的不中断。自然月按服务器时区（`TZ`，compose 默认 Asia/Shanghai）。
- 并发：每个用户同时运行的助手对话最多 `AGENT_MAX_RUNS_PER_USER`（2）个，超出返回 429 `TOO_MANY_RUNS`。
- 查看：`GET /me/llm-usage`（本月总量、上限、按来源）在设置 · 账号显示；`GET /admin/llm-usage?month=&group=user|project` 在管理 · 用量显示。

审计（2026 年 11 月 6 日）：`audit_logs` 记录登录、登录失败（记邮箱）、改密与重置、新建 / 停用 / 启用账号、设 / 撤管理员、成员增删与改角色、项目删除 / 恢复 / 清除 / 改派负责人、删除语料库 / 文档 / 子库 / 标注层 / 文献、管理员取消任务。与业务操作同一事务写入；`target_name` 记删除前的名称；`ip` 取 nginx 追加的 `X-Forwarded-For` 最后一项。管理员在管理 · 审计按操作人、操作、项目、日期筛选（`GET /admin/audit`）；项目负责人在设置 · 项目看本项目条目（`GET /projects/{id}/audit`）。不清理。

项目删除与恢复（2026 年 11 月 6 日）：

- `DELETE /projects/{id}`（负责人，浏览器会话）只设 `deleted_at`，不删数据与文件，并取消该项目排队与运行中的任务。之后该项目对所有接口如同不存在（404，含助手令牌），不出现在项目列表与助手会话列表；成员看到"你已不是该项目成员"页。
- 恢复：负责人在设置 · 项目"最近删除"（`GET /me/deleted-projects`）、管理员在管理 · 项目恢复（`POST /projects/{id}/restore`）；超过 `PROJECT_PURGE_DAYS`（7）天返回 410 `PURGED`。
- 清除：超期项目由维护任务硬删除（数据库级联、语料、知识库、上传与导出文件），记审计 `project_purge`。
- 改派负责人：`POST /admin/projects/{id}/owner`，目标用户不是成员时加入，原负责人降为 editor；不能改派给已停用账号。

维护任务（2026 年 11 月 6 日）：worker-light（`WORKER_MAINTENANCE=1`，worker 上为 0）后台线程在启动时与每小时检查 `DATA_DIR/maintenance/last-run`，超过 24 小时即执行：清除超期删除的项目；删除 `EXPORT_RETENTION_DAYS`（30）天前成功导出的文件（之后下载返回 410 `EXPORT_EXPIRED`"导出文件已过期，请重新导出"）；删除上传目录，条件是引用该目录的任务全部结束、其中有失败或取消的，且最晚结束时间早于保留期限。结果写 worker 日志一行；某步失败不影响其他步骤，次日重试。

安全与可靠性（P11，[contracts/p11.md](../contracts/p11.md) 第三节）：

| 项 | 规则 |
| --- | --- |
| 解压上限 | 语料与知识库的 DOCX / XLSX / PDF / bz2 解析前检查，`MAX_UNPACKED_BYTES`（500 MB）、`MAX_UNPACKED_FILES`（10,000）、`MAX_PDF_PAGES`（5,000），超过失败"文件解压后过大"（第四节） |
| 网页导入 | 每跳解析一次并按检查过的 IP 连接，重定向逐跳检查，不走环境变量代理（第八节） |
| 账号查找 | `GET /users` 仅项目负责人、限流、精确匹配（上方"账号"） |
| worker 模型请求 | 预标、对齐、摘要、术语抽取的模型调用遇连接错误、429、5xx 最多重试 2 次，等待 2 秒、6 秒，服务端给 Retry-After 时按它（最多 60 秒）；等待中任务可取消（1 秒内停止）；读超时（300 秒）不重试；仍失败时任务错误写实际原因（"对话模型返回 HTTP 503：…"） |
| agent 模型请求 | Pi 自带重试，见第九节"架构" |
| 任务列表 | 发起人、语料、子库、标注层、文档等名称批量取回，不再逐条查询 |

站内反馈（2026 年 11 月 6 日）：顶栏"反馈问题"按钮打开对话框，文本 1–2000 字，自动附当前页面路由与版本号，不附项目内容（`POST /feedback`，浏览器会话）。管理员在管理 · 反馈查看、标记已处理并备注（`GET / PATCH /admin/feedback`）。

### 任务

唯一 `jobs` 表。状态 queued / running / succeeded / failed / cancelled；进度为已处理数与总数，并带单位（导入：解析按"个文件"、分句与标注和写入按"字"；建索引按"篇"）；失败保留错误原因，用户可重试。页面轮询或 SSE 显示进度。

队列（2026 年 10 月 28 日）：任务分短任务与长任务两条道。短任务 = 统计、导出、预标注、知识库任务，以及上传小于 5 MB（`LIGHT_IMPORT_BYTES`）的导入和词数少于 100 万（`LIGHT_INDEX_TOKENS`）的建索引；其余导入与建索引，以及全部语义索引任务（`embed_corpus`）为长任务。worker-light 处理全部短任务；worker 处理全部任务，但先取短任务，再按创建时间取长任务。同一语料同时只建一个索引。排队中的任务显示"排队中 · 前面还有 n 个任务"（同一道中正在运行和更早排队的任务数），排到最前时显示"排队中 · 下一个执行"。

任务页与右下角任务托盘：标题写任务对象（统计为"频次 · 语料名"，其他为"导入 · 语料：文件"）；已完成显示"已完成"或结果（导入"N 篇 · N 句 · N 词"），点标题打开结果（统计结果页、导出下载，其他打开任务详情）；1280 px 宽时任务表操作列固定在右侧。

运行状态（2026 年 11 月 5 日）：`/api/health` 查询数据库，失败返回 503；worker 与 worker-light 每轮主循环和任务心跳更新 `DATA_DIR/worker-health/<WORKER_ID>`，compose 健康检查要求 90 秒内更新过；宿主机 `scripts/healthcheck.sh` 检查接口、容器健康、数据盘剩余与最近备份，失败时发告警（见部署手册）。管理 · 系统（`GET /admin/system`）显示版本、模型、各 worker 最近上报与健康、数据盘剩余、数据目录与检索缓存大小、最近备份时间（api 只读挂载 `BACKUP_DIR`）。

取消（2026 年 11 月 6 日）：发起人、项目 owner 与 editor 可取消，平台管理员（浏览器会话）可取消任何任务并记审计（`GET /admin/jobs` 列全部项目与内置语料的任务）。运行中的任务由一个监视线程每 2 秒读取任务状态，转为已取消后：统计终止 CQP 与 `cwb-scan-corpus`、`s-decode` 子进程，Python 计算循环定期检查；预标注按块检查（中文依存每 200 句一块）；导入、导出在块之间检查。纯 PostgreSQL 统计与译法统计的 SQL 部分只能等语句结束。

索引自动重建（2026 年 11 月 6 日）：删除文档、修改文档元数据（标题除外）、批量改元数据后，自动为该语料排一个建索引任务，已有排队中的不重复排；建索引遇到已删除的文档跳过。语料视图 `index_pending` 表示有排队或运行中的建索引任务，检索页与统计页在当前范围的语料 `index_pending` 时显示"索引更新中，完成前结果可能包含已删除或修改前的文档"。完成后按 `index_version` 使旧检索结果失效。

后端暂时不可用（502 / 503 / 504 无错误码，或连接失败）时统一提示："服务暂时不可用，本次修改未保存，请重试"（写操作）或"服务暂时不可用，请稍后重试"（读取）。

## 十一 前端页面

| 页面 | 内容 |
| --- | --- |
| 语料库 | 内置与项目语料列表；上传；元数据编辑；子库管理；语义索引状态与建立 |
| 检索 | 范围选择、查询式 / 语义两种模式、查询式输入与辅助面板、简繁通查开关（中文语料）、三项计数（平行语料第三项为句对）、KWIC、结果内筛选（追加同句条件重新检索）、上下文、导出、导出整洁数据 |
| 统计 | 方法切换（含文本指标、词汇等级、对比、词汇画像、近义词对比）、参数（含"区分大小写"）、词表管理、结果表与图、回到例句、导出整洁数据 |
| 帮助 | `/p/:id/help`，未进项目时 `/help`；顶栏帮助图标与命令面板"帮助"进入。六节：查询语法（示例可一键在检索页打开）、导入格式、统计指标（公式与文献取 `GET /api/help/metrics?style=gbt7714\|apa`，与方法附录同源 `engine/methods.py`）、角色与权限、数据与隐私、常见错误；内容维护在 `apps/web/src/features/help/` |
| 标注 | 标注层列表与进度；校对工作区（文档句子流 + 可视化编辑器 + 标签面板） |
| 知识库 | 文献、术语、规范、笔记四个分区；导入；检索 |
| 助手 | 独立页面，也可作为右侧抽屉在任意页面打开；对话、组件结果、工具调用过程折叠 |
| 任务 | 进度、取消、重试、结果入口 |
| 设置 | 标签：项目（改名、新建项目、删除项目、最近删除与恢复、成员与角色、本项目审计（负责人））/ 账号（修改密码、本月模型用量与上限）/ 数据与隐私（数据存放、管理员可见范围、发送到外部模型的操作与模型主机、版本）/ 管理（仅管理员，二级标签：用户、项目、任务、用量、审计、反馈、系统）。模型为系统信息（只读），不做在线配置；侧栏与命令面板同名"设置" |
| 修改密码页 | `/password`：临时密码登录后强制进入，改密前其他页面不可用，可退出登录 |
| 引导页 | 首次登录后五步：创建项目（名称最多 60 字）→ 导入语料（内置或上传，显示导入与索引进度）→ 第一次检索（预填在所选语料中确有命中的查询式，解释行随输入解析更新）→ 试试助手（迷你演示）→ 完成；每步可"跳过此步"，顶部"跳过引导"直接进入检索（尚无项目时用已填名称或"我的研究项目"建项目）；进入检索时沿用引导所选语料和最后一次查询；命令面板和空态可重新打开 |

布局：左侧导航 232 px + 顶部范围条（项目 › 语料库 › 子库；P11 起每段点击弹出该段的切换菜单：项目列表与"新建项目"、本项目语料库（内置标"（内置）"）、"不限子库"与当前语料的子库；右侧命令面板、帮助、深色切换、助手入口）+ 主区；右侧统一 360 px 检查器承载上下文、文档与任务详情。页面覆盖正常、空、处理中、失败四种状态。

### 视觉与组件规范

视觉风格为现代产品型：浅灰底 `#F6F7FA`、白色圆角卡片、柔和投影、单一蓝色强调 `#1570EF`（悬停 `#175CD3`、浅底 `#EFF8FF`、浅底上的文字用 `#175CD3` 保证对比度）；界面字体 Inter + PingFang SC / Microsoft YaHei，计数、坐标、编号与查询式用 JetBrains Mono。不使用紫色系、左侧色条卡片、渐变装饰、插画和 emoji。

| 元素 | 规则 |
| --- | --- |
| 区块小标题 | 12 px 大写字距灰色标签，右侧放动作；所有卡片头统一 |
| 卡片结构 | 头部浅灰条、正文、底部操作行三段式 |
| 阴影与圆角 | 阴影三级：卡片 / 浮层 / 对话框；圆角控件 8、卡片 12、浮层 16 |
| 语义色 | 成功、警告、错误、信息各一色及浅底版本，用于状态标签与提示 |
| 头像与项目徽标 | 首字母 + 按名称生成的浅色底 |
| 数字展示 | 加粗等宽数字、千分位、单位小字 |
| 分类色板 | 8 色低饱和，用于词性、标签集、图表系列 |
| 查询式块 | 浅底等宽块，词性、间隔、条件分别着色 |
| 按键样式 | 快捷键提示用键帽 `kbd` |
| 迷你图 | 行内 sparkline 表示频次趋势、任务速度 |
| 背景与细节 | 空态与登录页极淡点阵；焦点环 2 px 蓝色外环，按压 0.98 缩放；深底工具提示延迟 300 ms；卡片内 1 px 分隔线，区块之间只用留白 |
| 深色模式 | 同一套变量切换，主蓝略提亮 |

动效：助手思考链（闪光标题、灰字流式推理、工具步骤时间线的脉冲与扫光、完成后折叠为"已思考 N 秒 · N 次工具调用"）、流式回答光标、结果组件错峰滑入、计数滚动、KWIC 行错峰入场、图表生长、依存弧线与对齐连线描画、抽屉滑入、骨架闪烁、顶栏细进度线、任务条纹进度、证据钉住飞入。界面反馈 150 至 400 ms，展示类动画 600 至 900 ms；系统减少动态效果时全部关闭。

设计稿为静态 HTML，位于 `doc/ui-design/`（`index.html` 总览，含 `components.html` 组件规范页、`motion.html` 动效规范页与 `onboarding.html` 引导页），是前端开发的视觉基准；完整说明见《前端整体设计方案》（`doc/frontend-design.md` 及对应 Word）。

## 十二 开发顺序与验收

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| P1 语料与检索 | 登录项目；导入 Tatoeba、UD、TXT；CWB 索引；查询式全部语法；KWIC；子库；导出 | 内置语料上查 20 条金标查询，三项计数与人工核对一致；上传 TXT 后 1 分钟内可查 |
| P2 统计与 Agent | 六类统计与图表；agent 服务、工具、OpenUI 组件；对话完成检索与统计 | 关键词与搭配结果和独立参考实现一致；对话中生成 KWIC 表和频次图并能点开例句 |
| P3 标注一 | 词性、依存预标与校对；标注索引；按标注检索 | UD 测试集上预标准确率记录；校对 100 句后能按 `{dep=nsubj}` 检索 |
| P4 知识库 | 导入、分段、向量化；术语表；规范；笔记；kb.search；Agent 引用 | 导入 10 篇 PDF 后问答有出处；从双语语料抽取术语并确认入库 |
| P5 标注二 | 自定义片段与关系、双语对齐、导出 CoNLL-U / brat / TMX | 完成一篇文档的偏误标注并导出；对齐 200 句对并修改 |
| P6 收尾 | 维基子集、权限回归、部署文档、README | 干净环境 Compose 启动，两条研究流程走通 |

### 完整计划与进度（2026 年 10 月 27 日）

| 阶段 | 任务 | 状态 |
| --- | --- | --- |
| P1 语料与检索 | 登录、项目、成员角色；语料导入（txt / docx / csv / tsv / conllu / tmx / Tatoeba）；Stanza 分词词性依存；CWB 索引；类 CCL 查询式；KWIC、上下文、对齐句；子库；保存查询；CSV / XLSX 导出；任务系统 | 已实现，联调通过（`ab8e90b`）；Tatoeba 全量导入与内置语料发布未跑 |
| P2 统计与 Agent | 频次、n-gram、搭配、关键词、分布；证据篮；agent 服务（Pi、19 工具、OpenUI Lang）；前端按设计稿定稿（主题、外壳、命令面板、任务托盘、深色模式、统计页、助手页与抽屉、引导页、错误边界） | 已实现，联调通过（`18b0ab1`）；真实模型未验 |
| P2 补 | 真实模型接入验收；中文分词词性切换为 jieba；Tatoeba 全量导入与内置语料发布；管理员维护内置语料页面 | 真实模型已在 P2–P5 验收中使用（对话、预标、摘要、抽取、对齐）；jieba 已完成；内置语料导入与管理员页面在 P6-2 |
| P3 标注一 | 标注层、标签集、annotations 表（source / status / revision）；词性与依存预标任务（Stanza，可选 HanLP 对比）；校对工作区（词性点选、依存弧线拖拽、键盘快捷键、进度环）；AI 与人工差异视图；确认后写入 CWB 位置属性并重建索引；`{dep=}` 与词性查询接入检索与统计；标注统计；Agent 工具 annot.*；OpenUI 组件 DependencyTree、AnnotationDiff；导出 CoNLL-U | 已实现，联调通过 |
| P4 知识库 | knowledge_bases、kb_documents、kb_chunks、kb_terms 表与 pgvector；PDF / DOCX / Markdown / TXT / URL 导入与分段向量化；术语表（手工、从双语语料与文献抽取）；标注规范；研究笔记（证据篮与助手草稿写入）；混合检索；kb.search / kb.save / kb.extract_terms / kb.summarize 工具；OpenUI 组件 TermCard、KbCitation；TBX / CSV 导出；知识库页面 | 已实现，联调通过 |
| P5 标注二 | 自定义片段与关系标注（标签集、文本高亮、连线、LLM 预标按规范）；双语句级与词级对齐（候选生成、连线图编辑、确认）；学习者偏误与翻译策略标签集模板；多人标注一致性（kappa、alpha）与仲裁；OpenUI 组件 AlignmentGraph；导出 brat standoff、JSON、TMX；按自定义标签检索 `[标签]` | 已实现，联调通过 |
| P6 收尾 | 前端完成度专项审查（对照设计方案、设计稿与契约逐页逐状态核对并补齐）；维基中英子集内置语料；UD 中文树库内置；权限与撤销回归；备份恢复说明；性能基线（Tatoeba 全量检索与统计耗时）；部署文档；README；两条研究流程端到端验收 | 进行中：前端审查、权限回归、备份恢复已完成；内置语料按缩减范围导入（维基中英各 1000 篇、UD 英文 EWT 与中文 GSD 全量、Tatoeba 中英第 1 批约 26 万句对，其余 7 批与性能基线按用户决定暂停）；干净环境验收已完成（新卷 Compose 两条研究流程走通，见 [验收记录](acceptance.md)） |
| P7 批次 1：正确性与上线前 | 检索完整结果集与后台计数（翻页不重跑、排序在计数完成后生效、命中与缓存上限）；删除语料与文档的影响提示；助手抽屉页面上下文；证据篮"清空我钉的"与加载更多；账号生命周期（管理员用户页、临时密码与强制改密、停用、改密）；设置页"数据与隐私"与发送说明；`/api/health` 查库、worker 健康检查、`scripts/healthcheck.sh`；恢复脚本含 worker-light。契约 [contracts/p7.md](../contracts/p7.md)，来源[调研报告](reviews/2026-11-05-gap-research.md)第四节 | 已实现，整栈联调与独立审查通过 |
| P8 批次 2：研究能力 P0 | 命中频次分解（检索页"分解"）；频次离散度（range、DP、DPnorm、Juilland D）；关键词效应量（%DIFF、odds ratio、log ratio 95% 区间、Bonferroni、方向、指定词对比）与搭配 MI3、z、ΔP；平行语料译法统计与检索译文条件；检索结果抽样编码（抽样层、抽样模式、Wilson 区间与估计命中数，迁移 0009）；方法附录与参考文献（Markdown / DOCX，保存为笔记）；统计导出 DOCX；Agent 新增 5 个工具（共 44）与 BreakdownTable、TranslationTable 组件（共 16）。契约 [contracts/p8.md](../contracts/p8.md)，来源[调研报告](reviews/2026-11-05-gap-research.md)第二节 B1–B6 | 已实现，整栈联调与独立审查通过 |
| P9 批次 3：多人运营 | 模型用量记录与每人月度 token 上限、助手并发上限；设置 · 管理（用户、项目、任务、用量、审计、反馈、系统）；审计日志；项目软删除、7 天内恢复与到期清除；worker-light 每日维护（清除项目、过期导出与上传目录）；站内反馈；运行中任务可中断取消；删除文档与改元数据后自动重建索引及检索 / 统计页提示；非中英文语料明确报错；nginx 安全响应头；统一下载（过期导出提示）。迁移 0010。契约 [contracts/p9.md](../contracts/p9.md)，来源[调研报告](reviews/2026-11-05-gap-research.md)第四节批次 3 | 已实现，整栈联调与独立审查通过 |
| P10 批次 4：研究能力 P1 | 文本指标（TTR、STTR、MTLD、词汇密度、平均句长、平均依存距离、Flesch，分组汇总）；词汇等级画像（内置 NGSL 1.2，上传词表，迁移 0012）；整洁数据导出（每篇一行、codebook，CSV zip / XLSX）与导出防公式注入；多项对比与历时（LL、log ratio、Mann-Whitney、Spearman）；Word Sketch 与近义词对比；语料语义检索（语义索引、HNSW、迁移 0011）；导入 PDF、XLSX、JSONL 与正文去重；新增 ja、fr、de、es、ru 五种语言（自动识别、管线数上限）；Agent 新增 9 个工具（共 53）、WordSketch / SketchDiff / CompareChart 组件（共 19）与五个研究流程 Skills。契约 [contracts/p10.md](../contracts/p10.md)，来源[调研报告](reviews/2026-11-05-gap-research.md)第二节 B7–B15 | 已实现，整栈联调与独立审查通过 |
| P11 批次 5a：剩余缺憾与安全加固 | 纯属性 / 纯片段查询结果集与后台计数、SQL 超时、语境按句读取；检索导出读结果集并写查询与计数行；结果内筛选改为同句条件重新检索；统计默认合并大小写与"区分大小写"开关；简繁通查（opencc-python-reimplemented）；KWIC 片段高亮按页批量；新建层文档搜索分页、按子库建层与模型调用估算；对齐目标句分页与跳句；层进度增量计数；长文献分段摘要与术语抽取；笔记延迟重建向量与版本冲突 409；证据唯一约束（迁移 0013）；平行语料计数显示句对；帮助页；解压上限；网页导入防 DNS 重绑定；账号查找限权限流；上传来源与许可字段、真实上传进度与取消；模型请求重试；任务列表批量查询；面包屑切换菜单；`corpus.parse` 带会话范围。契约 [contracts/p11.md](../contracts/p11.md)，来源[调研报告](reviews/2026-11-05-gap-research.md)第一节中低优先级缺憾与第三节 | 已实现，整栈联调与独立审查通过 |
| 二期 | 命名实体、句子与文档分类、更多内置语料（报刊语料，见 `doc/corpus-collection-plan.md`）、实时多人协作；语义检索已在 P10 完成 | 不在首版 |

P11 批次 5b 待用户决定，未排期：

| 项 | 说明 |
| --- | --- |
| 合并 / 拆分词 | 改变 CWB 位置，影响全部标注层与已有坐标 |
| 内置与个人知识库 | 管理员维护的全站参考资料、属于个人而非项目的知识库 |
| P2 研究能力 | 偏误率导出、GDEX 好例句、命名实体与分类、按网址列表建库、术语一致性检查、口语转写稿导入 |
| 平台 | SSO、邮件通知、存储配额、站内公告、指标系统、CI |

贯穿各阶段：每阶段先写 `contracts/pN.md`，三方并行实现，整栈联调后提交；设计文档、Word、change-log 同批更新；每个新业务能力同批注册 Agent 工具与 OpenUI 组件。

两条验收用的研究流程：

1. 翻译研究：在 Tatoeba 中英子库检索某词，查看对齐句，统计译法频次，抽取术语入知识库，Agent 生成笔记草稿。
2. 学习者语料：上传作文 TXT，预标词性与依存，自定义偏误标签集标注，统计偏误分布，与参照库关键词比较。

## 十三 旧资产处理

- 当前仓库先做一次初始提交存档，再在新分支或清空后重建。
- 旧文档移入 `doc/history/2026-10-redesign-before/`，README 重写。
- `tmp/` 清空；根目录误生成文件删除；`docs/`、`output/` 删除。
- 保留参考：`pipelines/sources/tatoeba.py`、`pipelines/alignment/`、`workers/index_build.py` 中的 CWB 构建逻辑。

## 十四 待确认

1. 对话模型已配置（DeepSeek 兼容接口，deepseek-flash），密钥只在 deploy/.env；向量模型待定。
2. 已定：中文分词词性用 jieba，不引入 HanLP。
3. P4 向量模型：与对话模型同一 OpenAI 兼容服务，或本地模型。
