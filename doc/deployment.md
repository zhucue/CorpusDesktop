# 部署手册

单机 Docker Compose 部署。配置见 `deploy/compose.yaml`、`deploy/.env.example`。

## 一 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux x86_64（Windows / macOS 的 Docker Desktop 可用于开发） |
| Docker | Engine 24+ 与 Compose v2 |
| 资源 | 4 CPU、16 GiB 内存起（api 与 worker 各加载向量模型约 500 MB；Stanza 英文约 1 GiB）；磁盘：镜像约 8 GiB，模型缓存约 1.5 GiB，语料与索引按数据量（完整 Tatoeba 中英约 2 GiB） |
| 网络 | 首次启动需访问 Hugging Face（向量模型）、Stanza 模型源、对话模型服务；离线部署先在联网机器拉取 `models`、`stanza` 卷内容 |

## 二 服务

| 服务 | 镜像 | 端口 | 卷 |
| --- | --- | --- | --- |
| postgres | pgvector/pgvector:pg16 | 127.0.0.1:${POSTGRES_PORT} | postgres |
| api | deploy/Dockerfile.api | 内部 8000 | data、models、stanza |
| worker | deploy/Dockerfile.worker | — | data、models、stanza |
| agent | deploy/Dockerfile.agent | 内部 8700 | agentdata |
| web | deploy/Dockerfile.web（nginx） | 127.0.0.1:${HTTP_PORT} | — |
| test | api 镜像 | — | 同 api |

nginx 把 `/api/` 反代到 api、`/agent/` 反代到 agent（SSE：关闭缓冲，600 秒超时），`index.html` 不缓存。

## 三 `.env` 变量

| 变量 | 说明 |
| --- | --- |
| POSTGRES_PASSWORD | 必填 |
| POSTGRES_PORT、HTTP_PORT | 宿主端口，默认 15432、8080；端口被占用时同时改 HTTP_PORT 与 PUBLIC_ORIGIN |
| PUBLIC_ORIGIN | 浏览器访问地址，逗号分隔多个；非 GET 请求的 Origin 须匹配（api 与 agent 都校验） |
| MODEL_BASE_URL、MODEL_API_KEY、MODEL_ID、MODEL_API | 对话模型（OpenAI 兼容；`MODEL_API` 为 `openai-completions` 或 `openai-responses`）。未配置时助手与依赖模型的预标、摘要、抽取不可用，其余功能正常 |
| MODEL_CONTEXT_WINDOW、MODEL_MAX_TOKENS、MODEL_TIMEOUT_MS、MODEL_REASONING | 可选 |
| EMBED_PROVIDER、EMBED_MODEL、EMBED_BASE_URL、EMBED_API_KEY、EMBED_DIM | 向量模型；默认本地 `paraphrase-multilingual-MiniLM-L12-v2`（384 维），远程须 384 维 |
| MODELS_DIR、HF_HOME | 模型缓存目录（容器内 `/models`） |
| SEARCH_COUNT_TIMEOUT | 检索完整计数的超时秒数，默认 20；超时后页面显示"计算中"并可重取 |

密钥只放在 `deploy/.env`，不入库、不放 `tmp/`。

## 四 首次启动

```bash
cp deploy/.env.example deploy/.env           # 填 POSTGRES_PASSWORD、PUBLIC_ORIGIN、MODEL_*
npm ci --prefix apps/web && npm run web:build  # web 镜像打包 apps/web/dist
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email admin@example.edu --admin
```

api 启动时执行 Alembic 迁移并写入内置标签集；worker 首次启动下载向量模型（约 458 MB）；首次导入英文语料时下载 Stanza 英文模型（约 320 MB）。`GET /api/health`、`GET /agent/health` 可确认就绪；`/agent/health` 返回 `MODEL_NOT_CONFIGURED` 表示未配模型。

内置语料由管理员导入：`scripts/import_builtin.py tatoeba | ud | wiki`（见脚本帮助；导入完整 Tatoeba 需较长时间，可后台运行）。

## 五 升级

```bash
git pull
npm run web:build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

迁移随 api 启动自动执行；升级前先备份（第六节）。向量模型版本变更时知识库需重新向量化（文献页"重新导入"或后台任务）。

## 六 备份与恢复

脚本：`scripts/backup.sh`、`scripts/restore.sh`。在仓库根目录用 Bash 执行（Windows 用 Git Bash）。

### 备份内容

| 内容 | 来源 | 文件 | 默认 |
| --- | --- | --- | --- |
| 数据库 | `pg_dump -Fc`（经 `docker compose exec postgres`） | `db.dump` | 备份 |
| 语料文件、CWB 索引、导出文件、知识库文件 | 卷 `data` | `data.tar.gz` | 备份 |
| Pi 会话文件 | 卷 `agentdata` | `agentdata.tar.gz` | 备份 |
| 向量模型、Stanza 模型 | 卷 `models`、`stanza` | `models.tar.gz`、`stanza.tar.gz` | 加 `--with-models` 才备份；不备份时，worker 启动后重新下载 |

另写 `manifest.txt`（项目名、时间、卷、Alembic 版本）和 `SHA256SUMS`。备份含账号密码哈希与全部研究数据，按敏感数据保管。

### 备份

```bash
scripts/backup.sh                      # → tmp/backups/<时间戳>/
scripts/backup.sh /backup/corpus-1027  # 指定目录
scripts/backup.sh --with-models        # 连同模型缓存
scripts/backup.sh -p 项目名             # 非默认 Compose 项目名
```

服务运行时可直接备份。数据库是一致快照；卷中正在运行的导入、预标任务的文件可能不完整，宜在没有后台任务时执行。

### 恢复

```bash
scripts/restore.sh tmp/backups/<时间戳>
```

步骤：校验 SHA256 → 确认（`--yes` 跳过）→ 停止 api / worker / agent / web → 启动 postgres → 删除并重建 `corpus` 库后 `pg_restore` → 清空并解包备份中的各个卷 → `docker compose up -d` → 冒烟。

冒烟检查健康；设置 `SMOKE_EMAIL`、`SMOKE_PASSWORD` 后，还会登录并执行一次检索、读取一个标注层、执行一次知识库关键词检索。`SMOKE_QUERY` 设定检索词（默认 `the`）。密码只从环境变量读取，不写入文件。

恢复会清空目标项目的数据库和对应的数据卷。版本升级后恢复旧备份时，api 启动会执行 `alembic upgrade head`。

### 恢复演练（不影响运行中的环境）

用另一个 Compose 项目名和端口恢复，再删除：

```bash
scripts/backup.sh tmp/backups/drill
HTTP_PORT=18088 POSTGRES_PORT=25432 SMOKE_EMAIL=… SMOKE_PASSWORD=… \
  scripts/restore.sh -p corpus-restore --yes tmp/backups/drill
curl http://127.0.0.1:18088/api/health
HTTP_PORT=18088 POSTGRES_PORT=25432 docker compose -f deploy/compose.yaml -p corpus-restore down -v --rmi local
```

### 实测（2026-10-27，共享开发机，Docker Desktop / WSL2）

| 项目 | 结果 |
| --- | --- |
| 数据量 | 90 个账号、212 个语料库、20 984 句、32 114 条标注、192 个知识片段；卷 `data` 约 20 MB |
| 备份大小 | `db.dump` 5.5 MB，`data.tar.gz` 8.2 MB，`agentdata.tar.gz` 0.14 MB，合计 14 MB（不含模型；`models` 卷约 480 MB，`stanza` 卷约 920 MB） |
| 备份用时 | 7 秒 |
| 恢复用时 | 新项目首次恢复 31 秒（镜像已有缓存，含启动与冒烟）；覆盖已有项目 23 秒 |
| 校验 | 恢复库与源库 7 张主要表行数一致；检索命中数一致（1 / 1）；词性层句子读取、知识库关键词检索正常；原环境健康检查不受影响 |

## 七 常见故障

| 现象 | 原因与处理 |
| --- | --- |
| web 启动失败，端口占用 | 改 `HTTP_PORT` 并同步 `PUBLIC_ORIGIN` |
| 登录或写操作 403 `ORIGIN_REJECTED` | `PUBLIC_ORIGIN` 与浏览器地址不一致（含协议、端口、localhost 与 127.0.0.1 之别） |
| 助手提示"尚未配置模型" | `.env` 缺 MODEL_*；修改后 `up -d agent worker` |
| 助手报 MODEL_AUTH_FAILED / RATE_LIMITED / TIMEOUT | 模型服务密钥、限额或网络；agent 日志有细节 |
| 知识库检索提示向量未就绪 | worker 尚未下载完模型或 `models` 卷不可写；看 worker 日志 |
| 网页导入返回 403 / 失败 | 目标站点拒绝容器访问（如维基百科）；改用文件导入 |
| 导入很慢 | Stanza 英文解析与中文依存为 CPU 密集；大语料用管理员脚本后台导入 |
| api 刚启动时 503 | 迁移执行中或数据库未就绪，等待健康检查 |
