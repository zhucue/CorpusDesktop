# 部署手册

单机 Docker Compose 部署。配置见 `deploy/compose.yaml`、`deploy/.env.example`。

## 一 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux x86_64（Windows / macOS 的 Docker Desktop 可用于开发） |
| Docker | Engine 24+ 与 Compose v2 |
| 资源 | 4 CPU、16 GiB 内存起（api 与 worker 各加载向量模型约 500 MB；Stanza 英文约 1 GiB）；磁盘：镜像约 8 GiB，模型缓存约 1.5 GiB，语料与索引按数据量（完整 Tatoeba 中英约 2 GiB） |
| 网络 | 首次启动需访问 Hugging Face（向量模型）、Stanza 模型源、对话模型服务；离线部署先在联网机器拉取 `models`、`stanza` 卷内容（第四节） |
| 域名与证书 | 对外访问需域名和 HTTPS，由宿主机 Caddy 或 nginx 终止（第五节） |

## 二 服务

| 服务 | 镜像 | 端口 | 卷 |
| --- | --- | --- | --- |
| postgres | pgvector/pgvector:pg16 | 127.0.0.1:${POSTGRES_PORT} | postgres |
| api | deploy/Dockerfile.api | 内部 8000 | data、models、stanza |
| worker | deploy/Dockerfile.worker | — | data、models、stanza；处理全部任务，先取短任务；`--scale worker=N` 可加导入容量 |
| worker-light | 同 worker | — | 只处理短任务（导出、统计、预标、知识库，以及小文件导入和小语料建索引），不被大导入阻塞；见下方队列规则 |
| agent | deploy/Dockerfile.agent | 内部 8700 | agentdata |
| web | deploy/Dockerfile.web（nginx） | 127.0.0.1:${HTTP_PORT} | — |
| test | api 镜像 | — | 同 api |

队列规则：

| 道 | 任务 | 由谁处理 |
| --- | --- | --- |
| 短任务 | 统计、导出、预标注、知识库任务；上传总大小小于 `LIGHT_IMPORT_BYTES`（默认 5 MB）的导入；语料词数小于 `LIGHT_INDEX_TOKENS`（默认 100 万）的建索引 | worker-light（`WORKER_SMALL_IMPORTS=1`），worker 空闲时也处理 |
| 长任务 | 其余导入与建索引；没有记录大小的旧任务和管理员脚本任务 | worker |

每个 worker 先取短任务，再按创建时间取长任务；同一语料同时只运行一个建索引任务。排队中的任务在任务页和托盘显示"前面还有 n 个任务"（同一道中正在运行的和更早排队的）。导入大小记在任务参数 `bytes`，建索引的语料词数记在 `tokens`。worker-light 处理英文小文件导入时会加载 Stanza 英文模型（约 1 GiB 内存）。

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
| LIGHT_IMPORT_BYTES、LIGHT_INDEX_TOKENS | 短任务门槛，默认 5242880 字节、1000000 词（见第二节队列规则）；api 与 worker 读同一值 |

密钥只放在 `deploy/.env`，不入库、不放 `tmp/`。

## 四 首次启动

```bash
cp deploy/.env.example deploy/.env           # 填 POSTGRES_PASSWORD、PUBLIC_ORIGIN、MODEL_*
npm ci --prefix apps/web && npm run web:build  # web 镜像打包 apps/web/dist
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python scripts/create_account.py --email admin@example.edu --admin
```

api 启动时执行 Alembic 迁移并写入内置标签集；worker 首次启动下载向量模型（约 458 MB）；首次导入英文语料时下载 Stanza 英文模型（约 320 MB）。`GET /api/health`、`GET /agent/health` 可确认就绪；`/agent/health` 返回 `MODEL_NOT_CONFIGURED` 表示未配模型。

### 预先填充模型卷

验收实测向量模型下载 19 分钟、Stanza 英文 22 分钟，且 Stanza 首次下载连接中断导致导入失败。开放给用户前先填好 `models`、`stanza` 卷：

```bash
C="docker compose --env-file deploy/.env -f deploy/compose.yaml"
$C logs -f worker | grep -m1 "embedding model"   # 出现 "embedding model … ready in … s" 即向量模型就绪
$C exec worker python -c "from engine import nlp; nlp.pipeline('en'); nlp._zh_depparse()"   # Stanza 英文与中文依存；中断时重跑
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
| 登录限流 | `POST /api/auth/login` 每个客户端 IP 每分钟 10 次，可突发 5 次；超出返回 429 `LOGIN_RATE_LIMITED`（"登录尝试过多，请 1 分钟后再试"） | `deploy/nginx.conf` |
| 真实 IP | 来自 127.0.0.1 与私网段（10/8、172.16/12、192.168/16）的请求取 `X-Forwarded-For` 最后一个地址 | `deploy/nginx.conf` |
| 接口文档 | `/api/docs`、`/api/openapi.json` 在 nginx 返回 404 | `deploy/nginx.conf` |

nginx 把 `/api/` 反代到 api、`/agent/` 反代到 agent（SSE：关闭缓冲，600 秒超时），`index.html` 不缓存。

## 七 升级

```bash
git pull
npm run web:build
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

迁移随 api 启动自动执行；升级前先备份（第八节）。向量模型版本变更时知识库需重新向量化（文献页"重新导入"或后台任务）。

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
| api 刚启动时 503 | 迁移执行中或数据库未就绪，等待健康检查 |

## 十 上线检查清单

| 项目 | 检查 |
| --- | --- |
| `.env` | `POSTGRES_PASSWORD` 为强密码；`MODEL_*` 已填；文件不入库 |
| HTTPS | 宿主反代已配证书，http 跳转 https；防火墙只开 80、443 |
| PUBLIC_ORIGIN | 只含 `https://域名`，没有 http 地址 |
| 管理员账号 | `create_account.py --admin` 已建，密码已妥善保管 |
| 模型卷 | worker 日志有 `embedding model … ready`；Stanza 英文与中文依存已下载 |
| 备份 cron | 已配置，手动跑过一次 `scripts/backup.sh` 且恢复演练通过 |
| 健康检查 | `https://域名/api/health` 正常；`/agent/health` 不是 `MODEL_NOT_CONFIGURED`；`/api/docs` 返回 404 |
