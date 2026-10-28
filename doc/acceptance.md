# 干净环境验收记录

P6-8：新卷 Compose 环境中走通两条研究流程。日期 2026-10-28。操作用 Playwright（Edge，1440×900）在网页端完成，截图在 `doc/acceptance/`。

## 一 环境

| 项目 | 值 |
| --- | --- |
| 机器 | AMD Ryzen 7 H 255（Docker 分配 16 核、23 GiB），主机内存 47 GiB，Windows 11 家庭版 |
| Docker | Docker Desktop，Engine 29.4.3，Compose v5.1.3 |
| Compose 项目 | `corpus-accept`（新卷），HTTP_PORT=18088，POSTGRES_PORT=25432，PUBLIC_ORIGIN=http://127.0.0.1:18088；与开发环境 `corpus` 并行运行 |
| 代码 | `f8fcc14` 加本次修复（第四节） |
| 对话模型 | deepseek-flash（OpenAI 兼容接口，`deploy/.env`） |
| 镜像构建 | 136 秒（12 个层命中开发环境的构建缓存）；api / worker 3.74 GB，agent 535 MB，web 78 MB |
| 首次 `up -d` 到健康 | 17 秒（`/api/health` 返回 ok，`/agent/health` 返回 ok 与 model_id） |
| 建账号 | 管理员 admin@example.edu、普通用户 researcher@example.edu，容器内 `create_account.py --password-stdin`，各 3 秒 |
| 向量模型下载 | paraphrase-multilingual-MiniLM-L12-v2，约 470 MB，1145 秒（worker 日志 "ready in 1145.0 s"；Hugging Face 下载限速） |
| Stanza 英文模型下载 | 约 322 MB，06:20–06:43 约 22 分钟（首次英文导入触发）；第一次请求 resources.json 时连接被重置，导入任务失败，重跑后成功（第五节） |
| 内置语料 | Tatoeba 中英第 1 批（`import_builtin.py tatoeba --parts 32 --only 1`）：上传 3.4 MB；2 个文档，cmn 11,964 句 + eng 54,561 句 = 66,525 句，607,947 词，句对 15,410；导入 3222 秒（其中约 22 分钟等待 Stanza 模型下载），索引 10 秒，脚本总用时 54 分 9 秒 |
| 学习者语料 | 3 篇英语作文 TXT（`tmp/accept/essay1–3.txt`），386 词（平台计 438 词，含标点），36 句 |
| worker | 学习者语料上传前 `--scale worker=2`，避免排在 Tatoeba 导入之后 |

## 二 流程 1 翻译研究（researcher，项目负责人）

| 步骤 | 操作 | 结果 | 耗时 | 截图 |
| --- | --- | --- | --- | --- |
| 1 | 引导页建项目"翻译与学习者语料研究"；语料库页内置 Tatoeba 中英自动在范围内；按元数据 `tatoeba_lang` 建子库"Tatoeba 中文侧"（cmn）与"Tatoeba 英文侧"（eng） | 中文侧 1 篇 11,964 句 102,534 词；英文侧 1 篇 54,561 句 505,413 词；列表显示许可 CC BY 2.0 FR | 即时 | f1-01-create-project、f1-01-corpora、f1-01-subcorpus |
| 2 | 中文侧检索 `翻译`、`翻译/v`；点开命中看上下文与双语对照 | `翻译` 6 次 / 6 句；`翻译/v` 5 次；每行带英文对齐句；上下文面板显示前后句、双语对照、句序号、码点、索引版本 | 首屏与完整计数 0.34 秒 | f1-02-search、f1-02-context |
| 3a | 统计 · 搭配：中文侧，节点 `翻译`，窗口 ±5，logDice，最低频次 1 | 28 个搭配词（划线、原文、论文、贴切、几页…），表格与网络图 | 1.3 秒；未出现"计算中" | f1-03-collocation |
| 3b | 译法频次：英文侧检索 `translat*` | 33 次：translate 12、translation 9、translated 6、translating 3、translations 2、translator 1；6 个中文命中的对齐句中 translate 4、translation 1、translator 1 | 0.33 秒 | f1-03-translat-en |
| 4 | 知识库 · 术语 · 抽取：来源语料 Tatoeba 中英，词性模式，候选 50；确认 5 条 | 50 条英文草稿，各带中文译名候选；确认 foreign language/外语、traffic accident/交通事故、credit card/信用卡、post office/邮局、bad habit/坏习惯 | 抽取 5.1 秒 | f1-04-extract、f1-04-terms-draft、f1-04-terms-confirmed |
| 5 | 助手（范围：中文侧）要求归纳"翻译"用法与译法并用 kb.save 存为笔记 | 14 次工具调用；KWIC 与搭配组件；判读动词 4 例、名词 2 例（translation / translator）；笔记"Tatoeba 中"翻译"的用法与译法"写入知识库，9 条引用（检索、统计、7 条证据），12 个片段 | 65 秒 | f1-05-assistant、f1-05-note |
| 6 | 检索页钉 3 条命中到证据篮（助手另钉 7 条），证据篮导出 DOCX | 10 条；首次导出无来源行（第四节），修复后标题下有"来源：Tatoeba 中英；许可：CC BY 2.0 FR；署名：…；链接：…；版本：2026-10-24" | 导出 2.1 秒 | f1-06-evidence |

## 三 流程 2 学习者语料（researcher）

| 步骤 | 操作 | 结果 | 耗时 | 截图 |
| --- | --- | --- | --- | --- |
| 1 | 上传语料：新建"学习者作文"，3 个 TXT，英语，元数据 `{"genre":"学习者作文","level":"大学二年级"}` | 3 篇 36 句 438 词，可检索 | 导入 26.4 秒（新 worker 首次加载 Stanza）+ 索引 0.2 秒 | f2-01-upload、f2-01-ready |
| 2 | 新建词性层（upos）与依存层（ud-deprel）并预标；校对：essay2 句 5 When ADV→SCONJ，整句确认；句 2 read 中心词 play→prefer、mobile amod→compound，整句确认 | 两层各 438 词；修改项标"已修改 / 人工"；进度 15/438、13/438 | 预标：词性 6.5 秒，依存 1.1 秒 | f2-02-new-layer、f2-02-pos-fix、f2-02-dep-fix |
| 3 | 新建片段层"偏误"（learner-errors，14 个标签，单人），对话模型预标；校对：buyed 时态→拼写，拒绝 become 时态，拖选新建 writing skill 用词，其余逐个确认 | 模型建议 35 处；最终 35 处有效（含 1 处人工），36/36 句完成 | 预标 195 秒（35 句，deepseek-flash） | f2-03-new-span-layer、f2-03-span-modify、f2-03-span-add、f2-03-span-done |
| 4a | 统计 · 频次：单位"片段标签"，层"偏误" | 11 类：主谓一致 10、时态 7、多词 4、句式 3、冠词 / 拼写 / 搭配 / 用词各 2、介词 / 体 / 偏误各 1，合计 35，与 XLSX 合计一致 | 1.6 秒 | f2-04-error-dist |
| 4b | 统计 · 关键词：目标学习者作文，参照子库"Tatoeba 英文侧"，LL，最低频次 3 | 22 项；hometown（LL 30.11）、reading（29.75）、many（19.7）、become、every、very 等显著 | 1.6 秒；出现"计算中"后完成 | f2-04-keywords |
| 5 | 标注页导出"偏误"层 brat 与 XLSX，任务页下载 | brat zip：3 组 .txt/.ann + annotation.conf，T 行与片段一致；XLSX 两个 sheet（分布 14 标签 × 3 文档，合计 35；片段明细）。学习者语料无许可元数据，按契约不写来源行；关键词统计导出 XLSX 首行为参照库 Tatoeba 的来源行 | 导出各 1 秒内 | f2-05-export、f2-05-jobs |

## 四 发现的缺陷与修复

- 证据篮导出（CSV / XLSX / DOCX）不写来源与许可行。检索结果只能经证据篮导出 DOCX，钉住 Tatoeba 命中后导出的 DOCX 没有署名，违反 contracts/p6.md 第四节"导出带署名"。修复：`services/worker/tasks.py` `run_export_evidence` 按证据引用的文档和统计结果（含关键词参照库）收集语料，调用已有 `source_notice`；`tests/api/test_builtin_sources.py` 增加证据篮 DOCX 用例。`test_builtin_sources.py` 与 `test_stats_evidence.py` 12 项通过；重建 corpus-accept 的 worker 后重新导出，来源行正确。

## 五 问题与处理

- 首次英文导入失败：Stanza 下载 resources.json 时 `RemoteDisconnected`，任务失败（INTERNAL）。处理：重跑 `import_builtin.py`，脚本沿用语料并重新上传该批，成功。按"一般异常人工重试"处理，未改代码。
- 模型下载慢：MiniLM 19 分钟、Stanza 英文 22 分钟，期间导入停在"标注（字符）0%"，页面无下载提示。离线或慢网环境应按部署手册预先填充 `models`、`stanza` 卷。
- 流程 1 关键词比较：环境中没有中文参照语料（导入维基中文需再下载 Stanza 中文依存模型），中文侧关键词比较未做；以英文侧 `translat*` 译法频次和搭配统计代替，关键词比较在流程 2 完成。
- 片段工作区：句子全部确认后"待办"列表不刷新，切换"全部 / 待办"后正确；快捷键帮助列出"整句确认 Shift+Enter"，片段层不支持，需逐个片段 Enter。列入细节项。
- jieba 把"因为我想成为翻译"中的"翻译"标为 v，`翻译/v` 因此含 1 处名词用法；属分词词性工具的误差。

## 六 结论

两条流程在新卷环境中全部走通；证据篮导出缺少署名一处缺陷已修复并复验。结论：**通过**（流程 1 的关键词比较以译法频次代替，见第五节；片段工作区两处细节列入二期）。

## 七 截图

![f1-01-corpora](acceptance/f1-01-corpora.png)

![f1-01-create-project](acceptance/f1-01-create-project.png)

![f1-01-subcorpus](acceptance/f1-01-subcorpus.png)

![f1-02-context](acceptance/f1-02-context.png)

![f1-02-search](acceptance/f1-02-search.png)

![f1-03-collocation](acceptance/f1-03-collocation.png)

![f1-03-translat-en](acceptance/f1-03-translat-en.png)

![f1-04-extract](acceptance/f1-04-extract.png)

![f1-04-terms-confirmed](acceptance/f1-04-terms-confirmed.png)

![f1-04-terms-draft](acceptance/f1-04-terms-draft.png)

![f1-05-assistant](acceptance/f1-05-assistant.png)

![f1-05-note](acceptance/f1-05-note.png)

![f1-06-evidence](acceptance/f1-06-evidence.png)

![f2-01-ready](acceptance/f2-01-ready.png)

![f2-01-upload](acceptance/f2-01-upload.png)

![f2-02-dep-fix](acceptance/f2-02-dep-fix.png)

![f2-02-new-layer](acceptance/f2-02-new-layer.png)

![f2-02-pos-fix](acceptance/f2-02-pos-fix.png)

![f2-03-new-span-layer](acceptance/f2-03-new-span-layer.png)

![f2-03-span-add](acceptance/f2-03-span-add.png)

![f2-03-span-done](acceptance/f2-03-span-done.png)

![f2-03-span-modify](acceptance/f2-03-span-modify.png)

![f2-04-error-dist](acceptance/f2-04-error-dist.png)

![f2-04-keywords](acceptance/f2-04-keywords.png)

![f2-05-export](acceptance/f2-05-export.png)

![f2-05-jobs](acceptance/f2-05-jobs.png)

