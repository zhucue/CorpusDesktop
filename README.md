# 语料检索、分析与标注研究平台

面向高校外语、翻译和语言学研究生的网页平台：类 CCL 的语料检索、统计分析、Agent 预标加人工校对的可视化标注、知识库建设，以及基于 Pi SDK 与 OpenUI 的内置研究助手。

## 设计文档

- [平台重构设计](doc/语料检索分析与标注研究平台重构设计.docx)：定位、功能范围、数据模型、查询语法、统计、标注、知识库、Agent、技术架构、页面、开发顺序与验收。维护源 [platform-redesign.md](doc/platform-redesign.md)。
- [前端整体设计方案](doc/前端整体设计方案.docx)：视觉系统、页面、组件、动效、交互模式与实现映射。维护源 [frontend-design.md](doc/frontend-design.md)；设计稿 [doc/ui-design/index.html](doc/ui-design/index.html) 可直接用浏览器打开。
- [变更原因日志](doc/change-log.md)：修改前阅读相关决定，修改后同批追加原因。
- 协作规范见 [AGENTS.md](AGENTS.md)。

2026 年 10 月 27 日之前的设计文档在 `doc/history/2026-10-redesign-before/`，不作为当前基线。

## 当前状态

2026 年 10 月 27 日起按重构设计重建，当前处于 P1（语料与检索）。重构前的代码归档在提交 `2b0282b`，重建过程中逐步替换。

## 工程结构

```text
apps/web/          React + TypeScript + Vite + Ant Design
services/api/      FastAPI 业务接口与 Alembic 迁移
services/worker/   任务执行器（PostgreSQL 队列）：导入、索引、导出
engine/            解析、Stanza 标注、CWB 索引与检索、查询语法
contracts/         阶段接口契约（p1.md）
deploy/            Compose 与 Dockerfile
tests/             pytest：engine、api
```

## 本地开发

基线：Python 3.12（uv）、Node 24、Docker。CWB 与 Stanza 只在容器内可用。

```powershell
# 依赖
uv sync --frozen
npm ci --prefix apps/web

# 不依赖容器的测试与前端检查
uv run --frozen --with pytest pytest tests/engine -k "not cwb and not nlp" -q
npm run check

# 整套服务：复制 deploy/.env.example 为 deploy/.env，填 POSTGRES_PASSWORD；
# 8080 被占用时同时改 HTTP_PORT 和 PUBLIC_ORIGIN；对话模型填 MODEL_BASE_URL / MODEL_API_KEY / MODEL_ID
npm run web:build                                   # web 镜像打包 apps/web/dist，改前端后先构建
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email you@example.edu --admin   # 隐藏输入；脚本可用 --password-stdin
docker compose --env-file deploy/.env -f deploy/compose.yaml run --rm test   # api + engine 测试（真实 PostgreSQL、CWB、Stanza）
npm run agent:test                                  # agent 服务测试（假模型）
```

浏览器打开 http://localhost:8080。模型未配置时助手页提示"尚未配置模型"，其余功能可用。前端开发用 `npm run web:dev`（5173，代理 /api 到 8000、/agent 到 8700），此时 `PUBLIC_ORIGIN` 需加入 `http://127.0.0.1:5173`。首次导入会把 Stanza 中英模型（约 500 MB）下载到 `stanza` 卷。
