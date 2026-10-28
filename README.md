# 语料检索、分析与标注研究平台

面向高校外语、翻译和语言学研究生的网页平台：类 CCL 的语料检索、统计分析、Agent 预标加人工校对的可视化标注、知识库建设，以及基于 Pi SDK 与 OpenUI 的内置研究助手。

## 功能

| 模块 | 内容 |
| --- | --- |
| 语料库 | 导入 TXT、DOCX、CSV/TSV、CoNLL-U、TMX、Tatoeba；中文 jieba、英文 Stanza；元数据与子库；内置语料带许可与署名 |
| 检索 | 查询式：字串、`词/n`、相邻、`$N` 间隔、`\|`、`+`/`-` 同句条件、引号、`*`、`?`、`{pos=,dep=,lemma=}`、`[标签]`；KWIC、上下文、对齐句、分布条、导出 |
| 统计 | 频次、n-gram、搭配（MI / logDice / t / LL）、关键词（LL / log ratio）、分布、标注与对齐统计；图表；每行回到例句 |
| 标注 | 词性、依存、片段、关系、双语对齐五类层；Agent 预标 + 人工校对；多人一致性（κ / α）与仲裁；导出 CoNLL-U、brat、JSON、TMX、XLSX |
| 知识库 | 文献（PDF / DOCX / MD / TXT / URL）、术语表（抽取、译名、TBX）、标注规范、研究笔记；向量 + 关键词混合检索 |
| 助手 | 对话调用全部工具，回答内嵌 KWIC 表、图表、依存树、对齐图、术语卡、知识引用等组件；独立页与右侧抽屉 |
| 全局 | 证据篮、命令面板 Ctrl+K、任务托盘、快捷键、深色模式、引导页 |

## 文档

- [平台重构设计](doc/语料检索分析与标注研究平台重构设计.docx)：定位、功能、数据模型、查询语法、统计、标注、知识库、Agent、架构、计划与验收。维护源 [platform-redesign.md](doc/platform-redesign.md)。
- [前端整体设计方案](doc/前端整体设计方案.docx)：视觉系统、页面、组件、动效、交互与实现记录。维护源 [frontend-design.md](doc/frontend-design.md)；设计稿 [doc/ui-design/index.html](doc/ui-design/index.html)。
- [部署手册](doc/部署手册.docx)：环境、服务、变量、首次启动、升级、备份恢复、故障。维护源 [deployment.md](doc/deployment.md)。
- 接口契约 [contracts/p1–p6](contracts/)；审查记录 [doc/reviews](doc/reviews/)；[变更原因日志](doc/change-log.md)；协作规范 [AGENTS.md](AGENTS.md)。
- 旧版设计在 `doc/history/2026-10-redesign-before/`。

## 工程结构

```text
apps/web/          React 19 + TypeScript + Vite + Ant Design 5 + ECharts + OpenUI
services/api/      FastAPI 业务接口与 Alembic 迁移
services/worker/   任务执行器（PostgreSQL 队列）：导入、索引、统计、预标、导出、知识库
services/agent/    Node + Pi SDK 助手服务：会话、工具、OpenUI 流
engine/            解析、jieba / Stanza 标注、CWB 索引与检索、查询语法、统计、知识库、对齐、一致性
scripts/           账号、内置语料导入、性能基线、备份恢复
contracts/         阶段接口契约
deploy/            Compose、Dockerfile、nginx
tests/             pytest（engine、api、integration）、vitest、node:test
```

## 本地开发

基线：Python 3.12（uv）、Node 24、Docker。CWB、Stanza 与向量模型只在容器内可用。

```powershell
uv sync --frozen
npm ci --prefix apps/web
npm ci --prefix services/agent

# 不依赖容器
uv run --frozen --with pytest pytest tests/engine -k "not cwb and not nlp" -q
npm run check            # 前端类型检查、构建、vitest
npm run agent:test       # 助手服务（假模型）

# 整套服务：复制 deploy/.env.example 为 deploy/.env，填 POSTGRES_PASSWORD、PUBLIC_ORIGIN、MODEL_*
npm run web:build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email you@example.edu --admin
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test              # api + engine 测试
STACK_URL=http://localhost:8080 uv run pytest tests/integration -s -p no:cacheprovider   # 权限矩阵，对运行栈执行
```

浏览器打开 http://localhost:8080。模型未配置时助手页提示"尚未配置模型"，其余功能可用。前端开发用 `npm run web:dev`（5173，代理 /api 与 /agent），`PUBLIC_ORIGIN` 需加入 `http://127.0.0.1:5173`。内置语料由管理员用 `scripts/import_builtin.py` 导入；备份与恢复见部署手册。
