# 部署手册

单机 Docker Compose 部署。配置见 `deploy/compose.yaml`、`deploy/.env.example`。

## 一 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux x86_64（Windows / macOS 的 Docker Desktop 可用于开发） |
| Docker | Engine 24+ 与 Compose v2 |
| 资源 | 4 CPU、16 GiB 内存起（api、worker、worker-light 各加载向量模型，常驻约 800 MB；Stanza 英文标注时每个正在导入的 worker 峰值约 2 GiB；每多保留一种语言管线约多 330 MB，见第四节"语言模型"）；磁盘：镜像约 8 GiB，模型缓存约 1.5 GiB（每多一种 Stanza 语言约 315–340 MB），语料与索引按数据量（完整 Tatoeba 中英约 2 GiB），语义索引每句约 3.5 KB |
| 小内存（≤ 4 GiB） | 只跑一个 worker：`docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --scale worker-light=0`；或设 `EMBED_PROVIDER=openai`，不在三个容器各加载一份本地向量模型；并设 `STANZA_MAX_PIPELINES=1`。都不做时导入会被内核 OOM 终止 |
| 网络 | 首次启动需访问 Hugging Face（向量模型）、Stanza 模型源、对话模型服务；向量模型已在 `models` 卷缓存时离线加载，缓存缺失才联网下载；离线部署先在联网机器拉取 `models`、`stanza` 卷内容（第四节） |
| 域名与证书 | 对外访问需域名和 HTTPS，由宿主机 Caddy 或 nginx 终止（第五节） |

## 二 服务

| 服务 | 镜像 | 端口 | 卷 |
| --- | --- | --- | --- |
| postgres | pgvector/pgvector:pg16 | 127.0.0.1:${POSTGRES_PORT} | postgres |
| api | deploy/Dockerfile.api | 内部 8000 | data、models；宿主机 `BACKUP_DIR` 只读挂载到 `/backups` |
| worker | deploy/Dockerfile.worker | — | data、models、stanza；处理全部任务，先取短任务；`--scale worker=N` 可加导入容量 |
| worker-light | 同 worker | — | 只处理短任务（导出、统计、预标、知识库，以及小文件导入和小语料建索引），不被大导入阻塞；见下方队列规则；另执行每日维护（第六节） |
| agent | deploy/Dockerfile.agent | 内部 8700 | agentdata |
| web | deploy/Dockerfile.web（nginx） | 127.0.0.1:${HTTP_PORT} | — |
| test | api 镜像 | — | 同 api |

队列规则：

| 道 | 任务 | 由谁处理 |
| --- | --- | --- |
| 短任务 | 统计、导出、预标注、知识库任务；上传总大小小于 `LIGHT_IMPORT_BYTES`（默认 5 MB）的导入；语料词数小于 `LIGHT_INDEX_TOKENS`（默认 100 万）的建索引 | worker-light（`WORKER_SMALL_IMPORTS=1`），worker 空闲时也处理 |
| 长任务 | 其余导入与建索引；没有记录大小的旧任务和管理员脚本任务 | worker |

每个 worker 先取短任务，再按创建时间取长任务；同一语料同时只运行一个建索引任务。排队中的任务在任务页和托盘显示"前面还有 n 个任务"（同一道中正在运行的和更早排队的）。导入大小记在任务参数 `bytes`，建索引的语料词数记在 `tokens`。worker-light 处理英文小文件导入时会加载 Stanza 英文模型，标注时内存峰值约 2 GiB。

## 三 `.env` 变量

| 变量 | 说明 |
| --- | --- |
| POSTGRES_PASSWORD | 必填 |
| POSTGRES_PORT、HTTP_PORT | 宿主端口，默认 15432、8080；端口被占用时同时改 HTTP_PORT 与 PUBLIC_ORIGIN |
| PUBLIC_ORIGIN | 浏览器访问地址，逗号分隔多个；非 GET 请求的 Origin 须匹配（api 与 agent 都校验） |
| MODEL_BASE_URL、MODEL_API_KEY、MODEL_ID、MODEL_API | 对话模型（OpenAI 兼容；`MODEL_API` 为 `openai-completions` 或 `openai-responses`）。未配置时助手与依赖模型的预标、摘要、抽取不可用，其余功能正常。api 只读 `MODEL_BASE_URL`、`MODEL_ID`，用于在设置页"数据与隐私"显示模型主机与模型名，不调用模型 |
| MODEL_CONTEXT_WINDOW、MODEL_MAX_TOKENS、MODEL_TIMEOUT_MS、MODEL_REASONING | 可选 |
| EMBED_PROVIDER、EMBED_MODEL、EMBED_BASE_URL、EMBED_API_KEY、EMBED_DIM | 向量模型；默认本地 `paraphrase-multilingual-MiniLM-L12-v2`（384 维），远程须 384 维 |
| MODELS_DIR、HF_HOME | 模型缓存目录（容器内 `/models`） |
| SEARCH_COUNT_TIMEOUT | 首次检索的同步超时秒数，默认 20；在此之内完成直接返回完整计数，超时后转后台完整计数，页面显示"计算中"并轮询 |
| SEARCH_FULL_TIMEOUT | 后台完整计数的超时秒数，默认 300；超时后页面显示"计数超时"，不再轮询。全进程同时最多 2 个后台计数 |
| SEARCH_MAX_HITS | 一次检索的命中上限，默认 2000000；超过时后台计数失败并提示命中过多 |
| SEARCH_CACHE_MAX_BYTES | 检索结果集（`DATA_DIR/search-cache/`）总字节上限，默认 2 GB；超出按最近最少使用淘汰；api 启动时清空该目录 |
| APP_VERSION | 版本号，设置页"数据与隐私"显示；留空为 `dev` |
| ALERT_WEBHOOK_URL | `scripts/healthcheck.sh` 失败时 POST `{"text": "..."}` 的地址；留空只打印并以非零退出（第六节） |
| STANZA_MAX_PIPELINES | 每个 worker 进程同时保留的 Stanza 语言管线数，默认 2（中文依存算一个）；超过时按最近使用淘汰并释放内存。小内存机器设 1 |
| SEMANTIC_MAX_SENTENCES | 一个语料（或所选语言）可建语义索引的句数上限，默认 300000；超过时建索引返回 422 `TOO_LARGE` |
| LIGHT_IMPORT_BYTES、LIGHT_INDEX_TOKENS | 短任务门槛，默认 5242880 字节、1000000 词（见第二节队列规则）；api 与 worker 读同一值 |
| TZ | 服务器时区，默认 `Asia/Shanghai`；api、worker、agent 共用，模型用量按此时区的自然月统计 |
| LLM_MONTHLY_TOKENS_PER_USER | 每位用户每月对话模型 token 上限，默认 0（不限）；达到后助手新消息、重新生成、确认执行，LLM 预标、文献摘要、术语抽取及其重试返回 429 `LLM_QUOTA_EXCEEDED`；api 与 agent 读同一值 |
| AGENT_MAX_RUNS_PER_USER | 每位用户同时运行的助手对话数，默认 2；超出返回 429 `TOO_MANY_RUNS` |
| PROJECT_PURGE_DAYS | 删除的项目可恢复天数，默认 7；之后由维护任务清除数据与文件 |
| EXPORT_RETENTION_DAYS | 导出文件与上传目录保留天数，默认 30；之后由维护任务删除，下载返回 410 `EXPORT_EXPIRED` |
| WORKER_MAINTENANCE | worker-light 是否执行每日维护，默认 1；worker 固定为 0。设 0 后不再自动清除项目与过期文件 |
| BACKUP_DIR | 宿主机备份目录（`scripts/backup.sh` 输出位置，绝对路径），默认仓库 `tmp/backups`；只读挂载到 api 的 `/backups`，管理 · 系统显示最近备份时间；`scripts/healthcheck.sh` 也读此变量 |

密钥只放在 `deploy/.env`，不入库、不放 `tmp/`。

## 四 首次启动

```bash
cp deploy/.env.example deploy/.env           # 填 POSTGRES_PASSWORD、PUBLIC_ORIGIN、MODEL_*
npm ci --prefix apps/web && npm run web:build  # web 镜像打包 apps/web/dist
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email admin@example.edu --admin
```

api 启动时执行 Alembic 迁移并写入内置标签集；worker 首次启动下载向量模型（约 458 MB）；首次导入某种语言（en、ja、fr、de、es、ru）或首次做中文依存预标时下载该语言的 Stanza 模型（每种约 315–340 MB）。`GET /api/health`（查询数据库，失败 503）、`GET /agent/health` 可确认就绪；`/agent/health` 返回 `MODEL_NOT_CONFIGURED` 表示未配模型。

### 预先填充模型卷

验收实测向量模型下载 19 分钟、Stanza 英文 22 分钟，且 Stanza 首次下载连接中断导致导入失败。开放给用户前先填好 `models`、`stanza` 卷：

```bash
C="docker compose --env-file deploy/.env -f deploy/compose.yaml"
$C logs -f worker | grep -m1 "embedding model"   # 出现 "embedding model … ready in … s" 即向量模型就绪
$C exec worker python -c "from engine import nlp; nlp.pipeline('en'); nlp._zh_depparse()"   # Stanza 英文与中文依存；中断时重跑
$C exec worker python -c "from engine import nlp; [nlp.pipeline(l) for l in ('ja', 'fr', 'de', 'es', 'ru')]"   # 按需预加载其他语言
```

服务器不能联网或下载太慢时，从联网机器拷贝：

```bash
# 联网机器（已跑过上面两步）
scripts/backup.sh --with-models /backup/models-src   # 取其中 models.tar.gz、stanza.tar.gz
# 服务器：先建卷，再解包
docker compose --env-file deploy/.env -f deploy/compose.yaml up --no-start
for v in models stanza; do
  docker run --rm -i -v corpus_$v:/v --entrypoint tar pgvector/pgvector:pg16 xzf - --numeric-owner -C /v < $v.tar.gz
done
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
```

不要用 `scripts/restore.sh` 只为恢复模型：它会清空并替换目标数据库。

### 语言模型

自动标注支持 zh、en、ja、fr、de、es、ru。中文分词词性用 jieba（随镜像），其他语言与中文依存用 Stanza，模型首次用到时下载到 `stanza` 卷。

| 项 | 数值（实测 2026-11-06） |
| --- | --- |
| 磁盘 | 每种语言约 315–340 MB |
| 内存 | 每个已加载的语言管线约 330 MB；worker 进程最多保留 `STANZA_MAX_PIPELINES` 个（默认 2），按最近使用淘汰 |
| 内存峰值 | 一批同时导入 fr、de、ja：管线数 1 / 2 / 3 时 worker 峰值约 1.15 / 1.52 / 1.84 GB |
| 首次下载 | 每种约 5 分钟；任务进度显示"下载 fr 模型"，失败时导入失败 `MODEL_UNAVAILABLE`，重试即可 |

下载前只刷新该语言在 `resources.json` 中的条目，已下载的其他语言不重下；多个容器共用 `stanza` 卷时用文件锁与唯一临时文件，不会互相覆盖。离线或慢网环境用上一节命令预加载需要的语言，再按上一节方法拷贝 `stanza` 卷。

### 语义索引

语料语义检索须先在语料详情建语义索引（任务 `embed_corpus`，长任务道，由 worker 执行，可取消）。使用与知识库相同的向量模型，每批 512 句。

| 项 | 数值（Tatoeba 中英第 1 批，16 核，本地 MiniLM） |
| --- | --- |
| 速度 | 约 250–280 句 / 秒 |
| 只建中文侧 | 45,703 句，约 3–5 分钟，约 160 MB |
| 整库 | 中文 45,703 句 + 英文 220,395 句，约 20–25 分钟，约 0.9 GB |
| 磁盘估算 | 每句约 3.5 KB（向量与 HNSW 索引，在 `postgres` 卷） |

句数上限 `SEMANTIC_MAX_SENTENCES`（默认 300,000）。更换向量模型（`EMBED_MODEL` / `EMBED_PROVIDER`）后语义索引显示"向量模型已更换"，须重建。

### 内置语料

内置语料由管理员在宿主机用 uv 导入（服务器需安装 uv），脚本经网页入口调用接口：

```bash
export CORPUS_EMAIL=admin@example.edu CORPUS_PASSWORD=…
uv run python scripts/import_builtin.py tatoeba --base https://corpus.example.edu
uv run python scripts/import_builtin.py ud --treebank en_ewt --base https://corpus.example.edu
uv run --with mwparserfromhell --with opencc-python-reimplemented \
  python scripts/import_builtin.py wiki --lang zh --n 1000 --base https://corpus.example.edu
```

请求的 Origin 等于 `--base`，须在 `PUBLIC_ORIGIN` 中；`--base` 默认 `http://127.0.0.1:8088`，生产环境必须传 `https://域名`。不要为脚本往 `PUBLIC_ORIGIN` 加 http 地址：只有全部 origin 都是 https 时登录 cookie 才带 Secure。导入完整 Tatoeba 需较长时间，可后台运行；其余参数见脚本帮助。

## 五 HTTPS 与对外访问

web 只监听 `127.0.0.1:${HTTP_PORT}`，由宿主机反代终止 HTTPS。反代要求：

| 项目 | 要求 |
| --- | --- |
| 转发头 | `Host`、`X-Forwarded-For`、`X-Forwarded-Proto`；容器内登录限流按 `X-Forwarded-For` 的最后一个地址区分客户端 |
| `/agent/` | 关闭缓冲，读超时不少于 600 秒（SSE） |
| 上传 | 请求体上限不小于 500 MB |
| `.env` | `PUBLIC_ORIGIN=https://corpus.example.edu`；全部 origin 为 https 时登录 cookie 自动加 Secure；修改后 `up -d` |
| 防火墙 | 只开放 80、443（和 SSH）；Postgres 与 web 端口只绑定 127.0.0.1 |

Caddy（自动申请和续期证书；默认转发上述请求头、不限请求体、无读超时）：

```text
corpus.example.edu {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

nginx + certbot：先只启用 80 段执行 `certbot certonly --nginx -d corpus.example.edu`，再加 443 段并 `nginx -s reload`；certbot 自带续期定时任务。

```nginx
server {
    listen 80;
    server_name corpus.example.edu;
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    http2 on;
    server_name corpus.example.edu;
    ssl_certificate     /etc/letsencrypt/live/corpus.example.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/corpus.example.edu/privkey.pem;
    client_max_body_size 500m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }

    location /agent/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

## 六 运维配置

| 项目 | 配置 | 位置 |
| --- | --- | --- |
| 自动重启 | postgres、api、worker、worker-light、agent、web 为 `restart: unless-stopped`；手动 `stop` 后不自动拉起 | `deploy/compose.yaml` |
| 日志上限 | json-file，单文件 20 MB，每容器保留 5 个 | `deploy/compose.yaml` |
| 登录限流 | `POST /api/auth/login` 与 `POST /api/auth/password`（修改密码）共用一个限流区：每个客户端 IP 每分钟 10 次，可突发 5 次；超出返回 429 `LOGIN_RATE_LIMITED`（"登录尝试过多，请 1 分钟后再试"） | `deploy/nginx.conf` |
| 容器健康检查 | api 请求 `/api/health`（含数据库）；worker、worker-light 检查 `/data/worker-health/<WORKER_ID>` 在 90 秒内更新过（每轮主循环与任务心跳更新），每 30 秒一次，启动宽限 60 秒 | `deploy/compose.yaml` |
| 真实 IP | 来自 127.0.0.1 与私网段（10/8、172.16/12、192.168/16）的请求取 `X-Forwarded-For` 最后一个地址 | `deploy/nginx.conf` |
| 接口文档 | `/api/docs`、`/api/openapi.json` 在 nginx 返回 404 | `deploy/nginx.conf` |
| 安全响应头 | 页面与接口都带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: same-origin`、`Permissions-Policy: camera=(), microphone=(), geolocation=()`（`always`，错误响应也带；`/index.html` 单独重复一遍）；不加 CSP | `deploy/nginx.conf` |
| 每日维护 | 见下方“维护任务” | worker-light |
| 模型用量上限 | `LLM_MONTHLY_TOKENS_PER_USER`、`AGENT_MAX_RUNS_PER_USER`；用量在设置 › 管理 › 用量按用户 / 项目、月份查看 | `deploy/.env` |

nginx 把 `/api/` 反代到 api、`/agent/` 反代到 agent（SSE：关闭缓冲，600 秒超时），`index.html` 不缓存。

### 维护任务

worker-light 启动时与之后每小时检查 `/data/maintenance/last-run`，距上次运行超过 24 小时即执行一次：

| 步骤 | 内容 |
| --- | --- |
| 清除项目 | 删除超过 `PROJECT_PURGE_DAYS` 天的已删除项目：数据库记录级联删除，语料、索引、知识库、上传与导出文件一并删除；记审计 `project_purge` |
| 过期导出 | 删除 `EXPORT_RETENTION_DAYS` 天前成功完成的导出文件；之后下载提示“导出文件已过期，请重新导出” |
| 上传目录 | 引用同一上传目录的任务全部结束、其中有失败或取消的，且最晚结束时间早于 `EXPORT_RETENTION_DAYS` 天前时删除该目录（之后这些任务不能再重试） |

每次运行在 worker-light 日志写一行 `maintenance: purged N projects, removed N export files and N upload folders`；某步失败记 `failed:`，其他步骤照常，次日重试。要立即执行：删除数据卷中的 `maintenance/last-run` 后重启 worker-light。

### 账号管理

| 操作 | 网页（设置 › 管理 › 用户，仅平台管理员） | 命令行 |
| --- | --- | --- |
| 新建账号 | "新建"：邮箱、姓名、是否管理员；弹窗显示一次 16 位临时密码 | `create_account.py --email … [--name …] [--admin]` |
| 重置密码 | "重置密码"：显示一次临时密码，该用户全部会话与助手令牌失效 | `create_account.py --email … --reset`（不带 `--password-stdin` 时生成临时密码并打印） |
| 停用 / 启用 | 停用后登录返回"账号已停用，请联系管理员"，已登录的会话下一次请求失效 | — |
| 设 / 撤管理员 | 不能停用自己；不能停用或撤销最后一个可用管理员 | `--admin` 只在新建时生效 |

临时密码登录后必须先修改密码（12–1024 字符），之前其他接口返回 403 `PASSWORD_CHANGE_REQUIRED`。管理员忘记密码时在服务器上执行：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email admin@example.edu --reset
```

### 运行状态检查

`scripts/healthcheck.sh` 在宿主机检查：`/api/health`、api / worker / worker-light 容器健康状态、数据盘剩余空间低于 10%、最近一次备份超过 26 小时。任一项失败时，若设置了 `ALERT_WEBHOOK_URL`（环境变量或 `deploy/.env`）则 POST `{"text": "..."}` 到该地址，退出码 1。可选环境变量：`HEALTH_URL`、`DATA_PATH`（检查剩余空间的目录，默认 Docker 数据目录）、`BACKUP_DIR`（默认 `tmp/backups`，与定时备份目录不同时须设置）、`BACKUP_MAX_HOURS`、`DISK_MIN_FREE`；非默认 Compose 项目名用 `-p`。

管理员也可在设置 › 管理 › 系统查看各 worker 最近上报与健康、数据盘剩余、数据目录与检索缓存大小、最近备份时间（`BACKUP_DIR` 未挂载或为空时写“未找到”）。

cron 每 5 分钟执行：

```text
*/5 * * * * cd /opt/CorpusDesktop && BACKUP_DIR=/backup/corpus scripts/healthcheck.sh >> /var/log/corpus-health.log 2>&1
```

## 七 升级

```bash
git pull
npm run web:build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

迁移随 api 启动自动执行；升级前先备份（第八节）。从 2026 年 11 月 5 日之前的版本升级会执行迁移 `0008_account_lifecycle`（`users` 加 `disabled_at`、`must_change_password`、`last_login_at`），先 `up -d api` 等健康后再启动 worker；升级后设置 `APP_VERSION`，按需配置 `ALERT_WEBHOOK_URL` 与第六节的健康检查 cron。从 2026 年 11 月 6 日之前的版本升级会执行迁移 `0010_operations`（新表 `llm_usage`、`audit_logs`、`feedback`，`projects` 加 `deleted_at`），同样先 `up -d api` 等健康后再启动 worker 与 agent；按需在 `.env` 设置 `LLM_MONTHLY_TOKENS_PER_USER`、`BACKUP_DIR`、`TZ`。

从 P10 之前的版本升级会执行两个迁移，同样先 `up -d api` 等健康后再启动 worker 与 agent：

| 迁移 | 内容 | 耗时 |
| --- | --- | --- |
| `0011` | 新表 `sentence_embeddings`（384 维，HNSW）；`corpora.semantic`；`documents.content_hash` 及索引，任务类型加 `embed_corpus` | 补算存量文档的 `content_hash` 时逐篇读取正文文件，耗时随文档数与正文总量增长；文档多的库升级前预留时间，api 在迁移完成前健康检查不通过 |
| `0012` | 新表 `vocab_lists`、`vocab_entries`；内置 NGSL 词表首次使用时写入 | 秒级 |

升级后按需在 `.env` 设置 `STANZA_MAX_PIPELINES`、`SEMANTIC_MAX_SENTENCES`；已有语料不会自动建语义索引。向量模型版本变更时知识库需重新向量化（文献页"重新导入"或后台任务），已建的语义索引须在语料详情重建。

## 八 备份与恢复

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

### 定时备份

`crontab -e`（仓库在 `/opt/CorpusDesktop`，每天 03:00 备份到 `/backup/corpus/日期`，删除 14 天前的备份；crontab 中 `%` 须写成 `\%`）：

```text
0 3 * * * cd /opt/CorpusDesktop && bash scripts/backup.sh /backup/corpus/$(date +\%Y\%m\%d) >> /var/log/corpus-backup.log 2>&1 && find /backup/corpus -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

cron 用户须能执行 docker；`/backup` 宜在另一块磁盘或定期同步到异地。

### 恢复

```bash
scripts/restore.sh tmp/backups/<时间戳>
```

步骤：校验 SHA256 → 确认（`--yes` 跳过）→ 停止 api / worker / worker-light / agent / web → 启动 postgres → 删除并重建 `corpus` 库后 `pg_restore` → 清空并解包备份中的各个卷 → `docker compose up -d` → 冒烟。

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

## 九 常见故障

| 现象 | 原因与处理 |
| --- | --- |
| web 启动失败，端口占用 | 改 `HTTP_PORT` 并同步 `PUBLIC_ORIGIN` |
| 登录或写操作 403 `ORIGIN_REJECTED` | `PUBLIC_ORIGIN` 与浏览器地址不一致（含协议、端口、localhost 与 127.0.0.1 之别） |
| 启用 HTTPS 后 403 `ORIGIN_REJECTED` | `PUBLIC_ORIGIN` 仍是 http 地址；改为 `https://域名` 后 `up -d` |
| 所有人登录都返回 429 | 宿主反代未传 `X-Forwarded-For`，或反代与 web 之间的地址不在 `set_real_ip_from` 范围，所有请求共用一个限流桶；web 日志 `limiting requests` 行的 `client` 应为用户真实 IP |
| 导入内置语料脚本 403 | `--base` 与 `PUBLIC_ORIGIN` 不一致；生产环境用 `--base https://域名` |
| 助手提示"尚未配置模型" | `.env` 缺 MODEL_*；修改后 `up -d agent worker` |
| 助手报 MODEL_AUTH_FAILED / RATE_LIMITED / TIMEOUT | 模型服务密钥、限额或网络；agent 日志有细节 |
| 知识库检索提示向量未就绪 | worker 尚未下载完模型或 `models` 卷不可写；看 worker 日志 |
| 网页导入返回 403 / 失败 | 目标站点拒绝容器访问（如维基百科）；改用文件导入 |
| 导入很慢 | Stanza 英文解析与中文依存为 CPU 密集；大语料用管理员脚本后台导入；小于 5 MB 的导入与短任务由 worker-light 处理，不排在大导入后面；需要更多导入并发时 `--scale worker=2` |
| 内置语料追加导入期间 | 语料保持可检索并显示"更新中"，旧索引继续服务，新索引建好后替换 |
| 升级后 worker 报错 | 新镜像需要最新迁移，先 `up -d api` 再启动 worker |
| 导入失败 `MODEL_UNAVAILABLE`"下载 fr 模型失败" | Stanza 模型源不可达或下载中断；重试导入，或按第四节预加载、拷贝 `stanza` 卷 |
| 多语言导入时 worker 被 OOM 终止 | 降低 `STANZA_MAX_PIPELINES`（小内存设 1），或减少同时导入的语言 |
| 建语义索引 422 `TOO_LARGE` | 句数超过 `SEMANTIC_MAX_SENTENCES`；只建一种语言、拆分语料，或调高上限（磁盘每句约 3.5 KB） |
| 语义检索 503 `EMBED_UNAVAILABLE` | 向量模型未就绪；看 worker 与 api 日志中的 `embedding model` |
| api 刚启动时 503 | 迁移执行中或数据库未就绪，等待健康检查 |

## 十 上线检查清单

| 项目 | 检查 |
| --- | --- |
| `.env` | `POSTGRES_PASSWORD` 为强密码；`MODEL_*` 已填；文件不入库；`chmod 600 deploy/.env` |
| 模型费用 | 在模型服务商侧设消费上限；`.env` 设置 `LLM_MONTHLY_TOKENS_PER_USER`（每人月度模型用量上限，默认不限） |
| HTTPS | 宿主反代已配证书，http 跳转 https；防火墙只开 80、443 |
| PUBLIC_ORIGIN | 只含 `https://域名`，没有 http 地址 |
| 管理员账号 | `create_account.py --admin` 已建，密码已妥善保管；其他用户在设置 › 管理 › 用户中新建 |
| 模型卷 | worker 日志有 `embedding model … ready`；Stanza 英文与中文依存已下载，计划使用的其他语言（ja、fr、de、es、ru）已预加载 |
| 备份 cron | 已配置，手动跑过一次 `scripts/backup.sh` 且恢复演练通过；备份复制到另一台机器 |
| 健康检查 | `https://域名/api/health` 正常；`docker compose ps` 中 api、worker、worker-light 为 healthy；`/agent/health` 不是 `MODEL_NOT_CONFIGURED`；`/api/docs` 返回 404；`curl -I https://域名/` 可见四个安全响应头；设置 › 管理 › 系统显示最近备份时间 |
| 告警 | `scripts/healthcheck.sh` 手动执行通过，cron 每 5 分钟执行；`ALERT_WEBHOOK_URL` 已设并收到过一次测试告警 |
