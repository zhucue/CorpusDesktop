# 前端与接口设计规范

首版面向高校外语、翻译和语言学研究生，采用 React、TypeScript、Vite 网页工作台。浏览器只访问 FastAPI；系统内置“研究助手”，基于 Pi SDK 改造并融入检索、证据、分析和笔记。Pi 不作为外置产品或原生界面呈现，后台仍执行同步、索引、分析和导出。本规格用于页面实现、接口冻结和联调验收。

首版范围为 M01 至 M14。完整产品的 F001 至 F096 按阶段推进，不全部进入首版。本文补齐业务架构与网页技术设计中的页面和 HTTP 契约。已实现范围包括下述 S1 切片、第二节同步与索引及固定版本核准发布、第四节整库挂载与固定来源／私有修订研究快照、第五和第六节明确列出的手动检索切片；其余接口仍为待实现规格。各切片分别记录实际验收，不把代码实现等同于整阶段完成。

### S1 当前实现

当前网页接入真实登录、项目列表与创建、单文件上传，以及校验任务的读取、取消和有限重试。页面采用中性浅色和深色主题，权限、任务状态、进度和结果均读取后端。研究助手生产执行授权尚未完成验收；本轮 K09 增加下述真实会话工作台，模型未配置时禁发，不以占位答复冒充可用助手。2026 年 10 月 16 日已通过真实浏览器的登录、建项目、53 字节文本上传、后台校验与摘要核对，以及刷新恢复、主题切换和退出；这是本切片验收，不代表整个 S1 完成。

来源目录已接入持久 HTTP 接口，登录后无需项目即可查看 46 项初始登记，按名称、编号或发布方搜索，并按语言、类别、接入状态和能力筛选。桌面列表与详情并排，中文显示已知类别和语言；详情展示官方依据、材料范围、获取方式、许可、实际能力和已发布版本。目录登记与实验记录不代表全文可分析，目录整体许可仍待审核，只有目录发现能力为真；已发布列表仅记录经过固定版本核准的实际发布版。平台管理员可登记和编辑描述元数据，普通用户只读。

同日真实浏览器已验证无项目账号读取 46 项目录，D12、中文、平行语料组合筛选及详情，全文分析能力筛选为空；普通账号没有编辑入口。管理员新增登记后数量为 47，编辑边界后刷新会话，重新读取仍为修订 2 和已保存内容；临时验收账号与登记已清理。目录验收证据单独保存，不覆盖此前上传链路记录。

接口统一以 `/api/v1` 为前缀。`POST /auth/login` 接收 email、password，返回 actor、csrf_token 和 HttpOnly 会话 Cookie；`GET /auth/session` 恢复身份，`POST /auth/logout` 撤销会话。写请求校验精确 Origin，已登录写请求另校验 X-CSRF-Token。密码和会话凭据不进入日志或 localStorage，输入校验错误不得回显密码或请求正文。

`POST /projects` 当前仅接收 name，长度上限 160；返回 id、name、owner_id、role、created_at 和 permissions。工作区、研究目标、项目修订编辑仍待后续交付。项目返回 upload、manage_members、read_jobs 权限，任务单独返回 allowed_actions。成员接口当前只供负责人维护已存在账号 ID，不发送邮件邀请。

上传先建立本人项目会话，再由浏览器向同源受限地址 PUT 文件，最后提交 complete。成功只将文件置为 VALIDATED 暂存：完成真实大小、SHA-256、UTF-8 和非 NUL 检查，不代表 CSV／JSON 结构解析、材料修订或可检索 READY。当前默认单文件上限 100,000,000 字节，项目声明字节配额为 1,000,000,000 字节，实际以服务端配置和准入结果为准。

手动上传和任务操作以服务端 action_id 记录，不要求虚构 Pi run 或 invocation。生产 Pi 委托执行尚未完成验收，显式工具适配器与内部宿主验证不构成生产开放；不得据此开放计划工具。

| 范围 | 首版页面与交付 |
| --- | --- |
| M01 至 M02 | 来源目录、版本详情、管理员连接器及真实同步 |
| M03 至 M05 | 登录、项目成员、共享挂载、私有上传、子库与研究快照 |
| M06 至 M07 | 字符与词项查询、KWIC、上下文、筛选、抽样和保存查询 |
| M08 至 M09 | 词频、词组、共现、关键词和子库比较 |
| M10 | 双语检索、自动句对候选、一对一项目覆盖层修订、确认与版本固定 |
| M11 | 研究助手按当前身份调用全部已实现业务能力，贯通任务、证据和成果 |
| M12 至 M13 | 笔记、成果导出、任务状态、取消与有限重试 |
| M14 | 浏览器与服务联调、权限、部署及两条真实研究流程验收 |

### 实现边界

首版不做通用 PDF/OCR 导入、完整 CQL、音视频、实时多人协同编辑或任意脚本执行。组件库与图表库在基础工程阶段按项目需要选择；本规格不依赖某个库的特定版本。

前端呈现后端正式结果。来源、计数单位、版本、状态和错误是正文信息；不添加装饰性副标题、卡片脚注或重复介绍。

## 一 页面结构与布局

| 路由 | 页面与主操作 |
| --- | --- |
| /login | 登录 |
| /sources | 查找来源、查看版本、添加到项目 |
| /projects | 新建或进入项目 |
| /projects/:p/assistant | 项目默认入口：提出研究任务、查看过程、证据与成果 |
| /projects/:p/materials | 挂载、上传、筛选并建立快照 |
| /projects/:p/search | 选择快照、执行查询、查看 KWIC |
| /projects/:p/analysis | 选择方法、执行计算、返回例句 |
| /projects/:p/parallel | 双向检索、检查与修订关系 |
| /projects/:p/notes | 保存研究笔记、读取修订、手动接受确定修订 |
| /projects/:p/tasks | 查看项目任务及成果 |
| /projects/:p/settings | 项目名称与成员 |
| /admin/sources | 来源配置、同步、发布与撤回 |
| /admin/assistant | 管理员在平台范围管理来源、同步和授权策略 |

### 桌面工作区

以 1440 px 桌面为设计基准，完整研究操作最低适配到 1024 px。左侧导航 224 px、顶栏 52 px、底部状态栏 26 px，主内容横向留白 26 px，右侧检查器 380 px。导航按研究、成果、数据、管理分组，不设顶部横向一级导航。项目默认进入研究助手工作台，主区呈现对话、任务过程、结果与输入，辅助区呈现材料范围、结果、证据和成果。检索、分析、笔记等工具保留独立页面，解释结果等入口统一返回研究助手。1040 px 以下导航收为 60 px 图标栏，检查器改为覆盖式抽屉，工作台辅助区隐藏；720 px 以下查询表单纵向排列，隐藏 KWIC 来源列，复杂表格在容器内滚动。

正文与表格默认 11 至 13 px，对话正文 13.5 px，原文 14 px，输入控件高度 30 至 32 px；重要状态不能仅靠颜色区分。输入有可见标签，键盘可到达主要操作，弹窗关闭后焦点回到触发位置。交互采用 120、180、280 ms 过渡，系统要求减少动态效果时关闭位移、扫光、流式与计数动画。侧栏底部提供深色／浅色切换，默认深色；手动选择本机记忆。首屏提前应用主题，切换不重载业务视图或清空输入。页面采用仪器感科技风：近黑石墨底、1 px 细线、单一冷蓝强调色与等宽数据，不使用渐变、彩色光晕或大面积玻璃模糊；状态用方块加文字，不使用胶囊。

### 交互规则

页面只保留一个主要动作。检索表格优先给文本空间；通过结果行的“证据”按钮打开上下文抽屉，点击来源打开版本详情。参数修改后显示“条件已修改”，由用户重新运行；不自动覆盖已有结果。切换页面保留已提交运行，离开未保存编辑时提醒一次。

## 二 来源目录与同步管理

当前目录字段为编号、名称、发布方、登记类型、语言、类别、官方依据、材料范围、获取方式、使用边界、许可与接入状态。接入状态区分仅登记、待验证和已有实验记录；能力逐项展示可用或未开放。读取失败提供重新读取，空筛选显示没有匹配来源，版本为空显示暂无已发布版本。页面不把登记数量、实验样本或文件下载状态表示为全文 READY。

已发布版本展示固定版本、当前可挂载状态与 searchable。只有当前来源策略和固定处理版本允许时，searchable 才为真；使用者仍须是项目成员，并建立已准备完成的研究快照后查询。项目只能选择明确发布版整库挂载，不把私有 INDEXED、下载或发布完成当作研究 READY。后续连接器配置、检查更新、计划同步与完整撤回另列为待实现规格。

S2 当前接入 D12 的固定 Tatoeba 中英连接器。平台管理员在 D12 详情选择“同步管理”，启动同步、读取分页历史及当前任务，查看真实阶段、字节和记录进度，并按后端 allowed_actions 取消或有限重试。普通账号没有同步管理入口，后端独立核验管理员权限。任务从服务端重新读取，刷新后可找回；未知总量显示“未知”，不推算百分比。成功后隐藏最后处理步骤的文件与进度，仅展示正式质量结果；失败或取消保留最后进度。网络失败保留实际错误和重新读取入口，写入沿用同一幂等键，不自动创建新任务。

同步成功只得到管理员可读的 VALIDATED 暂存版本，显示上游导出日期、中文和英文句数、去重后的直接关系、排除或重复计数、与前版按上游 ID 比较的增删改，以及 manifest 摘要。首次同步明确显示“无前版”。上游许可声明与平台批准分开，尚未建立索引的结果不可检索，也不进入公开已发布版本列表；目录的许可和生产能力保持未批准。检查更新与计划同步未开放；固定索引发布另经下述核准流程。

2026 年 10 月 16 日连续两轮真实全量同步已通过 HTTP、常驻后台任务和私有版本化存储链路，每轮 13 个对象逐一回读核对摘要。第二轮六项差分为零，旧任务结果不变，公开版本列表仍为空。浏览器已验证管理员查看真实进度、启动及取消，实际任务详情、动作和列表三类响应通过 JSON Schema 校验。该结果不代表索引、公开发布或生产 Pi 已通过；首次执行的次轮失败记录另行保留。

### 当前 D12 同步接口

GET /admin/sources/D12/sync-runs 接收 cursor、page_size，返回 items、total、next_cursor、allowed_actions.start，按创建时间和 ID 倒序分页。POST 同路径仅接收空 JSON 与 Idempotency-Key，返回 202、action_id、sync_run_id、同值 job_id、state 和 run。连接器及获取地址由服务端固定，不接收浏览器或模型自定义 URL、recipe 或身份。

GET /admin/sync-runs/{sync_run_id} 返回来源登记修订与身份、attempt、state、stage、progress、result、error 和 allowed_actions。state 为 QUEUED、RUNNING、SUCCEEDED、FAILED 或 CANCELLED；stage 为 QUEUED、ACQUIRING、PARSING、STORING、VALIDATED、FAILED 或 CANCELLED。progress 分别返回已处理字节和记录数，total_bytes 与 total_records 可为 null。结果为 acquisition_id、VALIDATED、searchable=false、manifest_sha256、export_date、quality、diff、license。上述源任务独立于项目上传任务，不能用项目 job_id 查询。

POST /admin/sync-runs/{sync_run_id}/cancel 与 /retry 接收空 JSON 与 Idempotency-Key，返回动作及实际任务状态；是否允许操作以服务端 allowed_actions 为准。GET /admin/sync-runs/{sync_run_id}/events 使用 after_sequence、page_size 返回持久 JSON 事件，网页当前轮询任务列表，不声称 SSE 已接通。已有活动任务返回 SYNC_ALREADY_ACTIVE，来源身份被改动返回 SOURCE_IDENTITY_CHANGED，不可重试返回 SYNC_NOT_RETRYABLE。其余连接器配置与完整撤回仍按后续规格交付。

### 当前 D12 私有索引构建

S3 当前切片以固定 acquisition 为输入。管理员在同步管理中选中一项已完成同步，再点击“为所选版本建立索引”。未完成、失败或取消的同步没有可选输入，不能用最新成功项暗中替代。索引历史独立分页和刷新；列表读取错误与同步错误分别显示。详情正文显示该索引实际输入版本，避免把历史构建误认为当前所选同步版本的索引。

后台依次读取固定版本、构建、校验和保存索引；页面显示真实 state、stage、attempt 与可用进度，未知总量保持未知。成功后展示句子数、中文和英文句数、Unicode 码点数、含标点但不含空白的词项数、有效直接关系、归属人缺失数和实际产物字节，以及原句覆盖和词项位置回核结果。成功任务隐藏处理步骤残留进度，失败任务保留错误与可用重试。相同版本和固定配置已成功时展示复用原任务，不重复生成产物。

结果为私有 INDEXED，searchable=false。页面显示“私有索引已保存，正文检索尚未开放”；构建本身不批准许可、不发布版本，也不开放查询和模型外发。下载、解析和索引是技术事实，不能替代来源策略批准。

2026 年 10 月 16 日，真实 HTTP、常驻 Worker 和私有对象存储完成全量构建，历时 436.672 秒。产物完整回读、固定对象版本与摘要核验、解包后逐文件核验和新进程读取均通过；同一输入再次构建返回 existing=true，不增加产物，公开来源版本仍为空。真实任务、动作和列表共 5 个响应通过严格 Schema。浏览器已验证实时进度、最终统计和质量、复用提示、刷新恢复、普通用户无管理入口及退出；控制台无错误。该切片证据见 contracts/results/2026-10-16-s3-index-contracts.json。

索引覆盖 2,127,898 条来源句记录、82,951,215 个 Unicode 码点和 19,660,489 个词项，拒绝句数为 0。独立引擎验证在新进程核对全部原句和词项坐标，20 条明确查询的计数、首屏跨度与 KWIC 均一致。文档计数单位为导入的来源句记录；词项参考基于固定词层，不是独立分词质量金标。共享 4 CPU、8 GiB 环境的单次顺序核查中，字符零命中首屏最长 38.873 秒，完整计数最长 37.048 秒，未通过正式性能验收；不能当作并发 P95 或冷盘结果。引擎证据见 pipelines/query/results/2026-10-16-source-index.json。

2026 年 10 月 17 日，保留原索引、成员与 recipe，读取器优化后重新核对全部 2,127,898 条句记录及 19,660,489 个词项坐标，20 条固定字符字面串与词项等值查询的计数、首 50 条跨度和 KWIC 均一致。字符 10 条首屏最长 0.112 秒、完整计数最长 3.747 秒；词项 10 条分别为 1.246 秒和 1.512 秒。跨句零命中 endstart 首屏为 0.056 秒，组合字符零命中为 0.045 秒。该结果仍是共享 4 CPU、8 GiB 环境单次顺序核查，不是冷盘、并发 P95 或正式性能验收；复杂查询另按既有子集验证。证据见 pipelines/query/results/2026-10-17-source-reader-native.json。

POST /admin/sources/D12/index-builds 接收 acquisition_id 与 Idempotency-Key，返回 202、action_id、index_run_id、同值 job_id、state、existing 和 run。recipe 由后端固定，不能输入任意路径、URL、分词配置或身份。GET /admin/sources/{source_id}/index-builds 允许管理员读取已登记来源的构建历史，按 cursor、page_size 返回 items、total、next_cursor 与 allowed_actions.start；构建写入仍只接受 D12。

GET /admin/index-builds/{index_run_id} 返回固定 acquisition_id、recipe 的 ID 与摘要、来源身份、state、stage、attempt、progress、result、error 和 allowed_actions。stage 为 QUEUED、FETCHING、INDEXING、VERIFYING、STORING、INDEXED、FAILED 或 CANCELLED。成功 result 包含 index_id、INDEXED、searchable=false、identity_sha256、manifest_sha256、counts、artifact_bytes 与 quality，失败不得携带成功结果。

POST /admin/index-builds/{index_run_id}/cancel 与 /retry 接收空 JSON 和 Idempotency-Key；是否可操作以服务端 allowed_actions 为准。GET /admin/index-builds/{index_run_id}/events 使用 after_sequence、page_size。INDEX_ALREADY_ACTIVE、INDEX_QUOTA_EXCEEDED、INDEX_CLEANUP_REQUIRED、INDEX_RECIPE_CHANGED 等错误直接保留，前端不绕过后台限制。任务域独立于同步和项目上传，标识不能混用。

后续完整管理员页面将显示连接器、检查时间、当前发布版、最新同步阶段、成功数和失败数，提供真实上游“检查更新”和同步；撤回操作要求选择受影响能力并填写原因。上述后续页面不代表当前 D12 已实现上游检查或取得真实数据发布核准。数据管理员不能据此读取私人项目材料。

### 当前固定版本核准与发布

管理员从来源详情进入“核准与发布”，选择已成功的固定索引。界面显示实际 acquisition_id、原句覆盖、词项回核、采集许可声明及保存依据、unknown_owner 和 missing_endpoint_rows；这些质量计数与许可核准分别呈现。允许或拒绝必须明确选择，并填写核准说明与至少一个依据地址，不预选允许。

GET /admin/sources/{source_id}/policies/{acquisition_id} 读取当前策略；无记录返回 revision=0、decision=unknown。POST 同路径要求 Idempotency-Key，输入 expected_revision、decision=allow 或 deny、独立 export_decision=allow 或 deny、review_note、evidence_urls（最多 12 个 HTTP(S) 依据地址）。响应为 action_id 和 PolicyView，服务器写入核准人、时间、来源身份修订、采集与许可摘要。固定 scope=internal_research，export 按当前独立导出核准计算，model_egress=false；未提交导出决定时默认 deny。核准只作用这一采集版本；后续版本不继承。来源身份改变会使旧核准失效，改回字段也不恢复原核准。

POST /admin/sources/{source_id}/releases 要求 Idempotency-Key，输入固定 index_id 与 expected_policy_revision。当前策略、来源身份、固定索引、配置和对象存储回执由后端复核；返回 action_id、existing、ReleaseView，同时固定来源快照。相同索引复用原发布版，不增加产物。策略拒绝或身份改变后仍保留版本元信息，但 available=false，不得继续挂载或读取清单。目录整源 pending_review 不被单个采集版本的核准覆盖。

最初发布切片只批准内部研究并建立固定引用，后续成果切片增加独立导出决定；PUBLISHED 不代表公共查询已开放。真实 D12 当前没有许可核准；合成测试来源的核准只用于验证程序。页面刷新策略后清除旧发布状态，收到权限拒绝时清理相关缓存。2026 年 10 月 17 日，合成测试来源的真实 HTTP 核准、固定索引发布、整库挂载、清单回读和撤权检查通过；9 类共 23 个真实响应通过严格 Schema。浏览器验证管理员重复发布复用第二版，负责人挂载第二版、读取清单、移除并刷新后第一版挂载不变；只读成员没有增删或上传入口。外部撤销第一版许可后，读清单返回 403，旧清单被清除，刷新后显示许可受限且读取入口消失。验收数据与 26 个私有对象版本已清理，真实 D12 未批准。永久证据见 tests/integration/results/2026-10-17-source-releases.json 与 contracts/results/2026-10-17-s3-release-contracts.json。

### 当前目录读取接口

GET /sources 接收 q、language、category、status、capability、cursor、page_size，page_size 为 1 至 100，默认 50；输出 items、完整筛选结果 total、next_cursor。游标绑定筛选条件。GET /sources/{source_id} 读取详情；GET /sources/{source_id}/versions 接收 cursor、page_size，返回 items、total、next_cursor，版本条目为完整 ReleaseView，含 release_id、source_snapshot_id、index_id、acquisition_id、固定 recipe 和摘要、counts、quality、发布时 policy_revision 与 current_policy_revision、available、unavailable_reason；state=PUBLISHED，searchable 按当前策略和固定查询版本计算。单项元信息由 GET /sources/{source_id}/releases/{release_id} 读取，列表保留真实分页。

SourceView 保存 revision、created_at、updated_at；license_status 当前固定 pending_review，integration_status 为 catalog_only、verification_pending 或 experimental_evidence。capabilities 中 discover 为真，其余 remote_query、fulltext_analysis、export、model_egress 均为假。官方依据链接只说明登记依据，不承诺下载或当前可访问全文。

### 当前管理员目录写入接口

POST /admin/catalog 接收 source_id、name、publisher、entry_kind、categories、languages、official_url、materials、access_route、boundary，返回 201。PATCH /admin/catalog/{source_id} 接收完整可编辑元数据与 expected_revision。两者均要求平台管理员、Origin、CSRF 与 Idempotency-Key，返回 SourceView 和 action_id；不能写入许可、能力、接入状态或实验依据。

同幂等键不同参数返回 IDEMPOTENCY_CONFLICT，已有编号返回 SOURCE_EXISTS，版本冲突返回 REVISION_CONFLICT。页面保留未保存编辑并允许重新读取，不能静默覆盖并发修改。创建后刷新目录，编辑后显示服务端新 revision；管理员入口不赋予私人项目访问权。

### POST /admin/connectors

仅来源管理员。输入 source_id、adapter_type、允许的配置；输出 connector_id，201。配置只能来自已实现适配器；422 CONFIG_INVALID 返回字段错误。

### POST /admin/connectors/{id}/sync

仅来源管理员，携带 Idempotency-Key。输入 check_latest 或 target_version；202 返回 sync_run_id、job_id、state。409 SYNC_IN_PROGRESS 返回已有任务；422 SOURCE_NOT_CONFIGURED 表示配置缺失。

### GET /sync-runs/{id}

管理员或获准查看者。返回阶段、已处理量、质量报告引用、发布版本、实际错误和可重试状态；下载完成不等于可检索。普通研究者只读获准公开的版本状态。

### POST /admin/sources/{id}/restrict

仅来源管理员。输入 capabilities、reason、expected_policy_revision；202 返回 job_id、policy_revision。409 EDIT_CONFLICT 要求刷新；立即执行权限限制，后续任务完成受影响对象处理。

## 三 账号项目与成员

项目列表展示名称、负责人、更新时间及当前可用快照。新建只要求名称，研究目标可选。项目设置提供成员列表和角色变更。负责人、编辑可修改项目材料和记录；只读成员可读取获准材料、执行查询统计并查看成果，导出另验权限。研究助手会话首版归发起人，不开放多人共同续写。

### POST /auth/login 与 POST /auth/logout

登录输入 email、password，返回 actor、csrf_token；退出清除并撤销会话。采用同源 HttpOnly 会话 Cookie，HTTPS 部署设置 Secure，SameSite=Lax；写请求执行 Origin 和 CSRF 校验。凭据不存 localStorage。401 AUTH_INVALID 显示一次简短错误。

### GET /auth/session 与 GET /projects

登录用户读取身份、角色与可见项目。当前项目列表返回 items，只包含可访问项目；项目分页待后续补齐。刷新页面先恢复身份，不根据前端缓存自行判定权限。

### POST /projects 与 GET /projects/{p}

当前新建输入 name；201 返回 id、name、owner_id、role、created_at、permissions。创建人由服务器确定，name 最长 160 字符且不可为空；无效输入返回 422 VALIDATION_ERROR。创建项目尚无幂等账本，前端不得自动重试创建。research_goal、revision 和快照摘要待后续补齐。

### PATCH /projects/{p}

负责人或编辑更新项目名称与研究目标，输入 expected_revision；返回新 revision。409 EDIT_CONFLICT 保留输入并提供“刷新后重试”。删除项目不作为首条开发流程。

### GET 与 PUT /projects/{p}/members

当前仅负责人读取成员列表。PUT /projects/{p}/members/{user_id} 输入 role（editor 或 viewer），新增或更新已存在且启用的账号；返回 user_id、email、role。DELETE 同路径移除成员。负责人不可修改或删除，返回 409 OWNER_IMMUTABLE。账号搜索和邮件邀请尚未实现。

### 项目备份与恢复

项目设置提供备份、下载和恢复入口，助手调用同一项目迁移能力。POST /projects/{p}/backups 创建后台备份，GET /backups/{id} 读取进度与产物；项目负责人提交，内容按当前读取与导出权限生成。POST /project-restores/preview 接收已校验 backup_ref，返回可恢复对象、缺失来源与权限限制；POST /project-restores 明确预览引用和新项目名称后创建新项目，不覆盖已有项目。完成后返回新项目与任务引用，助手按新范围续接。数据库及整机备份属于运维，不开放为模型命令。

首次恢复由账号范围发起：POST /backup-uploads 输入 filename、size、sha256，返回本人 upload_id、受限上传地址和请求头；浏览器选择并传输备份包。POST /backup-uploads/{id}/complete 校验包完整性后返回 backup_ref，供恢复预览使用。只接受本人上传的项目备份包并重新校验材料权限，不要求预先创建空项目；上传凭据不进入模型上下文。

### 权限呈现

页面按服务端返回的 permissions 显示操作。隐藏按钮只用于交互，后端仍逐次鉴权。401 引导登录；403 显示当前操作不可用；不可暴露资源返回 404。权限变化后清理受影响数据缓存，不继续显示旧正文。

研究助手与手动入口使用同一权限。只读成员可建立本人会话，发现来源、读取获准材料、执行查询统计、复查证据；运行账本不视为修改项目材料。保存查询、笔记及修订仍要求写权限，导出独立检查 export 权限。负责人可通过助手执行成员管理，管理员可在独立的平台会话执行有权的管理业务。登录密码、连接器密钥等凭据由专用表单输入，不发送给模型。

## 四 材料上传挂载与快照

材料页分为来源挂载和私有材料，统一显示语言、规模单位、版本、处理状态。选中材料可保存子库筛选、预览成员数并“建立快照”。快照列表显示名称、固定版本、材料数、处理配置和索引状态；仅 READY 可作为研究输入。

### 当前项目整库挂载

项目页面提供“项目来源”，编辑或负责人搜索来源并选择具体发布版。只读成员读取已有挂载；创建和移除入口依据后端 allowed_actions 显示，平台管理员身份不能替代私人项目成员身份。版本选择标明当前是否允许挂载及建立研究快照后是否可检索；未发布和受限版本不能提交。挂载保持整库固定版本，不接收 filters；研究快照可组合这些挂载与私有固定修订，子集索引另行交付。

GET /projects/{p}/mounts 接收 cursor、page_size，返回 items、total、next_cursor、allowed_actions.create。POST 同路径输入 source_snapshot_id 与 Idempotency-Key，201 返回 action_id、existing、MountView。相同项目中的同一有效固定快照复用已有挂载；移除后的历史不恢复，重新创建产生新的挂载。新发布版不自动升级旧挂载。

GET /projects/{p}/mounts/{mount_id} 返回固定引用、ACTIVE 或 REMOVED 状态、发布版当前可用性，以及 read_manifest、remove 操作权限。POST /projects/{p}/mounts/{mount_id}/remove 接收空 JSON 和 Idempotency-Key，返回移除后的历史记录。GET /projects/{p}/mounts/{mount_id}/manifest 实际回读私有固定清单并核对摘要，返回 mount_id、source_snapshot_id、manifest_sha256、manifest，不返回对象存储键、VersionId、访问凭据或对象 URL。页面提供“读取固定清单”，收到拒绝后清除旧清单；项目权限失效时清除项目来源缓存。

SOURCE_POLICY_DENIED、SOURCE_IDENTITY_CHANGED、SOURCE_POLICY_MISMATCH、MOUNT_REMOVED 等阻止当前读取或写入；POLICY_REVISION_CONFLICT 提示重新读取核准版本。移除、撤权与身份变化后，旧请求重放及 Pi 历史依赖仍须重新鉴权。混合快照和正文查询按下述独立接口执行；后续子集与挂载升级另行交付。

### POST /mounts/{id}/upgrade

编辑或负责人显式指定新的 source_snapshot_id。先用 GET /mounts/{id}/upgrade-preview?target=... 查看规模和成员差异；提交返回新挂载或快照引用及 job_id，旧研究引用不变。缺少可用新版返回 422 TARGET_VERSION_INVALID。

### POST /projects/{p}/uploads

编辑或负责人提交 filename、size、media_type、sha256 和 Idempotency-Key；201 返回 upload_id、action_id、同源 upload_url、method、expires_at、max_bytes 及当前会话信息。新项目无需已有快照或对齐修订。浏览器以 Cookie 和 CSRF 向该地址 PUT 文件，进度只表示传输。类型不支持返回 422 UNSUPPORTED_FORMAT；单文件超限返回 413 UPLOAD_TOO_LARGE，项目准入超限返回 413 PROJECT_UPLOAD_QUOTA_EXCEEDED。

### POST /uploads/{id}/complete

上传完成后提交空 JSON 对象及 Idempotency-Key；202 返回 status=accepted、action_id、job_id、upload_id、任务 state 和 result_ref=null。相同键和参数返回原操作结果，不创建重复任务。校验由后台执行，失败原因保存在 job.error；checksum 或文本格式失败不自动重试。当前不返回 document_id，也不接收解析映射；CSV／TSV 列映射和 JSONL 字段路径在后续导入步骤实现。

完整助手页面的文件选择交互仍为后续目标。当前由独立上传表单取得用户选中的文件并传输；Pi 导入适配器只接收受限 upload_id 和显式语言，不返回文件名、正文、质量计数、上传地址或凭据。传输、校验和解析是不同步骤，不能将模型回复当作已上传或已解析。

### 私有 TXT 解析与固定修订

项目“私有文本”从 GET /projects/{p}/uploads?state=VALIDATED 的真实分页列表选择已校验 TXT。接受 .txt 且声明 text/plain 或 application/octet-stream 的文件，用户必须明确选择中文 cmn 或英文 eng。POST /projects/{p}/imports 输入 upload_id、language，要求编辑或负责人及 Idempotency-Key；202 返回 action_id、job_id、import_id、state、run。按钮为“解析 TXT”，不将该步骤称为建立检索索引。

GET /projects/{p}/imports 及 /imports/{import_id} 展示真实解析任务、阶段、字节与记录进度、错误和 allowed_actions；取消或有限重试复用 /jobs/{job_id}/cancel、/retry。TXT_IMPORT 与 UPLOAD_VALIDATE 共享持久任务账本，原上传仍保留 VALIDATED。失败或取消不能发布修订；READY 材料只是可靠解析结果，尚未建立研究索引。

GET /projects/{p}/materials 与 /materials/{material_id} 返回材料及其不可变 revisions、latest_revision、语言和状态，不返回全文或对象地址。每次成功修订包含原上传、固定 parser recipe、canonical 与 manifest 摘要，以及 documents=1、segments、characters。质量明确 complete_text_preserved=true、rejected_segments=0，分句采用固定标点与换行规则，不宣称语言学分句金标。相同上传、语言和固定 recipe 复用原任务；更正语言产生同材料的新修订，失败不遮蔽旧成功修订。

文本严格按 UTF-8 解码，只移除一个开头 BOM 并记录映射；其余 Unicode、CRLF、CR、LF 和空白原样保留。拒绝无效编码、NUL、空白文件及实际超限，不截断。一个上传 TXT 是一个文档，内部多句段不增加文件数；相同内容的不同上传材料也不合并为一个文件。

### 当前固定研究快照

项目“语料检索”页选择已有快照，或由负责人、编辑选择已挂载来源和私有固定修订。POST /projects/{p}/snapshots 接收 mount_ids、material_revision_ids，两数组默认空，合计 1 至 16 项、各自不重复；同一材料不同修订同时出现返回 MATERIAL_REVISION_CONFLICT。旧单 mount 请求仍有效。跨页已选名称和修订单独列出，可逐项移除；不得把最新修订静默替换用户已选修订。

202 返回 action_id、existing、job_id、snapshot；初始 PREPARING。单个来源挂载复用固定来源索引，index_kind=source_reuse；纯私有、多来源或混合成员在后台构建项目索引，index_kind=project。只有可靠索引和缓存准备成功后才 READY，失败显示正式错误并按 allowed_actions 有限重试。平台管理员不能越过项目成员权限。

GET /projects/{p}/snapshots 返回 items、total、next_cursor、allowed_actions.create；GET /projects/{p}/snapshots/{id} 读取固定成员、摘要、状态与实时可用性。成员为 whole_source_mount 或 private_revision 严格分支，分别绑定固定发布索引或材料修订。counts.documents 同时给出 document_units.source_records 与 private_files，不把来源句记录说成连续原文档。混合中任一成员失权，整个固定快照不可用；历史身份保留但材料计数为 null，不静默移除该成员重算旧结果。新增修订不升级旧快照。

当前不接受 filters、自选 recipe、name 或任意存储路径；过滤子集快照与正文编辑仍为后续目标。2026 年 10 月 17 日私有／混合切片已通过 51 项契约测试、38 项 Node 回归及构建检查，真实 HTTP 的 14 类 36 条响应通过严格模型校验。浏览器中，同上传同语言解析复用英文修订 1，中英文两份修订均保留；负责人选择两个文件建立纯私有快照，得到 2 文件、5 句段、12 词项，Hello 检索为 5 次命中、5 句段、2 文件。原句包含 emoji 与组合字符，全文 [8,13) 的 Hello 正确高亮。只读成员没有上传、解析或建立快照入口，但可查询混合快照，得到 125 次命中、65 句段、62 文档单位（60 来源句记录＋2 上传文件），分页为 50／50／25；后页私有原句坐标保持正确。来源拒绝后，混合结果与原句自动清空并禁用检索，纯私有快照仍返回 5／5／2。实际验收数据清理通过，证据见 contracts/results/2026-10-17-s3-private-contracts.json。

## 五 查询构建与上下文选择

当前项目“语料检索”页提供字符与词项 form 等值查询，可选精确匹配、连续序列、有限间隔和任一匹配。组合输入每行一项，间隔明确以码点或词项计；上下文窗口为前后各 0 至 200 个 Unicode 码点，默认 40。页面只展示已实现的句内查询。词性、词元、正则、元数据筛选、AND／NOT 与同段匹配尚未接入本片 HTTP。

以下控件表保留后续完整查询设计，未上线项不在当前页面提供可用入口。

| 控件 | 输入和行为 |
| --- | --- |
| 单位 | 字符或 token；间距控件随之明确显示“字距”或“词距” |
| 主查询 | 必填正向模式；默认精确字符串，禁止悄悄转为语义召回 |
| 条件 | 同句包含或不包含；明确显示“主查询 A，条件 B” |
| OR | 增加备选正向模式；返回跨度并集，同跨度只计一次 |
| 范围 | 默认同句；可选同段；上下文窗口独立设置 |
| 结果操作 | 排序、二次筛选、保存查询、按明确种子抽样 |

### 查询契约

POST /projects/{p}/queries 输入 snapshot_id、query、page_size 和 context_codepoints。page_size 为 1 至 50，默认 50；context_codepoints 为 0 至 200，默认 40，明确拒绝 context_tokens。query 固定 dsl_version=corpus-query/v1、within=sentence、overlap=all、normalization=none；排序固定为 document_ordinal、start、end。字符使用 literal、sequence 和 any_of；词项只允许 attr=form、op=eq。不得传入任意 CQP、对象路径或自选 recipe。

完整 AST 设计中的 condition={operator:and|not, pattern, within} 表示锚点过滤；OR 使用 pattern.type=any_of 与 patterns。已有原型与正式查询语法设计保留，当前 HTTP 只接收前述可执行子集。gap 必须有前后正向项，拒绝开头、结尾、连续 gap 或 min 大于 max；不支持的属性和组合明确报错，不能静默改写成普通字面查询。

A 出现两次、B 出现三次的同一句：A 为主查询且同句包含 B，返回 2 个命中和 1 个句子。交换主查询会改变命中数。页面始终显示主查询与过滤条件，不把二者呈现为对称表达式。

### 快照与已有结果

切换快照后清除不兼容属性，保留可理解的查询草稿，等待重新执行。旧结果留在自己的运行记录中，标记原快照；不会自动换材料重算。切换项目时关闭原项目结果和 AI 上下文，不能把旧会话绑定到新项目。

## 六 KWIC 与查询接口

结果区展示命中次数、匹配句段数和匹配文档单位数。document_count_unit 为 imported_sentence_record、uploaded_file 或 mixed_document_units；混合明确显示“文档单位（来源句记录＋上传文件）”，并给出 matched_document_units.source_records、private_files。私有文档按原文件去重，不能把每句段算作文件；Tatoeba 独立句记录也不冒充连续原文档。网页当前每页 50 条，KWIC 直接显示后端 left、match、right；完整结果完成后可翻页及读取整句。原句按 Unicode 码点高亮，保留完整文本、来源句编号、实际坐标和安全来源链接，不伪造跨句上下文。

### POST /projects/{p}/queries

有材料读取和查询权限的项目成员创建运行，包括只读成员，携带 Idempotency-Key。202 返回 action_id、job_id、query_run_id、result_set_id、state、run。GET 同路径列出持久历史，GET /queries/{query_run_id} 读取当前状态；取消与有限重试走同一项目路径下的 /cancel、/retry。原发起人可管理自己的分析，负责人可取消项目内查询；这些权限不等于材料写入。快照未就绪返回 SNAPSHOT_NOT_READY，不支持语法明确拒绝。

### GET /projects/{p}/result-sets/{id}/hits

输入 cursor 与固定 page_size，返回 hits、has_more、next_cursor、snapshot_id、query_run_id、page_state、count_state、completeness 及三项计数。首屏先发布有限预览；完整跨度和计数尚未发布时，计数全部为 null，preview 不给下一页游标。首屏尚未完成时返回 202、空 hits 和 pending，不能显示为零命中；完整零结果才返回三项零值。后续页直接读取已完成的固定结果，不为每页建立计算任务。

每条 hit 使用 hit_ref={result_set_id,ordinal}，含 revision_id、segment_id、source_sentence_id、start_cp、end_cp、left、match、right。字符坐标为固定 revision canonical 全文 Unicode 码点半开区间；词项查询另返回真实句内 token_start/end 及全库 global_token_start/end，字符查询四项均为 null。origin_kind 区分 source/private，document_id 固定文档身份；私有命中提供 material_id、material_revision_id 与文件名，source_id、source_sentence_id、source_url 均为 null，不伪造来源链接。evidence_id 固定 null，尚未实现保存证据对象。

GET /projects/{p}/result-sets/{id}/hits/{ordinal}/context 只在完整结果完成后返回对应句段与同一全文命中坐标，并给出 context_start_cp。前端以 start_cp-context_start_cp、end_cp-context_start_cp 对 Array.from(text) 高亮；来源独立句的 context_start_cp=0，不改变既有坐标。接口重新核验当前项目、来源许可和挂载。摘要绑定游标及固定 hit_ref 都不提供额外权限。缓存缺失明确返回 503 CACHE_NOT_READY，可通过 POST /projects/{p}/result-sets/{id}/prepare 准备固定结果；GET 不暗中启动下载或重新计算。页面在 401、403、404 或来源不可用时清除旧页、计数与原句，切换项目也清除；历史记录重新读取其原快照，不跟随输入框改换材料。

### 固定证据与后续结果操作

已完成查询的证据保存与读取使用 /projects/{p}/evidence，具体不可变登记、原句和权限规则见“证据、研究笔记与成果”。以下已保存查询和二次结果视图仍为待实现规格，不能由当前命中上下文入口推定完成。

### POST /projects/{p}/saved-queries

编辑保存 name、snapshot_id、query、context_codepoints；返回 saved_query_id。GET 同路径列出已保存查询。保存不会再次执行；打开后显示原参数，用户选择运行。

### POST /result-sets/{id}/views

可读取结果的项目成员创建排序、二次筛选或抽样视图，输入 sort、filters、可选 sample_size、seed；202 返回 view_id、job_id。完成后读取结果仍走 /result-sets/{id}/hits，使用新 result_set_id。返回 population_result_set_id 与抽样方法，原总体不变。

### 计数与显示

当前完整结果未完成时三项计数均为 null，页面显示统计处理中；失败时明确统计未完成，已获准的首屏预览可保留，不以预览行数代替总数。分页绑定固定查询、快照、顺序和页面大小，前端以 hit_ref.ordinal 标识行。后续抽样结果需显示样本量与总体引用，不能覆盖原总体。2026 年 10 月 17 日已通过 8 类 12 个真实 HTTP 响应校验及浏览器验收：负责人创建 62 句、304 词项的合成验收快照，观察 PREPARING 到 READY；零命中返回三项零值。只读成员检索 Hello 得到 120 次命中、60 个句段、60 个导入句记录，分页为 50／50／20；原句按码点 [11,16) 高亮，句内词项坐标为 [3,4)。结果展示实际已执行模式，改动草稿不会改写旧结果。刷新后恢复三条历史，选择旧运行自动绑定其原快照；撤权后清空 KWIC、计数和原句，禁用检索，刷新不再展示失权历史。验收数据已清理，真实 D12 未因合成验收获得许可核准。证据见 contracts/results/2026-10-17-s3-research-contracts.json。

固定全量索引另通过 20 条查询的完整跨度、三项计数及新进程 180 次页面／上下文核对。共享 4 CPU、8 GiB 环境单次测量中，字符首屏最长 0.070 秒、完整跨度导出落盘最长 6.512 秒，词项分别为 1.041 秒和 7.058 秒。该完整结果成本不同于此前仅计数测量，不代表独占环境、并发 P95 或运行服务端到端验收；Windows 绑定目录输出超时的失败证据单独保留。证据见 pipelines/query/results/2026-10-17-source-query-engine.json。

## 七 统计与比较

分析页按“词频”“词组”“共现”“比较”选择方法，显示输入快照、单位、参数和运行按钮。结果表与图共用后端结果，点击结果词项进入对应查询，带回运行、快照、筛选及证据。

| 方法 | 必须展示的参数或结果 |
| --- | --- |
| frequency | 字符或 token、属性、停用词配置；原始频次、文档频次、总量和标准化频率 |
| ngrams | n 为 2 至 4、单位、句界约束、最低频次；频次及分母 |
| collocations | 节点、窗口左右宽度、单位、最低频次；共现频次与 logDice 方法版本 |
| keywords | 目标和参照快照、单位、归一化基数、零频平滑；log likelihood 与 log ratio |
| distribution | 年份、体裁或来源维度；每组原始量、分母、标准化结果及缺失值组 |
| query_comparison | 两个固定查询及范围；各自命中、分母和可比性信息 |

### POST /projects/{p}/analyses

有输入材料读取和分析权限的项目成员，包括只读成员。输入 input_ref、method、params；比较类另传 reference_ref。input_ref 引用快照或完整查询运行。202 返回 analysis_run_id、job_id、state。422 INCOMPATIBLE_UNITS、EMPTY_REFERENCE 或 METHOD_INVALID 提示可修正原因。

### GET /analyses/{id} 与 GET /analyses/{id}/rows

项目成员读取状态、方法版本、输入摘要、结果规模、分母及 warnings；rows 接收 cursor、page_size、sort，返回 items、next_cursor、evidence_refs。按后端允许字段排序，不在当前页内伪装全局排序。

### 前端呈现

图表只绘制返回的聚合结果；排序前若只取前 N 项，标题直接显示“前 N 项”。不可比语料仍可查看原始结果，但影响解释的单位与范围差异明确显示。首版显著性指标作为探索性排序，不由前端标注为研究结论。空结果显示“没有符合条件的结果”及调整参数入口。

## 八 双语研究与修订

双语页选择来源侧语言和查询范围，默认源句与译句并排显示，允许切换方向。同一源句的多条译句分组展示；每条关系保留边 ID 和出处。顶部同时展示来源侧唯一句数、目标侧唯一句数与关系数；展示行数不作为语料规模。

### POST /projects/{p}/parallel-queries

有输入读取和查询权限的项目成员，包括只读成员。输入 snapshot_id、query_side、query、alignment_overlay_revision；202 返回 run_id、job_id。固定覆盖层修订，未指定时由服务器解析当前修订并回传，之后不可跟随最新值变化。422 LANGUAGE_PAIR_UNAVAILABLE。

### GET /parallel-results/{id}

项目成员，支持 cursor、page_size。返回 source_segments、target_segments、edges、display_rows、next_cursor，以及 matched_source_segments、matched_target_segments、matched_edges、count_state。所有计数完成前未知字段为 null；端点含 segment_id、revision_id、evidence_id。

### POST /projects/{p}/alignment-layers

编辑或负责人创建项目覆盖层，输入 snapshot_id 和基础关系集，可选 source_release_refs；来源关系、私有或混合材料都以固定研究快照为范围根，纯私有材料不要求 mount_id。201 返回 layer_id、revision。GET /layers/{id} 返回范围与当前修订。共享来源关系保持不变；项目不能提交范围外端点。

### POST /layers/{id}/commits

编辑提交 expected_revision、operations。每条包含 operation、base_edge_id 或 project_edge_id、source_segment_id、target_segment_id 和确认状态；新增边没有 base_edge_id。返回新 revision、变更边。候选保存不等于人工确认；确认必须绑定用户明确指定的边集合和修订，以及服务器记录的指令或确认动作。409 EDIT_CONFLICT 保留本地草稿、刷新后重提；422 ENDPOINT_OUT_OF_SCOPE。

### 自动对齐交互

双语页和助手都可选择项目内两份已处理材料、语言方向与对齐方法，提交同一后台对齐能力。结果展示候选句对、未配对句段、方法版本和需要复查的关系；有分数时说明其含义，不当作人工正确率。任务详情保留输入修订、参数、进度和实际错误。

首版自动生成一对一句对候选；用户可在双语页逐条修改，也可指示助手替换、拒绝、确认或保存明确选中的关系。复杂多对多只读，不用聊天绕开首版边界。保存得到新的覆盖层修订，后续分析固定该修订；原始材料、公共句对和旧运行保持原版本。具体对齐任务、候选读取和提交字段统一维护在[全业务能力契约](assistant-capabilities.md)。

### 对齐任务与候选接口

POST /projects/{p}/alignment-runs 输入 snapshot_id、source_segment_scope、target_segment_scope、源目标语言和 recipe_version；202 返回 alignment_run_id、job_id。GET /alignment-runs/{id} 返回状态、方法、输入版本、候选集合和未配对摘要。GET /alignment-runs/{id}/candidates 接收 cursor、page_size 和复查筛选，返回 candidate_set_id、items、next_cursor；候选含 candidate_id、两侧端点、match_score、review_reason 和 evidence_refs。保存候选的提交可引用 candidate_id，来源边、项目边与候选 ID 不混用。

POST /alignment-candidate-sets/{id}/reviews 由编辑或负责人提交 expected_review_revision、operations；每项指定 candidate_id 和 review、edit 或 discard，edit 另给项目范围内的一对一端点。返回新 review_revision，409 EDIT_CONFLICT 时保留编辑后刷新。审阅追加到独立修订，原始候选、分数和旧证据不改变；候选读取可指定 review_revision，返回审阅状态与修订端点。未保存候选通过此接口复查、修改或舍弃；保存时以 add 引用 candidate_id、review_revision 和明确端点。已有基础边或项目边才使用 replace、reject、confirm。用户已明确核对的候选可在 add 时附确认依据，一次完成保存与人工确认。

### 编辑范围与统计

首版只在明确一对一关系上显示新增、替换、拒绝和确认操作；多对多等复杂关系只读。保存成功后当前页面可选择按新覆盖层重新运行，旧结果不变。中文一句对应英文三句时显示 1、3、3；单语词频按唯一材料计算，不随关系展开重复。

关系导出包含两侧句段 ID、边 ID、覆盖层修订和 counting_unit。来源升级后修订作为迁移候选，不能自动继承人工确认。

## 九 研究助手交互

### K09 当前运行基础切片

登录后默认进入“研究助手”，同时保留项目和来源目录，以及项目材料、语料检索、笔记与成果的手动入口。会话范围可选“我的账号”或一个已授权项目；项目范围的材料引用仍为空。切换范围清除当前会话与显示记录，下一次发送建立干净的新会话；各范围未发送草稿只在内存中分别保留，不把旧会话正文迁入新范围。

页面读取真实会话、用户消息、工具调用摘要、持久运行状态和后台任务。GET /agent/runtime 未配置时显示“尚未配置模型”并禁发；后端显式开启 fixture 时显示“本地流程测试”；兼容 OpenAI 配置有效时显示“已配置模型”及服务端模型名，配置无效时显示“模型配置有误”并禁发。配置可提交不代表宿主在线或模型已经连通，尚未领取的运行显示真实“排队中”，不会伪造助手回应。用户已有兼容接口，实际 URL、模型名和协议仍待固定与实测，生产模型与材料外发尚未验收。

会话固定创建时的服务端配置身份。旧会话配置与当前配置不匹配时，仍可读取经当前权限复核的历史，页面禁止继续发送并提示新建会话；AGENT_CONFIG_CHANGED 拒绝后保留输入。用户明确新建后才使用当前配置，不将 fixture 历史或此前模型上下文自动交给另一提供方。浏览器不接收模型服务地址或密钥。

发送失败保留输入，SESSION_BUSY 不自动转为排队，本片没有 follow-up 队列。成功只清除已接受的输入。取消针对实际 run，离开工作台或打开手动页面不取消任务。成果按钮使用后端固定 kind 与 resource_id 映射到项目、材料、检索或成果页面，不打开模型生成的 URL。

刷新只在本机保存本人 session ID，消息、工具结果和凭据不存入 localStorage。页面重新读取和鉴权后恢复会话；默认轮询 session/run 元数据，仅状态或 event_sequence 变化才重读聊天投影。已显示的旧运行也独立重验依赖，避免被取消或失败的旧运行绕过后续基线检查。401、403、404 或 CHECKPOINT_AUTH_CHANGED 清除历史显示，并使旧响应失效；正文、工具参数、原始检查点和内部思考不属于聊天响应。

2026 年 10 月 17 日，本地构建、62 项契约测试和 5 项前端客户端及状态测试通过；实际运行 HTTP 的 7 类 10 份响应通过严格契约校验。固定测试流程实际提交上传校验、保存等待检查点，后台完成后在同一 run 的新 epoch 恢复，未重复写入，私有正文未进入模型。浏览器验证账号与项目范围隔离、真实项目消息完成、刷新恢复、返回账号历史和取消后会话列表终态同步。恢复默认未配置状态后，最终资源下非空输入保留、发送禁用、成功刷新无旧错误，手动项目入口正常；临时账号已清理，刷新回登录页。该范围是 K09 运行基础验收，不是完整 K09 或真实研究模型验收。

兼容协议增量已通过 63 项契约、6 项前端客户端及状态测试和网页构建；最终运行契约专题 5 项与完整 Ruff 检查通过。安装的 SDK 分别经本机合成 HTTP 服务执行 Completions 和 Responses 协议，每种协议的 7 类 10 份实际响应通过严格校验；各以两个独立宿主进程接续同一后台任务，epoch 从 1 到 3，业务 action、job 和执行 attempt 各一次，模型 HTTP 请求各 4 次。此结果验证真实协议适配与持久接续，不代表用户提供的外部接口已通过。

浏览器已验证模型配置标识、协议配置变化后旧历史可读且禁发、旧排队运行可取消，以及显式新建会话发送。Responses 首次本机 401 请求产生 FAILED／MODEL_AUTH_FAILED 且不发布检查点；同会话后续新运行成功并保存可靠检查点，刷新后保留失败和成功两轮。实际页面资源与冻结版本一致。用户接口地址、模型与协议仍待固定，材料范围和模型外发仍未开放，production_ready=false、生产工具 0 保持不变。证据见 contracts/results/2026-10-17-k09-provider.json；上一固定工作台验收保留。

### 后续完整研究交互目标

研究助手工作台是项目默认入口和一级导航页面，主区集中会话、任务过程与输入，辅助区展示材料范围、可用结果、证据和本会话成果。检索、分析与笔记可独立手动使用；“解释结果”“核对证据”“起草笔记”等操作统一返回主工作台，复用同一会话、输入、消息与队列。工具过程默认折叠，展开后查看方法与参数。SDK、原生工具名和内部状态不作为主要界面文案。

### 全业务调用与结果续作

助手调用当前身份有权使用的全部已实现业务：来源发现与管理、同步、项目与成员、挂载上传、清洗质检、子库快照、检索与结果操作、统计比较、双语对齐修订、笔记、导出、任务和业务状态查询。具体动作以[全业务能力契约](assistant-capabilities.md)的注册表为准；后续功能随业务同批接入，未上线能力不显示为可执行。浏览器登录、文件选择和下载由网页承接，运维部署不开放为模型脚本。

请求目标和参数清楚时直接执行，缺少必要参数时展示对应选择器或简短询问。保存查询、生成候选、笔记草稿、分析和导出不增加通用确认弹窗。删除、撤回和影响权限的操作核对明确目标与影响，已有相同授权不重复确认。人工确认必须由用户指定内容和修订，允许按钮操作或明确指令；模型判断不能代替人工确认。

工具返回的 result_view 指向手动页面和固定对象，前端用已登记路由映射渲染“查看结果”“继续编辑”等动作，不执行模型生成的任意 URL。跳转携带项目、快照、运行、候选集合或覆盖层修订；在手动页继续操作仍调用相同业务接口。同范围回到助手复用原会话；新范围按下节接续。工具成功后刷新相关对象与任务缓存，不能只在聊天中声称已保存。

### 可用能力与权限

当前 GET /me/capabilities 接收可选 project_id，返回当前身份可用的 manual_actions、空 available_tools 和生产 Pi 未完成验收的原因；项目与任务仍分别提供 permissions、allowed_actions。后续助手能力发现再加入 scope_kind、capability_id、availability 和 result_view。平台操作只在管理员会话开放；平台会话不混入私人项目正文。账号范围支持项目发现和创建，尚无项目或研究快照也能开始选材；正文读取仍要求明确的项目和固定范围。

| 动作或状态 | 页面行为 |
| --- | --- |
| 提交研究问题 | 固定 input_scope；显示已使用的快照和分析引用 |
| 查询与分析 | 用户要求执行时调用正式工具，结果可跳转手动页；仅要求草稿时展示待编辑条件 |
| 上传与对齐 | 打开文件选择或材料选择，展示真实传输和后台任务，结果进入双语页继续修订 |
| 保存与确认 | 按指令保存并显示实际修订；人工确认记录明确内容、修订和用户指令 |
| 证据问答 | 引用可点击到原文或结果行；没有证据时明确说明未找到 |
| 统计解释 | 先取得完成的后端统计结果，再给解释；展示方法与结果入口 |
| 忙碌时发消息 | 提供“排队发送”，成功后显示队列位置；不提供 steer |
| 取消 | 显示“正在取消”，收到持久终态后结束；已生成成果仍可查看 |
| 需要核对 | 显示具体原因与已有任务入口，用户选择新建会话或人工检查 |
| 权限变化 | 停止继续发送受影响材料；提示改用仍有权限的材料创建新会话 |

### 上下文绑定

会话固定 scope_kind、发起人和 input_scope；项目会话另固定 project_id。同一输入范围的页面与助手复用会话。改变快照、材料或覆盖层修订时新建会话，旧消息、工具正文和摘要不带入新会话。页面切换不会改变进行中的运行；解释和笔记固定实际运行及证据，未发送输入按范围隔离。

同一固定快照和覆盖层上的新查询、统计、证据及笔记是范围内派生成果；增加 result_refs 不改变 scope_digest，不另建会话。只有项目、材料成员、快照或覆盖层身份实际变化才触发新范围，防止每次查询后都被迫换会话。

创建项目、建立快照或保存新覆盖层后，工具只向原会话返回对象引用、计数和 scope_effect。用户已要求后续分析时，服务端记录 continuation_intent，包含新目标引用、允许步骤、结构化参数和原授权引用；旧 run 结束后创建净化会话，重新鉴权、读取新范围并继续。工作台将 next_session_id 关联为同一任务的下一步，显示新范围，不要求用户重复输入。续接不继承旧正文或摘要，原排队消息留在旧会话并要求选择适用范围；没有后续指令时仅展示成果入口。

### 真实状态

页面成功状态只认 FastAPI 发布的 SUCCEEDED。模型停止输出、Pi 发出 agent_end 或 SSE 结束都不意味着研究任务成功。等待统计时展示关联任务，用户可以继续浏览其他页面；切换到手动工具页或关闭网页都不取消运行。

## 十 研究助手会话接口

### 当前 K09 HTTP 契约

所有以下路径以 /api/v1 为前缀，使用已有 Cookie、Origin 和 CSRF 规则。GET /agent/runtime 返回 production_ready=false、mode、fixture_enabled、can_submit、服务端 config_id 或 null、reason 和安全的 runtime_manifest。mode 为 unconfigured、fixture 或 openai-compatible；can_submit 只表示配置允许受理，不保证宿主在线。未配置时 reason=MODEL_NOT_CONFIGURED；兼容配置错误时 reason=MODEL_CONFIGURATION_INVALID，config_id 与 manifest 均为 null，禁止提交。

fixture 的 config_id 固定为 local-fixture-v1，原有八字段 manifest 保持不变。真实提供方 config_id 为 openai- 加配置 SHA-256 的前 48 位，manifest 使用 corpus-k09-openai-v1、corpus-openai-compatible 和 corpus-explicit-resources-v1，另明确 model_api 为 openai-completions 或 openai-responses，并含 model_config_sha256。两类清单严格分支，不用额外 null 字段改变旧归档。浏览器只读取配置摘要与模型标识，不得到服务地址、模型或宿主密钥；模型选择不是用户消息或工具参数。

POST /agent/sessions 只接收 scope，201 返回 session_id、scope、scope_digest、config_id、活动运行与检查点 ID、lease_epoch 和创建时间。GET /agent/sessions 可按 scope_kind、project_id、before、limit 读取本人历史；GET /agent/sessions/{id} 重新核验访问。项目 scope 的 snapshot_ids、material_revision_ids、result_refs 只允许空数组，alignment_overlay_revision 只能为 null。

POST /agent/sessions/{id}/runs 接收 request_key、1 至 8000 字符的非空白 message 和 scope_digest，201 返回持久 RunView。同键重试绑定同一消息与范围，不以重发新消息恢复任务。范围不同返回 SESSION_SCOPE_CHANGED；会话繁忙返回 SESSION_BUSY；运行配置未开启或无效返回 AGENT_RUNTIME_UNAVAILABLE；旧会话配置不匹配返回 AGENT_CONFIG_CHANGED。拒绝提交保留输入，不推断已经排队。

模型错误仅显示受限原因：MODEL_AUTH_FAILED 为认证失败，MODEL_RATE_LIMITED 为请求受限，MODEL_TIMEOUT 为响应超时，MODEL_REQUEST_FAILED 为调用失败，MODEL_RESPONSE_INVALID 为响应格式不支持；不显示上游原始错误、地址或凭据。没有业务调用和恢复检查点的模型失败可进入 FAILED 并释放会话；已有调用时保留 WAITING_REVIEW，不能丢弃已发生的业务事实。

GET /agent/sessions/{id}/runs 和 /messages 支持 before、limit，返回 items、next_before；消息投影按 run 包含 user_message、assistant_messages 的 id/text、工具 invocation_id/tool_name/status/result_view 和实际状态。助手文字仅来自可靠检查点中的可展示文本，原始 SDK 日志不直接返回浏览器。工具数据、参数和内部思考均不在投影中。

GET /agent/runs/{id} 返回运行及 waiting_jobs 状态；状态为 QUEUED、RUNNING、WAITING_JOB、WAITING_REVIEW、CANCELLED、SUCCEEDED 或 FAILED。GET /agent/runs/{id}/events?after 返回至多 100 条持久 JSON 事件与 next_after，当前不是 SSE；网页仅展示已知状态、工具与事件类型，不转储原始 payload。POST /agent/runs/{id}/cancel 接收空 JSON，返回实际状态。

后台接受必要任务后，可信宿主保存核验过的完整线性会话并进入 WAITING_JOB；后续领取重新校验范围、任务与依赖，再在同一 run 的新执行 epoch 恢复。必要任务未成功不能发布 SUCCEEDED；缺失或不明确的上下文仍进入 WAITING_REVIEW。固定任务引用由后端账本产生，浏览器和模型不能替换任务或报告路由。

Pi SDK、内部领取、执行凭据与归档接口不直接暴露浏览器；本片不增加通用工具或生产材料授权。严格契约见 contracts/agent.py、contracts/types/agent.ts 与 contracts/schemas/k09-agent-*.schema.json。

### 后续完整会话与材料范围接口目标

以下项目别名路由、follow-up、SSE 和材料范围自动接续仍为目标规格，与上列当前实现分开验收。

当前后端支持已发布的完整线性 Pi v3 检查点，经私有对象存储与数据库指针固定；后续 run 在新目录打开副本恢复上下文。成功仍要求 settled、授权、工具账本及必要任务核对通过，模型结束不能提前显示成功。缺失或不可靠检查点、进行中调用不明确时保持 WAITING_REVIEW；无外部资源、无真实模型网络的固定 provider 验证不代表生产材料外发或完整恢复验收。

2026 年 10 月 16 日真实双进程验证已通过：首个 run 创建项目并发布检查点，第二个独立 Node 进程从归档恢复同一会话，继承项目结果且没有重复工具调用，两次均取得后端 SUCCEEDED。该结果仅验证当时内部已完成会话接续；新增 K09 页面与任务等待接续另行验收。

### POST 与 GET /projects/{p}/agent-sessions

项目成员创建自己的会话，输入 name、initial_scope；201 返回 session_id、scope_kind、project_id、owner_id、active_run_id。只读成员创建会话不获得写工具权限。列表只返回本人的可访问会话。GET /agent-sessions/{id} 返回会话摘要、可见消息投影、活动运行、待发送列表及关联的前后会话引用。

### 账号与平台会话入口

POST 与 GET /agent-sessions 支持 account 和 platform 作用域，输入 name、scope_kind、initial_scope；POST /agent-runs 提交同结构运行。平台会话要求具备对应平台业务权限，各工具逐项鉴权；账号会话只允许账号范围业务。项目路由仍为同一业务处理器的项目入口。创建新项目或跨作用域执行已授权步骤时采用 continuation_intent 接续，不将项目会话直接改成平台会话。后续读取、取消和事件均复用 /agent-sessions/{id}、/agent-runs/{id}。

### POST /projects/{p}/agent-runs

输入 session_id、message、input_scope、model_config_id，携带 Idempotency-Key；202 返回 run_id、state。input_scope 引用 snapshot_ids、可选 result_refs 和 alignment_overlay_revision；身份由服务器绑定。409 SESSION_BUSY 返回 active_run_id；403 MODEL_EGRESS_DENIED；422 SCOPE_INVALID。input_scope 必须与会话固定范围一致，变化时返回 409 SESSION_SCOPE_CHANGED。前端按用户当前目标建立新会话；已授权任务产生新范围时由宿主按 continuation_intent 接续，不反复提交失败请求。

### POST /agent-sessions/{id}/follow-ups

仅会话所有者。输入 message、input_scope，201 返回 follow_up_id、queue_position。input_scope 必须与会话固定范围一致；改变范围需新建会话。当前 run 结束后开始新的 run。DELETE /agent-sessions/{id}/follow-ups/{message_id} 删除尚未开始的消息；已开始返回 409 MESSAGE_ALREADY_STARTED 并提供 run_id。

### GET /agent-runs/{id} 与 GET /agent-runs/{id}/events

仅会话所有者。详情返回 state、input_scope、tool_calls、job_refs、final_result_ref、artifacts、next_session_id 和 error。工具结果带 result_view、scope_effect 与 version_refs，页面从业务引用定位结果。SSE 使用 event_id、sequence、kind、run_id、payload；流式文本用于即时展示，完整答复从详情读取。Last-Event-ID 用于重连。

### POST /agent-runs/{id}/cancel

仅会话所有者，重复调用幂等。返回实际 state；CANCEL_REQUESTED 不显示为已取消。服务端拒绝新工具并处理专属子任务；已发布成果不删除。操作返回 409 RUN_FINISHED 时读取终态。

关联任务的取消按钮指向当前活动 run；取消后不再启动尚未开始的 continuation。已保存的快照、修订和成果继续保留。

### 续接规则

会话繁忙不自动把普通新消息改为排队，前端调用明确的 follow-ups 接口。服务重启后按 run_id 恢复状态；前端不得通过重发上一条消息恢复任务。无可靠检查点时显示 WAITING_REVIEW，保留已有成果入口。

## 十一 证据、研究笔记与成果

项目“笔记与成果”页提供研究笔记、已保存证据和导出任务。查询页只在完整结果完成后提供“保存证据”和完整查询导出；命中上下文中的 evidence_id=null 不代表已保存证据。保存是明确的后端登记动作，成功后产生真实不可变 evidence ID。编辑或负责人可保存证据、创建和修改笔记；只读成员可阅读获准成果，并在独立导出许可允许时导出。

### 固定命中保存与读取

POST /projects/{p}/evidence 输入 result_set_id、ordinal，ordinal 从 0 开始，携带 Idempotency-Key。服务器按完整结果重新定位原文和坐标，返回 action_id、existing、evidence；不接受浏览器提交的引文、起止坐标或伪造证据 ID。GET /projects/{p}/evidence 返回分页列表，GET /projects/{p}/evidence/{id} 返回不可变上下文、固定查询方法和摘要，并重新核验当前权限。页面按 start_cp/end_cp 减 context_start_cp 后，以 Unicode 码点切片高亮原句。

### 笔记与不可变修订

GET 与 POST /projects/{p}/notes 读取分页列表或新建笔记。创建输入 title、body、evidence_ids、query_run_ids；查询引用必须已完成，零命中研究也可关联其方法。PATCH /projects/{p}/notes/{id} 另传 expected_revision，每次保存产生新的 draft 修订，不覆盖旧版，也不继承“已接受”状态。GET 同单项路径可带 revision=N；GET /projects/{p}/notes/{id}/revisions 读取历史列表并支持继续加载。

笔记显示引用与权限依赖分开记录：authorization_evidence_ids、authorization_query_run_ids 继承前一修订依赖并加入本次引用，合计最多 100 项，超限明确拒绝。移除展示引用不会解除仍可能包含旧引文的正文权限。标题和正文按整份修订依赖重新鉴权，失权列表隐藏该项，详情拒绝读取；页面清除旧正文、证据原句及选择，旧异步响应不能恢复缓存。

POST /projects/{p}/notes/{id}/accept 只接收 expected_revision，要求真实登录用户的会话和 CSRF。接受固定当前修订；模型不能提供 confirmed=true 代替授权。409 NOTE_REVISION_CONFLICT 保留编辑草稿，用户可重新读取服务器修订后处理冲突。显式保存成功后才显示保存结果；页内切换、项目与检索导航、切换项目、退出和关闭页面均保护未保存修改。

### 完整查询与固定笔记导出

POST /projects/{p}/exports 输入 format 和 target，携带 Idempotency-Key。format 只接受 csv 或 json；target 为 query_runs（1 至 16 个唯一 query_run_ids）或 note_revision（note_id、revision），两者互斥。多个查询按给定顺序完整导出，各自保存计数、单位和方法，不构造跨查询去重总数。查询页当前提交一个完整运行，不能用当前页、游标或首屏预览替代完整范围。笔记导出固定一个修订及其结构化证据引用，保留 draft／accepted 状态。

返回 202 action_id、export_id、job_id 和真实任务；export_id 与 job_id 相同。GET /projects/{p}/exports 和单项路径读取进度、错误、实际文件名、类型、字节数和 SHA-256。CSV 成果包是 ZIP，包含 results.csv 与 methods.json；JSON 为保留原文的单文件。CSV 所有非空文本使用可逆单引号前缀 text-prefix/v1 防止公式执行，编码帮助按需展开。记录同时保留 0 基 ordinal 和每个查询 1 基 row_number，避免显示行号与命中身份混用。

任务完成后 GET /projects/{p}/exports/{id}/download 重新鉴权，由 API 代理私有对象字节，不暴露对象存储地址或凭据。尚未完成、失败与取消分别显示真实状态；取消和有限重试走既有 jobs 接口。只读成员可取消或重试自己获准的 EXPORT 任务，不能因此获得上传、导入或笔记写权限。下载失败不伪装为重新计算完成。

### 独立导出许可与来源说明

管理员在固定采集版本的策略页分别选择内部研究 decision 与 export_decision；导出默认 deny，不继承内部研究 allow。两项选择共同记录核准说明和依据，实际许可由后端判断。来源身份或许可摘要变化使旧核准失效，不能通过保留 allow 字段恢复权限。撤回导出只阻止导出读取和下载，不阻止仍获准的手动研究；撤回内部研究则阻止相关原文、证据和笔记。真实 D12 的许可没有被测试来源核准代替。

成果携带固定快照、查询 AST、计数单位、输入修订、recipe、来源 URL 与可得归属信息。上游 owner 是归属人，不保证为原始作者；私有文件没有已知署名时保留 null，不把上传者当作者。XLSX、SVG、DOCX 及抽样等其他格式或范围仍为后续能力，不显示无后端的按钮。

2026 年 10 月 17 日，本片 58 项契约、44 项 Node 回归和构建检查通过；11 类 30 个真实 HTTP 响应通过严格模型校验。完整导出核对三查询共 130 行（各运行分别保留计数）、纯私有 5 行、零命中 0 行与固定笔记 1 行，CSV 成果包和 JSON 的实际下载均完成摘要核对。浏览器验证笔记读取、编辑、修订保存与接受，接受后正文、列表和修订下拉状态一致；独立导出许可撤回后清除已选 CSV，直接刷新仍可读取纯私有 5 行成果；全文撤权后清除笔记标题和正文，证据列表为空。验收数据清理通过，真实 D12 未核准。未保存离开确认框已实现，但浏览器自动化确认框阻塞，交互验收尚未完成；不把这项限制扩大为已通过。永久证据见 contracts/results/2026-10-17-s3-outcomes-contracts.json。

## 十二 任务事件与常见错误

任务中心显示类型、对象、发起人、阶段、进度、耗时和结果入口。已知总量显示百分比，未知总量只显示阶段与已处理量。管理员查看同步任务，项目成员只查看获准项目任务；取消和重试由发起人或负责人按任务权限执行。

### GET /projects/{p}/jobs 与 GET /jobs/{id}

当前列表支持 cursor、page_size，返回 items、next_cursor；包含 UPLOAD_VALIDATE、TXT_IMPORT 与 EXPORT，状态和类型筛选待补齐。详情返回 job_id、project_id、actor_id、action_id、upload_id、filename、state、stage、attempt、lease_epoch、lease_expires_at、progress、result、result_ref、error、allowed_actions 和时间。progress 包含 processed_bytes、total_bytes；未知总量为 null。UPLOAD_VALIDATE 结果仅在 SUCCEEDED 时返回 VALIDATED 文件信息。TXT_IMPORT 结果只含 material_id、material_revision_id、state=READY，result_ref 为该固定修订；五字段 progress 与专用导入详情一致。EXPORT 的 upload_id、filename 为 null，成功 result 与 result_ref 只含 export_id、state=READY，实际文件信息由导出详情读取。未完成不得显示校验、解析或导出成功。

### GET /jobs/{id}/events

当前使用 GET /jobs/{id}/events?after=序号 读取持久 JSON 事件，返回 items、next_after。事件包含 event_id、job_id、sequence、kind、state、attempt、payload、created_at，独立于 Pi run。网页轮询任务详情，按请求序号拒绝过期响应；刷新后重新读取账本。SSE 传输留待后续，不能把当前 JSON 接口标为 SSE。

### POST /jobs/{id}/cancel 与 POST /jobs/{id}/retry

两个操作均提交空 JSON 对象及 Idempotency-Key。当前取消在事务内置为 CANCELLED 并递增 fencing epoch，旧执行者不能发布；已成功的任务不通过取消删除结果。retry 仅对 allowed_actions 包含 retry 的失败任务开放，沿用逻辑 job_id 并增加 attempt，最多三次，保留原执行记录。不可重试返回 409 JOB_NOT_RETRYABLE。权限撤销、取消及租约过期均在执行和发布边界重新检查。

| HTTP 与 code | 前端处理 |
| --- | --- |
| 401 AUTH_REQUIRED | 回到登录，保存无敏感信息的当前路由 |
| 403 ACCESS_DENIED | 禁用该操作并显示原因，清理失效材料缓存 |
| 404 NOT_FOUND | 显示资源不可用与返回入口 |
| 409 EDIT_CONFLICT | 保留本地编辑，刷新后重提，不静默覆盖 |
| 422 VALIDATION_ERROR | 按 field_errors 标注字段；保留输入 |
| 429 RATE_LIMITED | 按 Retry-After 显示稍后重试，不自动重发写操作 |
| 503 SERVICE_UNAVAILABLE | 显示服务暂不可用；读请求有限重试，写请求先查询已有任务 |

错误体统一为 code、message、request_id、field_errors、retryable。页面主要覆盖正常、空数据、处理中和失败；取消、权限及编辑冲突按上述真实业务补充，不为假设场景增加状态面板。

## 十三 前端状态与接口约定

| 状态位置 | 存放内容与规则 |
| --- | --- |
| URL | project_id、snapshot_id、run_id、页面筛选和排序；复杂查询用 saved_query_id 或 run_id 引用 |
| 服务器 | 授权、正式参数、运行状态、计数、笔记、证据、会话和任务；均为事实来源 |
| 前端请求缓存 | 键包含项目、快照、运行及分页参数；切换身份或失去权限时清理 |
| 组件状态 | 未提交查询、打开抽屉、选中行、表单错误；不假定已保存 |
| 本地偏好 | 日夜主题等非敏感 UI 设置；不保存正文、凭据或聊天上下文 |

### 分页与请求

列表使用 cursor 与 page_size，返回 items 和 next_cursor；KWIC 使用 hits。普通列表默认 50 条、最大 100 条；当前查询每页最多 50 条。游标由服务器生成，绑定筛选与排序。新查询取消前端旧请求并以 query_run_id 校验响应归属，旧响应不能覆盖新页面。取消 HTTP 请求不等于取消后台任务。

接口统一位于 /api/v1，字段 snake_case，ID 为字符串，时间 ISO 8601 UTC；空值与缺失含义由 Schema 明确。计数类型由 Schema 明确，前端不自行换算或四舍五入。S1 当前共享手工维护的 contracts/types/s1.ts 客户端，网页与适配器不重复定义字段。OpenAPI 自动生成客户端仍待接通；Schema 和示例存 contracts/。

### SSE 与恢复（后续目标）

当前查询使用 JSON 详情轮询，尚未接入 SSE。后续页面只订阅当前活动任务或运行；切换时关闭旧连接。断线按 1、2、5 秒有限重连，失败后显示重连按钮，任务仍继续。重连携带 Last-Event-ID；先补事件或重新读取详情，再继续流式显示。实际鉴权沿用同源 Cookie，不把凭据放 URL。

### 最小模块

按 sources、projects、materials、search、analysis、parallel、notes、tasks、agent 分前端业务目录。共享组件只抽取重复出现的范围选择器、结果表格、证据抽屉和任务状态；不先建设通用低代码页面框架。权限、统计公式和 Pi 状态转换都留在后端。

## 十四 首条流程与联调验收

| 顺序 | 完成证据 |
| --- | --- |
| S0 契约 | 来源样本与查询金标、Pi 锁定版本、HTTP Schema 和事件样例可运行 |
| S1 页面骨架 | 登录、项目、来源、任务、默认研究助手工作台及独立工具入口；真实 API 与权限可联调 |
| S2 同步 | 管理员启动 Tatoeba 获取；可查真实阶段、文件校验和质量报告 |
| S3 纵向流程 | 来源索引发布、挂载、TXT 上传、混合快照、KWIC、Pi 引用、笔记、CSV/JSON |
| S4 至 S5 | Wikimedia 与 UD、其他表格导入、专业检索、统计与比较 |
| S6 至 S7 | 自动句对候选、覆盖层修订、范围接续、完整导出、跨模块助手流程和恢复 |
| S8 验收 | M01 至 M14、三类来源、两条研究流程和部署验证全部通过 |

### 当前最小联调样例

POST /projects/{p}/queries，snapshot_id 指向获准 READY 快照；query={dsl_version:"corpus-query/v1",unit:"token",pattern:{type:"term",attr:"form",op:"eq",value:"language"},within:"sentence",overlap:"all",normalization:"none",sort:["document_ordinal","start","end"]}；page_size=50，context_codepoints=40。请求携带 Idempotency-Key，202 返回 action_id、job_id、query_run_id、result_set_id、state、run。

轮询 GET /projects/{p}/queries/{query_run_id} 取得正式状态；GET /projects/{p}/result-sets/{result_set_id}/hits 读取首屏，三项计数 complete 后按返回游标翻页。命中以 hit_ref={result_set_id,ordinal} 固定引用；GET /projects/{p}/result-sets/{result_set_id}/hits/{ordinal}/context 重新鉴权后读取同一修订的整句和码点，evidence_id=null。Pi 只返回规定元数据，不将运行静默加入材料 scope；正文检索和上下文工具分别拒绝 SNAPSHOT_SCOPE_UNAVAILABLE、MODEL_EGRESS_DENIED。

### 手动成果续作与后续研究范围

完整查询后，编辑或负责人可 POST /projects/{p}/evidence 登记固定命中，再通过 /projects/{p}/notes 保存笔记和明确修订；接受需真实用户会话。具备独立导出许可的成员向 /projects/{p}/exports 提交固定查询列表或笔记修订，后台完成后经鉴权代理下载 CSV 成果包或 JSON。获准材料的 Pi 研究会话与其他成果格式仍为后续目标，不能由手动页面读取权推导模型外发权。

### 验收清单

必须验证：管理员不能读私有正文；只读成员不能改结果；计数与展示行分离；A/B 锚点和 1 对 3 双语计数正确；甲项目修订不影响乙；刷新浏览器恢复任务；忙碌消息只排队；取消不吞掉已有成果；版本冲突不覆盖草稿；来源更新不改变旧运行。

每项业务验证手动与助手入口的工具覆盖、权限、同参数结果一致和结果互跳。新增验收包括私有材料上传、对齐、修订、换范围分析导出；账号创建和恢复项目；管理员同步撤回；只读会话与人工确认依据。连续任务不要求重复输入，不向新会话传旧正文。界面验证正常、空数据、处理中、失败及必要权限状态，后续能力遵守同批接入要求。S3 演示不等于阶段 A 验收通过。
