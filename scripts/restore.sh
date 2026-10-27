#!/usr/bin/env bash
# 从 scripts/backup.sh 的备份目录恢复：停 api / worker / agent / web → 重建数据库并 pg_restore → 解包数据卷 → 启动 → 冒烟。
#   scripts/restore.sh [-p 项目名] [--yes] 备份目录
# 会清空目标项目的数据库与对应卷（data、agentdata，备份中含 models、stanza 时一并恢复）。
# 恢复到另一套环境演练：HTTP_PORT=18088 POSTGRES_PORT=25432 scripts/restore.sh -p corpus-restore --yes 备份目录
# 冒烟检查健康与登录后的检索、标注层读取、知识库检索；登录需环境变量 SMOKE_EMAIL、SMOKE_PASSWORD（不设则只查健康）。
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

cd "$(dirname "$0")/.."
PROJECT=${COMPOSE_PROJECT_NAME:-corpus}
YES=""
SRC=""
while [ $# -gt 0 ]; do
  case "$1" in
    -p) PROJECT=$2; shift 2 ;;
    --yes) YES=1; shift ;;
    -h|--help) sed -n 2,6p "$0"; exit 0 ;;
    *) SRC=$1; shift ;;
  esac
done
[ -n "$SRC" ] && [ -f "$SRC/db.dump" ] || { echo "用法：scripts/restore.sh [-p 项目名] [--yes] 备份目录（需含 db.dump）" >&2; exit 2; }
(cd "$SRC" && sha256sum -c --quiet SHA256SUMS)
if [ -z "$YES" ]; then
  read -r -p "将清空项目 $PROJECT 的数据库与数据卷并从 $SRC 恢复，输入 yes 继续：" answer
  [ "$answer" = yes ] || exit 1
fi
COMPOSE=(docker compose -f deploy/compose.yaml -p "$PROJECT")
HELPER=pgvector/pgvector:pg16
start=$(date +%s)

echo "停止 api / worker / agent / web"
"${COMPOSE[@]}" stop api worker agent web 2>/dev/null || true

echo "启动 postgres"
"${COMPOSE[@]}" up -d postgres
for _ in $(seq 60); do
  "${COMPOSE[@]}" exec -T postgres pg_isready -U corpus -d postgres -q && break
  sleep 2
done

echo "重建数据库并导入"
"${COMPOSE[@]}" exec -T postgres psql -U corpus -d postgres -v ON_ERROR_STOP=1 -q \
  -c 'DROP DATABASE IF EXISTS corpus WITH (FORCE)' -c 'CREATE DATABASE corpus OWNER corpus'
"${COMPOSE[@]}" exec -T postgres pg_restore -U corpus -d corpus --no-owner --exit-on-error < "$SRC/db.dump"

for archive in "$SRC"/*.tar.gz; do
  v=$(basename "$archive" .tar.gz)
  name="${PROJECT}_$v"
  if ! docker volume inspect "$name" > /dev/null 2>&1; then
    docker volume create --label "com.docker.compose.project=$PROJECT" \
      --label "com.docker.compose.volume=$v" "$name" > /dev/null
  fi
  echo "卷 $name ← $archive"
  docker run --rm -i -v "$name:/v" --entrypoint sh "$HELPER" \
    -c 'find /v -mindepth 1 -delete && tar xzf - --numeric-owner -C /v' < "$archive"
done

echo "启动全部服务"
"${COMPOSE[@]}" up -d
for _ in $(seq 120); do
  "${COMPOSE[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" \
    2> /dev/null && break
  sleep 3
done
echo "恢复用时 $(( $(date +%s) - start )) 秒，开始冒烟"

"${COMPOSE[@]}" exec -T -e SMOKE_EMAIL -e SMOKE_PASSWORD -e SMOKE_QUERY api python - <<'PY'
import http.cookiejar, json, os, urllib.request

base = "http://localhost:8000/api"
origin = os.environ["PUBLIC_ORIGIN"].split(",")[0].strip()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(method, path, body=None):
    req = urllib.request.Request(base + path, method=method, headers={"Origin": origin, "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with opener.open(req, timeout=120) as r:
        return json.loads(r.read() or b"null")


print("health", call("GET", "/health"))
email, password = os.environ.get("SMOKE_EMAIL"), os.environ.get("SMOKE_PASSWORD")
if not (email and password):
    print("未设置 SMOKE_EMAIL / SMOKE_PASSWORD，跳过登录后的检查")
    raise SystemExit(0)
call("POST", "/auth/login", {"email": email, "password": password})
projects = call("GET", "/projects?page_size=200")["items"]
corpora = [c for p in projects for c in call("GET", f"/corpora?project_id={p['id']}&page_size=200")["items"]]
corpora += call("GET", "/corpora?page_size=200")["items"]
ready = next(c for c in sorted(corpora, key=lambda c: c["project_id"] is None) if c["status"] == "ready")
res = call("POST", "/search", {"scope": {"corpus_id": ready["id"]}, "query": os.environ.get("SMOKE_QUERY") or "the"})
print(f"search {ready['name']}: hits={res['counts']['hits']} complete={res['counts']['complete']}")
layers = [l for p in projects for l in call("GET", f"/projects/{p['id']}/layers")["items"]]
if layers:
    layer = layers[0]
    read = {"span": "spans", "relation": "spans", "alignment": "alignments"}.get(layer["kind"], "sentences")
    page = call("GET", f"/layers/{layer['id']}/{read}?page_size=1")
    print(f"layer {layer['name']} ({layer['kind']}): {read} items={len(page['items'])}")
for p in projects:
    if call("GET", f"/projects/{p['id']}/kb/documents")["total"]:
        kb = call("POST", f"/projects/{p['id']}/kb/search", {"q": os.environ.get("SMOKE_QUERY") or "the", "mode": "keyword"})
        print(f"kb search {p['name']}: items={len(kb['items'])}")
        break
print("冒烟通过")
PY
echo "完成，总用时 $(( $(date +%s) - start )) 秒"
