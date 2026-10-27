#!/usr/bin/env bash
# 备份 PostgreSQL（pg_dump 自定义格式）与数据卷 data、agentdata；--with-models 另备 models、stanza。
#   scripts/backup.sh [-p 项目名] [--with-models] [输出目录]
# 默认项目名 corpus（compose.yaml 的 name），输出到 tmp/backups/<时间戳>/。
# 运行中即可备份：数据库为一致快照；卷内正在写入的任务文件可能不完整，建议在无导入、预标任务时执行。
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'   # Git Bash：不改写容器内路径

cd "$(dirname "$0")/.."
PROJECT=${COMPOSE_PROJECT_NAME:-corpus}
VOLUMES=(data agentdata)
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -p) PROJECT=$2; shift 2 ;;
    --with-models) VOLUMES+=(models stanza); shift ;;
    -h|--help) sed -n 2,5p "$0"; exit 0 ;;
    *) OUT=$1; shift ;;
  esac
done
OUT=${OUT:-tmp/backups/$(date +%Y%m%d-%H%M%S)}
COMPOSE=(docker compose -f deploy/compose.yaml -p "$PROJECT")
HELPER=pgvector/pgvector:pg16   # 已随 postgres 拉取，自带 tar / gzip
mkdir -p "$OUT"
start=$(date +%s)

echo "数据库 → $OUT/db.dump"
"${COMPOSE[@]}" exec -T postgres pg_dump -U corpus -d corpus -Fc > "$OUT/db.dump"

for v in "${VOLUMES[@]}"; do
  name="${PROJECT}_$v"
  docker volume inspect "$name" > /dev/null
  echo "卷 $name → $OUT/$v.tar.gz"
  docker run --rm -v "$name:/v:ro" --entrypoint tar "$HELPER" czf - --numeric-owner -C /v . > "$OUT/$v.tar.gz"
done

{
  echo "project=$PROJECT"
  echo "created=$(date -Iseconds)"
  echo "volumes=${VOLUMES[*]}"
  echo "alembic=$("${COMPOSE[@]}" exec -T postgres psql -U corpus -d corpus -Atc 'SELECT version_num FROM alembic_version')"
} > "$OUT/manifest.txt"
(cd "$OUT" && sha256sum db.dump ./*.tar.gz > SHA256SUMS)

echo "完成：$OUT（$(du -sh "$OUT" | cut -f1)，$(( $(date +%s) - start )) 秒）"
ls -l "$OUT"
