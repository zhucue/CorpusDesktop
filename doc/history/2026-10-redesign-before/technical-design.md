# 高校研究生语料与 AI 研究工作台 网页端技术设计

采用网页端优先的建设方式。研究助手工作台作为默认入口，按用户权限调用全部已上线业务能力；手动页面保留独立入口。React 展示结果，FastAPI 维护业务事实，Celery 完成处理与计算，Node.js/Pi 宿主组织研究步骤。面向外语、翻译及语言学研究生，支持高校部署。

### 一 开发基线

采用 React/TypeScript 前端、FastAPI 业务后端、Node.js/Pi Agent 宿主、PostgreSQL、CWB 与字符索引、对象存储及 Celery。Python 保持模块化工程，Node 为明确的 Agent 运行边界；不按菜单拆微服务。以下为可进入开发评审的技术设计，性能数值均是待验证的目标。

| 决策 | 本版要求 |
| --- | --- |
| 交付形态 | 浏览器访问，同源 HTTPS；Linux 容器部署。Windows 开发机通过 WSL2 或开发容器运行后端依赖。 |
| 数据位置 | 原件、正文、索引、模型输出均在部署方服务器。高校内网无互联网时，使用已安装模型或停用云端 AI。 |
| 研究可信性 | 原件不可变；处理生成新版本；每次分析绑定快照、工具版本、参数及实际输入范围。 |
| 功能范围 | 延续产品规划的 F001 至 F096；重新安排网页端依赖。账号、项目隔离、上传、三类真实来源同步、基础对标查询和持久任务全部进入第一阶段；首版边界固定为 M01 至 M14。 |
| 本次技术交付 | 模块职责、数据结构、查询与统计规则、HTTP 契约、AI 执行、部署、测试与实施顺序。 |

### 与先前产品方案的变化

本版为 2026 年 10 月 16 日修订基线，数据源同步提前至阶段 A。首版不包含桌面壳、SQLite 本地工作区和离线同步。关闭浏览器不终止服务端任务。个人项目表示访问权限仅属于本人，不表示文件保存在个人电脑。后续桌面端如有需求，作为网页应用的独立扩展评估。收费与商业定价不进入本设计。

## 首版功能边界 1

阶段 A 必须完成 M01 至 M14。功能名称不是完成标准，必须有真实输入、持久结果和对应验收。每项关联长期 F 编号，跨阶段 F 项仅交付本表规定的子集。

| 首版项 | 对应目录 | 必须交付的行为 |
| --- | --- | --- |
| M01 来源目录 | F012 F016 | 覆盖现代、古代、学习者、口语、双语、学术、文学、网页新闻、词典、树库及机构仓储；每项显示入口、版本、能力与接入状态。 |
| M02 真实数据同步 | F013 F016 F070 | Tatoeba 中英、Wikimedia 中英文、UD 至少一个核准树库；检查版本、定时执行、校验、差分、重试与发布。 |
| M03 账号与项目 | F001 F081 F084 | 负责人、编辑、只读及管理员；项目私有材料隔离，共享来源通过受控挂载使用。 |
| M04 上传与清洗 | F009 F010 F014 F015 | UTF-8 TXT、CSV、TSV、JSONL；来源专用 XML、CoNLL-U 解析。编码校验、基础清洗、精确去重与质量报告。 |
| M05 子库与快照 | F002 F003 F005 F006 F007 | 按来源、语言、体裁、时间等筛选；固定命名快照、来源版本和处理版本；展示构成及缺失字段。 |
| M06 中文及英文查询 | F025 F026 F028 | 字符、词项、短语；带明确主查询锚点的 AND/OR/NOT、有限字距或词距、受限正则、已有 lemma/POS 条件；字段能力校验。 |
| M07 上下文与结果 | F029 F030 | KWIC、整句、展开段落、前后段、左右排序、出处、二次筛选、收藏、固定种子抽样、保存查询。 |

## 首版功能边界 2

阶段 A 必须完成 M01 至 M14。功能名称不是完成标准，必须有真实输入、持久结果和对应验收。每项关联长期 F 编号，跨阶段 F 项仅交付本表规定的子集。

| 首版项 | 对应目录 | 必须交付的行为 |
| --- | --- | --- |
| M08 基础统计 | F033 F034 F035 F041 F042 | 字频、词频、文档频次、标准化频率、连续 2 至 4 元词组、窗口共现及 logDice；结果可下钻例句。 |
| M09 子库与历时比较 | F036 F037 F046 | 两组关键词比较，首版固定 log likelihood 和 log ratio；按年、体裁或来源分布及双查询对比，显示分母和缺失。 |
| M10 双语研究 | F031 F049 F052 F067 | 双向查询，私有或共享材料自动一对一对齐候选、未配对检查、覆盖层修订与确认；固定版本分析，复杂关系只读。 |
| M11 研究助手 | F065 至 F071；横向覆盖 M01 至 M14 | 研究助手默认工作台；按当前用户权限调用全部已上线业务动作，包括创建、修改、后台执行、保存及导出。与手动入口共用业务服务；后续能力上线同批接入。 |
| M12 成果与导出 | F073 F074 F076 F078 | 保存笔记及证据，导出 CSV、XLSX、SVG、DOCX 和 JSON 方法清单；附数据版本、统计参数与来源。 |
| M13 任务与撤回 | F070 F087 F089 F093 | 后台进度、取消、有限重试、恢复、同步异常及授权失效；关闭页面不终止任务。 |
| M14 部署与验收 | F079 F090 F091 F094 | Linux 容器部署、备份恢复、审计、项目与 AI 越权测试、查询与统计金标、真实源同步验收。 |

### 后续阶段的明确边界

阶段 B 增加通用 DOCX/PDF/OCR、近似去重、完整 CQL 风格语言、依存查询、复杂标注、复杂对齐、多译本和术语。阶段 C 增加多人标注裁决、统一登录、音视频转写及时间轴；阶段 D 扩展规模、语言与专业格式。首版不运行任意模型生成脚本，不宣称复现所有 CCL/BCC 查询语法。

## 第一阶段来源同步架构

SourceRegistry、Sync 和 Corpus 共用统一任务账本。平台已发布来源属于共享数据域，项目选择固定版本后建立受控挂载；用户上传属于私有项目域。AI、检索与导出均从项目快照读取，不能绕过挂载直接读取来源对象。

```text
SourceRegistry + ConnectorConfig
  -> Scheduler -> Execution(job + outbox)
  -> Sync worker -> staging objects
  -> Validate + Parse + Quality report
  -> immutable source_release + source_snapshot
  -> project_source_mount -> project_snapshot
  -> Query / Analysis / Evidence / AI
```

| 连接器 | 版本发现与格式 | 阶段 A 特定处理 |
| --- | --- | --- |
| Tatoeba | 官方周导出；句子表与翻译 Links | 固定文件清单；句 ID 与翻译边去重；作者、许可、增删改及断链检查。 |
| Wikimedia | 新 current 月度导出；SHA256SUMS | zhwiki/enwiki；page_id + revision_id；命名空间、重定向、模板和清洗映射固定。 |
| UD 指定树库 | 正式 release；CoNLL-U 与许可文件 | 分句、词元/POS、依存结构及 train/dev/test；原生标注不得被普通分词覆盖。 |

官方依据分别为 Tatoeba 下载说明、Wikimedia 新导出文档、UD 发布与许可规范；产品设计来源全景提供对应链接。S0 确认确切版本、语言包、署名和服务器处理权限，再登记可用能力。计划检查不代表上游有新版本；下载失败与无更新是不同结果。

阶段 A 流式解析来源文件，新来源版本完整建索引。整库挂载且正文、token 层、顺序与处理配置一致时复用来源索引；子集或共享私有混合快照按配额构建项目索引。索引键固定引擎、字符或 token 单位、规范化、recipe、有序修订与 token 层摘要；复用仍逐项目鉴权。支持断点获取需以源 ETag/长度/Range 语义验证为前提；不支持时安全重下，不能拼接不同版本。已发布对象保持不可变。容量不足则失败并保留旧版本，不自动缩小样本却仍标完整。

## 同步数据模型与项目挂载

| 表 | 关键字段 | 约束 |
| --- | --- | --- |
| source_catalog | source_id, parent_id, kind, homepage, facets, status | 区分发布方、聚合入口与具体子库；目录不承载接入成功状态。 |
| source_policies | id, version, evidence_url, subject, actions, retention | 文本、标注和元数据分别登记；四态权限和适用主体；变更有审计。 |
| connector_configs | collection_id, adapter_version, params, schedule, secret_ref | 来源域允许列表；凭据服务端保存；一个配置固定语言及格式。 |
| sync_runs | id, config_id, target_version, state, lease, cursor, checkpoint | 并发锁按配置；操作幂等键与请求摘要；检查和发布游标分别保存。 |
| source_releases | id, collection_id, version, manifest_hash, policy_id, state | 唯一 collection_id + version + manifest_hash；同名不同内容生成新修订。 |
| source_records | release_id, upstream_id, revision, hash, object_ref, tombstone | 来源范围内稳定 ID；保留内容来源，不用内容 hash 代替身份。 |
| source_snapshots | id, release_id, pipeline_digest, manifest_key, state | 只有完整校验且索引就绪后发布；含语言和质量计数。 |
| project_source_mounts | id, project_id, source_snapshot_id, policy_epoch | 指向固定已发布版本；有效权限为来源策略与项目策略的交集。 |
| mount_items | id, mount_id, source_revision_id, metadata_hash | 唯一 mount + revision；服务端校验源修订属于挂载快照。 |
| snapshot_items 扩展 | private_revision_id 或 mount_item_id | CHECK 恰好一个非空；项目复合外键，清单固定有效成员。 |

共享 catalog 数据由专门角色管理，普通用户仅可读取允许公开的目录字段。私有来源配置必须带所属 workspace，禁止泄露名称和规模。源正文读、缓存命中、结果回放、AI 外发与下载都通过项目挂载鉴权；RLS 的 public 标志不构成直接访问对象存储的权限。

### S1 来源目录与修订

S1 以固定种子登记产品基线 D01 至 D46，保留名称、官方依据、材料说明、接入路线与研究边界；entry_kind 区分发布方、聚合入口和数据集，分类及语言为登记维度。publisher 沿用基线发布名称，不表示已另行核实法律主体。聚合入口不计全文规模，mul 表示多语而非完整语言清单。

实际表为 app.catalog_sources、catalog_actions 和 catalog_releases，独立于私有项目。登录用户可发现目录，来源能力只开放 discover；remote_query、fulltext_analysis、export、model_egress 均未开放，许可状态为 pending_review。D12、D13、D14、D21 的 experimental_evidence 指向已有 S0 验证，其他条目为仅目录或待核实。种子不创建生产发布版本，版本列表为空；不得以目录条数、上游规模或 S0 样本推导可分析规模。

GET /api/v1/sources 支持编号、名称或发布名称搜索，以及语言、分类、实际接入状态和已上线能力筛选；返回完整筛选范围的 total、当前 items 与 next_cursor。按 source_id 稳定排序，游标绑定筛选条件，每页最多 100 项。GET /sources/{source_id} 返回登记详情，GET /sources/{source_id}/versions 只查询持久发布版本；本切片没有发布接口。

管理员使用 POST /api/v1/admin/catalog 创建登记，PATCH /admin/catalog/{source_id} 完整替换可编辑元数据。新增 source_id 为 1 至 64 位 ASCII 字母、数字、下划线或短横线，首位为字母或数字；既有 ID 不变。名称、分类、语言、URL 和说明均有长度与类型约束，URL 仅允许无凭据的 HTTP(S) 参考地址，服务器不会抓取该地址。管理员不能通过目录编辑批准许可、填入生产版本或打开未接入能力。

目录写入先取得 actor 锁，重新读取当前账号启用与平台管理员身份，再取得来源锁。RLS 同样查询当前账号，普通用户不能写目录或版本。更新必须提交 expected_revision，过期修订返回 409 REVISION_CONFLICT；幂等作用域为平台目录、actor、operation、Idempotency-Key，同参返回原 action_id 和原响应，异参返回 409 IDEMPOTENCY_CONFLICT。目录和动作记录在同一 PostgreSQL 事务提交，复用响应前仍复查权限。

名称、发布名称、官方 URL 或登记类型改变时，保守清除旧实验引用并降为 catalog_only，避免替换来源后继承旧证据；只改分类或说明不改变已有来源身份。已有 S0 原始证据文件保持不变。D12 固定连接器的完整获取按下节实现；来源策略、发布与撤回仍按后续阶段独立验收。

### S2 Tatoeba 完整获取与私有暂存

本切片固定 D12 和 tatoeba-cmn-eng-v1，只读取官方 cmn、eng 详细句子包及 cmn-eng 直接边包。目录的名称、发布名称、登记类型或 URL 偏离原固定身份时拒绝启动；可编辑参考 URL 不能变成下载目标。首次下载前观察三个文件的 ETag、Last-Modified、长度和导出日期，并立即持久到运行记录；条件 GET、实际长度、下载后 HEAD 共同核对，同任务人工重试沿用该身份，变更返回 SOURCE_VERSION_CHANGED。原件 SHA256 仅为本地内容身份，无上游官方校验和或原子快照承诺。

app.source_sync_runs、source_sync_attempts、source_sync_events、source_sync_actions、source_sync_outbox 和 source_acquisitions 构成独立平台任务域，不伪造项目 ID，不借项目任务读取平台材料。管理员通过 POST /api/v1/admin/sources/D12/sync-runs 启动，GET 同路径分页读取；GET /admin/sync-runs/{id} 与 /events 返回真实状态和顺序事件，POST /cancel 或 /retry 执行动作。写入带 Idempotency-Key，同 actor、operation 和 key 同参重放返回原响应，异参冲突；请求摘要含 source_id 或 run_id。同来源只有一个 QUEUED／RUNNING 任务，普通用户在 HTTP 与 RLS 层均不可读取或写入此账本。

运行状态为 QUEUED、RUNNING、SUCCEEDED、FAILED 或 CANCELLED，处理中另报 ACQUIRING、PARSING、STORING；成功阶段为 VALIDATED。事务 outbox 持久投递，attempt、随机 lease token、epoch 和 90 秒到期共同约束领取和发布。进度回调最多约每秒持久一次，首次输入身份立即保存；解析及 SQL 长语句均检查回调，取消、旧租约和撤权停止结果登记。最终登记事务先取得发起人和来源锁，再复查启用账号、平台管理员身份、固定来源身份及当前租约，保证撤权先完成时不能随后发布。人工最多三次尝试，非可重试错误明确拒绝；不建立无限自动恢复。

完整句子流式读取并按源 ID 保存至 SQLite，保留原文、当前 owner、日期、句子 URL 和来源行。相同 ID 同记录去重、冲突失败；相同文字不同 ID 仍保留。直接边统一方向、去重，缺端点或错误语言关系排除并计数，不补间接关系。SQLite 是完整派生与差分产物，不替代 PostgreSQL 业务账本；新任务在创建时固定同连接器和来源身份的上一成功 acquisition，按固定对象版本下载并校验后，比较全部句 ID、记录／正文摘要及边的增删改。首次没有基线时标 initial，不能把全部记录计作相对某未知旧版的变化。

raw 三包、两份官方许可 HTML、全部句子和边 gzip、SQLite、质量、差分、许可、acquisition 与 manifest 共 13 个产物以随机服务端对象键 create-only 写入私有桶，保存 VersionId、ETag、字节数和 SHA256，并按固定版本读回核验。全体对象通过后才在同一数据库事务登记 acquisition 与任务成功。存储或事务失败不改旧成功结果；可能遗留无引用私有对象，自动孤儿清理尚未实现。临时目录按 run／attempt／epoch 分开并在结束时清理，源原文不进入公开报告。

连接器单文件压缩上限 64 MiB、总新网络 160 MiB、socket 15 秒、下载总时限 1800 秒，每文件GET 网络／短 body 最多重试一次，HEAD 网络失败走有限人工重试；本切片尚未实现 Retry-After 和指数退避。展开每文件 512 MiB、每行 1 MiB、句子 300 万、边输入 200 万、解析 1200 秒、产物检查上限 2 GiB。Linux 明确设置仓库 tmp 下的 SQLITE_TMPDIR；Windows 专用进程启动前设置 TMP／TEMP，解析器以 GetTempPathW 校验实际临时路径。SQL 长语句通过 SQLite progress handler 检查时间和取消；上述产物检查不冒称硬磁盘配额。

固定工具分派允许 platform 的 sync.start／sync.report；platform jobs.list 使用 source_id，jobs.get／cancel／retry 必须使用 sync_run_id。项目任务仍使用 job_id，不能混用。accepted 同步登记为共享后台任务，只有 SyncRun 成功且成功 sync.report 已进入工具上下文，才满足 settle 的必要任务条件；取消 Pi run 不隐式取消共享同步。该受限宿主验证不开放生产 available_tools，也不等于真实模型研究验收。

VALIDATED 只表示完整获取和结构校验完成；result.searchable=false，catalog_releases 不新增，普通目录能力仍仅 discover。当前 owner 不等于原始作者，CC BY 2.0 FR 的许可事实不等于本项目已批准发布或模型外发；CC0 子集不被自动套用。缺端点和署名缺失保留质量报告，形成可分析版本前仍须满足来源策略、索引与发布门槛。本切片不交付定时治理、来源撤回、项目挂载或公开全文检索。

### S3 固定全量索引与私有产物

索引任务只接受已校验的固定 D12 acquisition，下载其中固定对象版本的 SQLite 和 acquisition manifest，并核对实际长度与 SHA256。调用方不能提供任意来源路径、分词参数或可执行命令。管理员通过 indexes.build／indexes.report 与同一后台业务服务操作；platform jobs.list 使用 source_id 与 task_kind=source_index，读取、取消和重试使用 index_run_id。相同 acquisition 与 recipe 已有成功索引时返回原结果，仍复查当前管理员权限；同来源活动构建不重复启动。目录登记和获取成功不直接产生公开可检索版本。

基础词形 recipe 固定 jieba 0.42.1、默认字典 SHA256 与 HMM=False；英文使用 NLTK 3.10.3 的 TreebankWordTokenizer.span_tokenize，不下载 Punkt 或模型。词形为原始句子的 Unicode 码点切片，保留大小写、标点和数字，只排除空白；空白外字符必须完整覆盖且坐标不能重叠。此层只提供 form，lemma、POS 与其他标注属性明确拒绝；Stanza 和领域分词质量另行验收。none 规范化不合并预组合和组合字符。

CWB 3.5.0 原生编码实测会合并部分 Unicode 规范等价字符，因此内部词项改用 u 前缀加原始 UTF-8 十六进制的可逆键。form 等值查询只在深拷贝的 AST 上作同一转换，返回时始终映射原文码点；构建后完整 cwb-decode 解码回原始词形逐项校验。CQP 只加载服务端生成的独立 registry，关闭用户初始化文件与宏配置，不接受任意 CQL 或 shell 参数。

全部句子按数字源 ID 顺序流式构建，持久保存原文、成员与元数据清单、直接双语边、token 坐标及字符 postings。字符位置使用小端定宽 uint64 文件和只读 mmap，记录映射及 token 坐标也按固定宽度读取，不把全库 Revision 或成员数组装入内存或 PostgreSQL JSON。本版尚未实现字符位置压缩。小 manifest 引用完整成员清单摘要；身份同时绑定 acquisition、SQLite、有序修订、元数据、词层、码点层、引擎和构建 recipe。任何影响语义的修复须升级 recipe，避免错误复用旧索引。

首屏和完整计数分别执行，首屏未完成的总数返回 null／pending，不用完整计数阻塞首屏。字符路径共享准确匹配迭代器；词项路径复用已验证的 CWB 有界 dump 和独立计数适配。顶层精确字面串使用现有 texts.utf8 的原生 mmap.find 定位候选句，按保存的字节范围排除跨句候选，再由原文匹配器生成全部重叠 Unicode 码点跨度；不将字节偏移直接返回为字符坐标。每句最多进入匹配器一次，跨句候选后从当前句末继续，以免跳过下一句合法命中。复合字符查询选择必需项中最稀疏的字符 posting，OR 合并所有分支候选；记录定位和句内 posting 跳过采用单调局部括界与二分。仅改变候选读取，索引格式、recipe、身份及最终排序、句界、计数和 KWIC 语义不变。当前 reader 支持的受限语法与内部构建验证不等于公共检索接口已经发布。

后端在事务锁内按已登记实测字节和活动预留作准入，默认单构建预留 8 GiB、总额度 20 GiB；专用 index-worker 限 4 CPU、8 GiB。构建工作区预算包含输入、索引、临时文件及归档副本，按回调采样检查，不能宣称操作系统硬磁盘配额。每阶段最多 1800 秒、构建总时限 7200 秒，CWB 子进程定期回调并在取消或失租时终止。单产物最多 4 GiB；本版输出一个 index.tar 和小 manifest，不为每个字符建立对象。

构建任务保留事务 outbox、幂等、attempt／epoch／租约、进度、取消及有限人工重试。最终登记事务重新检查当前管理员身份、来源身份、固定 acquisition、recipe 和租约；私有产物按不可变对象版本及实际 SHA256 校验，未完成清理不提前释放占用。构建结果阶段为 INDEXED，published=false、query_ready=false；此动作不创建目录发布版本。Pi accepted 索引必须已成功且 indexes.report 的成功结果进入会话上下文，才满足必要后台任务条件；取消 Pi run 不隐式取消共享构建，生产 available_tools 仍为空。来源策略、发布及整库挂载另经下述业务服务执行；真实来源许可仍待核准；混合快照与受权项目 KWIC 的后续验收见下述切片，未开放匿名正文查询。

依赖锁保留官方 jieba sdist 摘要与固定构建依赖，生产镜像从官方源码独立构建；不要求各环境生成的 wheel 字节相同。字典及运行包版本仍在分词器启动时复核。依赖锁、完整构建与新进程重开证据分别保留，正式独占环境性能门槛不变。

### S3 来源核准、发布与整库挂载

来源核准绑定固定 acquisition、其 manifest 与许可摘要，以及目录来源身份修订。管理员提交 allow／deny、依据链接、审查说明和预期修订号；每次决定追加记录并更新当前指针，不覆盖既有决定。仅核准平台内部研究使用，export 与 model_egress 保持 false；依据链接只保存，不由服务器任意访问。未核准、来源身份改变或摘要不一致均不可发布或读取挂载材料。

发布从已成功的固定 SourceIndex 创建不可变 release 与 source_snapshot，并在同一事务更新来源默认指针。发布时读取小 manifest 并校验 SHA256，核对固定索引包的 VersionId、长度及 ETag；对大 tar 执行 HEAD，不重新计算整包 SHA256。完整包的摘要依据来自已校验的构建归档链。新发布不修改旧记录，既有项目挂载不自动跟随默认版本。

项目 owner／editor 可创建或移除整库挂载，viewer 可读取获准挂载的实际私有 manifest；平台管理员不因此取得项目权限。每次访问、幂等回放及 Pi 历史结果对账均复查项目成员、来源当前策略、身份修订和挂载状态。撤销核准后读取返回拒绝，前端清除旧 manifest；移除保留历史记录。前端不接收私有对象键或凭据。

来源版本的 searchable 按当前来源策略、身份修订及固定索引是否具有受支持的查询 recipe 判断；它不代表调用者已经建立项目研究快照或获得任意项目材料。混合快照见下述项目索引切片，子集筛选、导出及模型外发继续接入，生产 Pi 工具仍未开放。真实 D12 许可保持 pending_review；独立测试来源的 allow 决定不替代 Tatoeba 审查。发布功能通过不表示全部 46 个来源已有可分析版本。

### S3 研究快照与持久查询结果

项目研究快照是独立、不可变的业务对象。本切片由一个有效整库挂载创建，固定项目、挂载、release、来源快照、索引身份及有序成员清单摘要；不将挂载编号当研究快照编号，也不向数据库复制全部句子。新版本或新挂载需建立新研究快照，既有查询不自动升级。该基础切片先支持单个整库挂载；私有修订及多成员构建按下述项目索引扩展，子集筛选另行实现。

后台首先从固定私有对象版本读取索引包，核对长度与 SHA256，并按 manifest 的明确成员清单逐文件校验、安全解包。缓存位于 Linux 私有持久卷，index-worker 可写，API 只读；以完整包摘要定位，并原子发布 ready 标记。首次准备及显式恢复核验完整字节，普通查询和分页复用已核验缓存，不为每页重下或重新散列大包。预算包含下载 tar 和展开文件的同时占用；容量不足明确拒绝，不引入自动淘汰体系。缓存缺失或损坏时 GET 返回 503，显式 prepare 在锁内只恢复对应固定对象，不改快照、查询或结果身份。

FIRST_PAGE 任务实际读取最多 50 条加一条探测，发布有限首屏并保持三个总数为 null；随后单独的 FULL_RESULT 持久任务导出全部去重、有序跨度并计算完整命中、句段和文档数。两任务沿用同一个消费者先后执行，不宣称并行。全部跨度和摘要成功归档至固定 S3 版本、通过租约及授权复核后，才将 count_state 置为 complete。超时、取消或超限不产生伪零值或截断后的完整计数，可用首屏与完整结果状态分别呈现。

完整结果使用版本化的 32 字节定宽记录：句子序号、句内起止码点、全局起止 token；字符命中的 token 字段为空标记。结果文件上限 512 MiB，CQP 全量 dump 临时文件上限 1 GiB，执行上限 120 秒；输出按文件流读取，不把全部 dump 收进 Python 内存。字符组合在单句生成过程中检查取消与期限，中间跨度超过 250000 条即明确 QUERY_RESULT_TOO_LARGE，不静默截断。子进程超时或取消必须终止并回收。现有来源把每个导入句子作为一个文档，统计单位明确为 imported_sentence_record，不冒充原出版文档。

API 仅按固定结果文件序号读取有限跨度并映射原文，不执行 CWB、不重新匹配、不创建缓存。业务 hit_ref 绑定结果集与稳定命中序号；引用包含真实来源句子 ID、由原文摘要固定的 revision_id、完整 canonical 修订的 Unicode 码点半开区间和实际句段内 token 区间，字符 token 坐标为 null。context_codepoints 取 0 至 200、默认 40，按原文码点扩展，不能把该参数写作词数或忽略 context_tokens。evidence_id 保持 null，直到实际创建证据对象。游标绑定固定结果、快照、查询、排序和页大小；游标不授予访问权。

当前运行子集为句内字符 literal／sequence／有界 gap／any_of，以及 token 的 form eq／sequence／有界 gap／any_of；保留重叠命中和 normalization=none。POS、lemma、正则、条件过滤、段落范围和任意 CQP 文本明确拒绝。每次提交、领取、心跳、发布、回放、翻页、上下文和恢复都复查当前成员、挂载及来源核准；撤权后不得继续返回已缓存正文或计数。Pi 暂只提供元数据适配，空材料范围不扩大为查询授权，search／context 不越过材料与 model_egress 限制；生产工具开放另验。

### S3 私有 TXT 与项目单索引

私有导入以已校验上传的固定对象版本为输入，由后台任务产生不可变 material_revision；解析成功与研究快照可查询是不同状态。MaterialView 的 READY 表示已有可选择的解析修订，只有研究快照 READY 才表示固定索引已准备好。语言显式选择 cmn 或 eng，不自动猜测。utf8-txt/v1 使用严格 UTF-8，只移除文件开头的一个 BOM；CRLF、CR、LF、空白、组合字符及大小写原样保留，不做 NFC、trim 或静默截取。manifest 固定原件与 canonical 摘要、解析 recipe、文档／修订 ID，以及 BOM 的源字节和源码点前缀；canonical 码点可据此前缀及 UTF-8 长度追溯原件。

规则分段识别换行、中英文终止标点及其闭引号，保护 Mr.、Mrs.、Ms.、Dr.、Prof.、e.g.、i.e.、字母 initial 和小数的常见形式。它是固定规则句段，不宣称语言学分句金标。空白附着相邻内容，不制造无词项空段；有序句段完整连续覆盖 canonical。非法 UTF-8、NUL、纯空白、超过 100000000 字节的原件或超过 100000 码点的单段均整件失败，原件保留，不产生部分成功修订。解析执行上限 300 秒并检查取消及工作区字节预算。

纯私有、共享＋私有或多个来源挂载采用 project-surface-index/v1，流式构建一个字符与 CWB 词形索引；单一来源整库仍复用既有 source-index/v1。输入固定实际修订和来源索引身份，同一 actual revision 只纳入一次，同文不同文档不能按文字合并；同时选择同一私有文档的两个不同修订明确拒绝。内部稳定顺序由来源命名空间／身份及私有文档／修订决定，与用户选取顺序区分记录；一个文档的句段连续保存。完整成员与元数据落文件，manifest 保存摘要及计数，身份纳入固定快照、处理 recipe、词层与引擎版本。

字符 posting、mmap 原文与固定宽度坐标复用既有存储；CWB 的文档边界覆盖文件全部句段。中文继续采用固定 jieba 且 HMM=False，英文采用固定 Treebank 跨度；仅支持原文 form。文档总数区分 source_records 和 private_files：每个来源导入句记录保持原单位，一个私有 TXT 的多个句段只计一个文件。查询的命中、句段与文档数独立计算，并返回两类命中文档分项。

命中固定 document_id、revision_id、segment_id 和 origin_kind。start_cp／end_cp 指向完整 canonical 修订；context_start_cp 是所返回句段在该修订中的起点，页面据此定位高亮。来源单句修订的起点仍为 0，旧结果兼容；私有命中的 source_sentence_id、source_url 为 null，不生成虚构 Tatoeba 链接。词项命中保留真实句段内及全局 token 半开区间，字符命中 token 字段为空。结果跨度文件内部仍用句段局部坐标，API 投影时通过固定元数据转换。

当前引擎已通过严格解析、真实 CWB 私有／混合构建及既有全量包读取兼容核验；后台版本归档、持续授权、快照发布以及实际 HTTP／浏览器链路已通过本批受限验收。导入复用现有 Job／outbox 与受限 Pi 元数据调用：新建独占导入任务可随该 Pi 运行取消，复用的任务不被误取消；成功后台结果仍需 imports.get 将固定修订读入调用账本，不能仅凭任务终态完成会话。研究快照复用已有字节预算、租约、取消和固定对象校验规则；不得把材料解析就绪解释为研究快照已索引或来源许可批准。真实 D12 核准、Pi 材料范围、模型外发及正式并发性能门槛不变。

### S3 固定证据 笔记与成果生成

本切片以已完成持久结果为研究成果输入，显式保存证据才产生 evidence 身份；不得把 hit_ref 或临时页号伪装为已保存证据。证据绑定真实 result_set_id、原 0-based ordinal、固定查询及快照，通过原索引重新定位原文。笔记保存不可变修订及固定证据／查询引用，draft 与人工接受的 accepted 状态分开；零命中方法笔记可以只引用完整查询，不强制附加命中证据。

项目 owner／editor 可保存证据、创建或编辑笔记，viewer 可读有权访问的记录并申请导出。更新使用 expected_revision；历史修订不覆写，编辑后的新修订重新为 draft。采纳必须由当前有效登录会话的真人操作，记录接受者及时间，不能由 Pi 执行凭据代替。即使后续编辑移除显示引用，既有证据与查询的授权依赖仍保留；访问、导出和下载均重新检查全部固定输入，撤权不因已保存笔记或文件而失效。

查询导出选择 1 至 16 个不同的已完成 query_run_id，按请求顺序读取各自完整持久跨度；不重新匹配、不限当前页、不把跨查询重复命中去重。row_number 在每个查询内从 1 开始，hit_ref.ordinal 保留原 0-based 语义。methods 保存各查询 AST、完整计数与单位、固定快照／输入版本／处理 recipe，以及当前导出核准和许可凭据；总 row_count 仅表示导出行数之和。私有文件名、上传和修订身份单独映射，不冒充上游作者。

JSON 单文件保存 methods 与全部 rows，精确保留正文、空值、Unicode 和换行。CSV 实际交付 application/zip 成果包，内含 results.csv 与 methods.json；不是直接 .csv 下载。CSV 使用 UTF-8、无 BOM、CRLF 记录分隔和双引号转义，全部非空文本额外前置一个 ASCII 单引号，数字保持数字；方法记录 text-prefix/v1，可移除恰好一个前缀恢复文本。CSV 空列不能区分 null 与空字符串，精确区分使用 JSON。嵌套引用采用同样前缀的 JSON 文本；不承诺所有表格软件或二次另存后仍保留防护。

query 行包含查询与结果身份、固定文档／修订／句段、origin、原文全文码点、真实 token 坐标、KWIC、来源句 ID／URL／owner／license 与出处摘要。owner 表示实际上游归属人，可能未知，不保证是原作者。旧来源索引按固定成员文件单调读取署名，混合索引复用其元数据；私有来源 URL、owner 与公共 license 均为空，不制造 Tatoeba 链接。笔记导出一行固定修订，包含正文、draft／accepted 和结构化证据及查询引用，不静默升级为已接受成果。

纯生成模块不持有数据库或对象存储凭据、不自行批准许可。后端必须先核对当前项目、所有固定输入及独立 export 决定，并在发布和下载时重验；仅全文可分析不等于可导出。renderer 顺序核对每个查询实际行数与方法清单，包含零结果查询；完整跨度校验后才生成。全局 600 秒期限覆盖多查询读取和 SHA 验证，默认成品与本次临时工作区各限 512 MiB；方法对象上限 1 MiB、单行 JSON 上限 2 MiB，超出明确失败而非截断。写入和 ZIP 收尾均检查字节预算及取消。失败删除本次 partial，不发布截断文件；成功返回实际文件长度和 SHA256，持久发布由后台账本负责。

本批纯生成与既有索引读取验证、8 项真实数据库／对象存储／CWB 业务集成及运行 HTTP 闭环已通过，具体页面验收范围见验证记录。导出复用 jobs／attempt／outbox 账本，发布前复核当前授权和租约，失败清理本次固定对象；未知 PUT 不提前释放预留，撤权后不可读的已存产物仍计入项目总字节。既有完整复现包、图表、多媒体、XLSX 与模型外发仍按后续范围实施。

## 同步状态与发布一致性

```text
CHECKING -> NO_CHANGE
CHECKING -> ACQUIRING -> VERIFYING -> PARSING
  -> VALIDATING -> INDEXING -> READY
Any active stage -> FAILED / CANCELLED
Policy mismatch -> WAITING_REVIEW
Published source may later become RESTRICTED
```

调度器每次检查创建运行记录；同一目标版本仅一个有效租约。重试沿用逻辑运行，执行尝试单独记录。处理阶段使用 manifest_hash + adapter_version + recipe_digest 去重。worker 发布时同时校验 lease fencing token、取消标记、策略版本与对象完整性。

原始对象和索引先写唯一 staging 路径并完成校验，再用数据库事务将 release、snapshot 与默认指针同时发布；数据库指针只能引用完整对象。事务失败产生的孤立对象由保留期后清理，不会暴露为可分析版本。新版本只改变来源默认指针，既有 project_source_mount 不自动跟随。

记录 discovered_cursor、download_checkpoint 和 committed_cursor。只有原子发布成功才推进 committed_cursor；API 时间窗重叠读取并按稳定 ID 去重。部分下载或过滤后的列表不能用于推断删除；完整清单比对或官方撤回事件才生成 tombstone。

普通内容更新或常规移除生成新版本；若上游要求撤回、许可终止或涉及隐私，则更新访问策略、作废缓存与未交付导出、停止相关在途任务。旧快照保留可允许的摘要与运行记录，但不继续返回被撤回正文。统计结果能否继续展示单独执行策略，不默认允许。

### 质量与发布门槛

必需文件、校验和、主键、语言、空记录、乱码、重复、句对端点、CoNLL-U 结构和元数据缺失均有报告。关键文件损坏、关系断链或权利字段缺失不得 READY；允许的脏记录隔离必须形成显式排除清单及实际计数。质量阈值与采样清单在 S0 固定，不用 AI 自动“修正”原文补齐。

## 同步接口与运维契约

| 接口 | 权限与返回 | 行为 |
| --- | --- | --- |
| GET /sources | 可见目录；200 | 返回条目、能力、状态、实际已发布版本与规模；未接入字段不得伪装为零。 |
| GET /sources/{id}/releases | 按来源授权；200 | 版本、许可、质量与索引状态；仅授权元数据可见。 |
| POST /admin/connectors | 来源管理员；201 | 创建允许列表中的适配器配置；不得提交任意目标 URL 进行抓取。 |
| POST /admin/connectors/{id}/sync | 来源管理员；202 | Idempotency-Key；目标版本或 check_latest；返回 sync_run_id 与 job_id。 |
| GET /sync-runs/{id} | 管理员或获准查看者；200 | 阶段、可恢复状态、检查时间、发布版本、错误与计数。 |
| POST /projects/{p}/source-mounts | 项目编辑；201 或 202 | 固定 source_snapshot_id 与筛选；创建挂载，异步发布项目快照。 |
| POST /mounts/{id}/upgrade | 项目编辑；202 | 显式指定新版本并预览变化；新快照不覆盖旧快照。 |
| POST /admin/sources/{id}/restrict | 来源管理员；202 | 策略修订、缓存失效与访问撤回任务；审计理由。 |

同步与索引使用独立队列和磁盘配额；每来源设置并发、请求间隔、重试上限与总字节限制。遵守 Retry-After，指数退避并加抖动；不通过切换身份绕过限流。下载器校验 DNS/IP、重定向目标和 HTTPS；机构私网连接使用明确部署配置，不能开放用户任意网络探测。

监测 last_check、last_success、源版本延迟、排队与阶段时长、字节数、解析失败数、记录增删改、质量漂移、校验失败和许可状态。连续失败触发运维事件；不能把“最近检查成功”显示为“最近数据更新”。UI 对未知进度返回未知，不虚构百分比。

## 中文字符查询与统一统计语义

对标 CCL 的字距检索必须同时支持 character 与 token 单位。字符路径在选定修订的规范化正文上建立版本化位置倒排；词位路径使用 CWB/CQP。字串命中不能依赖某个分词结果碰巧切成同样的词。两条路径返回同一 canonical_text 码点坐标，保留规范化到原文的映射。

```text
{"dsl_version":"corpus-query/v1",
 "unit":"character", "within":"sentence",
 "pattern":{"type":"sequence","items":[
   {"type":"literal","value":"把"},
   {"type":"gap","min":0,"max":8},
   {"type":"literal","value":"给"}]},
 "normalization":"none", "overlap":"all"}
```

示例 gap 指两个匹配之间的 Unicode 码点数，不含两端；token 模式则是间隔词位数，是否含标点由 token recipe 固定。AND/NOT 默认同句：A 为主查询锚点，B 只过滤 A 所在句；两个 A 和三个 B 时 A AND B 为 2 命中、1 句，B AND A 为 3 命中。界面明确主查询；OR 按修订和跨度并集，纯 NOT 拒绝。二次过滤可选同段，显示窗口不改变范围。受限正则采用无回溯风险子集及超时、长度上限，不支持反向引用等未验收语法。

阶段 A 形式查询编译为受限 AST，不接受任意 CQP 命令。字符位置索引由流式构建的排序词典和压缩位置表实现候选交集，再按原正文校验字串、间距与边界；S0 在重复、标点、简繁、emoji、跨词边界和重叠命中上验证。不能满足正确性或容量目标则调整引擎后再交付，不退化为语义召回。

返回 total_hits、matched_segments、matched_documents 及 count_state；未完成总数为 null，命中按修订和跨度去重。双语分别返回两侧唯一句数、关系数和展示行数；一句中文关联三句英文时为 1、3、3，单语词频不随展开行翻倍。缺少 POS/lemma 时返回 FIELD_UNAVAILABLE，不偷偷改为词形搜索。UD 保留原始 token 层，不能用百科分词器覆盖。

### 首版分析的固定方法

字频和词频使用不同分母；2 至 4 元词组默认不跨句；共现按固定左右窗口统计并提供 logDice。两组关键词提供 log likelihood 与 log ratio，零计数处理及平滑参数写入方法版本；小样本不输出未经支持的显著性结论。所有计数在完整选定范围完成，分页仅影响展示。

历时比较使用文本年代而非同步时间；年份未知单列，标准化频率除以该年有效字符或词位数。不同来源先分层，合并必须明确去重及统计单位。图表的每个点保存 filter_spec，可复用条件检索例句。具体计数规则继续遵循后文分析算法契约。

## 首版来源与分析验收门槛

| 验收组 | 必须通过的测试 | 产物 |
| --- | --- | --- |
| 目录覆盖 | 产品来源全景全部入目录，分类及能力状态完整；聚合入口与子库不重复统计。 | 来源注册表及覆盖缺口。 |
| 真实同步 | 三类来源真实获取并发布，Wikimedia 同时有中英文；每类至少一次真实版本检查。 | 文件清单、校验和、源 ID、许可与运行报告。 |
| 更新恢复 | 新增/修改/删除、源同名换内容、断网、重复投递、取消、旧租约发布分别注入。 | 可控夹具与恢复结果；模拟更新不得冒充上游真实更新。 |
| 查询与统计 | 至少 200 条独立查询金标；字符/token边界、重叠、筛选、计数及每种统计独立参考。 | 整数一致；浮点容差及不适用输入说明。 |
| 快照与权限 | 新版本不改旧结果；跨项目、受限挂载、撤回、缓存、导出及 AI 均不可绕过权限。 | 自动测试与审计记录。 |
| 研究场景 | 中英译法对比；中文或英文子库频率比较；可从导出数字定位到结果及原文。 | 两个完整项目与方法清单。 |
| 运行 | 固定硬件测量查询、索引、同步峰值；备份恢复后重跑同一查询。 | 测量报告、资源上限及恢复记录。 |

试点建议样本量为 1 万至 5 万句对、zh/en 各 1 千至 5 千篇正文与一个核准树库。样本规模不是上游总量；正式发布须选择明确包或可复现抽样，并显示实际规模。准备阶段锁定容量预算，不能以“覆盖全部来源”推导首版必须一次处理全部互联网文本。

平台对标的是能力与方法。CCL/BCC 的原库频次不作为本平台不同数据集的正确答案；单次人工演示、静态卡片或只有下载成功均不满足发布门槛。

## 二 技术选型与替代条件

| 层次 | 推荐实现 | 选择理由与约束 |
| --- | --- | --- |
| 网页前端 | React + TypeScript + Vite | 内部研究工作台无需首版服务端渲染；通过 OpenAPI 生成类型客户端。[T01] |
| 交互与图表 | 路由 + 请求缓存 + 虚拟列表；SVG 图表 | 页面状态与服务器数据分开；KWIC 和长表分页。具体 UI 库在首个页面原型后锁定。 |
| 业务后端 | FastAPI + Pydantic；SQLAlchemy + Alembic | Python 统一连接文本处理、统计及模型；数据库迁移单独运行。[T02] |
| 关系与向量 | PostgreSQL + pgvector | 研究对象、权限、任务是事务数据；语义向量单独版本化，不能替代精确语料索引。[T03][T06] |
| 精确检索 | CWB 与 CQP Linux 工作进程 | 复用成熟词位及属性索引；由内部查询 AST 编译，用户不能执行任意 CQP 命令。[T04][T05] |
| 大文件 | 兼容 S3 的对象存储 | 保存原件、正文、Parquet、索引包和成果；私有桶。具体供应商由部署环境选择。 |
| Agent 宿主 | Node.js + TypeScript + Pi SDK | SDK 嵌入；沿用 Pi 模型层、会话与工具扩展，业务状态由 FastAPI 管理。 |
| 后台执行 | Celery + RabbitMQ；PostgreSQL 任务账本 | 队列承载投递，数据库承载状态与结果；按至少一次投递设计幂等。[T07] |
| NLP 与模型 | Stanza 起步；版本化模型适配器 | 中英文优先，基于金标选管线；预标注与人工确认分层。[T09] |
| 运行环境 | Docker Compose；反向代理 HTTPS | 首版单机或少量主机；达到明确扩容条件后再引入 Kubernetes。 |

依赖版本在开发起步时通过兼容性样例验证，锁入前端与 Node 锁文件、Python 锁文件及镜像 digest；禁止生产使用浮动 latest。这里确定技术路线，不把未经联合测试的版本号写成已验证组合。

CWB 若在真实语料的属性、许可或性能验证中不达标，先冻结 QueryEngine 的契约，再评估替代索引；不直接退化为数据库 LIKE 查询。pgvector 首版采用过滤后精确距离计算，小规模确认正确后才启用近似索引。[T06]

## 三 运行结构与模块职责

```text
Browser --HTTPS--> Reverse proxy
Reverse proxy --static--> React assets
Reverse proxy --/api/v1--> FastAPI
FastAPI --transaction--> PostgreSQL (job + outbox)
Dispatcher --reads--> PostgreSQL outbox
Dispatcher --publishes--> RabbitMQ --> Celery workers
Workers --facts and job state--> PostgreSQL
Workers --files and results--> Object storage
Query worker --exact search--> CWB + character index
Node/Pi --claim runs / tools / events--> FastAPI
Node/Pi --model requests--> configured providers
FastAPI --SSE--> Browser
```

| Module | 对外 Interface | 内部职责 |
| --- | --- | --- |
| ProjectPolicy | authorize(actor, action, resource) | 身份、项目角色、资源限制、授权撤销；所有调用统一执行。 |
| SourceRegistry / Sync | discover / sync / publish_release | 来源与许可、连接器、增量检查、清单和来源发布；阶段 A 实现。 |
| Corpus | import_batch / publish_snapshot | 原件、修订、处理清单、快照和质量报告；隐藏格式转换细节。 |
| QueryEngine | execute(query_spec, snapshot) | 校验、编译、索引加载、精确命中、分页、抽样与统计范围。 |
| Analysis | run(analysis_spec, input_ref) | 频率、关键词、搭配、分布及图表数据；固定算法版本。 |
| Annotation | commit(change_set, expected_revision) | 标注层、裁决、对齐与乐观锁；维护人工修改不变量。 |
| Execution | submit / cancel / resume / get | 投递、租约、幂等、检查点、进度、原子发布和故障恢复。 |
| ResearchAI / Pi | claim_run / tool / events / settle | Node 执行 Pi；FastAPI 管运行、权限、幂等和发布；不直接写业务库。 |
| EvidenceExport | resolve / package / export | 例句定位、结果引用、研究记录及可复现包。 |

Module 表示封装行为的模块，Interface 包含参数、前置条件、错误与一致性保证。HTTP 控制器、队列任务及 AI 工具只是调用入口，不各自重写清洗、计数或权限逻辑。用文件存储与对象存储两种 Adapter 验证存储接缝，其他可替换点只在出现实际差异时抽象。

## 四 页面与用户操作流程

| 页面路径 | 主要操作 | 持久状态 |
| --- | --- | --- |
| /login | 登录 | 服务端账号会话。 |
| /sources | 来源发现、状态与能力筛选 | 来源登记、授权条件和上游版本。 |
| /projects | 创建、查找、归档研究项目 | 项目、成员与最近访问。 |
| /projects/:p/materials | 挂载、上传、清洗、快照 | 材料修订与快照清单。 |
| /projects/:p/search | 查询、KWIC、原文 | 查询、结果集与排序。 |
| /projects/:p/analysis | 词频、关键词、搭配与比较 | 分析配置和结果表。 |
| /projects/:p/parallel | 双向查询、关系修订 | 项目覆盖层与修订号。 |
| /projects/:p/notebooks | 证据、笔记、导出 | 笔记修订与成果包。 |
| /projects/:p/tasks | 查看进度、重试、取消 | 后台任务与结果。 |
| /projects/:p/settings | 项目与成员设置 | 项目角色和配置。 |
| /admin/sources | 来源、同步、版本发布 | 连接器与同步审计。 |
| /projects/:p/assistant | 研究助手默认工作台与全部已上线业务工具 | 会话、运行、范围、证据与正式结果。 |

标注与媒体页面在后续阶段增加，首版不提供占位入口。

### 首个端到端场景

管理员配置 Tatoeba 中英句对同步，服务端发现版本、下载、校验、清洗并发布可检索来源版本。S3 学生挂载该版本并导入私有 TXT，形成混合快照，完成 KWIC、双语跳转、Pi 真实工具、笔记与 CSV/JSON 导出。S4 补 CSV/TSV/JSONL；统计与完整成果按 S5/S6 交付。再次同步生成新来源版本，旧项目结果保持不变。Wikimedia 和 UD 按同一流程完成各自适配。

### 前端必须呈现的状态

上传中、解析中、等待复核、建索引中和可分析分别显示；失败文档可以单独重试。查询同时显示命中口径、总数是否完成、当前快照和结果是否抽样。界面不能把前 100 条当作全库结果，也不能在重新分词后自动把旧结果改成新结果。

会话创建时固定 scope_kind、项目和 input_scope。改变项目、快照或对齐修订时，旧 run 不变；需继续的已授权步骤保存为 continuation_intent，在旧 run 结束后新建净化会话。只传新目标引用、步骤、参数及授权引用，不传旧正文或摘要。网页保持步骤衔接，后端仍分属不同会话。

## 五 账号权限与数据隔离

### 身份与会话

首版支持邮箱账号和 Argon2id 密码哈希；部署方可关闭开放注册。使用服务端随机会话，Cookie 设置 HttpOnly、Secure、SameSite=Lax，写请求校验 CSRF Token 与 Origin。会话只存摘要，退出及管理员停用可立即撤销。高校统一登录通过 OIDC 授权码流程与 PKCE 后续接入，不在浏览器保存模型密钥。

| 项目角色 | 允许操作 | 默认限制 |
| --- | --- | --- |
| Owner | 成员、策略、语料、研究与导出管理 | 受源材料不可导出等限制约束。 |
| Editor | 导入、清洗、建库、分析、标注、笔记 | 不能变更成员与外发策略。 |
| Annotator | 查看分配材料、提交自己的标注 | 不能下载全库或修改他人确认层。 |
| Reviewer | 查看授权结果、批注、裁决 | 是否允许查看原文由资源权限决定。 |
| Viewer | 查看、检索和分析获准材料；可保存相应执行账本。 | 不能修改材料或共享对象；导出与模型外发分别授权。 |

### 权限检查位置

所有项目领域对象携带 workspace_id 与 project_id。平台共享来源版本使用独立 catalog_scope，不伪造 project_id；项目通过受控挂载引用共享快照，具体桥接约束见同步数据模型。HTTP 读取、工作进程开始、工具调用、成果发布及下载时重新校验权限。后台任务使用发起人的受限执行身份；服务账号不能因运行任务而获得任意项目权限。项目内关联必须同项目；共享来源引用只能经过已授权的 project_source_mount，不能直接绕过项目策略读取共享对象。

PostgreSQL 对核心业务表启用 RLS 作为第二层隔离。应用账户不能拥有表，也不能有 BYPASSRLS；必要表使用 FORCE ROW LEVEL SECURITY。事务内通过 SET LOCAL 设置已鉴权的上下文，连接归还前不遗留用户状态。RLS 不能保护对象存储、CWB 或模型请求，这些仍由 ProjectPolicy 校验。[T03]

S1 使用独立 corpus_owner 执行迁移，corpus_app 处理用户请求，corpus_worker 运行受信任的任务和 outbox 投递器。运行角色均非超级用户、非表所有者且无 BYPASSRLS；worker 需要跨项目读取执行账本，但不能修改账号或项目成员。每次 HTTP 请求检查当前账号及项目权限，worker 领取、心跳和最终发布重新核对原发起人的有效状态与 owner/editor 角色；平台管理员不自动取得私有项目权限。

写操作统一按 actor、project 顺序取得事务 advisory 锁；停用账号取得同 actor 锁，修改成员取得同 project 锁。最终结果发布在同一事务取得这些锁、重新检查权限和租约，再写结果及终态，避免已撤权任务随后发布。等待锁后的业务行重新读取，不能用 ORM 缓存中的旧状态判断。

### 授权撤销后的研究记录

保留运行 ID、算法与不可读状态；不继续返回已撤销材料的原文、KWIC、引用摘录及可反推的统计结果。多来源分析要求所有输入仍可访问，否则需在新范围上重算。下载由鉴权代理执行；大型媒体的短效签名链接应有明确有效期，不能承诺发出链接后即时失效。

## 六 数据模型与不可变事实

数据库保存需要关联、鉴权和事务更新的记录；对象存储保存大内容。主键统一 UUID，时间统一 UTC timestamptz，文本统一 UTF-8。下表是核心字段契约；审计字段 created_at、created_by 适用于业务表；项目表强制项目外键，共享来源表采用 catalog_scope 和受控挂载。

| 表 | 核心字段 | 约束 |
| --- | --- | --- |
| workspaces / projects | id, workspace_id, name, status | 项目名允许重复；权限不按名称识别。 |
| project_members | project_id, user_id, role, version | 唯一 project_id + user_id。 |
| assets | id, object_key, sha256, bytes, mime, source_policy_id | 原始二进制不可变；对象键不采用用户路径。 |
| documents | id, asset_id, current_revision_id, metadata | 可编辑目录信息；不承载原始正文。 |
| document_revisions | id, document_id, parent_id, text_key, text_hash, pipeline_run_id | 正文修订不可变；语言与结构清单固定。 |
| segments | id, revision_id, ordinal, start_cp, end_cp, kind | 偏移指向该修订正文；区间左闭右开。 |
| pipeline_runs | id, input_hash, recipe_json, model_digests, output_manifest | 清洗、分词、标注各自有版本与质量报告。 |
| corpus_snapshots | id, corpus_id, manifest_hash, manifest_key, state | 仅 READY 可分析；清单发布后不允许修改。 |
| snapshot_items | snapshot_id, item_id, private_revision_id 或 mount_item_id, token_layer_id | 恰好一种成员引用；固定来源、token 层和元数据副本。 |
| index_builds | id, snapshot_id, engine_version, index_key, manifest_hash, state | 同一索引键只发布一次；数据可重建。 |

原件按项目范围去重，禁止通过跨项目哈希查询泄露文件是否存在。内容相同不代表来源相同，source_records 保留每次获取方式和授权信息；共享来源内与私有项目内分别去重，不建立可被普通用户查询的跨租户文件存在性接口。元数据修改不改写已发布快照；通过新快照影响后续分析。

## 七 标注研究与运行数据模型

| 表 | 核心字段 | 关系与规则 |
| --- | --- | --- |
| annotation_schemas | id, version, labels, relations, constraints | 方案发布后不可变；改标签生成新版本。 |
| annotation_layers | id, revision_id, schema_id, owner_id, kind, head_version | manual、model、adjudicated 分层。 |
| annotation_commits | id, layer_id, parent_id, changeset, revision_no | 追加写；唯一 layer_id + revision_no。 |
| source_alignment_edges | source_release_id, edge_id, source_segment_id, target_segment_id, provenance | 共享来源边属于来源发布版本，不带 project_id；发布后不可改写。 |
| alignment_overlays | project_id, snapshot_id, source_release_refs?, revision | 项目覆盖层追加修订；纯私有材料无需来源挂载；分析固定 revision。 |
| query_runs / result_sets | snapshot_id, canonical_spec, engine_version, result_key, completeness | 结果记录绑定查询与稳定顺序。 |
| analysis_runs | input_ref, method_version, params, denominator, result_key | 输入可为快照或结果集；保存实际范围。 |
| evidence | revision_id, span, quote_hash, run_id, row_key | 证据引用原文或结果行；每次访问鉴权。 |
| notebook_revisions | note_id, parent_id, content, evidence_ids | 笔记修订引用证据，不只存链接文本。 |
| jobs / job_attempts | actor_id, kind, state, lease_token, checkpoint, deadline | 一个逻辑作业有多个执行尝试。 |
| outbox / job_events | event_id, job_id, sequence, payload | 事务消息与恢复事件；按序列号去重。 |
| agent_sessions / runs / tool_invocations | session_id, input_scope, lease, invocation_id, job_id, result_ref | Pi 上下文归档；业务账本、调用与事件由 FastAPI 管理。 |
| export_manifests | snapshot_ids, run_ids, hashes, format, policy_digest | 导出时重新鉴权；记录缺失或禁止内容。 |

人名、说话人真实身份等敏感映射独立表保存，默认不进入分析正文或模型上下文。annotation_spans 等高频读取投影可从提交历史重建；正文、人工提交历史、原件与关键结果是恢复时优先保护的事实数据。

## 八 数据库约束与事务示例

下面展示私有或共享快照成员与幂等键的 SQL 形态。正式迁移还需项目复合外键、挂载来源归属、token 层所属修订验证及 RLS；跨多个挂载指向同一源修订时，清单构建阶段按实际修订去重。片段不是完整初始化脚本。

```text
CREATE TABLE snapshot_items (
  project_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  item_id uuid NOT NULL,
  private_revision_id uuid,
  mount_item_id uuid,
  token_layer_id uuid NOT NULL,
  metadata_hash text NOT NULL,
  CHECK ((private_revision_id IS NOT NULL) <>
         (mount_item_id IS NOT NULL)),
  PRIMARY KEY (snapshot_id, item_id),
  UNIQUE (snapshot_id, private_revision_id),
  UNIQUE (snapshot_id, mount_item_id)
);

CREATE TABLE idempotency_records (
  project_id uuid NOT NULL,
  actor_id uuid NOT NULL,
  operation text NOT NULL,
  key text NOT NULL,
  request_hash text NOT NULL,
  job_id uuid NOT NULL,
  PRIMARY KEY (project_id, actor_id, operation, key)
);

CREATE INDEX jobs_ready
  ON jobs (queue_name, available_at)
  WHERE state = 'QUEUED';
```

### 必须由事务维护的不变量

同一事务插入作业、幂等动作与 outbox 事件，再提交。S1 幂等作用域为 project、actor、operation、Idempotency-Key；服务端分配 action_id 并保存请求摘要。相同作用域、键和参数返回原响应与原作业，异参返回 409 IDEMPOTENCY_CONFLICT。完整上传会话只关联一个校验作业，换键也不重复创建。手动调用不要求 Pi run_id。幂等记录至少保留到作业与结果被清理；读取或复用旧响应前仍检查当前权限。

snapshot_items 对私有修订使用项目复合外键；共享成员通过 mount_item_id 外键引用已锁定的来源修订，二者必须恰好有一个有效。发布快照时锁定草稿，固定成员与元数据版本；索引校验完成后单次事务切换为 READY。运行记录只能引用 READY 快照和已发布标注版本。

人工修改以 expected_revision 提交，更新条件包括当前修订号；影响行数为零返回 409 EDIT_CONFLICT，并返回最新版本供合并。绝不通过最后写入者胜出静默覆盖。数据库迁移使用 expand、backfill、contract 三步，收缩操作另一个发布窗口执行。

## 九 正文坐标与语言处理

### 统一定位规则

每个 document_revision 的 canonical_text 是唯一定位基准。字符偏移按 Unicode 码点计数，采用左闭右开区间；不能使用 UTF-8 字节数或 JavaScript UTF-16 下标替代。浏览器维护码点与 UTF-16 的转换表，选择区域后转换再提交。组合字符和 emoji 以字素边界校验，存储仍用码点。

PDF 保存页号、字符到页坐标的映射和映射置信度；OCR 保存文本区块与图像框。清洗记录原文区间与新正文区间的映射，允许一对多、多对一和无法精确定位。无法精确定位时展示来源页或段，不伪造字符级定位。

| 数据 | 表示 | 规则 |
| --- | --- | --- |
| token | token_id, segment_id, start_cp, end_cp, form | 顺序固定，定位回正文；标点是否入统计单独配置。 |
| 词位属性 | lemma, upos, xpos, feats | 缺失值明确标为缺失，不能自动等于词形。 |
| 依存关系 | sentence_id, token_id, head_id, deprel | 不等同普通相邻窗口；根节点和空节点单独处理。 |
| 时间锚点 | media_id, start_ms, end_ms, channel | 整数毫秒，原始精度同时记录；不和文本偏移混用。 |
| 向量片段 | revision_id, span, model_digest, dimensions | 切块与嵌入分别版本化；全文修订后不复用旧偏移。 |

### 中英文与其他语言

首期支持 UTF-8 中文与英文，发布明确的分词规则和中英文测试集；复合词、缩写、标点、大小写和数字都写入 recipe。首期可以使用导入的 lemma 与 POS，自动管线在专业分析阶段完善。Stanza 作为多语言管线起点，但每个语言与模型需独立验收。[T09]

NFC 等规范化生成新修订并保留映射，不原地改写正文。分词改变会生成新的 token_layer_id 与索引；旧标注不按新词序自动迁移。人工迁移经过差异预览与确认，无法映射的跨度进入待复核列表。

## 十 上传与建库流水线

```text
UPLOAD -> VERIFY -> EXTRACT -> CLEAN_DRAFT
       -> REVIEW -> TOKENIZE -> BUILD_INDEX
       -> VALIDATE -> PUBLISH_READY
```

| 步骤 | 执行内容 | 失败与恢复 |
| --- | --- | --- |
| 申请上传 | 校验项目额度，创建 upload_id，S1 返回同源受限 PUT 地址 | 上传会话有期限；只可访问自己的对象键。 |
| 传输与完成 | S1 固定对象版本并创建异步校验任务；真实读取大小、SHA256 和 UTF-8 文本 | ETag 不当作 SHA256；重复完成幂等；结构解析在后续导入阶段。 |
| 隔离解析 | 允许格式列表；限制解压体积、页数、耗时 | 无网络低权限容器；失败文件隔离，其他文件继续。 |
| 提取清洗 | 记录解析器、规则、编码、原文映射与重复候选 | 按文档检查点恢复；正文过少或乱码率高则待复核。 |
| 人工检查 | 用户选择保留、排除、修改规则、脱敏 | 批次报告保存决定，不能默认隐藏失败材料。 |
| 构建索引 | 固定快照清单，生成词位文件和索引包 | staging 区构建；未完成索引永远不可查询。 |
| 校验发布 | 核对 token 数、文档数、摘要和抽样定位 | 通过后写发布指针，旧索引继续服务历史运行。 |

首期用户导入为 UTF-8 TXT、CSV、TSV、JSONL；来源连接器同步支持各自所需 XML 和 CoNLL-U。通用 DOCX、PDF、HTML、OCR、TEI、TMX、XLIFF 与媒体在后续阶段扩展。每个导入器声明可读、可写、可无损往返三个不同能力，不支持字段写入 loss_report。

### 输入限制与网络导入

文件名仅作展示，拒绝路径穿越、超限压缩包、宏执行与 XML 外部实体。预览 HTML 必须清洗并隔离，不在主站域执行。远程 URL 导入经出口代理验证协议、解析 IP 与每次重定向，阻断内网、元数据地址和 DNS 重绑定。[T08]

S1 单文件默认上限为 100,000,000 字节，项目上传字节准入默认为 1,000,000,000 字节，均可由部署参数调整。申请会话时在项目锁内汇总预留和已存储字节，避免并发超额。尚未使用的 CREATED 会话过期可释放预留；已存储、失败或取消对象保守占用额度，自动保留期清理尚待实现。限制是资源保护参数，不代表已验收吞吐能力。后续批量及媒体额度另行实现。

### S1 私有单文件校验

本轮真实流程为登录、创建或进入项目、申请上传会话、浏览器传输、complete 创建持久任务、读取或取消任务、取得已校验暂存材料。SUCCEEDED 的结果明确为 VALIDATED，只证明原件完整性及基本文本条件；不生成 READY 材料、正文修订、解析结果或索引。TXT、CSV、TSV、JSON 和 JSONL 的声明类型可接受，但 CSV/JSON 的结构有效性尚未在本切片验收。

POST /projects/{p}/uploads 固定文件名、大小、声明类型和 SHA256，返回 upload_id、action_id、同源 PUT 地址与 30 分钟期限。对象键由服务器随机生成，客户端不能指定。PUT /uploads/{id}/content 仅创建者且仍有项目写权限可用；Content-Length 必须符合会话，实际流每块检查大小，接收限时 120 秒。超过 1 MiB 的临时内容转入仓库 tmp 下的有界临时文件，传输结束或失败关闭删除。

私有桶必须启用版本控制。成熟 S3 客户端以 IfNoneMatch=* 创建对象，保存响应 VersionId 和 ETag；同一会话一旦开始传输就不允许再 PUT 覆盖，失败需新建会话。未取得有效 VersionId 不标为上传完成。后续校验始终按版本和 ETag 读取，数据库只发布该固定版本的引用，避免最新对象被替换时混淆校验结果。[T14]

POST /uploads/{id}/complete 不执行同步全文校验，幂等提交后返回 202、action_id 和 job_id。真实 worker 逐块读取固定对象，检查总大小、SHA256、UTF-8 编码和 NUL 字符；读取错误保存可人工重试的失败，大小、摘要或文本错误明确失败且无结果。GET /jobs/{id} 与按 sequence 分页的 JSON 事件接口读取持久账本，刷新页面可恢复；本切片尚未交付 SSE 订阅。

本轮真实 PostgreSQL、MinIO 和 RabbitMQ/Celery 的 10 项集成检查通过，另有 3 项单元测试及 5 个子用例；主审独立执行常驻服务的 6 组 HTTP 检查通过。证据见 tests/integration/results/2026-10-16-upload-pipeline.json。验证包括幂等、跨项目与只读拒绝、对象版本、真实摘要错误、投递失败恢复、取消、撤权发布拒绝、租约过期及有限重试；不替代生产部署、解析或索引验收。

## 十一 精确索引与版本发布

### CWB 索引设计

以快照为索引发布单位，将固定顺序的文档展开为词位流。p 属性存 form、folded_form、lemma、upos 等，s 属性保存文档、句子和段落边界。cpos 到 token_id、revision_id 与字符区间的映射另存压缩列式文件；生成器同时产出计数摘要。[T04][T05]

新来源版本完整建索引，首版不做在线增量合并。整库挂载在正文、token 层、顺序与处理配置一致时复用来源索引；子集或混合快照按配额另建。索引键含引擎、字符或 token 单位、规范化、recipe、有序修订及 token 层摘要，不能只比较原件哈希。元数据清单另行固定；READY 前不替换默认快照。

### 查询进程隔离

CQP 在受限工作进程中运行，仅挂载指定快照索引和可写临时目录，无外网、无数据库管理凭证。服务端生成 registry 标识与参数，禁止拼接 shell。AST 编译器仅输出允许的检索表达式，拒绝系统命令、宏定义、任意文件读写和重定向。

每个工作进程同一时间只执行一个查询，不复用带有上次用户结果或活动语料状态的会话。超时终止子进程并清理临时文件。请求包含语法复杂度、最大结果体积与最大执行时限；受限结束必须返回 incomplete，不将部分计数写为总数。

### 索引与对象一致性

对象存储中的不可变索引包是发布物，查询主机使用有容量上限的 SSD 缓存。下载后按 manifest 校验，完成原子目录切换后使用。数据库只引用已验证包；失败包可重建。对象上传成功但事务未提交形成孤儿，由延迟清理任务回收。

### 容量策略

海量 token 不逐条写入 PostgreSQL 主业务表。正文结构与可编辑标注进库，token 属性和大结果进入 Parquet 等列式文件与 CWB 索引。以 1000 万 token 样本测量索引、映射、向量与多版本磁盘放大，再计算高校部署容量；不得按原始文本体积直接估算总盘。

## 十二 查询语言与结果契约

### 受支持的查询子集

普通检索编译成内部 AST。首版完整目标包括词形精确值、词位序列、允许属性的等值和正则、有限间隔、句内约束及快照元数据过滤；当前 S3 可执行子集见“研究快照与持久查询结果”，以下带 filters 的示例保留为后续目标。语法标识为 corpus-query/v1，不宣称完全兼容 CQL 或 CQP。

```text
{
  "dsl_version": "corpus-query/v1", "unit": "token",
  "pattern": {
    "type": "sequence",
    "items": [
      {"type": "term", "attr": "form",
       "op": "eq", "value": "climate"},
      {"type": "term", "attr": "form",
       "op": "eq", "value": "change"}
    ]
  },
  "within": "sentence",
  "overlap": "all",
  "filters": {"genre": ["academic"]},
  "sort": ["document_ordinal", "start", "end"]
}
```

词形 eq 编译为字面值匹配，不能直接继承 CQP 属性值默认正则的语义。[T05] 首期查询仅允许可确定去重语义的模式；相同文档内相同起止跨度只算一次，不同重叠跨度分别计数。实现必须用金标验证引擎匹配策略，不能依赖引擎默认行为。

### 完整性与分页

result_set 保存命中跨度、稳定序号、input_manifest 和 completeness。total_hits 在完整执行前为 null，count_state 为 pending；complete 后才返回整数。本切片使用参数摘要绑定的校验游标，固定结果集、查询摘要、快照 manifest、排序、页大小和 attempt；不是密钥签名，也不授予权限，每页仍独立鉴权。不匹配返回 422 INVALID_CURSOR。当前结果不自动到期，后续保留策略及 410 RESULT_EXPIRED 另行实现。

全量大结果异步生成。抽样以已完成结果集为输入，保存 seed、算法与抽中 hit_id，默认 reservoir/v1 或固定哈希排序抽样；样本频率不能冒充全库频率。研究笔记引用的结果进入保留策略，临时缓存过期不应破坏已归档证据。

## 十三 统计口径与可验证计算

| 指标 | 计算契约 | 必须展示 |
| --- | --- | --- |
| 词频与文档频率 | 词位计数；文档频率对 revision_id 去重 | 有效 token 总数、文档总数、排除规则。 |
| 标准化频率 | 每百万词 = 词频除以有效 token 数再乘 1000000 | 零分母返回 null 和原因；不返回 0。 |
| 关键词 | 目标与参照的二乘二计数；G 检验或预设方法 | 原始频数、效应量、检验方法与校正。 |
| 窗口搭配 | 固定左右窗口与句边界；按位置对统计 | 窗口机会数、节点与搭配项边际计数。 |
| 语法搭配 | 按已选依存关系抽取有方向词对 | 管线版本、关系定义、缺失分析比例。 |
| 词汇丰富度 | TTR 与固定窗口 MATTR 分开 | 窗口大小、步长、短文本处理规则。 |
| 分布与趋势 | 按文档或元数据组汇总 | 组样本量、时间粒度与缺失值处理。 |

### 统计实现的固定规则

所有计数使用整数。词频默认排除标点但保留数字，大小写合并、词形归并与停用词作为显式开关；“过滤输出行”与“改变统计分母”必须是两个参数。输入快照使用相同分词规则时才允许默认比较；不同规则提示并要求选择统一处理方案。

关键词 G 检验使用未平滑的二乘二表，零观察量的项贡献定义为零；空语料拒绝计算。A 阶段将 G 值用于探索排序，不自动发布显著性判断。log ratio 定义为两组标准化频率比的 log2；仅在任一目标词计数为零时，对四格各加 0.5 并重算两组分母，记录 smoothing=haldane-anscombe/0.5。B 再扩展推断检验、BH 校正及精确方法。

搭配 v1 将全部合法有向位置对定义为样本空间：f_xy 是节点 x 到词 y 的位置对数，f_x 和 f_y 是同一空间的边际频数。A 的 window-pair/logDice-v1 = 14 + log2(2*f_xy/(f_x+f_y))，仅对 f_xy>0 输出。该方法明确采用位置对边际，与采用词项出现频数的实现不直接对分；界面和导出保留方法名及公式。B 的 MI、t-score 也必须声明样本空间。[T12]

每个算法交付可手算的小样本、独立参考实现和异常测试。与外部工具对比先对齐分词、窗口、边界、平滑和过滤条件；不承诺不同口径下数值相等。图表仅使用已完成结果表，不由 AI 生成数字。

## 十四 标注与双语协作

### 人工标注提交

人工编辑在浏览器形成 change_set，包含创建、删除、改标签与关系变更。服务端校验文本修订、跨度、方案版本和 expected_revision，在单一事务内生成 annotation_commit 并更新读模型。撤销也是新提交，不删除历史。自动预标注存模型层，确认时复制为人工提交并保留 provenance。

多人先采用文档或标注任务分配加乐观锁，首期不实现实时协同光标或 CRDT。标注员看不到他人未完成标签，提交后进入复核；一致性统计按任务共享的同一文本和同一方案计算。类别、跨度和关系标注分别选匹配规则，不能用一个一致率覆盖全部类型。

### 平行语料模型

共享 source_alignment_edges 固定来源版本及句段。项目 alignment_overlays 以 project_id、snapshot_id 为范围根；source_release_refs 和共享基础关系可选，纯私有材料不要求挂载。项目提交追加修订，分析固定 overlay revision。首版支持自动一对一候选与修订，复杂关系只读；端点都必须属于固定材料范围。

| 操作 | 规则 | 版本结果 |
| --- | --- | --- |
| 自动对齐 | A 生成一对一句级候选；保存方法、参数、匹配分数与未配对结果。 | 写入 candidate_set；不覆盖 confirmed。 |
| 项目关系修订 | 首版一对一；新增记录端点，替换或拒绝引用基础边 | 项目覆盖层新修订；后续扩展拆分合并。 |
| 确认或拒绝 | 记录候选或边 ID；人工确认关联用户核对的消息或事件。 | human_confirmed 或 rejected；自动候选为 proposed。 |
| 重跑模型 | 只更新建议层或生成新建议版本 | 人工确认结果不被覆盖。 |
| 导出 TMX | 明确段落拼接、空对齐、标注丢失规则 | 保存 loss_report 与原始关联 ID。 |

来源升级后生成迁移候选，确认不自动继承。甲项目修改不改变乙或旧运行。双语返回两侧唯一句数、matched_edges 和 display_rows；一个中文句连三个英文句时为 1、3、3，单语词频按唯一材料计数。导出保存边 ID、覆盖层版本与 counting_unit。

### 首版自动对齐任务

alignment.start 输入固定 snapshot_id、两侧句段范围、语言和 recipe_version，返回 accepted 与 job_id。Celery 使用部署许可内的版本化算法生成 candidate_set_id、稳定 candidate_id、端点、匹配分数、复查原因及未配对清单。方法验证覆盖私有 TXT 与共享材料，复杂对应只报告、不强制凑对。

alignment_runs 和 alignment_candidate_sets 保存输入、方法及候选结果。候选先在独立候选修订中审阅、修改或舍弃，再以 add 纳入覆盖层；已有边才使用 replace、reject、confirm。alignment.layers.create 绑定项目快照，commits 校验版本、引用及端点并返回 overlay_revision、changed_edges 和 scope_effect。未核对候选保持 proposed，明确核对才记 human_confirmed。

## 十五 多模态与格式互通

### 媒体管线

原媒体作为不可变 asset；另生成浏览器播放代理、波形与缩略图，保留转码参数和原始时间映射。ASR、说话人分离、词级时间戳和人工转写各自成层。转写修改不能悄悄改变媒体时间，低置信度片段进入复核列表。

时间轴读取按区间分页，浏览器仅加载可见区间；播放器与选择区间通过同一 media_id 和毫秒坐标同步。多轨媒体保存 channel，时间拉伸、裁切和拼接必须有源时间映射。媒体作业与文字检索隔离队列，GPU 不成为基础建库的必要条件。

| 格式或能力 | 内部映射 | 验证方式 |
| --- | --- | --- |
| ELAN EAF | tier、父子关系、受控词表、时间锚点 | 导入导出后对齐结构与时间；不支持项报告。 |
| Praat TextGrid | interval tier、point tier 与精度 | 空区间、重叠规则、首尾时间和编码样本。 |
| CoNLL-U | 词位、词形、属性、依存关系及 MISC | 保留多词 token、空节点与原行映射。 |
| TEI XML | 文档结构、标注、命名空间及原片段 | 按明确支持 profile 验证，未知扩展留存。 |
| TMX 与 XLIFF | 双语单元、语言、内联标记与状态 | 标签配对、语言代码、空对齐和重排。 |
| 声学分析 | 媒体范围、参数、工具与测量结果 | 原音频可重放；采样率和预处理记录完整。 |

### 插件执行约束

格式适配器声明 schema_version、输入 MIME、输出 profile 和能力等级。外部 Praat、OCR 或 ASR 进程通过固定命令模板与资源限制执行，不把用户文字插入命令行代码。模型文件、可执行程序和数据集分别登记许可证与校验值。

浏览器支持的播放格式与服务器支持的输入格式不同，解析成功不等于可播放。上传完成后返回兼容性状态，转码失败保留原件与失败原因，不生成不可播放的成功记录。

## 十六 后台任务与故障恢复

```text
QUEUED -> RUNNING -> SUCCEEDED
RUNNING -> WAITING_REVIEW -> QUEUED
RUNNING -> RETRY_WAIT -> QUEUED
RUNNING -> FAILED
Any nonterminal state -> CANCEL_REQUESTED -> CANCELLED
```

### 投递与占有

事务 outbox 扫描器将 job_id 投递到持久队列，消息确认后记投递状态；重复投递正常存在。工作进程通过数据库条件更新领取租约，生成递增 fencing_token。心跳建议每 15 秒一次，租约 90 秒；超时后重排前先检查已有结果。Celery 的 late acknowledgement 不能单独提供业务上的恰好一次。[T07]

S1 上传校验使用 QUEUED、RUNNING、SUCCEEDED、FAILED、CANCELLED。每个逻辑 job 保存独立 attempts 和单调事件；outbox 按 job/attempt 去重，发布写入与确认等待各限 5 秒，确认后才记已投递。broker 不可达保留待投递记录，间隔 5 秒且每次执行尝试最多 20 次失败，随后明确 DELIVERY_FAILED，不无限重试。

worker 领取生成递增 lease_epoch 和随机 token，租约 90 秒，流式校验每 15 秒续租。重复消息不能重复领取或发布；取消事务立即清除租约并提交 CANCELLED，旧进程只能停止读取或被最终发布检查拒绝。租约过期明确失败，允许的人工 retry 沿用逻辑 job 并新增 attempt，最多 3 次，保留旧失败记录；摘要等不可修复错误需重新上传。发起人或项目负责人操作时仍须具有写权限。

### 检查点与结果发布

作业分为可恢复阶段，每阶段记录输入摘要、工具版本与输出校验值。工作进程写 staging 对象，完成后上传不可变结果；数据库事务校验当前 fencing_token、取消标记和授权，再发布 result_ref 与成功状态。旧租约进程即使晚返回，也不能发布结果。

数据库与对象存储没有跨系统事务，因此通过不可变对象、发布指针和孤儿清理解决中间状态。消费者只读取已发布引用。取消先记录请求，在安全检查点退出；不支持中断的外部程序达到超时后终止，未发布结果隔离清理。

### 重试与公平性

网络超时、短期限流和暂时资源不足使用带随机抖动的指数退避，默认最多 3 次；文件损坏、参数不合法和权限撤销不重试。AI 外部调用若超时但结果未知，不自动重复执行有副作用的操作，记录 UNKNOWN 并进入核查。

Celery 按业务任务类型分 sync、ingest、query、analysis、NLP、media、export 队列，不运行 Agent 循环。Node/Pi 通过内部 API 领取运行；首版按实际负载配置工作进程。首版设置每项目并发上限与全局限额，优先保障交互查询。任务额度只用于资源调度，不涉及收费。队列崩溃可依据数据库未完成账本重新投递；浏览器连接不承担任务存活责任。

## 十七 Pi 执行与来源约束

### 宿主与工具边界

采用 @earendil-works/pi-coding-agent SDK 嵌入 Node.js/TypeScript 服务，沿用 Pi 模型层、SessionManager、工具和 Skills。S0 锁定 SDK 与 Node 版本；不引入第二套 Agent 框架。Pi 选择和组织业务动作，Celery 执行同步、清洗、索引、对齐、分析及导出。

```text
Browser -> FastAPI -> persisted Agent run
Node/Pi -> claim run -> model loop
  -> FastAPI tools -> business result / Celery job
  -> evidence validation -> session archive
FastAPI -> publish result -> SSE -> Browser
```

浏览器和 Pi 共用 FastAPI 业务服务。执行凭据由服务端绑定 actor、account/platform/project 作用域、会话、运行、工具及外发范围；模型不能改写身份。平台同步只向相应管理员开放，管理员不因此取得私人项目读取权。原文中的指令属于资料，不影响宿主权限。

### S1 运行身份与调用账本

本轮 S1 已实现受限执行身份与运行账本基础，尚不开放生产研究工具。会话固定 account、platform 或 project 范围；当前只接受空材料引用，任何 snapshot、material revision、result ref 或 alignment overlay 均明确拒绝。平台工具要求当前管理员，project 工具检查当前成员角色，管理员不获得私人项目特权。

新增 agent_sessions、agent_runs、agent_credentials、agent_invocations 与 agent_events 表，均启用 FORCE RLS。数据库约束与 session/run 锁保证同一会话只有一个活动运行；每次领取递增 epoch。受信宿主用独立密钥领取，服务端生成随机执行 token，仅存摘要，绑定 actor、session、run、scope、工具及期限。租约 60 秒，宿主 15 秒续租，凭据 300 秒；本 S1 切片当时未提供续期或常驻宿主，后续 K09 实现见下节。

固定工具分派复用手动业务 handler，在严格校验 actor 的 bound_transaction 中共享同一 PostgreSQL 事务；不跨线程共享 Session。服务端分配 invocation_id/action_id，SDK toolCallId 只作关联；已有业务 action 时使用同一标识。相同登记键和参数返回旧结果，防止已提交写入在响应丢失后重做；savepoint 保存失败调用并回滚业务错误。模型不能指定身份或任意 HTTP 目标，上传结果不含传输地址。

执行前与提交前均检查当前权限、epoch、取消和期限；慢调用跨过期会回滚全部业务写入。取消在同一事务中处理独占上传作业并使本人运行失效；降为 viewer 后仍可停止本人运行，子作业无权取消时记录明确结果，不阻断运行取消。材料权限撤回仍阻止后续工具及 worker 发布。

真实 PostgreSQL 的 10 项测试通过，其中单写由两个独立进程和连接竞争验证，覆盖响应丢失重放、SQL 错误恢复、撤权、双作业取消和事务身份清理。主审另以真实 Pi SDK 1.3.0、两次固定模型请求、HTTP 和 PostgreSQL 验证账号读取与 6 个持久事件；永久证据见 tests/api/results/2026-10-16-agent-runtime.json。固定模型未使用付费或外部模型，不能推定真实模型质量。

上一身份账本切片在缺检查点时进入 WAITING_REVIEW／CHECKPOINT_NOT_IMPLEMENTED，该历史验证保留。当前新增私有不可变检查点、完整上下文对账与条件成功发布，具体实现和受限范围见下节；公开 available_tools 继续为空。

### S1 私有检查点与完整会话接续

新增 agent_checkpoints 和 session 最新检查点、run 基线及最终检查点引用。检查点绑定 actor、session、run、租约 epoch、SDK 会话 ID、末节点、运行清单、调用与项目依赖；复合外键和 FORCE RLS 隔离归属，检查点行只允许创建和读取。模型不选择对象键，不取得存储凭据或执行 token。

当前接收最多 8 MiB 的 UTF-8 Pi v3 JSONL，HTTP 信封另限 16 MiB。只支持固定 SDK 1.3.0、固定本地模型与受审资源配置下的线性、未压缩会话；分支、压缩及其他节点类型明确拒绝，不丢弃节点后伪装完整上下文。首归档 SDK 会话 ID 必须与业务 session 一致，续接必须逐条保留固定基线且实际追加内容。

归档逐个核对 toolCallId、工具名、参数摘要、invocation_id、结构化结果和模型可见文本；当前运行已提交的调用不得遗漏，也不能引入其他 session 或未发布运行的结果。已记录的普通工具失败可由模型处理，但未知调用和未解决的工具调用阻止完整检查点。历史项目引用由实际业务结果导出，读取归档、模型请求前检查及发布时重新验证权限。

对象先以服务端随机键和 IfNoneMatch=* 写入私有版本桶，再按固定 VersionId、ETag、实际字节数及 SHA256 回读校验。只有当前租约、授权、取消状态、基线和 settled 边界仍有效时，才在 PostgreSQL 事务中条件切换指针并发布 SUCCEEDED。对象成功而数据库未提交只留下未发布对象，不形成可恢复指针；自动保留期清理尚未交付。重复成功请求返回原检查点，不创建第二成果。

新运行固定最新已发布检查点。Node 校验运行清单、字节摘要和节点身份，将归档复制到 session／run／epoch 隔离目录，再用受支持的 SessionManager.open 打开工作副本；原下载归档不交给可写会话。prompt 完成、事件提交与调用对账结束后，从实际持久文件生成下一检查点，不将 message_end 或仅内存消息视为落盘完成。

必要 accepted 作业仍须按原 job_id 核查真实终态，成功结果还须被 jobs.get 读取并进入当前 SDK 上下文；作业未完、失败或取消时不发布运行成功。agent_end 不能替代 agent_settled；迟到归档和终态提交不能越过取消、撤权或旧租约。本 S1 检查点切片当时只验证已完成检查点的后续运行接续；后续 K09 补充可靠 WAITING_JOB 接续。任意运行中崩溃没有可靠上下文时仍进入 WAITING_REVIEW。

本轮 9 项真实 PostgreSQL／私有对象存储测试及 2 项格式测试全部通过；运行服务上的两个独立 Node 进程均发布成功，第二次继承实际项目结果且没有重放工具。永久证据见 tests/api/results/2026-10-16-agent-checkpoints.json。仍使用固定模型且不访问外部模型，保持空材料范围；不以归档通过推定真实模型质量、模型外发许可、分支恢复、常驻宿主或生产研究工具已验收。

### K09 常驻宿主与可靠等待接续

本切片继续复用 Pi SDK 1.3.0、既有调用账本和私有线性检查点，新增持久用户消息及常驻 Node 单并发宿主。提交运行必须携带 message、request_key 和固定 scope_digest；首段只提交该持久消息，恢复段只提交服务端生成的 continuation_message，不重复原始写入意图。运行清单升级为 corpus-k09-linear-v1，不兼容的旧清单明确拒绝，不静默改写历史归档。

前一运行基础切片默认 AGENT_RUNTIME_MODE 为 unconfigured，API 不接受新运行，宿主存活探针可返回 200，但就绪为 503，且不领取任务。该切片仅显式 fixture 配置允许固定本地模型；Node 还要求 AGENT_ENABLE_LOCAL_FIXTURE=true。常驻 fixture 对普通消息只返回测试答复，不推断或执行写入；真实上传验收场景通过受信测试进程输入，且必须与持久消息中的测试意图和 upload_id 完全一致。该 fixture 宿主不取得数据库、对象存储或外部模型密钥，内部 HTTP 只额外允许明确配置的 http://api:8000。

宿主顺序领取一个运行，默认每 2 秒轮询；租约 60 秒、每 15 秒心跳。执行凭据有效期 300 秒，每 120 秒申请续期，续期不能越过当前 900 秒活动段；等待总期限固定为 24 小时，恢复创建新的活动段并提升 epoch。SIGTERM／SIGINT 停止领取并中止 SDK；SDK aborted、失权、取消、过期或未知调用都不能发布成功。事件使用稳定 event_id，传输失败仅作有限同键重试；不自动重启业务作业。

accepted 工具结果只表示原业务任务已受理。宿主等待实际 agent_settled 和持久会话文件完成，核对调用账本后上传完整私有检查点，再 suspend 为 WAITING_JOB。服务端从已记账调用推导必要 job 及报告工具，释放运行租约并保存 resume_checkpoint；会话 latest 仍指向上次成功结果。即使业务任务已快速结束，未读入 SDK 上下文也不能直接宣告成功。

原业务任务终态后，新进程领取同一 run，取得更高 epoch 和新执行凭据；原凭据不可继续写入。宿主校验并复制 resume_checkpoint 到本次独立目录，再用 SessionManager.open 恢复，原归档不写。恢复只调用服务端指定的报告工具读取原 job，确认结果进入上下文后才允许 settle；失败或取消的业务任务进入明确 JOB_NOT_SUCCEEDED 待核查，不误报归档损坏，也不重做原写入。最终成功才切换 latest。常驻宿主完成或失败后删除本次本地工作副本，私有对象归档由服务端保管。

本批迁移 0014 已应用，运行基础、检查点和等待专项共 29 项通过，其中 27 项使用真实数据库／私有存储，2 项为格式测试。默认 Node 24.15.0 宿主已实际验证存活与未配置就绪状态；两个独立进程跨 WAITING_JOB 的真实上传校验接续和本地 fixture 工作台核心交互已通过。可靠 settled 边界之外的任意崩溃恢复、分支／压缩、真实 provider、材料 scope 及模型外发尚未验收，production_available 保持 false。

### K09 兼容模型协议接入

模型配置由服务器维护，运行模式区分 unconfigured、fixture 和 openai-compatible。兼容模式直接复用 Pi 1.3.0 的 openai-completions 或 openai-responses 内置适配器，不另写流式协议解析器；文本及工具调用使用同一个 segment、调用账本、settled、检查点和 WAITING_JOB 生命周期。真实服务尚未提供地址、模型与协议，本批仅对本机合成 HTTP SSE 服务执行验证，不据此宣称真实模型服务、质量或材料外发已通过。

固定配置包含协议、服务地址、模型、上下文窗口、输出上限、请求期限及本机 HTTP 开关。默认上下文 8192、输出 1024、请求 60000 毫秒；这只是本地保守配置，不代表服务商实际容量。紧凑 JSON 数组的 SHA256 固定 config_id，运行清单同时绑定 model_api 与配置摘要。变更后新运行与恢复必须精确匹配，不把 fixture 历史归档改成真实模型档；历史仍按当前权限读取，旧会话不能直接用新配置执行，返回 AGENT_CONFIG_CHANGED。

服务地址仅允许 HTTPS；显式测试开关才允许 localhost、127.0.0.1 或 [::1] 的 HTTP。拒绝用户信息、查询参数、片段、反斜杠与空白；实际模型请求只能访问配置的固定协议端点，拒绝重定向。API 只读取无密钥配置，模型密钥只由 Node 从进程环境读取并置入内存凭据；部署宿主令牌、业务执行凭据不发送给模型。缺模型密钥的宿主明确不就绪且不领取，API can_submit 仅表示配置允许受理，不能证明宿主存活。

显式注册固定模型和受限业务工具，关闭隐式资源扫描、通用文件与命令工具、compaction、cache warming 和模型自动重试。每次模型请求前重新心跳检查权限与租约，每活动段最多 16 次模型请求。Chat Completions 显式使用 max_tokens，Responses 使用内置 store=false；总请求期限同时约束响应流。SDK 仍负责文本、工具参数分片与协议终态处理。

401／403、429、超时、传输失败及非法响应映射为固定 MODEL_AUTH_FAILED、MODEL_RATE_LIMITED、MODEL_TIMEOUT、MODEL_REQUEST_FAILED、MODEL_RESPONSE_INVALID，不保存上游原始错误、响应头或密钥。非成功响应体在进入 SDK 前丢弃，流事件复制后才交给会话，SDK 诊断日志关闭；错误、断流及 aborted 不能归档为成功。尚无本运行调用且无恢复档时明确 FAILED 并释放会话；已有调用或恢复档则 WAITING_REVIEW，保留账本且不重放业务写入。

两协议各以真实 SDK 网络请求、本机合成 SSE、两个独立 Node 进程和真实后台上传任务贯通 WAITING_JOB 接续；Node 72 项通过，HTTP 每协议 7 类 10 条响应通过，原 job／action 未重复。完整记录及分轮失败见验证文档。真实 provider 仍待用户配置，非空材料范围、来源模型外发与研究质量继续单独验收；production_ready 保持 false。

### 资源与证据

显式配置模型、凭据、会话目录和资源加载器，只装入审核的提示词、Skills 与研究工具；不扫描服务器用户目录或上传材料中的 .pi 配置。首版不开放通用 bash、文件编辑、任意脚本与第三方扩展安装。

工具覆盖全部已上线业务动作，包括账号项目、来源治理和同步、挂载、导入清洗、快照、查询、分析、双语候选与修订、笔记、成员策略、任务及导出。按角色、资源范围和上线状态筛选，但每次调用仍由 FastAPI 鉴权。后续 F 功能与工具同批交付。数字来自真实结果，语义发现不能替代计数；完整映射见《研究助手业务能力与工具契约》。

### 共享业务能力注册表

contracts 中维护静态注册表：capability_id、feature_ids、module_id、tool_name、schema_version、availability、handler、operation_kind、input_schema、output_schema、permission、scope_kind、version_inputs、scope_effect、authorization_policy、execution、idempotency、result_view 和 common_errors。FastAPI 拥有业务规则，Node 使用生成客户端调用；构建时校验已上线业务动作覆盖。

scope_kind 分 account、platform、project；输入范围可以为空以支持创建项目，但不得读取未绑定材料。平台操作使用净化的平台会话；管理员进入私人项目仍须独立授权。工具按动作独立注册，禁止万能 HTTP、SQL 或 shell 工具。文件选择与下载由前端 action request 完成，只把业务引用交还宿主。

模型调用前按当前身份和来源策略筛选工具，实际调用、任务执行及结果发布仍重新校验权限。每个工具返回正式结果类型和 result_view，主工作台与手动页面通过同一引用显示，不能把模型描述当作任务成功。

授权按业务影响区分：只读成员可在获准材料上创建查询和分析运行，其账本写入不等于修改材料；导出与模型外发仍单独授权。项目备份的创建、检查和恢复属于业务工具；首次恢复可从 account 作用域发起备份上传。整机运维、密钥和数据库管理不向模型开放。

完整注册字段、工具族、错误和接续流程以同目录 assistant-capabilities.md 及《研究助手业务能力与工具契约》为准。该契约是各模块新增业务动作的同批交付检查表。

### 权限变化

每次模型请求前核对项目、来源及 model_egress 策略，记录证据依赖。撤回时暂停受影响会话，旧正文、工具结果及摘要不得继续外发；首版从仍授权的材料引用创建新会话。已经外发的内容不能承诺远程收回。

已授权且目标明确的可逆操作直接执行；保存查询、笔记草稿、候选关系和导出不额外审批。删除、共享、撤回或扩大外发范围核对具体目标与既有授权，缺少授权时再请求确认。人工确认必须关联用户明确核对的内容或修订 ID；模型自行判断只能记 proposed。

## Pi 会话状态与业务任务

### 状态归属

Pi SessionManager 是模型上下文与分支的权威；私有对象存储保存完整会话归档，PostgreSQL 保存指针与摘要。界面消息是投影，不能重拼另一套上下文。业务运行、权限、工具调用、任务和成果由 FastAPI 维护。

| 对象 | 最小契约 |
| --- | --- |
| agent_sessions | 创建时固定 account/platform/project 作用域、所有者与 input_scope；Pi 版本、资源清单、归档、active_run 和 lease_epoch。 |
| agent_runs | 固定范围、策略版本、attempt、租约、模型配置、预算、状态和最终结果引用。 |
| tool_invocations | 稳定 invocation_id、工具及 schema、参数摘要、scope_digest、job_id 或 result_ref；写入另绑定 action_id。 |
| agent_events / run_jobs | 单调事件序号与幂等事件 ID；记录子任务归属及取消策略。 |
| session_evidence_refs | 记录消息、工具结果和摘要依赖，供权限变化时定位受影响会话。 |

### 单写与恢复

同一会话只有一个活动运行和租约。普通忙碌请求返回 409 SESSION_BUSY；明确的 follow-up 队列在当前运行结束后消费，不混作 steer。Node 通过内部长轮询领取，心跳与提交校验 attempt 和 lease；首版不让 Node 消费 Celery 协议。

项目、材料成员、快照或覆盖层身份改变时新建会话；旧 run 范围不变，不符返回 409 SESSION_SCOPE_CHANGED。同一范围产生 query/analysis/evidence/note result_ref 不改变 scope_digest。产生新范围的工具只回 ID、状态、计数及 scope_effect；旧 run 结束后按 continuation_intent 和 next_session_id 重新鉴权接续，不复制旧正文或摘要，排队消息不自动迁移。

会话归档先写不可变对象，再条件切换指针。重启从完整检查点恢复并查询已有工具结果；没有可靠上下文则等待核对，不重放写入。同调用重试沿用 invocation_id，笔记或导出沿用 action_id；同 ID 不同参数返回冲突。

### 等待完成与取消

长任务返回 accepted 和 job_id；必要结果未完成时进入 WAITING_JOB，恢复后查询同一任务。Pi 的 agent_end 不等于业务完成；settled 后核对必要结果、引用、取消状态及会话归档，FastAPI 才发布成功。

取消先写账本并拒绝新工具，再通知 Pi abort；取消专属可中断任务，复用任务仅解除等待。已发布成果保留，迟到输出不能将取消改成成功。关闭网页只断开订阅。完整字段和接口见同目录《业务架构与开发计划》的 Pi 运行部分。

## 十八 AI 工具契约与降级

注册表将每项业务动作显式映射至 command/query 和 Pi 工具。输入输出使用共享 Pydantic/OpenAPI schema，模型不传 actor 或任意路由。服务端登记 invocation_id，写操作关联 action_id；结果为 succeeded、accepted、failed 或 unknown，包含 scope_ref、version_refs、result_ref/job_id 及 result_view。accepted 等待原任务，unknown 查询原调用，不盲目重发。

```text
{
  "tool": "corpus.search", "schema_version": "1",
  "args": {
    "snapshot_id": "<snapshot-uuid>",
    "query": {
      "dsl_version": "corpus-query/v1", "unit": "token",
      "pattern": {"type": "term", "attr": "form",
                  "op": "eq", "value": "climate"},
      "within": "sentence", "overlap": "all"
    }
  }
}
{
  "invocation_id": "<invocation-uuid>", "status": "succeeded",
  "scope_ref": {"kind": "project", "project_id": "<project-uuid>"},
  "version_refs": {"snapshot_id": "<snapshot-uuid>"},
  "result_ref": "<result-set-uuid>",
  "result_view": {"page": "search", "result_ref": "<result-set-uuid>"},
  "completeness": "complete", "evidence_refs": ["<evidence-uuid>"]
}
```

| 情况 | 系统处理 |
| --- | --- |
| 模型不可用或限流 | 手动工具继续可用；保存草稿与失败步骤，用户可选择重试或校内模型。 |
| 上下文超限 | 按范围检索与分段摘要；返回实际覆盖清单，不声称读完全部文件。 |
| 引用校验失败 | 阻止该引用发布；重新定位或明确无法支持，不补造页码和例句。 |
| 外发被项目策略禁止 | 转到允许的本地模型，或停用该步骤；不能自动降低保密级别。 |
| 输出不是合法结构 | 有限次数修复后失败；不把未经校验的输出当作工具参数执行。 |

每个运行记录最大步骤数、最长时间、输入与输出 token 配额。提示模板只作版本化配置，不存密钥。新增模型通过离线任务集验证查询正确率、引用支持率和中文术语表现，再逐步开放。

## 十九 HTTP 接口与通用规则

接口根路径 /api/v1。服务器输出 OpenAPI 并生成 TypeScript 客户端；领域类型与 HTTP 传输模型分开。以下路径均在鉴权后执行，p 表示项目 UUID。长任务返回 202 和 job_id；小型读取返回 200，创建记录返回 201。

| 方法与路径 | 用途 | 关键约束 |
| --- | --- | --- |
| POST /projects | 创建个人或课题组项目 | 服务器确定工作区与创建人。 |
| POST /projects/{p}/uploads | 申请上传会话 | 大小、类型、文件摘要与项目限额。 |
| POST /uploads/{id}/complete | 完成上传并创建持久校验作业，202 返回 job_id | 支持 Idempotency-Key。 |
| POST /projects/{p}/imports | 提交 UTF-8 TXT 解析 | upload_id、cmn／eng；原件必须已校验，返回 202 与 import_id。 |
| GET /projects/{p}/imports/{id} | 读取解析任务 | 返回真实进度、错误或不可变修订。 |
| GET /projects/{p}/materials | 读取私有材料 | 当前项目授权内的材料与修订元数据。 |
| GET /projects/{p}/materials/{id} | 读取材料修订 | 保留固定修订；不向 Pi 投影正文。 |
| POST /projects/{p}/snapshots | 固定成员并提交准备 | mount_ids 与 material_revision_ids 合计 1 至 16 项；recipe 服务端固定。 |
| GET /projects/{p}/snapshots/{id} | 读取状态和材料摘要 | 只返回有权查看的固定范围。 |
| POST /projects/{p}/queries | 创建查询运行 | snapshot_id + corpus-query/v1。 |
| GET /projects/{p}/result-sets/{id}/hits | 读取 KWIC 分页 | cursor、page_size；再次检查权限。 |
| POST /projects/{p}/analyses | 提交统计分析 | input_ref、method、params。 |
| POST /layers/{id}/commits | 提交人工标注 | If-Match 或 expected_revision。 |
| GET /agent/runtime | 读取宿主可用性 | 区分 mode、production_ready、fixture_enabled、can_submit；配置无效与未配置分别说明，受理不代表宿主存活。 |
| POST /agent/sessions | 创建 Pi 会话 | 固定所有者和 account／platform／project scope；当前材料范围为空。 |
| GET /agent/sessions<br>GET /agent/sessions/{id} | 会话列表与详情 | 仅当前有权读取的会话。 |
| POST /agent/sessions/{id}/runs | 提交研究请求 | request_key、message、scope_digest；范围改变返回 409 SESSION_SCOPE_CHANGED。 |
| GET /agent/sessions/{id}/runs<br>GET /agent/sessions/{id}/messages | 运行及持久消息 | 页面刷新重新读取服务端事实。 |
| GET /agent/runs/{id}<br>GET /agent/runs/{id}/events | 运行状态与 JSON 事件 | 有界游标轮询，当前不是 SSE。 |
| POST /agent/runs/{id}/cancel | 取消本人运行 | 立即 fencing；业务任务按既有独占／复用规则处理。 |
| POST /projects/{p}/evidence | 保存固定命中证据 | result_set_id 与原 0-based ordinal；owner／editor，幂等。 |
| GET /projects/{p}/evidence<br>GET /projects/{p}/evidence/{id} | 证据列表与原文方法 | 当前材料授权；不存在或无权访问时隐藏记录。 |
| POST /projects/{p}/notes<br>PATCH /projects/{p}/notes/{id} | 保存笔记修订 | 固定证据／query_run_ids；更新必须 expected_revision。 |
| GET /projects/{p}/notes<br>GET /projects/{p}/notes/{id}<br>GET /projects/{p}/notes/{id}/revisions | 当前笔记与历史修订 | revision 可固定旧版；每次检查继承授权依赖。 |
| POST /projects/{p}/notes/{id}/accept | 人工采纳当前修订 | 有效登录会话与 expected_revision；不等于模型自动接受。 |
| POST /projects/{p}/exports | 生成完整成果包 | 1 至 16 个 query_run_ids 或一个固定 note_revision；独立 export 核准，202 返回 job_id。 |
| GET /projects/{p}/exports<br>GET /projects/{p}/exports/{id} | 成果任务与固定产物摘要 | 当前授权内的状态、真实行数、文件大小及 SHA256。 |
| GET /projects/{p}/exports/{id}/download | 下载固定成果 | 再次检查全部输入和导出核准，按固定私有对象版本读取。 |
| GET /jobs/{id}<br>GET /jobs/{id}/events | 任务状态与 SSE 事件 | Last-Event-ID 可恢复事件消费。 |
| POST /jobs/{id}/cancel | 请求取消任务 | 幂等；成功返回请求状态。 |

服务端字段使用 snake_case，时间使用 ISO 8601 UTC，空值与缺失分开。错误体统一包含 code、message、request_id、field_errors 和 retryable。401 需重新登录，403 无权限，404 对不可暴露资源隐藏存在性，409 冲突，422 参数错误，429 限流，503 暂时不可用。

## 二十 查询请求与响应示例

示例中的尖括号字段代表测试时需要替换的 UUID，不是生产允许的 ID 字符串。客户端不提供 actor_id。响应只摘录关联字段；实际响应同时包含完整 run 对象和状态能力，见 contracts/research.py。

```text
POST /api/v1/projects/<project-uuid>/queries
Idempotency-Key: 4e0e9f58-84ab-46d0-b9ad-d8c8eec4a87d
Content-Type: application/json

{
  "snapshot_id": "<snapshot-uuid>",
  "query": {
    "dsl_version": "corpus-query/v1", "unit": "token",
    "pattern": {"type": "term", "attr": "form",
                "op": "eq", "value": "language"},
    "within": "sentence", "overlap": "all",
    "normalization": "none",
    "sort": ["document_ordinal", "start", "end"]
  },
  "page_size": 50,
  "context_codepoints": 40
}

HTTP/1.1 202 Accepted
{
  "action_id": "<action-uuid>",
  "job_id": "<job-uuid>",
  "query_run_id": "<query-run-uuid>",
  "result_set_id": "<result-set-uuid>",
  "state": "QUEUED"
}
```

### 结果页字段

hits[] 包含 hit_ref（result_set_id 与 ordinal）、origin_kind、document_id、revision_id、segment_id、source_sentence_id、token_start、token_end、global_token_start、global_token_end、start_cp、end_cp、context_start_cp、left、match、right、source_url 和 evidence_id。start_cp/end_cp 为完整 canonical 修订码点，context_start_cp 为返回句段的全文起点；token_start/end 为句段内真实区间，全局 token 区间也来自固定层。字符查询的四个 token 坐标均为 null，私有材料的来源句 ID 和 URL 为 null。evidence_id 当前为 null，不伪造证据对象。外层包含 project_id、snapshot_id、result_set_id、query_run_id、next_cursor、has_more、三项计数及文档单位分项、page_state、count_state、completeness、码点上下文和排序配置。所有区间均左闭右开；完整句段通过项目结果集与命中 ordinal 的 context 接口重新鉴权读取。

若计数未完成，total_hits 为 null，count_state 为 pending；若用户执行抽样，额外返回 population_result_set_id、sample_size、seed 和算法。示例检索的结果不能在后端无索引时偷偷回退到语义召回。

### 事件恢复

当前研究查询通过 JSON 轮询恢复持久状态。后续 SSE 事件规划包含 job_id、sequence、type、stage 与 progress；已知工作量才返回进度，未知时为 null。事件保留建议 7 天，超过窗口重新读取任务状态；模型流式 token 可短期保留，但最终输出以持久结果为准。

## 二十一 研究成果与复现包

### 证据定位

每条证据包含来源修订、正文跨度或媒体时间、原文摘要和生成它的运行引用。打开证据时先校验权限，再验证摘要；原文发生新修订仍打开旧修订。若原始资料因到期或删除不可用，显示不可用及原因，不能静默跳到相似新文本。

### 导出内容

当前 S3 切片提供 JSON 的 methods＋rows 单文件，以及仅含 results.csv＋methods.json 的 CSV 成果 ZIP；完整固定查询或笔记导出必须通过全部输入的独立导出核准。下列目录为后续完整复现包目标，不表示当前已包含图表、运行归档、全文副本或重算环境。

```text
research-package/
  manifest.json
  checksums.sha256
  methods.json
  queries/*.json
  runs/*.json
  results/*.csv
  evidence/*.jsonl
  figures/*.svg
  sources/                 # only when permitted
  README.txt               # reproduction instructions
```

manifest 固定 schema_version、快照清单、正文及模型摘要、算法版本、容器 digest、输入和输出参数、随机种子、许可与被排除材料。CSV 明确 UTF-8 编码、分隔符和小数格式；XLSX 不填背景色、标题用宋体，并防止公式注入。图表应可导出 SVG，表格保留未四舍五入原始值和显示精度。

### 三个复现等级

| 等级 | 必须包含 | 结果承诺 |
| --- | --- | --- |
| 结果复核 | 结果、方法、证据定位与摘要 | 可审查原输出；不承诺能重新计算。 |
| 同环境重算 | 全部允许输入、配置和固定工具环境 | 确定性计数相等；浮点按声明容差。 |
| 模型辅助重跑 | 模型与参数、原始请求及已保存输出 | 可检查过程；生成内容可能与原输出不同。 |

后续可按许可范围生成不含受限输入的成果包，并记录缺失输入与复现等级；当前完整命中／笔记导出不做自动脱敏或部分放行，任一固定输入未获导出许可即明确拒绝。已经下载到用户电脑的文件无法通过撤销网页权限追回；因此导出权限独立控制。笔记中的 AI 草稿、研究者编辑与最终采纳保留修订关系。

## 二十二 前端工程与状态管理

### 数据归属

服务器是项目、任务、标注和研究结果的唯一事实来源。前端请求缓存以 project_id、snapshot_id、resource_revision 和规范化参数构造键；切换用户时清空。URL 保存可分享的查询配置或已保存 query_id，不放原文、密钥和模型提示全文。

视图局部状态仅保存选择区域、面板宽度、排序和未提交草稿；草稿如落浏览器存储，按用户和项目隔离、可清除，并遵守项目敏感数据策略。AI 对话、原文和结果响应设置适当缓存控制，不由 Service Worker 默认永久缓存。

### 长文本与性能

KWIC、文档列表和标注任务采用服务端分页与窗口渲染。长正文按段加载，虚拟化后仍通过 segment_id 维护选区，不使用当前 DOM 下标当研究坐标。前端统计只用于页面展示，正式统计必须使用后端结果。

研究助手主工作台和任务中心通过 SSE 订阅更新；中断后有限退避重连，事件按序列去重。结果引用定位手动页面，并使用相同版本；scope_effect 触发新会话接续。多个标签页编辑同一层时提示版本冲突；保存失败保留草稿，不展示成功。

| 工程约束 | 实现要求 |
| --- | --- |
| 类型与契约 | OpenAPI 生成客户端进入 CI 校验；手写 UI 类型不能重复定义后端字段含义。 |
| 可访问性 | 键盘可完成检索、翻页与基本标注；图表有数据表替代，颜色不作唯一状态提示。 |
| 错误呈现 | 区分零命中、无权限、索引未就绪、超时与服务错误。支持按 request_id 反馈。 |
| 国际化 | 中文界面优先，文献与语料保留原语言；日期按用户时区显示，底层不改写 UTC。 |
| 浏览器范围 | 先验收桌面 Chrome 与 Edge 当前稳定版本；平板阅读可用，复杂标注优先桌面。 |

## 二十三 部署与运维设计

### 首版部署拓扑

在 Linux 主机使用 Docker Compose 运行 reverse-proxy、web、api、agent-runtime、worker、dispatcher、PostgreSQL、RabbitMQ。对象存储可使用独立存储服务或云端 S3 兼容服务。CWB 与 NLP 模型安装在对应工作进程镜像；持久数据使用独立卷，不存容器临时层。

对外只开放 HTTPS；数据库、队列、对象管理口和指标端点处于内网。API 与 UI 同源，媒体与成果经鉴权代理或受控短期链接下载。API 多进程不加载大型 NLP 模型，模型进程独立管理，避免每个 API worker 重复占内存。[T02]

### 环境与配置

| 配置组 | 必需项 | 保存位置 |
| --- | --- | --- |
| 站点 | PUBLIC_ORIGIN、会话过期、注册模式 | 环境配置；各环境独立。 |
| 数据 | 数据库地址、对象桶、加密配置 | 密码与访问密钥由 secrets 注入。 |
| 执行 | 队列地址、并发、超时、磁盘限额 | 管理员配置；任务记录实际值。 |
| AI | provider、endpoint、model、外发策略 | 模型密钥仅服务器读取。 |
| 模型与索引 | 模型摘要、索引缓存目录、最大空间 | 只读模型目录；受控可写缓存。 |

### 发布与回滚

CI 构建锁定镜像，执行迁移兼容检查、契约测试和样例建库，再发布到测试环境。生产先运行可向后兼容迁移，再滚动更新 API，工作进程停止领新任务并排空。新版本运行不得覆写旧版本结果；镜像回滚不自动回滚已经收缩的数据结构。

内网部署提供镜像、锁文件、模型包、校验清单和离线安装说明；首次启动不能临时联网下载模型。学校无需外网即可使用已安装的确定性工具，云端 AI 在连接不可用时显示未启用。

## 二十四 备份删除与可观测性

### 备份和恢复

事实数据采用 PostgreSQL 基础备份与 WAL 归档，结合对象版本清单形成一致恢复点。[T10] 对象存储保留原件、正文、人工提交、Pi 会话归档与成果；CWB 和向量属于可重建数据，但保存所需工具和模型。备份跨故障域保存并加密，每月至少做一次恢复演练。

试点暂定 RPO 24 小时、RTO 8 小时；高校持续使用阶段目标 RPO 15 分钟、RTO 4 小时。目标依赖备份频率、WAL 归档与数据体积，必须在演练中测量后才能作为运行承诺。数据库恢复成功还需校验对象清单、租约及权限状态。

### 删除生命周期

项目归档、软删除和永久清除分别操作。软删除立即禁止普通访问并取消未完成任务；保留期后清除对象与派生索引。永久删除还包含向量、引用摘录、缓存、日志中的受控内容及备份生命周期。备份恢复后先应用删除清单再开放访问，避免被清除数据重新出现。

### 监控与排障

| 类别 | 指标或记录 | 触发处理 |
| --- | --- | --- |
| 接口 | 错误率、p50/p95、权限拒绝、request_id | 超过基线报警；不记录原文和会话密钥。 |
| 任务 | 排队时长、重试次数、租约失效、卡住阶段 | 重投递或人工核查；防止无限重试。 |
| 数据 | 缺失对象、索引摘要错误、备份年龄 | 停止受影响快照，修复或重建。 |
| 资源 | 磁盘余量、内存、CPU、GPU、队列积压 | 降低并发或暂停新建库，保留查询能力。 |
| AI | 模型延迟、失败率、引用无效、配额耗尽 | 降级至手动流程或已配置的可用模型。 |

审计日志记录谁在何时对哪个对象执行什么操作，以及结果和关联运行 ID；原文与完整提示不进入普通应用日志。需要保存的模型请求作为受权限保护的研究记录管理，保留周期与项目策略一致。

## 二十五 性能预算与扩容条件

以下是性能实验的起点，不是已完成压测结果。基准必须固定语料、分词规则、过滤选择率、结果规模和缓存状态，分别报告首屏延迟、完整计数耗时、索引构建时间与资源峰值。

| 场景 | 建议实验环境 | 验收目标 |
| --- | --- | --- |
| 小规模试点 | 8 vCPU、32 GB 内存、SSD；1000 万 token，5 个并发查询 | 常见精确词与短语查询首屏 p95 ≤ 3 秒；高频全量计数独立报告。 |
| 高校验证 | 16 vCPU、64 GB 内存、SSD；1 亿 token，20 个并发查询 | 同类首屏 p95 ≤ 3 秒作为优化目标；冷索引加载另行标记。 |
| 普通元数据操作 | 上述环境，不含上传与计算 | p95 ≤ 500 毫秒；后台作业提交 ≤ 1 秒。 |
| 长分析与建库 | 单独 CPU 队列；固定任务集 | 可恢复、可取消、进度真实；吞吐由实验确定。 |
| 语义搜索与 AI | 记录模型、片段数、设备与 provider | 模型生成延迟独立统计；不计入精确检索指标。 |

### 避免错误优化

KWIC 第一页快不代表全量计数快。高频词、宽正则、低选择性元数据过滤和复杂结构查询必须进入压力集。系统可将超时查询转为异步，但不能用抽样结果冒充全量完成。数据库索引、缓存与工作进程并发根据剖析数据调整。

### 扩容触发

当队列等待长期超过交互目标时，先增加对应队列工作进程并限制项目并发；当数据库写入或连接压力成为瓶颈时再拆读写负载。索引缓存反复淘汰时增加 SSD 或按快照路由；模型队列单独扩 GPU。只有跨主机调度和高可用需求明确时才引入 Kubernetes。

容量至少包含原件、正文多版本、token 文件、CWB、向量、结果集、媒体代理和备份。先测每种数据的单位增长，再乘实际保留版本和冗余数量；不得把无限保存所有中间结果设为默认。

## 二十六 测试与发布门槛

| 测试层 | 测试内容 | 通过条件 |
| --- | --- | --- |
| 契约 | JSON Schema、OpenAPI、错误码、分页、版本冲突 | 前后端契约一致；未知字段和非法枚举按规则处理。 |
| 计数金标 | 200 条中英文查询、重复跨度、句边界、元数据组 | 命中集合与整数计数全部一致。 |
| 文本定位 | emoji、组合字符、全半角、OCR、清洗映射 | 跨度往返不漂移；不精确映射明确标记。 |
| 统计金标 | 小样本手算、空语料、零频、窗口边界 | 计数精确；浮点建议绝对 1e-8 或相对 1e-6。 |
| 权限 | 跨项目 ID、RLS、异步任务、撤权、导出与媒体 | 未经授权无法取得正文、结果或对象链接。 |
| 故障注入 | 断网、重复消息、进程被杀、队列和数据库重启 | 无重复发布；租约恢复；已确认人工数据不丢失。 |
| AI 评估 | 30 个真实任务、100 条引用；全业务工具覆盖、对齐到分析、管理员同步、权限及恢复。 | 手动结果一致，无越权或重复提交；引用定位 100%，支持率目标 ≥ 95%。 |
| 专业能力 | 500 个对齐样例、多标注员、格式往返 | 关系和标签保留；损失字段显式报告。 |
| 端到端 | 上传到导出，失败重试，关闭浏览器恢复 | 每类用户至少 80% 独立完成核心场景。 |

上述样例数量与阈值是验收基线。语言专家制作独立金标，评估集与提示调优样本分开；AI 引用支持由人工判定，不能只检查链接存在。安全和跨项目隔离用例零失败，不能被平均准确率掩盖。

### 持续集成

每次提交执行类型检查、静态检查、领域单测和关键契约测试；合并前运行真实 PostgreSQL、对象存储与工作进程的集成测试。定期跑大规模性能、格式往返和恢复演练。关键不变量从公开 Interface 测试，避免只用 mock 验证实现调用顺序。

发布候选必须通过样例项目完整重建与成果导出，并保留测试环境、语料摘要、工具版本和原始结果。尚未验收的专业能力在产品界面明确标识，不以菜单存在作为已实现。

## 二十七 仓库结构与开发顺序

```text
corpus-workbench/
  apps/web/                 # React and TypeScript
  services/api/             # FastAPI modules and migrations
  services/agent-runtime/   # Node, Pi, tools, session recovery
  workers/                  # Python job entry points
  contracts/                # OpenAPI and tool schemas
  pipelines/                # versioned NLP recipes
  tests/golden/             # corpus and expected outputs
  tests/integration/
  tests/e2e/
  deploy/                   # Compose and image definitions
  doc/                      # design Word and source documents
```

### 先完成可演示的纵向流程

按 S0 至 S8 实施：S0 冻结注册表、查询与范围接续契约，并验证对齐算法；S1 搭建主工作台及基础读写工具；S2 至 S4 同批交付来源、导入和首条研究流程的工具；S5 补齐统计工具，S6 完成自动对齐到分析导出，S7 验证跨模块任务，S8 核验全部已上线业务覆盖。

每一步都让浏览器触发真实后端并保存数据。三类外部来源接入是阶段 A 必交项；OCR、多媒体、复杂对齐、实时协作和其余第三方连接器后续扩展。先用目录占位并不能通过首版验收。

### 开发启动阶段的验证任务

| 任务 | 具体产物 |
| --- | --- |
| 索引与 Pi 验证 | 固定检索基准；Pi 注册表、读写权限、单写恢复、范围接续及私有材料对齐。 |
| 版本与恢复验证 | 杀死建库进程后恢复；重复消息只发布一次；旧快照结果仍能定位。 |
| 授权验证 | 两个互不可见项目；工作进程及 AI 均无法跨项目读取。 |
| 部署验证 | 全新 Linux 主机按文档启动；备份恢复后完成相同查询。 |

启动阶段结束应锁定依赖版本、索引支持子集和前后端契约。若实验无法满足关键不变量，调整相关实现后再扩展页面，避免将技术风险带入整套功能。

## 首版开发顺序与依赖

| 步骤 | 依赖 | 交付与验收 |
| --- | --- | --- |
| S0 契约与技术验证 | 无 | 领域＋后端＋AI；核验来源、查询和 Pi；定义业务能力注册表、授权及范围接续，验证私有双语自动对齐算法。 |
| S1 基础工程与契约 | S0 | 后端＋前端＋AI；主工作台、账号项目、目录、任务、上传与 Node/Pi；按权限筛选工具，验证只读和可逆写操作。 |
| S2 首类真实获取 | S1 | 后端＋数据工程；真实 Tatoeba 获取、许可与质量；同步工具同批交付。未完成索引不得 READY。 |
| S3 首条研究流程 | S2 | 前端＋后端＋AI；挂载、私有 TXT、混合快照、KWIC、双语查询、笔记及 CSV/JSON 导出；业务动作同批提供助手工具。 |
| S4 来源与导入覆盖 | S3 | 数据工程＋后端；Wikimedia、UD、表格导入、版本检查与撤回；管理员工具与权限验证。 |
| S5 查询与统计 | S3 | 检索＋领域＋AI；M06 至 M09 全部工具与手动结果一致；200 条金标、独立统计参考及准确计数。 |
| S6 双语与成果 | S5 | 前端＋后端＋AI；自动一对一候选、项目修订、固定版本分析、范围接续及全部导出工具；复算核对。 |
| S7 完整 Pi 能力 | S5 S6 | AI＋前端＋后端；跨模块组合任务、研究 Skills、权限隔离、撤回、恢复及工具覆盖审查。 |
| S8 综合验收 | S4 S6 S7 | 测试＋全组；三类来源、两个研究案例、M01 至 M14 和已上线业务工具覆盖、权限恢复及性能验收。 |

S4 与 S5 可在 S3 后并行。Pi 在 S0/S1 接入，S2 至 S6 的业务模块与助手工具同批交付，S7 验证跨模块任务。准备阶段原估算 2 至 3 周，A 阶段 12 至 16 周，按领域 1、前端 2、后端 2、NLP/AI 2、测试 1 人投入；S0 实测后重估，非交付承诺。详细任务见同目录《业务架构与开发计划》的开发任务部分。

## 二十八 全量功能分期与依赖

延续完整产品规划的 96 项功能编号。以下把功能组落实到技术模块；每组内按首版闭环、专业能力、协作多模态、规模化扩展分期，不要求同组所有功能同时交付。

| 功能范围 | 责任 Module | 阶段依赖 |
| --- | --- | --- |
| F001 至 F008 项目与语料设计 | ProjectPolicy、Corpus | A：账号与项目；B：复杂抽样与设计模板。 |
| F009 至 F016 同步与清洗 | SourceRegistry、Sync、Corpus | A：三类连接器、目录、调度、质量报告；B/D：更多来源及 OCR。 |
| F017 至 F024 语言与标注 | Corpus、Annotation | A：词位与导入属性；B：自动标注和人工裁决。 |
| F025 至 F032 查询 | QueryEngine | A：字符、词项、有限组合、元数据、KWIC 和双向句对；B/D：完整专业语法。 |
| F033 至 F040 统计 | Analysis | A：词频、2 至 4 元词组、关键词、频率与分布；B：丰富度及更多方法。 |
| F041 至 F048 搭配与探索 | Analysis | A：窗口共现与 logDice；B：语法搭配；D：高级网络与主题。 |
| F049 至 F056 双语与术语 | Annotation、Analysis | A：双向查询、自动一对一候选及项目修订；B：复杂对齐、多译本和术语。 |
| F057 至 F064 多模态 | Corpus、Annotation、Execution | C：时间轴与 ASR；D：完整格式与声学。 |
| F065 至 F072 AI 与 Agent | ResearchAI/Pi、Execution | A：调用全部已上线业务动作；后续功能按 B/C/D 与对应工具同批交付。 |
| F073 至 F080 证据与成果 | EvidenceExport | A：引用与基础成果包；B/D：专业格式与复现。 |
| F081 至 F088 协作与策略 | ProjectPolicy、Annotation | A：隔离与基础角色；C：任务分配、SSO、管理。 |
| F089 至 F096 平台与扩展 | Execution、Adapters | A：部署与基础监控；C/D：扩容及插件。 |

网页端将权限隔离、持久任务及备份提前到 A。A 增加一对一句级自动候选与版本化修订；B 扩展复杂对齐。每阶段业务能力同时交付助手工具及验证；96 项仍按长期目录分期。所有统计都依赖固定输入清单。

## 二十九 里程碑与交付门槛

| 阶段 | 建议周期 | 完成标志 |
| --- | --- | --- |
| 准备与验证 | 2 至 3 周 | 技术风险样例通过；契约、依赖、部署与金标初版落地。 |
| A 同步与分析首版 | 12 至 16 周 | M01 至 M14 全部通过；三类真实来源、更新恢复、对标基础查询和两个研究案例可实际运行。 |
| B 专业研究能力 | 8 至 12 周 | 标注复核、复杂查询、关键词搭配、复杂对齐与术语具备金标验收。 |
| C 课题组与多模态 | 10 至 14 周 | 任务分配、SSO、机构管理、媒体转写、时间轴与校内模型。 |
| D 格式与规模扩展 | 6 至 10 周 | 更多语言、格式往返、第三方适配及大库性能达标。 |

以上为配备产品或领域负责人 1 人、前端 2 人、后端 2 人、NLP 或 AI 2 人、测试 1 人，并有语言专家参与的规划估算；单人开发不能沿用此排期。全阶段串行约 38 至 55 周，需根据启动实验和真实团队调整，不能据此承诺全部市场工具功能一次上线。

### 必须提前解决的风险

第一，查询口径和文本坐标错误会污染所有后续研究，必须先用独立金标锁定。第二，平台公共语料与项目私有材料共存，挂载鉴权、授权撤销和同步账本必须进入首个版本。第三，来源目录全覆盖与全文接入分开验收，资源连接器逐个声明托管、检索、导出和模型处理能力；目录不能替代三类真实连接器交付。

第四，多语言模型与专业格式的质量不能由框架支持列表证明，要按研究场景验收。第五，大语料索引的实际内存和磁盘需要实验，不以模型宣传或单次演示估算。第六，软件、模型权重及数据的授权条件分别登记，部署前核对所选版本。

### 每一阶段的交付件

交付可运行版本、迁移脚本、锁定镜像、接口与工具注册表、金标及测试结果、部署说明和已实现清单。逐项核验已上线业务动作有工具及权限测试，UI 交互与运维操作独立分类。阶段演示跨模块研究任务并回查原文；通过验收后才标记完成。

## 三十 官方技术依据

T01  Vite 官方指南

用于网页开发与生产构建选型；具体版本由项目兼容性验证后锁定。

[打开官方文档](https://vite.dev/guide/)

T02  FastAPI 部署概念

HTTPS、进程、重启、内存与单次迁移执行的部署依据。

[打开官方文档](https://fastapi.tiangolo.com/deployment/concepts/)

T03  PostgreSQL 行安全策略

RLS、默认拒绝与表所有者等绕过条件；数据库隔离只覆盖数据库访问。

[打开官方文档](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

T04  IMS Open Corpus Workbench

词位和结构属性索引路线的官方入口；部署版本需单独验证。

[打开官方文档](https://cwb.sourceforge.io/)

T05  CQP 词位属性查询

属性值默认正则、字面值匹配及词形与标注属性查询。

[打开官方文档](https://cwb.sourceforge.io/files/CQP_Tutorial/2_5.html)

T06  pgvector 官方仓库

精确与近似向量查询及过滤行为；语义召回独立于精确语料计数。

[打开官方文档](https://github.com/pgvector/pgvector)

## 三十一 执行与分析依据

T07  Celery 任务指南

任务幂等、确认与重试机制；业务账本和原子发布由本系统实现。

[打开官方文档](https://docs.celeryq.dev/en/stable/userguide/tasks.html)

T08  OWASP 文件上传指南

允许类型、体积限制、文件名与隔离存储等上传设计依据。

[打开官方文档](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)

T09  Stanza 官方文档

多语言文本处理管线选型；每种语言模型仍需本项目数据验证。

[打开官方文档](https://stanfordnlp.github.io/stanza/)

T10  PostgreSQL 连续归档与时间点恢复

基础备份与 WAL 归档恢复；对象存储一致性由成果清单补充。

[打开官方文档](https://www.postgresql.org/docs/current/continuous-archiving.html)

T11  CQP 随机子集

抽样能力参考；产品额外保存样本 ID、种子和算法版本。

[打开官方文档](https://cwb.sourceforge.io/files/CQP_Tutorial/3_6.html)

T12  Sketch Engine logDice

关联分数的指标参考；产品按明确样本空间计算并公布统计口径。

[打开官方文档](https://www.sketchengine.eu/glossary/logdice/)

T13  Pi SDK 官方文档

SDK 嵌入、SessionManager、资源配置与事件依据；S0 按锁定版本核验。

[打开官方文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)


### T14 S3 条件创建与固定版本读取

S1 使用 IfNoneMatch=* 防止同键覆盖，保存 VersionId 并按指定版本读取；ETag 只作为对象条件，不替代 SHA256。官方依据：[PutObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)、[GetObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html)。
