# 高校语料与 AI 研究工作台

面向外语、翻译和语言学研究生的网页研究平台。首版以系统内置研究助手工作台为主要入口，集中研究任务、材料、证据与成果；真实数据源同步、检索、分析和笔记保留独立手动工具入口。研究助手基于 Pi SDK 改造，按当前用户权限调用全部已上线业务能力，包括同步、选材、清洗、检索、对齐、分析、保存与导出；Pi 是技术基础，不作为外置产品或原生界面交付。

## 正式设计文档

正式文档统一放在 `doc/`。

- [平台重构设计](doc/语料检索分析与标注研究平台重构设计.docx)（维护源 [platform-redesign.md](doc/platform-redesign.md)）：2026 年 10 月 27 日起的设计基线——类 CCL 检索、统计分析、可视化标注、知识库与基于 Pi + OpenUI 的 Agent。以下旧文档待迁入 `doc/history/`。
- [完整产品设计](doc/高校研究生语料与AI研究工作台完整设计规划.docx)：96 项长期功能、14 组首版功能、46 个来源登记项。
- [研究助手业务能力与工具契约](doc/研究助手业务能力与工具契约.docx)：全业务工具映射、权限、自动对齐、范围接续与覆盖验收。
- [网页端技术设计](doc/高校研究生语料与AI研究工作台网页端技术设计.docx)：技术栈、数据模型、同步、检索与 Pi 集成。
- [业务架构与开发计划](doc/业务架构与开发计划.docx)：业务边界、S0 至 S8、K01 至 K10、验收用例与架构审查。
- [前端与接口设计规范](doc/前端与接口设计规范.docx)：页面、交互、组件状态与前后端接口契约。
- [前端 UI 设计方案](doc/前端UI设计方案.docx)：研究工作台布局、视觉样式、动效和内置研究助手交互，细化现有前端规范。
- [S0 验证与工程准备](doc/S0验证与工程准备.docx)：已取得的来源、契约、Pi 宿主与检索实验结果，以及基础工程和剩余验收门槛。

## 开发入口

1. [业务架构与 Pi 运行基线](doc/business-architecture.md)
2. [首版开发任务与验收](doc/development-plan.md)
3. [前端与接口规范维护源](doc/frontend-specification.md)
4. [业务架构审查记录](doc/reviews/2026-10-15-architecture-review.md)
5. [研究助手工具契约维护源](doc/assistant-capabilities.md)
6. [完整产品维护源](doc/product-design.md)与[网页技术维护源](doc/technical-design.md)
7. [变更原因日志](doc/change-log.md)：修改前阅读相关决定，修改后同批追加原因。

设计文档的 Markdown 用于维护，变更同步对应 Word。`doc/history/` 保存历史材料，不作为当前开发基线。

当前推进 K09 兼容模型协议接入，S3／K08 已贯通全量持久索引、固定来源核准发布、项目整库挂载及受限研究快照查询，进度及复跑入口见 [验证记录](doc/s0-validation.md)。邮箱登录、项目与成员权限已接真实 PostgreSQL，9 项认证和 RLS 集成测试通过；私有上传、队列校验和持久任务链路另有 10 项真实依赖测试通过，该校验结果止于 VALIDATED；后续 TXT 导入和研究快照索引已另接入。来源目录已接入 46 项元数据和管理员修订；Pi 已实现受限执行凭据、PostgreSQL 单写租约与调用账本，并加入私有不可变检查点、完整会话归档校验和跨进程打开机制；9 项真实数据库／存储测试及两个独立 Node 进程接续验证通过。可靠 WAITING_JOB 接续及常驻宿主已实现并完成专项检查，两个独立进程跨 WAITING_JOB 的真实上传校验链及本地 fixture 工作台核心交互已通过；运行中未知调用、真实模型服务、材料范围和模型外发仍未验收，生产研究工具未开放。46 个来源登记项不代表 46 个已同步全文库，S0 尚未整体验收通过。

后续 S0 实验已将千万中文码点查询的最大逐查询 P95 从 15.563 秒降至 2.827 秒；CWB 首屏与完整计数分离后，千万 token 普通首屏最大逐查询 P95 从 21.554 秒降至 1.361 秒，普通完整计数最大 2.501 秒。高频 gap 首屏仍为 3.282 秒。上述性能结果来自共享环境的合成样本实验；S0 索引身份和字节配额为契约实验，S3 的真实构建与配额集成另行记录。

中英文 Wikimedia 固定完整分片均已通过官方 SHA256，各确定性选取 1000 篇；中文 972 篇、英文 996 篇取得受限正文及原文映射，其余明确拒绝。真实 UD 的 1964 句、40407 词已核对 CWB 坐标、属性及计数。WMT19 新闻文档评估补充公开参考证据，测试集计入超长整篇拒绝后的召回为 69.897%，项目领域质量仍未验收。完整证据和限制见验证记录；S1／K06 首条链路已通过运行服务的 6 组独立 HTTP 检查和真实浏览器上传、刷新、退出回归，S1 来源目录另经 7 项真实数据库测试、4 组 HTTP 和浏览器回归通过；Pi 运行基础通过 10 项真实数据库测试。私有检查点发布及已完成会话的跨进程接续已通过受限验证，第二次运行继承结果且未重复创建项目；后续 K09 接续结果另列，任意崩溃恢复和模型外发门槛保留；S2 已完成管理员 D12 固定连接器和后台全量解析；S3 的固定 acquisition 字符及词形索引已通过实际构建与私有归档验收，已补受限来源核准发布、整库挂载与项目查询，已补私有 TXT 与混合快照，并接入固定证据、笔记和完整查询成果。

D12 连接器处理官方完整中文、英文及直接关系三包，共 37,141,424 字节；解析保留 2,127,898 句与 78,089 条有效直接边，明确排除 199 条缺端点关系。原件、许可页面、全量句子／关系、SQLite 差分依据和 manifest 保存为私有固定对象版本。结果仅为 VALIDATED，目录发布版本仍为空，不能检索或作为模型外发批准。两次运行服务的完整同步、各 13 个私有对象校验及再次零差分均已通过，验证记录保留早期失败与限制。

S3 已用上述全部句子构建 82,951,215 码点、19,660,489 词项的持久索引。读取优化后全量坐标及原 20 查询核验一致；共享环境单次字符首屏最大 0.112 秒、完整计数最大 3.747 秒，正式并发性能另验。基础词形仅有 form。独立测试来源已通过核准、固定版本发布、项目整库挂载、刷新与撤权回归；真实 D12 仍待许可核准，索引构建本身仍只到 INDEXED。项目成员现可在获准整库挂载上创建固定研究快照、执行句内字符或词形查询、读取稳定分页及真实上下文；首屏与完整结果分为持久任务，撤权后停止展示。9 项真实依赖测试、运行 HTTP 与浏览器验证通过；完整既有索引的 20 条查询及 180 次分页／上下文核验通过，完整跨度落盘成本单独记录。当前登记 143 个动作、52 个显式适配器，生产 Pi 工具为 0；材料查询与模型外发尚未授予 Pi。完整证据及旧失败基线见验证记录。

私有 UTF-8 TXT 与混合材料已贯通解析、固定修订、项目单索引和查询：完整 canonical 文本保留换行与 Unicode，句段坐标可回到完整修订；纯私有和共享＋私有材料构建一个固定项目索引，按真实文件与导入来源记录分别计数。当前 parser 5 项、真实 CWB 项目索引 6 项通过，既有全量来源索引的 4 条代表查询兼容核验通过。真实 HTTP 与浏览器已验证纯私有 2 文件／5 句段，以及混合查询 125 命中／65 句段／62 文档单位；共享来源撤权后混合结果清空，纯私有仍可查询。材料解析成功只表示修订可选，快照索引准备完成才可检索；来源许可、Pi 材料范围和正式性能门槛保留。

固定证据、不可变笔记修订与 CSV／JSON 导出已接入真实后台：可保存首尾命中，人工采纳指定笔记修订，并按固定查询顺序导出完整结果；CSV 成果包包含数据表与方法 JSON。8 项真实依赖测试、完整 HTTP 及本批核心浏览器交互通过；笔记旧修订固定，撤权后已选内容清除。来源导出核准独立于全文检索许可，发布及下载均重新检查权限。当前继续本地开发；正式独占环境性能保留待验，不阻塞后续功能推进。

K09 新增持久用户消息、单并发宿主和可靠后台任务接续；29 项专项检查通过，两个独立进程的真实业务等待接续、7 类 10 条 HTTP 响应和本地 fixture 工作台核心交互已通过。默认宿主未配置模型，就绪检查明确返回 503，且不领取任务；显式本地 fixture 只用于运行链测试，不向外部模型发送材料，不自动开放生产工具。

兼容 OpenAI 的两种内置协议已接入同一运行生命周期，固定服务器配置并限制模型请求目的地，模型密钥只进入 Node 内存。两协议均通过本机合成 SSE、两个独立 Node 进程及真实后台任务接续，Node 72 项通过；真实服务仍待地址、模型与协议，尚未连接，材料范围和模型外发没有随协议接入开放。

## 本地开发

开发基线为 Python 3.12、Node.js 24.15.0 和 npm 11.12.1。Python 依赖由 `uv.lock` 固定，前端和 Pi 宿主分别使用自己的 `package-lock.json`。

```powershell
uv sync --frozen --python 3.12.14
npm ci --prefix apps/web --ignore-scripts
npm ci --prefix services/agent-runtime --ignore-scripts
npm run check
npm test
uv run --frozen pytest
```

`npm run web:dev` 启动前端开发页，`uv run uvicorn services.api.main:app --reload --port 8000` 启动 API。API 需要非管理员 `DATABASE_URL`、`PUBLIC_ORIGIN` 及依赖服务配置。默认要求 HTTPS；仅本机开发显式允许 HTTP。依赖或迁移未就绪时返回 503；公开能力目录与当前用户授权分开，生产 Pi 工具仍未开放。

Compose 配置位于 `deploy/compose.yaml`。`scripts/init_dev_env.py` 只追加缺失配置，不改已有密码和端口；凭据保留在忽略的 `deploy/.env`，不得放在 tmp。初始化顺序如下：

```powershell
uv run python scripts/init_dev_env.py
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --wait database broker object-storage
docker compose --env-file deploy/.env -f deploy/compose.yaml build api db-bootstrap migrate test-auth worker dispatcher manage-account index-worker test-index
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm db-bootstrap
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm migrate
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm storage-init
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth python -m unittest discover -s tests/integration -p test_catalog_pipeline.py -v
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth python -m unittest discover -s tests/api -p test_agent_runtime.py -v
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth python -m unittest discover -s tests/api -p test_agent_checkpoints.py -v
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth python -m unittest discover -s tests/integration -p test_upload_pipeline.py -v
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-auth python -m unittest discover -s tests/integration -p test_source_sync_pipeline.py -v
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test-index
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile worker up -d --wait api worker dispatcher index-worker
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm manage-account create --email researcher@example.edu
```

上述真实依赖测试在常驻消费者启动前运行；已有服务复跑时先暂停本项目 dispatcher／worker／index-worker，测试结束恢复。索引镜像另用固定 CWB、分词和构建依赖锁，API 不加载分词字典。API 就绪后可执行 `uv run python scripts/agent_runtime_smoke.py`，以临时账号和两个独立 Node 进程验证固定模型的 SDK → HTTP → PostgreSQL／私有对象存储路径：首次创建项目并发布检查点，第二次继承结果且不重复执行。报告写入 tmp/pi-s1，临时账号、运行记录与私有归档随后清理；不调用外部模型。该检查只覆盖已完成检查点的接续。K09 的 scripts/agent_waiting_smoke.py 另验证同 run 的后台任务等待与恢复；两者均须管理员显式启用 fixture API 后运行，结束恢复 unconfigured。默认 agent-host 可单独部署并保持未配置状态，不能用本地 fixture 就绪替代生产 provider 就绪。

最后一条命令通过交互隐藏输入建立账号；密码不放命令参数或日志。开放注册默认关闭。`corpus_owner` 仅用于迁移和账号 CLI，API 使用 `corpus_app`，Worker 使用独立 `corpus_worker`。本机保留 [60636 入口](http://127.0.0.1:60636)，服务运行时可访问；最终 HTTP 链路验收与实验边界见验证记录。临时文件统一放在 `tmp/`。

## 前端 UI 原型

- [打开新版原型（v2.1）](tmp/ui-v5/index.html#assistant)：静态 HTML，可直接用浏览器打开，无需构建。
- [本机预览](http://127.0.0.1:8852/#assistant)：预览服务运行期间可访问；启动命令 `node tmp/ui-v5/serve.cjs 8852`。
- [UI 设计维护源](doc/frontend-ui-design.md)：与正式 Word 同步维护。

v2.1 采用仪器感科技风：近黑石墨底、1 px 冷白细线、单一冷蓝强调色、等宽编号与计数，不使用褪色渐变、彩色光晕或大面积玻璃模糊。左侧按研究、成果、数据、管理分组，顶部显示页面、运行状态与当前快照，底栏显示项目、范围与任务状态。检索与结果以 KWIC 表格为主体，命中为冷蓝下划线；证据、来源与任务详情在右侧检查器展开。状态用方块加等宽文字，进度用 1 至 2 px 单色细线，动效只用于操作反馈与真实运行状态。

研究助手为对话式工作台：用户消息、助手消息、可折叠的执行过程、流式回答、结果卡片与等宽证据引用，输入框固定在底部；运行中显示顶部细线位移、步骤扫光、状态呼吸与停止按钮。查询、分析、材料、任务、笔记、同步和助手仍使用内存示例与确定性模拟，刷新后重置，不代表真实业务实现。v2 渐变版 `tmp/ui-v4/`、v1 学术工作台 `tmp/ui-v3/` 与更早设计保留，不作为当前预览入口。
