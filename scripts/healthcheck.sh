#!/usr/bin/env bash
# 运行状态检查：/api/health、api / worker / worker-light 容器健康、数据盘剩余空间、最近备份时间。
#   scripts/healthcheck.sh [-p 项目名]
# 任一项失败：设置了 ALERT_WEBHOOK_URL（环境变量或 deploy/.env）时 POST {"text": "..."} 到该地址；退出码 1。
# 用 cron 每 5 分钟执行：
#   */5 * * * * cd /srv/CorpusDesktop && scripts/healthcheck.sh >> tmp/healthcheck.log 2>&1
# 可选环境变量：HEALTH_URL（默认 http://127.0.0.1:$HTTP_PORT/api/health）、DATA_PATH（检查剩余空间的目录，
# 默认 Docker 数据目录）、BACKUP_DIR（默认 tmp/backups）、BACKUP_MAX_HOURS（默认 26）、DISK_MIN_FREE（默认 10，百分比）。
set -uo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

cd "$(dirname "$0")/.."
PROJECT=${COMPOSE_PROJECT_NAME:-corpus}
while [ $# -gt 0 ]; do
  case "$1" in
    -p) PROJECT=$2; shift 2 ;;
    -h|--help) sed -n 2,8p "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

env_value() {  # deploy/.env 中的值（环境变量优先）
  local name=$1
  if [ -n "${!name:-}" ]; then printf '%s' "${!name}"; return; fi
  [ -f deploy/.env ] && sed -n "s/^$name=//p" deploy/.env | tail -n 1 | tr -d '\r'
}

COMPOSE=(docker compose -f deploy/compose.yaml -p "$PROJECT")
HTTP_PORT=$(env_value HTTP_PORT); HTTP_PORT=${HTTP_PORT:-8080}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:$HTTP_PORT/api/health}
BACKUP_DIR=${BACKUP_DIR:-tmp/backups}
BACKUP_MAX_HOURS=${BACKUP_MAX_HOURS:-26}
DISK_MIN_FREE=${DISK_MIN_FREE:-10}
WEBHOOK=$(env_value ALERT_WEBHOOK_URL)
failures=()

# 1 接口与数据库
if ! body=$(curl -fsS --max-time 10 "$HEALTH_URL" 2>&1); then
  failures+=("接口健康检查失败：$HEALTH_URL $body")
fi

# 2 容器健康状态（worker 扩容时逐个检查）
for service in api worker worker-light; do
  ids=$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null)
  if [ -z "$ids" ]; then
    failures+=("容器未运行：$service")
    continue
  fi
  for id in $ids; do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null)
    [ "$status" = healthy ] || failures+=("容器不健康：$service ${id:0:12} $status")
  done
done

# 3 数据盘剩余空间
DATA_PATH=${DATA_PATH:-$(docker info -f '{{.DockerRootDir}}' 2>/dev/null)}
if [ -n "$DATA_PATH" ] && used=$(df -P "$DATA_PATH" 2>/dev/null | awk 'NR == 2 { sub("%", "", $5); print $5 }') && [ -n "$used" ]; then
  free=$((100 - used))
  [ "$free" -ge "$DISK_MIN_FREE" ] || failures+=("数据盘剩余 ${free}%（$DATA_PATH），低于 ${DISK_MIN_FREE}%")
else
  failures+=("无法读取数据盘空间：${DATA_PATH:-未知目录}")
fi

# 4 最近备份
latest=$(ls -1t "$BACKUP_DIR"/*/db.dump 2>/dev/null | head -n 1)
if [ -z "$latest" ]; then
  failures+=("没有找到备份：$BACKUP_DIR/*/db.dump")
else
  age=$(( ($(date +%s) - $(date -r "$latest" +%s)) / 3600 ))
  [ "$age" -lt "$BACKUP_MAX_HOURS" ] || failures+=("最近备份已 ${age} 小时：$latest")
fi

if [ ${#failures[@]} -eq 0 ]; then
  echo "$(date -Iseconds) 正常"
  exit 0
fi

text="语料平台检查失败（$(hostname)，$(date -Iseconds)）"
for f in "${failures[@]}"; do text+=$'\n'"- $f"; done
echo "$text"
if [ -n "$WEBHOOK" ]; then
  bs='\'  # JSON 字符串转义；引号内的替换文本按字面处理（bash 5.2+ 不再解释其中的反斜杠）
  json=${text//"$bs"/"$bs$bs"}; json=${json//'"'/"$bs\""}
  json=${json//$'\t'/ }; json=${json//$'\r'/}; json=${json//$'\n'/"${bs}n"}
  curl -fsS --max-time 10 -H 'Content-Type: application/json' -d "{\"text\":\"$json\"}" "$WEBHOOK" > /dev/null \
    || echo "告警发送失败：$WEBHOOK" >&2
else
  echo "未设置 ALERT_WEBHOOK_URL，只打印" >&2
fi
exit 1
