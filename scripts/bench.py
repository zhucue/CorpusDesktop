"""Performance baseline against the running stack; writes doc/performance.md.

  uv run python scripts/bench.py [--corpus-name "Tatoeba 中英"] [--runs 5] [--out doc/performance.md]

Login: BENCH_EMAIL / BENCH_PASSWORD (falls back to CORPUS_EMAIL / CORPUS_PASSWORD), or --email with
--password-stdin. Any account works: built-in corpora are readable by everyone; statistics and the
knowledge base use the user's project named --project (created when missing; the knowledge-base check
imports tests/fixtures/kb-sample.* into it once).

Search: each query runs once to warm up, then --runs times as a fresh search (no search_id), page 1 of 50;
P50 / P95 (nearest rank) of the response time. counts.complete=false means CQP did not finish counting within
the API's 20 s count timeout and the page shows "计算中" / "未完成". Statistics: one job per method, timed from
submit to job end (includes queueing). Import timings are read from tmp/builtin/run-*.json written by
scripts/import_builtin.py.
"""

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    ("字串", "翻译"),
    ("字串", "文化"),
    ("词/词性", "语言/n"),
    ("词性＋同句条件", "翻译/v +文化"),
    ("距离", "文化 $2 交流"),
    ("英文词", "the"),
    ("属性（PostgreSQL）", "{pos=v}"),
    ("属性（PostgreSQL）", "{lemma=translate}"),
]
NOTES = "## 说明"  # hand-written section of the output file, kept on rerun
KB_QUERIES = ["语料库", "翻译策略", "corpus linguistics", "搭配 统计", "术语抽取"]


def log(*args):
    print(f"[{datetime.now():%H:%M:%S}]", *args, flush=True)


class Api:
    def __init__(self, base):
        base = base.rstrip("/")
        self.http = httpx.Client(
            base_url=base + "/api", headers={"Origin": base}, timeout=900
        )

    def call(self, method, path, **kw):
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} → {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None

    def timed(self, method, path, **kw):
        t = time.perf_counter()
        body = self.call(method, path, **kw)
        return time.perf_counter() - t, body

    def job(self, job, poll=0.5):
        t0 = time.perf_counter()
        while job["state"] in ("queued", "running"):
            time.sleep(poll)
            job = self.call("GET", f"/jobs/{job['id']}")
        if job["state"] != "succeeded":
            raise RuntimeError(f"任务 {job['kind']} {job['state']}: {job.get('error')}")
        return time.perf_counter() - t0, job


def pct(values, p):
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def secs(v):
    return "—" if v is None else f"{v:.2f}"


def environment():
    env = {"host": platform.platform(), "python": platform.python_version()}
    try:
        info = json.loads(
            subprocess.run(
                ["docker", "info", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        env["docker"] = (
            f"{info.get('OperatingSystem')} {info.get('ServerVersion')}，"
            f"{info.get('NCPU')} vCPU，内存 {info.get('MemTotal', 0) / 2**30:.1f} GiB"
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        env["docker"] = "未取得"
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "$c=Get-CimInstance Win32_Processor | Select-Object -First 1;"
                        "$m=(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory;"
                        '"$($c.Name.Trim())|$($c.NumberOfCores)|$($c.NumberOfLogicalProcessors)|$m"'
                    ),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            name, cores, threads, mem = out.split("|")
            env["cpu"] = (
                f"{name}，{cores} 核 {threads} 线程，内存 {int(mem) / 2**30:.1f} GiB"
            )
        except (OSError, subprocess.CalledProcessError, ValueError):
            env["cpu"] = "未取得"
    else:
        env["cpu"] = platform.processor() or "未取得"
    return env


def find_corpus(api, name):
    res = api.call("GET", "/corpora", params={"page_size": 200})
    for c in res["items"]:
        if c["project_id"] is None and c["name"] == name:
            return c
    raise SystemExit(f"没有名为 {name} 的内置语料")


def find_project(api, name):
    res = api.call("GET", "/projects", params={"page_size": 200})
    for p in res["items"]:
        if p["name"] == name:
            return p
    return api.call("POST", "/projects", json={"name": name})


def bench_search(api, corpus, runs):
    rows = []
    for kind, q in QUERIES:
        body = {"scope": {"corpus_id": corpus["id"]}, "query": q, "page_size": 50}
        try:
            api.timed("POST", "/search", json=body)  # warm-up
            times, counts = [], None
            for _ in range(runs):
                t, res = api.timed("POST", "/search", json=body)
                times.append(t)
                counts = res["counts"]
            rows.append({"kind": kind, "query": q, "times": times, "counts": counts})
            log(
                f"检索 {q}：P50 {statistics.median(times):.2f}s，命中 {counts['hits']}，完整 {counts['complete']}"
            )
        except RuntimeError as e:
            rows.append({"kind": kind, "query": q, "error": str(e)})
            log(f"检索 {q} 失败：{e}")
    return rows


def bench_stats(api, corpus, project):
    cid, pid = corpus["id"], project["id"]
    scope = {"corpus_id": cid}
    sub = {"corpus_id": cid, "filter": {"part": 1, "tatoeba_lang": "cmn"}}
    plans = [
        ("频次（词）", "frequency", {"scope": scope, "unit": "word", "top": 200}),
        ("n-gram（2）", "ngrams", {"scope": scope, "n": 2, "unit": "word", "top": 200}),
        (
            "搭配（翻译，±5）",
            "collocations",
            {"scope": scope, "node": "翻译", "window": 5},
        ),
        (
            "关键词（第 1 批中文 vs 全库）",
            "keywords",
            {"target": sub, "reference": scope},
        ),
        (
            "分布（翻译 × part）",
            "distribution",
            {"scope": scope, "query": "翻译", "field": "part"},
        ),
    ]
    rows = []
    for label, method, body in plans:
        try:
            job = api.call("POST", f"/stats/{method}", json={**body, "project_id": pid})
            t, job = api.job(job)
            stat = api.call("GET", f"/stats/{job['result']['stat_id']}")
            rows.append({"label": label, "seconds": t, "rows": stat["row_count"]})
            log(f"统计 {label}：{t:.1f}s，{stat['row_count']} 行")
        except RuntimeError as e:
            rows.append({"label": label, "error": str(e)})
            log(f"统计 {label} 失败：{e}")
    return rows


def bench_kb(api, project, runs):
    pid = project["id"]
    docs = api.call("GET", f"/projects/{pid}/kb/documents", params={"page_size": 200})
    if not docs["total"]:
        fixtures = [
            ROOT / "tests/fixtures" / n
            for n in ("kb-sample.pdf", "kb-sample.docx", "kb-sample.md")
        ]
        files = [
            ("files", (p.name, p.read_bytes(), "application/octet-stream"))
            for p in fixtures
        ]
        res = api.call("POST", f"/projects/{pid}/kb/documents", files=files)
        for item in res["items"]:
            api.job(api.call("GET", f"/jobs/{item['job_id']}"))
        docs = api.call(
            "GET", f"/projects/{pid}/kb/documents", params={"page_size": 200}
        )
    rows = []
    for q in KB_QUERIES:
        body = {"q": q, "mode": "hybrid", "top_k": 8}
        api.timed("POST", f"/projects/{pid}/kb/search", json=body)
        times, res = [], None
        for _ in range(runs):
            t, res = api.timed("POST", f"/projects/{pid}/kb/search", json=body)
            times.append(t)
        rows.append(
            {
                "query": q,
                "times": times,
                "mode": res["mode"],
                "items": len(res["items"]),
            }
        )
        log(
            f"知识库 {q}：P50 {statistics.median(times) * 1000:.0f}ms，模式 {res['mode']}"
        )
    return rows, docs["total"]


def import_runs():
    out = []
    for p in sorted((ROOT / "tmp" / "builtin").glob("run-*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def write_doc(
    path, env, corpus, corpora, imports, search, stats_rows, kb_rows, kb_docs, runs
):
    s = corpus["stats"]
    lines = [
        "# 性能基线",
        "",
        f"测量时间：{datetime.now():%Y-%m-%d %H:%M}。复跑：`uv run python scripts/bench.py`（见脚本说明）。",
        "",
        "## 环境",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 主机 | {env['host']} |",
        f"| CPU / 内存 | {env['cpu']} |",
        f"| Docker | {env['docker']} |",
        "| 部署 | deploy/compose.yaml 全部服务同机；worker 单进程；与其他项目容器共享主机 |",
        "",
        "## 数据集",
        "",
        "| 内置语料 | 文档 | 句 | 词 | 索引版本 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for c in corpora:
        cs = c["stats"]
        lines.append(
            f"| {c['name']} | {cs['documents']:,} | {cs['sentences']:,} | {cs['tokens']:,} | {c['index_version'] or '—'} |"
        )
    lines += ["", "## 导入与索引", ""]
    if imports:
        lines += [
            "| 语料 | 批 | 导入任务（上传到完成，秒） | 句 | 词 | 对齐 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for run in imports:
            for r in run["imports"]:
                lines.append(
                    f"| {run['corpus']} | {r['part']} | {r['seconds']:,.0f} | {r.get('sentences', 0):,} | "
                    f"{r.get('tokens', 0):,} | {r.get('alignments', 0):,} |"
                )
        lines += [
            "",
            "| 语料 | 末次索引等待（秒） | 脚本总用时（秒） |",
            "| --- | ---: | ---: |",
        ]
        for run in imports:
            lines.append(
                f"| {run['corpus']} | {run['last_index_wait_seconds']:,.0f} | {run['total_seconds']:,.0f} |"
            )
    else:
        lines.append("没有 tmp/builtin/run-*.json 导入记录。")
    lines += [
        "",
        f"## 检索（{corpus['name']}，{s['sentences']:,} 句、{s['tokens']:,} 词）",
        "",
        f"每条查询预热 1 次后执行 {runs} 次新检索（第 1 页 50 条），单位秒；P95 为最近秩。",
        "",
        "| 类型 | 查询式 | P50 | P95 | 命中 | 句 | 计数完整 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in search:
        if "error" in r:
            lines.append(
                f"| {r['kind']} | `{r['query']}` | 失败 | | | | {r['error'][:80]} |"
            )
            continue
        c = r["counts"]
        hits = f"{c['hits']:,}" if c["hits"] is not None else "—"
        sents = f"{c['sentences']:,}" if c["sentences"] is not None else "—"
        lines.append(
            f"| {r['kind']} | `{r['query']}` | {secs(statistics.median(r['times']))} | "
            f"{secs(pct(r['times'], 95))} | {hits} | {sents} | {'是' if c['complete'] else '否（20 秒计数超时）'} |"
        )
    lines += [
        "",
        "## 统计",
        "",
        "每种方法提交一次后台任务，计时从提交到任务结束（含排队），单位秒。",
        "",
        "| 方法 | 耗时 | 结果行数 |",
        "| --- | ---: | ---: |",
    ]
    for r in stats_rows:
        if "error" in r:
            lines.append(f"| {r['label']} | 失败 | {r['error'][:80]} |")
        else:
            lines.append(f"| {r['label']} | {r['seconds']:.1f} | {r['rows']:,} |")
    lines += [
        "",
        f"## 知识库混合检索（项目知识库 {kb_docs} 篇文档）",
        "",
        f"预热 1 次后每条 {runs} 次，单位毫秒。",
        "",
        "| 查询 | P50 | P95 | 模式 | 返回条数 |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for r in kb_rows:
        lines.append(
            f"| {r['query']} | {statistics.median(r['times']) * 1000:.0f} | {pct(r['times'], 95) * 1000:.0f} | "
            f"{r['mode']} | {r['items']} |"
        )
    text = "\n".join(lines) + "\n"
    if path.exists():  # keep the hand-written analysis section across reruns
        old = path.read_text(encoding="utf-8")
        if NOTES in old:
            text += "\n" + old[old.index(NOTES) :]
    path.write_text(text, encoding="utf-8", newline="\n")
    log(f"已写入 {path}")


def main():
    parser = argparse.ArgumentParser(description="性能基线")
    parser.add_argument(
        "--base", default=os.environ.get("CORPUS_BASE", "http://127.0.0.1:8088")
    )
    parser.add_argument("--email")
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--corpus-name", default="Tatoeba 中英")
    parser.add_argument("--project", default="性能基线")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, default=ROOT / "doc" / "performance.md")
    args = parser.parse_args()
    email = (
        args.email or os.environ.get("BENCH_EMAIL") or os.environ.get("CORPUS_EMAIL")
    )
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = os.environ.get("BENCH_PASSWORD") or os.environ.get("CORPUS_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "需要账号：BENCH_EMAIL 与 BENCH_PASSWORD，或 --email 加 --password-stdin"
        )
    api = Api(args.base)
    api.call("POST", "/auth/login", json={"email": email, "password": password})
    corpus = find_corpus(api, args.corpus_name)
    if corpus["status"] not in ("ready", "stale"):
        raise SystemExit(f"{corpus['name']} 状态为 {corpus['status']}，未就绪")
    corpora = [
        c
        for c in api.call("GET", "/corpora", params={"page_size": 200})["items"]
        if c["project_id"] is None
    ]
    project = find_project(api, args.project)
    env = environment()
    search = bench_search(api, corpus, args.runs)
    stats_rows = bench_stats(api, corpus, project)
    kb_rows, kb_docs = bench_kb(api, project, args.runs)
    raw = {
        "env": env,
        "corpus": corpus,
        "search": search,
        "stats": stats_rows,
        "kb": kb_rows,
    }
    raw_path = ROOT / "tmp" / "builtin" / f"bench-{datetime.now():%Y%m%d-%H%M}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    write_doc(
        args.out,
        env,
        corpus,
        corpora,
        import_runs(),
        search,
        stats_rows,
        kb_rows,
        kb_docs,
        args.runs,
    )


if __name__ == "__main__":
    main()
