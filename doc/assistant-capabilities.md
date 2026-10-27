# 研究助手业务能力与工具契约

研究助手按目标设计调用当前用户有权使用的全部已上线业务能力。每项能力与手动入口共用后端命令、查询、权限和结果；首版 M01 至 M14 的业务动作随各模块同批接入，后续 F001 至 F096 中的能力上线时同批注册。当前 S1 至 S3 已实现下述手动 HTTP 切片和显式适配器，各切片验收分别记录，生产 Pi 执行授权尚未完成验收，不能将计划表当作可调用工具目录。

## S1 至 S3 当前实现与开放边界

### K09 会话工作台与任务等待

本轮连接默认研究助手工作台与真实持久会话、用户消息、运行及安全消息投影。账号和项目会话仍为空材料范围，用户消息按 request_key 与 scope_digest 固定；服务器选择 config_id，不接收浏览器或模型自报凭据、模型 URL 或运行身份。范围改变建立干净的新会话，SESSION_BUSY 拒绝提交并保留输入，不实现排队消息。

默认不启用模型；显式 AGENT_RUNTIME_MODE=fixture 配置用于本地流程测试，网页明确显示“本地流程测试”。兼容 OpenAI 的真实提供方采用独立配置与清单，页面显示“已配置模型”及模型名；这只表示配置允许受理，不表示宿主在线、接口已连通或真实研究任务已通过。常驻宿主从持久运行领取任务，经执行凭据调用同一后端业务。工具定义版本保持 s3-outcomes-tools-v1，本地测试 host_policy 为 corpus-k09-linear-v1；真实提供方为 corpus-k09-openai-v1，不静默转换旧检查点。

必要异步任务由服务端从调用账本固定关联，宿主在可靠线性检查点后进入 WAITING_JOB，后续领取以同一 run 的新 epoch 恢复并读取实际任务报告。未完成或失败的必要任务不能作为整体成功。租约失效、未知上下文或不可恢复记录继续 WAITING_REVIEW，不猜测重放写入。本片固定测试已实际通过运行服务和浏览器流程，不能将固定模型桩等同真实模型研究质量。

浏览器只读取经当前授权复核的用户消息、可展示助手文字、工具状态与固定成果引用；不返回原始检查点、内部思考、工具参数或原始业务数据。轮询状态变化后才刷新消息，已显示的历史运行亦重验依赖；撤权时清除旧记录。已有证据正文、笔记正文与模型人工采纳边界不因工作台出现而改变。

本轮本地契约 62 项、前端客户端/状态 5 项测试及网页构建通过。实际 HTTP 的 7 类 10 份响应通过严格校验；上传校验固定流程经历 WAITING_JOB，保存检查点后在同一 run 的新 epoch 恢复并完成，未重复写入，私有正文未进入模型。浏览器通过账号/项目范围隔离、项目消息完成与刷新恢复、取消后的会话列表同步；最终默认未配置模型时保留非空输入并禁发，刷新成功后不残留旧网络错误，手动入口正常。临时账号已清理。证据见 contracts/results/2026-10-17-k09-workbench.json 与 contracts/results/2026-10-17-k09-http-contracts.json。注册表仍为 143 个动作、52 个显式适配器，生产 available_tools 仍为空。用户已有 OpenAI 兼容接口，但 URL、模型名与协议尚待固定，实际 provider 尚未配置；完整 K09 的材料 scope、外发批准和真实研究任务质量尚未通过。

### K09 兼容协议配置增量

运行契约区分 unconfigured、fixture 和 openai-compatible。production_ready 固定为 false；未配置或配置无效时 can_submit=false，分别返回 MODEL_NOT_CONFIGURED 或 MODEL_CONFIGURATION_INVALID，并清空 config_id 与 manifest。真实提供方配置 ID 为 openai- 加受信配置摘要前 48 位；浏览器和模型不能提交模型 URL、密钥或配置身份。

fixture 清单保持原八字段，真实清单使用 provider=corpus-openai-compatible、resource_config=corpus-explicit-resources-v1，并新增 model_api 和 model_config_sha256。model_api 明确区分 openai-completions 与 openai-responses；配置摘要绑定协议、服务地址、模型、上下文与输出上限、超时及测试 HTTP 策略。公开响应只提供非密钥摘要与模型标识，不公开服务地址。严格联合类型不允许 fixture 携带额外 null 协议字段。

新运行和恢复必须匹配当前受信配置。旧会话配置不匹配时返回 AGENT_CONFIG_CHANGED，保留输入并要求用户新建会话；仍有权限的历史按其自身清单与会话配置核验后可读。关闭 fixture 不会把其历史自动交给真实提供方。材料 scope 继续为空，正文工具、人工采纳和模型外发边界不变，注册表仍为 143 个动作、52 个显式适配器，生产 available_tools 为空。

上游失败映射为 MODEL_AUTH_FAILED、MODEL_RATE_LIMITED、MODEL_TIMEOUT、MODEL_REQUEST_FAILED 或 MODEL_RESPONSE_INVALID，不暴露原始错误、地址或凭据。没有调用事实和恢复档时可记为 FAILED；已有调用则进入 WAITING_REVIEW，避免丢失业务事实或猜测重放。页面使用具体中文原因，不增加新的通用恢复流程。

兼容协议增量已通过 63 项契约、6 项前端客户端及状态测试和网页构建；最终运行契约专题 5 项与完整 Ruff 检查通过。安装的 SDK 分别经本机合成 HTTP 服务执行 Completions 和 Responses 协议，每种协议的 7 类 10 份实际响应通过严格校验；各以两个独立宿主进程接续同一后台任务，epoch 从 1 到 3，业务 action、job 和执行 attempt 各一次，模型 HTTP 请求各 4 次。此结果验证真实协议适配与持久接续，不代表用户提供的外部接口已通过。

浏览器已验证模型配置标识、协议配置变化后旧历史可读且禁发、旧排队运行可取消，以及显式新建会话发送。Responses 首次本机 401 请求产生 FAILED／MODEL_AUTH_FAILED 且不发布检查点；同会话后续新运行成功并保存可靠检查点，刷新后保留失败和成功两轮。实际页面资源与冻结版本一致。用户接口地址、模型与协议仍待固定，材料范围和模型外发仍未开放，production_ready=false、生产工具 0 保持不变。证据见 contracts/results/2026-10-17-k09-provider.json；上一固定工作台验收保留。

### S1 手动入口与基础适配

已实现真实登录、项目读取与创建、负责人管理已有账号成员、私有单文件上传、持久文件校验任务，以及无需项目的来源目录读取和管理员登记编辑。浏览器和固定工具适配器使用相同 FastAPI 路由和业务规则。共享类型位于 contracts/types/s1.ts 与 contracts/types/catalog.ts，逐动作输入和任务契约位于 contracts/schemas/s1-*.schema.json，覆盖登记位于 contracts/s1-capabilities.json。

已提供 18 个明确动作的契约测试适配器：account.get、projects.list/get/create、members.list/update/remove、uploads.create/complete、jobs.list/get/cancel/retry、sources.list/get/versions、catalog.create/update。members.update 仅新增或更新已存在账号 ID 的项目角色，不代表邮件邀请。登录密码、文件字节传输和下载凭据不提供给模型；上传地址与 csrf_token 从模型可见结果中剥离。

适配器的 HTTP 客户端、会话、CSRF、项目范围与幂等键由受信宿主注入，不接受模型传入 actor、凭据、任意请求目标 URL、HTTP 方法或 shell；许可依据 URL 仅作为记录，不作为抓取或执行目标。每次 HTTP 操作仍由后端鉴权，生产 Pi 委托执行尚未完成验收，因此这 18 项仍标为 planned，available_tools 为空。其余能力继续按原阶段实现，不批量开放计划动作。

account、platform、project 三种范围都包含 account.get 与来源读取；account 另可列出和创建本人项目，platform 的目录写入每次核验当前平台管理员身份，project 业务仍受绑定项目及角色约束。sources.list 保留服务端搜索、筛选和分页，sources.versions 保留 cursor、page_size，不将当前空版本列表变成无分页契约。目录写入只接收描述元数据，catalog.update 必须带 expected_revision；幂等键由宿主提供，冲突返回正式业务错误。46 项初始登记、实验记录和许可待审核均不能推导全文分析、导出、模型外发或已发布版本。

内部宿主执行基础另设专用路由，绑定 actor、session、run、固定范围、工具集合、lease epoch 和有效期，模型不能自行提供执行凭据。当前范围只覆盖已上线账号、平台和项目业务，拒绝非空研究材料引用。完整线性 Pi v3 会话可经 API 存入私有版本化对象存储；服务器固定 Pi 版本、模型与资源配置，核对调用账本、权限、必要任务及 settled 状态后原子发布检查点与 SUCCEEDED。Node 不持有对象存储密钥。

同一会话的后续 run 固定读取已发布基线，下载后核对摘要，在新 run 和 lease epoch 的隔离目录中复制，再通过 SessionManager.open 恢复真实上下文。旧检查点不就地追加，历史工具结果不作为新写入重放；每次模型请求前再校验当前授权及历史读取依赖。当前只接收未压缩、无分支的完整线性日志；缺档、损坏、权限变化或进行中调用不明确时进入 WAITING_REVIEW，不猜测历史。检查点和终态提交响应丢失只对同一请求有限重试。该范围不等于完整崩溃恢复、真实模型或材料外发验收，生产 available_tools 仍为空。

S2 新增平台范围的固定 Tatoeba 同步适配：sync.start 只接收 source_id=D12，sync.report 只接收 sync_run_id。平台 jobs.list 的同步分支接收 D12 与分页参数；jobs.get/cancel/retry 使用 sync_run_id，项目范围仍使用原 job_id，严格拒绝标识混填或跨范围替换。手动和工具操作复用同一管理员 API、幂等、来源身份和租约规则。S2 交付时新增 2 项，总计 20 个明确动作；独立契约登记见 contracts/s2-capabilities.json，类型见 contracts/types/source-sync.ts。

源同步任务不属于私人项目，不要求项目或研究快照。启动为异步 202，结果只能标为已校验、不可检索的暂存版本；质量和差分报告不等于许可批准、索引 READY 或公开版本发布。sync.check 没有真实上游检查实现，计划同步仍未接入，固定索引发布由下述 S3 新切片提供，本轮不提供这些工具。平台历史结果仍逐次鉴权；实际 source acquisition 不进入 sources.versions 公开发布列表。

S3 私有索引切片新增 indexes.build 和 indexes.report，当时注册表总计 137 项，显式适配共 22 项，生产 available_tools 仍为空。构建参数严格为 source_id=D12 与固定 acquisition_id；报告参数为 index_run_id。配置由后端固定，不允许模型提交路径、URL、分词选项、身份或许可批准。输入与结果契约位于 contracts/schemas/s3-*.schema.json，共享类型为 contracts/types/source-index.ts，覆盖登记为 contracts/s3-capabilities.json。

平台 jobs.list 增加显式 task_kind=source_index 分支，仍要求 source_id=D12；省略 task_kind 保留同步语义。平台 jobs.get/cancel/retry 严格选择 sync_run_id 或 index_run_id，不能混填；项目分支继续使用 job_id。异步构建返回持久任务引用，只有完整产物保存后才有 INDEXED 结果，searchable 保持 false。相同 acquisition 与固定 recipe 的成功结果可复用，但不能由此推导来源使用权。该索引切片本身不含许可核准、发布、挂载或研究查询；固定版本核准与挂载由下述新切片提供。

工具适配与手动入口共用业务服务，管理员权限和任务租约仍由后端核验。实际受限宿主必须等索引任务终态，并将对应报告读入上下文，不能把接受构建当作成功。当前新增 3 项 Node 适配器测试及完整 27 项 Node 回归通过；后台索引 9 项、Pi 10 项和检查点 11 项真实服务测试通过。这些结果不代表生产模型、材料外发或工具授权已完成验收。

真实 HTTP 全量构建及固定对象版本回读、解包逐文件核验、新进程读取、相同输入复用均通过，1 个任务、2 个动作和 2 个列表响应通过严格 Schema。浏览器核对进度、最终统计和质量、复用提示、刷新恢复、普通用户无管理入口及退出；公开来源版本保持为空。证据见 contracts/results/2026-10-16-s3-index-contracts.json。全量索引覆盖 2,127,898 条句记录、82,951,215 个 Unicode 码点、19,660,489 个词项，拒绝 0 句；新进程 20 条明确查询核对一致，词项参考基于固定词层，不代表独立分词质量金标。

2026 年 10 月 16 日的历史字符查询测量中，共享 4 CPU、8 GiB 环境单次顺序核查的字符零命中首屏最长 38.873 秒、完整计数最长 37.048 秒。该历史失败证据保留，不作为当前优化后时延。当时尚未开放研究查询 API；本轮手动查询切片另行记录。这些引擎结果不替代来源策略核准或查询服务验收，生产 available_tools=0 的边界保持。

2026 年 10 月 17 日，保留原索引、成员与 recipe，读取器优化后重新核对全部 2,127,898 条句记录及 19,660,489 个词项坐标，20 条固定字符字面串与词项等值查询的计数、首 50 条跨度和 KWIC 均一致。字符 10 条首屏最长 0.112 秒、完整计数最长 3.747 秒；词项 10 条分别为 1.246 秒和 1.512 秒。跨句零命中 endstart 首屏为 0.056 秒，组合字符零命中为 0.045 秒。该结果仍是共享 4 CPU、8 GiB 环境单次顺序核查，不是冷盘、并发 P95 或正式性能验收；复杂查询另按既有子集验证。证据见 pipelines/query/results/2026-10-17-source-reader-native.json。

当前运行 manifest 的 tool_schema 已升级为 s3-outcomes-tools-v1。旧 s1-tools-v1、s2-tools-v1、s3-tools-v1、s3-release-tools-v1、s3-query-tools-v1 和 s3-private-tools-v1 检查点明确不兼容，不能静默套用新工具定义恢复；Pi SDK 版本及固定资源策略保持；K09 的 host_policy 另升级为 corpus-k09-linear-v1。已完成线性会话恢复与运行中任务接续仍分别验收。

S2 固定客户端与工具适配器新增 3 项测试通过，宿主完整 Node 回归 24 项通过。连续两轮真实全量同步成功，每轮 13 个对象回读核验，第二轮六项差分为零；浏览器另验证启动与取消。真实任务、动作和列表响应通过严格 JSON Schema，证据位于 contracts/results/2026-10-16-s2-http-contracts-final.json。首次执行的次轮失败证据保留；这些结果不代表生产授权、可检索索引或公开版本已经通过。

2026 年 10 月 16 日已通过真实 Pi SDK、HTTP、PostgreSQL 与私有版本化对象存储的双进程验证：首个 run 创建一个项目并发布检查点；第二个独立 Node 进程恢复同一会话，继承原项目和 invocation，新增工具调用为零，两次均由后端发布 SUCCEEDED。固定模型请求数分别为 2 次和 1 次；宿主完整 Node 回归 21 项通过，其中运行客户端与检查点专题 7 项。该证据覆盖当时已完成线性会话接续；本轮新增工作台与 WAITING_JOB 另行验收，仍不开放生产工具。

来源目录另通过真实浏览器验收：无项目账号读取 46 项、组合筛选 D12、查看许可与空版本、全文分析筛选为空，管理员新增和修订登记后刷新仍可读取修订 2。9 项固定客户端与适配器测试通过，包含三种范围来源读取、版本分页参数、固定管理员路由及拒绝越权字段；这些证据不将生产 available_tools 从空列表改为可用。

手动上传和任务操作先登记业务 action_id，幂等作用域为 project、actor、operation、key；同键不同参数返回冲突。手动 action 不要求 Pi run，未来 Agent 关联以可选且由服务器控制的 invocation_id、run_id 保存，不为手动请求伪造运行。当前手动 HTTP projects.create 尚无幂等账本，网页与契约测试适配器不自动重试该动作；内部 Pi 调用通过 invocation 请求键和同一事务复用结果，不能混同这两种重试边界。

uploads.create 在没有快照的新项目中也可执行，不要求 snapshot_id 或 alignment_overlay_revision。uploads.complete 为异步提交：空 JSON 对象与 Idempotency-Key 返回 202、action_id、job_id、upload_id，不能当作校验完成。后台只验证大小、SHA-256、UTF-8 和非 NUL 文本；VALIDATED 仍是暂存文件，不是已解析材料或可检索 READY。

任务记录独立保存 actor、action、attempt 和 lease epoch，任务事件以 job_id、sequence 标识，不依赖 Pi run 事件。取消在事务中使旧执行者失效，重试保留历史 attempt；读取、执行和发布均校验当前权限。网页当前轮询持久状态，事件接口返回 JSON；生产 Agent 会话单写、运行恢复和 SSE 仍须另行验收。2026 年 10 月 16 日真实浏览器已通过登录、建项目、53 字节文本上传、后台校验与摘要核对、刷新恢复和退出；6 项 S1 客户端与适配器回归通过，包含浏览器 fetch 接收者绑定。该证据不代替生产 Pi 授权验收。

### 固定来源版本核准与项目挂载

2026 年 10 月 17 日新增 releases.get、mounts.get、mounts.manifest，复用原计划 policies.get/update、releases.publish、mounts.list/create/remove。当时注册表为 140 项，显式适配为 31 项，生产 available_tools 仍为空。严格输入和结果位于 contracts/schemas/s3-release-*.schema.json，共享类型位于 contracts/types/source-release.ts，覆盖登记见 contracts/s3-release-capabilities.json。本轮 38 项契约测试、3 项能力过滤测试、30 项 Node 回归及 6 项真实发布挂载测试通过；9 类 23 个实际 HTTP 响应通过 Schema。浏览器已验证固定版本发布复用、负责人挂载与移除、只读权限、刷新持久和撤权后 403 清除旧清单。临时合成来源及 26 个私有对象版本已清理，真实 D12 仍未核准。永久证据见 tests/integration/results/2026-10-17-source-releases.json 和 contracts/results/2026-10-17-s3-release-contracts.json。

平台 policies.get/update 强制 policy_kind=source、source_id 与 acquisition_id；update 另含 expected_revision、明确 allow 或 deny、核准说明和依据地址。服务器固定内部研究范围并记录当前核准身份、时间、来源身份修订及采集和许可摘要。模型不能传入 actor、导出许可、外发许可或任意授权范围。此分支不代表原计划模型允许列表和数据外发策略管理已经实现。真实 D12 未核准，测试来源批准不能转用于实际语料。

平台 releases.publish 只接受 source_id、index_id、expected_policy_revision，返回固定 release_id 和 source_snapshot_id。目录元数据写入不能代替策略核准；同一索引复用发布版也要复核当前权限。releases.get 在账号、平台和项目范围读取固定发布元信息；sources.versions 返回同样的 ReleaseView，包括发布时与当前策略修订、实际计数、当前 available 及受限原因。searchable 按当前策略和固定查询版本动态计算，为真仍须经项目研究快照授权才能手动查询，不能推导模型外发许可。

项目 mounts.list/get/create/remove/manifest 将项目身份从受信 scope 绑定，不接受模型传入 project_id。create 只接受 source_snapshot_id，整库挂载；get、remove、manifest 只接受 mount_id，list 保留分页。编辑或负责人可创建与移除，只读成员可读获准挂载及真实固定清单；清单不含对象存储地址或凭据。当前策略、来源身份、成员关系及挂载有效性由后端逐次核验，历史元信息可保留，旧获准结果不能绕过撤权。

本片挂载只建立固定业务引用，工具 scope_effect=none；不会把新挂载静默注入既有会话的研究材料范围。非空材料 scope 仍拒绝，子集构建和材料模型外发尚未交付；手动混合研究快照按后文新切片扩展。内部 Pi 分派与网页复用后端服务，调用重放和归档恢复重新核验服务器派生的发布与挂载依赖；工具参数不携带存储路径、凭据或自定义 recipe。

### 固定研究快照与手动查询

本轮复用既有 snapshots.create/get、corpus.describe/search、results.get/context 六项注册动作，不增加重复业务名称。该查询切片的显式适配总数为 37，其中四项只返回元数据，两项材料入口明确拒绝；注册表 140 项的生产状态仍全部 planned，available_tools=0。严格模型和生成 Schema 位于 contracts/research.py 与 contracts/schemas/s3-research-*.schema.json，共享类型位于 contracts/types/research.ts。46 项契约测试、34 项 Node 回归及 TypeScript／网页构建通过；8 类 12 个真实 HTTP 响应通过严格模型校验。浏览器已验证快照准备、零命中三项零值、120 次命中按 50／50／20 分页、完整原句的 Unicode 高亮、历史恢复与撤权清空。临时验收数据清理通过。证据见 contracts/results/2026-10-17-s3-research-contracts.json 与同目录 s3-research-http-contracts 报告；完整引擎的独立正确性和单次性能另见 pipelines/query/results/2026-10-17-source-query-engine.json，不作为生产并发性能验收。

最初已验收的手动查询切片使用单个 whole_source_mount；私有 TXT 与混合扩展见下节。后端先返回 202 PREPARING，后台验证固定索引与缓存后才为 READY。它产生新范围引用，但不更改当前 Pi 会话；挂载、source_snapshot 和项目研究 snapshot 是不同业务身份。过滤子集快照尚未实现。

手动查询支持句内字符字面串和词项 form 等值、连续序列、有限间隔与 OR。固定 context_codepoints 为前后各 0 至 200 个 Unicode 码点，默认 40；不接受 context_tokens、任意 CQP、POS／lemma、正则、AND／NOT 或元数据筛选。首屏与完整跨度分阶段处理，total_hits、matched_segments、matched_documents 只有完整结果持久化成功后才返回数值；来源版文档单位是导入句记录，私有／混合版增加明确单位分项。命中使用可重新鉴权解引用的 hit_ref={result_set_id,ordinal}，上下文中的 evidence_id=null；只有后文 evidence.create 明确登记并返回真实 ID 才表示已保存证据。

当前 Pi 仍只接收空材料 project scope。snapshots.create 返回 action_id、job_id、snapshot_id、project_id、state 和 next_action=snapshots.get；snapshots.get、corpus.describe 返回上述快照与任务身份、state，下一动作按实际就绪状态为 manual_query 或 wait。results.get 返回 id、project_id、snapshot_id、result_set_id、state、first_page_state、count_state、next_action=manual_result_view。投影剔除 AST、由查询生成的名称、KWIC、材料计数及原句。snapshot_id、result_set_id 作为参数只用于这些明确元数据动作，不自动赋予正文读取权。异步建快照必须实际完成，并通过元数据读取观察 READY，不能将 accepted 当成功。

corpus.search 与 results.context 不进入当前宿主 allowed_tools；即使直接命中注册分派也在读取材料之前拒绝：前者返回 SNAPSHOT_SCOPE_UNAVAILABLE，后者返回 MODEL_EGRESS_DENIED。Node 契约适配器与后端采用相同错误边界。后端、调用重放、归档恢复和每次模型请求的权限重验都须守住同一边界。后续非空 snapshot scope、逐材料外发许可和真实模型研究流程仍待实现与验收，不能因为手动页面能读取正文而允许模型读取。

网页与工具元数据复用相同后端快照、任务和权限事实。项目 viewer 可手动创建分析运行，但不能创建材料快照或修改挂载；平台管理员不能读取非成员项目。来源拒绝、身份变化或挂载移除后，既有结果、原句和准备读取均重新鉴权，前端清除旧正文与计数。普通元数据和处理结果没有公开对象路径、存储凭据或任意目标 URL。

### 私有 TXT、不可变修订与混合快照

该私有材料切片复用已有 imports.start/get、materials.list/get 四项动作，当时 140 项注册不变，显式适配增加为 41 项，生产 available_tools 仍为 0。契约位于 contracts/materials.py、contracts/schemas/s3-private-*.schema.json 和 contracts/types/materials.ts。运行 manifest 的 tool_schema 升为 s3-private-tools-v1；包括 s3-query-tools-v1 在内的旧工具 schema 检查点不得静默恢复。51 项契约、38 项 Node 回归与构建检查通过，14 类 36 条真实 HTTP 响应通过严格模型校验。浏览器验证同配置解析复用、语言更正保留旧修订、两文件纯私有查询的 5／5／2 计数、混合查询的 125／65／62 及 50／50／25 分页、全文 Unicode 坐标高亮、只读权限与来源撤权。混合结果失权后自动清空，纯私有结果继续可读；验收数据清理通过。永久证据见 contracts/results/2026-10-17-s3-private-contracts.json。

imports.start 在已绑定项目上接收 upload_id 和明确的 cmn／eng，复用手动解析服务，不接受路径、URL、任意 parser recipe 或身份。TXT_IMPORT 只发布不可变解析修订；相同上传、语言、固定 recipe 复用原任务，更正语言生成同文档新修订。索引在研究 snapshot 准备阶段建立。materials.list/get 只读取当前项目元数据；同一文档的旧修订仍可显式选择，旧快照始终引用原修订。

Pi 导入结果投影为 import_id、job_id、project_id、material_id、state、material_revision_id 与 next_action；start 另含 action_id。材料投影为 material_id、project_id、state、import_id、material_revision_id、固定 revisions 的 ID／序号／语言与 next_action。materials.list 保留 items 和 next_cursor。文件名、正文、句段、质量和派生计数均剔除；通用 jobs 读取 TXT_IMPORT 也使用相同受限原则，不能成为泄漏旁路。accepted 导入须后台真正完成并由 imports.get 观察修订后才满足成功归档条件。

snapshots.create 扩为 mount_ids、material_revision_ids，两数组合计 1 至 16 项；不得同时选择同材料的不同修订，不按内容摘要合并不同文件。正文命中 start_cp/end_cp 指向 revision canonical 全文，context_start_cp 给出返回句段的起点；私有来源句编号与 URL 为 null。matched_documents 按文件或来源记录身份计数，并通过 matched_document_units 说明来源句记录／上传文件分项。完整结果未完成时，三项总计数与分项对象均为 null。

导入、材料与快照工具不会扩张当前空材料 project scope，也不向模型注入新文件。corpus.search 继续拒绝 SNAPSHOT_SCOPE_UNAVAILABLE，results.context 继续拒绝 MODEL_EGRESS_DENIED；生产模型、材料外发及非空材料会话范围仍待独立验收。

### 固定证据、笔记修订与完整导出

本片新增 evidence.create、evidence.list、exports.list 三个明确动作，注册表为 143 项；与既有 notes 和 exports 动作合计提供 11 项成果适配，显式适配总数为 52，生产 available_tools 仍为 0。严格模型位于 contracts/outcomes.py，固定客户端和投影位于 contracts/types/outcomes.ts。运行 manifest 的 tool_schema 升为 s3-outcomes-tools-v1，旧 schema 检查点不得静默恢复。

手动 evidence.create 以完整结果的 result_set_id 与 0 基 ordinal 登记不可变证据，服务器定位和保存原句、坐标、方法与摘要，不接受自报引文。notes.create/update 保存 title、body、evidence_ids 与完成的 query_run_ids；零命中查询可作为方法引用。每次更新追加 draft 修订，expected_revision 冲突不覆盖旧版。继承的 authorization_evidence_ids、authorization_query_run_ids 共同约束正文与标题，移除显示引用不能解除旧材料权限。notes.accept 只接受真实用户会话针对当前确定修订的动作。

当前空材料 Pi 范围只允许 evidence.create/list、notes.list、exports.create/list/get 的受限元数据路径。证据投影为 evidence_id、project_id、query_run_id、result_set_id、snapshot_id、hit_ref 与 next_action；hit_ref 仅为固定结果身份与 ordinal。笔记列表只返回 note_id、project_id、revision、status、显式及继承引用 ID 数组和 next_action。导出只返回 export_id、job_id、project_id、state、next_action。创建动作另含 action_id，证据创建另含 existing；列表保留 items、next_cursor、total。投影没有正文、标题、原文码点、KWIC、文件名或派生材料统计。

evidence.get 与 notes.get/create/update 不进入当前宿主允许集合，直接调用适配或分派也返回 MODEL_EGRESS_DENIED；notes.accept 返回 HUMAN_AUTHORIZATION_REQUIRED，不接受模型伪造 confirmed。实际模型材料范围和外发许可仍未开放。通用 EXPORT job 投影仅含任务及导出身份、kind、state 和 next_action，不能经 filename、progress 或 result 绕过正文限制。

exports.create 使用严格 target 二选一：1 至 16 个唯一且完整的 query_run_ids，或确定 note_id、revision。后台按输入顺序导出每个运行全部命中，保存每个查询独立计数与单位；不等同浏览器当前页，也不伪造跨查询去重合计。CSV 实际为 results.csv 与 methods.json 的 ZIP 成果包，非空文本采用可逆 text-prefix/v1 前缀；JSON 保留原文。笔记成果为一行固定修订及结构化证据引用，状态不被导出提升为人工接受。只读成员仅可操作自己获准的导出任务，不能借 jobs.cancel/retry 写入其他业务。

固定 acquisition 的 export_decision 默认 deny，独立于内部研究 decision，模型输入不能设置它。手动管理员页明确提交两项决定；真实内部宿主的 policies.update 仅能在同一有效许可身份、采集和许可摘要上保留已有人工导出决定，旧身份失效不能复活旧 allow。旧直连手动 HTTP 的契约适配器无法提供该事务边界，因此 policies.update 明确返回 HUMAN_AUTHORIZATION_REQUIRED；这一拒绝不等同真实内部宿主写入不可用。每次导出建立、执行、读取和下载都重验权限；真实 D12 仍未核准，生产 Pi 委托仍未完成验收。

本片 58 项契约、44 项 Node 回归和 TypeScript／网页构建通过；父端另独立验证 8 项新增真实集成与 56 项既有真实回归。11 类 30 个实际 HTTP 响应通过严格模型校验，完整查询、零命中和固定笔记的 CSV／JSON 成果回读、独立导出撤权及全文撤权均通过。浏览器验证修订接受状态一致、撤权后清除旧成果且纯私有成果继续可用、笔记标题正文和证据列表失权清空；真实 D12 未核准，验收数据清理通过。未保存离开确认框交互因自动化阻塞未完成，不计入通过。永久证据见 contracts/results/2026-10-17-s3-outcomes-contracts.json；这是当前手动成果切片的受限验收，不代表生产 Pi、整个 S3 或正式独占环境性能通过。

## 能力范围与交付原则

“全部业务能力”包括读取、创建、修改、运行、取消、重试、保存和导出，以及有权限管理员的目录治理、全局同步与撤回。登录验证、文件选择和浏览器下载由网页完成，助手可以发起相应交互并接收业务引用，不能代用户提供密码或读取任意本机文件。服务器部署、整站备份演练、服务器凭据和任意 shell 属于运维过程，不因 M14 或工具覆盖要求向模型开放；F079 的项目备份、校验、恢复与迁移属于业务能力，必须提供工具。

普通研究者、项目编辑、只读成员与平台管理员沿用既有权限。工具列表按角色和可用模块筛选，每次调用仍由 FastAPI 校验；管理员身份不赋予私人项目读取权。同步的下载、解析、校验与发布由确定程序执行，管理员可在助手中启动、检查、取消和重试。

会话分 account、platform、project 三种作用域。登录用户可在 account 会话查看自己的项目并创建项目；平台管理员可进入 platform 会话治理目录和同步；项目只读成员也可进入 project 会话执行允许的读取与查询，业务写入仍按具体动作授权。新项目创建后按固定范围规则衔接项目会话。只有 project 会话必须有 project_id，其他作用域不能借空项目 ID 访问项目数据。

只读成员执行查询或统计会产生 run、job 与结果记录，这属于 create_analysis_run 权限，不等于修改项目材料。write_project_material、write_note、manage_members 分别控制内容和成员修改；export 与 model_egress 单独校验，不从“可查询”自动推导。AI 会话记录及工具账本由系统写入，不因此拒绝只读研究操作。

已授权且目标明确的可逆操作直接执行，不重复请求确认。删除、来源撤回、覆盖或不明确的批量修改先展示具体目标与影响；用户已明确授权相同目标和影响时沿用授权。成员授权变更按同一业务规则核对。新建笔记草稿、生成候选对齐、保存查询和导出不增加通用审批。

人工确认代表用户核对过指定内容。助手可提交用户明确确认的修订 ID，并关联该用户消息或界面事件；模型自己判断“正确”只能记录机器建议，不能生成 human_confirmed。保存成果与人工核对是不同状态。

## 首版能力映射

下表的工具名是稳定的契约名称。每个动作独立注册并指向对应后端 command/query；表内并列动作不得实现为接受任意路由或任意方法的万能工具。具体 HTTP 路由和 Pydantic schema 在 S0/S1 对齐 OpenAPI。

| 模块 | 必须提供的业务动作 | 工具族与开发步骤 |
| --- | --- | --- |
| M01 来源目录 | 列表、搜索、详情、能力和许可、版本与接入状态；管理员新增或修订目录登记 | sources.list/get/versions、catalog.create/update；S1、S4 |
| M02 真实同步 | 检查上游版本、启动同步、查看校验与质量报告、构建固定版本索引及查看报告；管理员发布通过校验的版本、设置同步计划 | sync.check/start/report、indexes.build/report、releases.publish/get、policies.get/update 的来源分支、sync.schedule.get/update；S2 至 S4 |
| M03 账号项目 | 查看当前身份、创建及修改项目、归档项目、查看和管理成员、挂载或移除来源、选择固定来源版本 | account.get、projects.list/get/create/update/archive、members.list/invite/update/remove、mounts.list/get/create/remove/manifest；S1、S3 |
| M04 上传清洗 | 发起网页文件选择和上传会话、提交已上传对象、解析、选择清洗配置、查看质量、去重及生成材料修订 | uploads.create/complete、imports.start/get、materials.list/get、processing.preview/run、quality.get；S1、S3、S4 |
| M05 子库快照 | 筛选材料、保存子库条件、预览成员、构建和查看固定快照、按新材料生成新版快照 | subcorpora.list/create/update、snapshots.preview/create/get；S3、S5 |
| M06 中英查询 | 生成与校验查询草稿、字符或 token 查询、短语、布尔条件、距离、受限正则和属性检索 | queries.validate、corpus.describe/search；S3、S5 |
| M07 上下文结果 | KWIC、上下文、出处、排序、二次筛选、抽样、收藏、保存及恢复查询 | results.get/context/filter/sample、evidence.get、bookmarks.list/create/remove、savedQueries.list/create/update/run；S3、S5 |
| M08 基础统计 | 字词频、文档频率、标准化频率、2 至 4 元词组、共现和 logDice | analysis.frequency/ngrams/collocations、results.get；S5 |
| M09 子库比较 | 关键词 log likelihood 与 log ratio、年份体裁来源分布、双查询比较及图表数据 | analysis.keywords/distribution/compare、charts.get；S5 |
| M10 双语研究 | 双向查询、自动一对一对齐候选、查看错配与未配对、创建覆盖层、新增替换拒绝确认、按固定修订重跑分析 | parallel.search、alignment.start/get/candidates、alignment.layers.create、alignment.commits.create、analysis.compare；S3 查询，S6 完整闭环 |
| M11 研究助手与笔记 | 研究计划、证据问答、真实统计解释、笔记草稿、读取与编辑笔记、按用户指令保存、研究 Skills；会话查看与任务取消由宿主提供 | notes.list/get/create/update/accept、research.plan、evidence.create/list/get；S1、S3、S7 |
| M12 成果导出 | 参数及来源方法清单、CSV/XLSX/SVG/DOCX/JSON 产物创建、状态与下载引用 | exports.create/list/get、artifacts.list/get；S3 最小输出，S6 全部格式 |
| M13 任务与撤回 | 查看任务、进度、错误、取消、有限重试、恢复与影响范围；管理员来源撤回及受影响范围查询 | jobs.list/get/cancel/retry、invocations.get、sources.impact/withdraw；S1、S2、S4、S7 |
| M14 部署与验收 | 查看部署已公开的服务可用性、软件与数据版本、当前权限及配额；复用任务和来源报告核查业务状态 | system.status/versions、account.capabilities/quota；S1、S8；部署和恢复演练由运维执行 |

account.capabilities 返回当前可用工具及未上线原因，不能将后续能力伪装为可调用工具。实时协作、复杂标注、多译本、音视频、OCR 等长期能力保留既定阶段；对应业务上线时增加有类型的工具、权限与验收，不另建第二套业务实现。

长期功能按以下分组检查覆盖。每个 F 项上线前都需记录其实际业务动作或明确的 UI/运维分类；分组映射不代替逐项验收。

| 功能编号 | 业务范围 | 关联能力 |
| --- | --- | --- |
| F001 至 F008 | 项目与语料设计 | M03、M05；projects、members、subcorpora、snapshots |
| F009 至 F016 | 同步与清洗 | M01、M02、M04、M13；sources、sync、imports、processing |
| F017 至 F024 | 语言处理与标注 | M04 及后续标注；processing，标注上线时同批增加有类型的读写工具 |
| F025 至 F032 | 查询 | M06、M07；corpus、queries、results |
| F033 至 F040 | 统计 | M08、M09；analysis、charts |
| F041 至 F048 | 搭配与探索 | M08、M09 及后续探索；analysis |
| F049 至 F056 | 双语与术语 | M10 及后续术语；parallel、alignment，术语模块上线时补齐 |
| F057 至 F064 | 多模态 | 后续材料、标注与任务能力，跟随媒体模块接入 |
| F065 至 F072 | AI 与 Agent | M11 横向调用全部业务；F067 中一对一对齐候选进入首版，预标注与术语按后续阶段 |
| F073 至 F080 | 证据与成果 | M07、M11、M12；evidence、notes、exports、artifacts |
| F081 至 F088 | 协作与策略 | M03、M13 及后续协作；members、权限和策略相关业务工具 |
| F089 至 F096 | 平台与扩展 | M14 与后续连接器等业务能力；部署运维、凭据操作按边界分类 |

## 首版逐项补充动作

以下动作补齐跨模块业务，均适用相同权限、版本和幂等规则。它们进入所属模块的发布验收，不能仅以模块工具族存在认定覆盖。

| 功能 | 首版动作与工具 | 步骤 |
| --- | --- | --- |
| F001、F065 | 研究问题、方案与方法分支读取保存；research.questions.list/create/update、research.plans.get/save | S3、S7 |
| F002 | 元数据字段类型、枚举与校验配置，材料元数据修订；metadata.schemas.get/update、metadata.validate、metadata.commit | S4、S5 |
| F005 | 纳入排除及理由读取写入；selection.records.list/commit，快照固定对应记录 | S5 |
| F017 | 分句分词配置与自定义词典版本；processing.recipes.get/create、dictionaries.get/update、processing.run | S4 |
| F032 | 授权资料语义发现；discovery.search，返回相似度和引用，不返回语料频次 | S5 |
| F071 | 模型允许列表、数据外发策略、用量与审计；models.list、policies.get/update、usage.get、audit.list；仅授权管理角色可改策略，模型凭据经独立表单配置 | S1、S7 |
| F073、F074 | 文献和研究记录关联、证据与论断关联；references.list/create/update、claims.list/create/update；notes.accept 需用户针对指定笔记 revision 的接受依据 | S3、S6 |
| F079 | 项目备份创建、完整性校验、恢复及路径映射；projectBackups.create/get/validate、backupUploads.create/complete、projectRestores.preview/start；账号级上传本人备份包不要求已有项目；首版仅恢复为新项目，不提供覆盖现有项目入口 | S6、S8 |
| F087、F093 | 权限内审计与业务限额查询，管理员调整项目资源限额；audit.list、quotas.get/update；同步和计算任务仍执行同一限额 | S1、S7 |
| F087 | 项目和材料删除影响预览、软删除、恢复及正式生命周期清除；projects.deletionImpact/delete/restore、materials.deletionImpact/delete/restore；永久清除仅调用既有后台业务命令，按保留策略和明确授权执行 | S4、S7；具体路由 S0 冻结 |
| F013、F016 | 核准连接器配置查询与更新、版本升级预览；connectors.get/update、mounts.previewUpgrade/upgrade；敏感凭据不回传模型 | S2、S4 |

F001 至 F096 的各子项以产品功能清单的 A/B/C/D 阶段为准。首版 A 部分全部纳入上述覆盖矩阵；混合阶段功能仅交付其 A 部分。未来 B/C/D 的业务操作在同一注册表加行，不能把“未来将接入”计入首版真实可用数量。

## 注册表与调用契约

注册表维护在 contracts 中，作为业务动作与 Pi 工具的显式映射。FastAPI 业务模块拥有规则，Node 适配器使用生成的类型客户端调用。首版采用静态注册清单和构建时校验，不建设插件市场、动态 API 发现或通用工作流引擎。

| 字段 | 要求 |
| --- | --- |
| capability_id、feature_ids、module_id | 稳定动作 ID、关联 F 编号和 M 模块；一个动作可服务多项功能 |
| tool_name、schema_version、availability | 唯一工具名、输入输出版本、计划阶段及实际可用状态 |
| handler、operation_kind | 明确后端 command/query 标识；read、write 或 task |
| input_schema、output_schema | 与后端共享 Pydantic/OpenAPI 定义；禁止自由 SQL、任意路由或方法执行参数；核准连接器 URL、路径映射等合法业务字段按各自规则校验 |
| permission、scope_kind | 服务端权限规则；account、platform 或 project；项目动作必须绑定 project_id |
| version_inputs、scope_effect | 固定 snapshot、材料修订、覆盖层 revision 和 expected_revision；标注 none 或 produces_scope |
| authorization_policy | 直接执行、需明确目标或需破坏性动作授权；服务端核对已有用户授权 |
| execution、idempotency | 同步或后台 job；invocation_id 和写操作 action_id 由服务端分配 |
| result_view、common_errors | 结果类型与手动页面定位引用；列明当前动作实际发生的错误 |

actor_id、角色、可调用工具、session/run、租约和授权凭据由宿主注入，模型不能填充或更改。platform 操作只在平台管理作用域中执行，不携带项目正文；项目助手收到管理员全局操作指令时，宿主可创建净化的平台会话执行该结构化指令。进入私人项目仍须项目授权。

当前 HTTP 使用 GET /me/capabilities，以及 /agent/sessions、/agent/sessions/{id}/runs、/agent/runs/{id}；浏览器本片仅账号和项目空材料范围。后续完整目标的 account/platform 别名入口为 POST /agent-sessions 与 POST /agent-runs，项目路由复用同一 handler。对齐任务使用 POST /projects/{p}/alignment-runs、GET /alignment-runs/{id} 与 GET /alignment-runs/{id}/candidates；覆盖层沿用 POST /projects/{p}/alignment-layers 和 POST /layers/{id}/commits。具体请求与展示字段见前端规范。

账号级备份导入通过 POST /backup-uploads 创建本人上传会话，POST /backup-uploads/{id}/complete 校验后返回 backup_ref，再调用 POST /project-restores/preview 和 POST /project-restores。上传和恢复均核对 owner、格式与完整性，不要求先建空项目。

所有结果返回 invocation_id、action_id（写操作）、status、scope_ref、version_refs，以及 result_ref 或 job_id。只读列表和预览可返回受限结构化 items；涉及语料正文的 items 仍受 model_egress 检查。可定位的结果附 result_view 和 evidence_refs。模型只能根据实际返回值说明成功或失败。

状态为 succeeded、accepted、failed、unknown。accepted 返回 job_id，宿主等待任务事件后恢复 Pi；unknown 使用 invocations.get 核对原调用。重试沿用 invocation_id/action_id，同 ID 参数变化拒绝；用户明确更改参数才产生新动作。分页不改变完整计数，未完成计数返回 null。

常见错误包括 403 FORBIDDEN 或 MODEL_EGRESS_DENIED、404 RESOURCE_NOT_FOUND、409 SESSION_SCOPE_CHANGED 或 EDIT_CONFLICT、422 INVALID_INPUT 或 ENDPOINT_OUT_OF_SCOPE、409 CAPABILITY_UNAVAILABLE、429 QUOTA_EXCEEDED。后端可对存在性敏感资源统一返回 404。任务失败保留真实错误和 retryable；不通过模型猜测补出结果。

## 双语对齐完整流程

首版增加自动一对一句级对齐候选。输入可以是共享材料、两份私有材料或两者组合，前提是均已解析成项目可访问的固定修订与句段。未配对、疑似合并拆分和多对多关系只读呈现，首版不强制凑成一对一或提供复杂关系编辑。

1. 上传或选择两侧材料，完成解析和句段处理，构建研究快照。用户已指定“对齐并分析”时，后续步骤可自动继续。
2. alignment.start 接收 snapshot_id、source_segment_scope、target_segment_scope、源目标语言和 recipe_version，返回 accepted 与 job_id。范围由固定材料修订和句段 ID 集合表达；服务端验证两侧端点、语言、配额及模型外发限制。
3. 后台执行版本化对齐管线，生成 candidate_set_id、稳定 candidate_id、两侧端点、匹配分数、需复查原因、未配对清单和方法版本。可使用获准的对齐模型；模型不可外发的材料使用部署内获准算法，若无可用算法则报错，不擅自上传。
4. alignment.get/candidates 返回候选、进度、来源证据和分页。匹配分数仅是算法输出，不显示为人工确认或未经校准的正确概率。未保存候选由 alignment.candidates.review 调用 POST /alignment-candidate-sets/{id}/reviews，输入 expected_review_revision 与 operations（candidate_id、review/edit/discard、可选新端点），追加独立 review_revision；不改原候选输出。保存时 add 固定 candidate_id 与 review_revision，舍弃候选不要求伪造已有 edge_id。
5. alignment.layers.create 绑定 project_id、snapshot_id 和基础关系集；可选 source_release_refs，纯私有材料不要求 mount_id 或基础来源边。用户指令可通过 alignment.commits.create 保存候选或修改一对一关系。
6. commits 输入 layer_id、expected_revision、operations；每项包含操作、base_edge_id 或 project_edge_id 或 candidate_id、两侧端点和 confirmation。新增可以没有基础边，但端点必须完整；替换、拒绝与确认必须引用已有边。用户明确核对的未保存候选可在同一 commit 中执行 add 并携带 human_confirmed 及授权依据，无需先保存再确认两次。操作成功返回新的 overlay_revision、changed_edges 和 scope_effect。机器建议保存为 proposed；用户明确核对的项按授权证据记为 human_confirmed。
7. 新修订产生新研究范围。宿主按下一节切换会话，再运行 parallel.search、统计、解释、笔记与导出。旧分析仍绑定旧版本，不被重算覆盖。

数据对象增加 alignment_runs 与 alignment_candidate_sets，保存 snapshot、recipe、任务、候选与未配对结果；alignment_overlays 以 snapshot_id 为范围根，source_release_refs 仅在引用共享基础关系时存在。来源边保持不可变，项目边和候选用不同 ID 类型，避免将私有生成关系冒充原始来源关系。

首版管线采用已有版本化分句结果，按文档或用户指定段落配对，使用部署内多语种句向量相似度与长度比、数字标点锚点打分，再以保持句序的动态规划寻找一对一匹配或跳过；不生成多对多编辑。recipe 固定向量模型及摘要、分句版本、打分权重、跳过代价和复查阈值。未具备模型时任务明确不可用，不把长度启发式结果冒充同等质量的模型对齐。S0 使用领域人员独立标注的小样本比较候选正确率、覆盖率与未配对率，并包含漏译、重排和长短句；据实选模型与阈值，登记性能和适用材料。S6 在固定金标上验证未配对和疑似错配可复查、端点不越界、重复运行同 recipe 可回查，质量不达标时调整管线再验收。LLM 可解释或建议修订，最终关系仍写入上述候选及修订对象。

双语查询与导出分别返回源句数、目标句数、关系数和展示行数。候选数、已保存关系数、人工确认数单独列出；单语统计仍按唯一材料计数。复杂关系可随来源读取，不能经助手绕过首版只读约束。

## 固定范围与连续任务

会话继续固定 input_scope 和 scope_digest，已有 run 的输入不随页面或工具结果改变。创建项目、生成快照、保存覆盖层修订不会就地扩大旧会话的材料范围。

同一固定 snapshot 与 overlay 上产生的新查询、分析、证据或笔记 result_ref 属于范围内派生成果，增加这些引用不改变 scope_digest，不触发新会话。只有项目、材料成员、快照或覆盖层修订身份实际改变才标记 produces_scope，避免每个工具结果都造成会话切换。

产生新范围的工具只向旧 run 返回业务 ID、状态、计数和 scope_effect，不返回新范围正文。若用户任务还包含后续分析，FastAPI 将剩余用户意图保存为 continuation_intent，字段限定为新目标引用、允许的业务步骤、结构化参数和原授权引用，不携带旧消息、正文、工具摘要或模型推理。旧 run 完成当前步骤并记录 next_session_id，宿主重新授权后建立新会话，重新读取新范围所需材料再继续。

网页可以在同一工作台显示步骤衔接及新范围，但不能把这种展示连续性实现为 Pi 历史复用。原排队消息保留在旧会话，范围变化时标记需要重新选择范围；不自动投递到新会话。若无剩余已授权任务，展示新快照或修订，由用户下一次操作选择。手动切换范围走同一规则。

取消按钮指向当前活动 run，并停止同一用户任务尚未启动的 continuation_intent。宿主在创建续接 run 前检查取消状态，取消后不自动开新 run；已发布的快照、修订或成果保留并明确显示。

新会话校验项目权限、来源许可和模型外发权限。仅有新版本引用不构成外发授权。发生撤回时按既有净化规则停止受影响会话，不携带撤回正文或摘要续接。

## 同批开发与验收

S0 定义注册表、权限与 scope_effect schema，验证 Pi 类型化调用及私有双语对齐算法。S1 建账户、项目、目录、任务与上传工具。S2 至 S4 随真实同步、挂载、导入、快照、查询、笔记和最小导出逐项注册。S5 接入完整检索与统计。S6 完成自动对齐、修订、范围接续和全部成果格式。S7 验收跨模块组合任务及恢复。S8 对照 M/F 清单核验覆盖，后续模块遵守相同发布规则。

每项业务发布必须同时提交手动入口、后端操作、工具定义、权限、结果定位与相应测试。纯展示行为标记 UI interaction，未上线功能标记 planned，运维动作标记 operations；不能靠虚假 no-op 工具凑覆盖率。M14 的业务状态查询和运维部署分别验收。

验收至少包含：研究者从材料选择到分析导出；纯私有双语材料自动对齐、修订、换范围分析和证据回查；管理员经助手同步与撤回，普通成员调用被拒绝；只读成员不能通过助手写入；人工确认有真实用户授权依据；同参数手动与工具结果一致；重复调用不重复提交；新范围不外发旧正文；全部已上线业务动作有工具覆盖或明确的 UI/运维分类。详细编号见开发计划 A13 至 A18。
