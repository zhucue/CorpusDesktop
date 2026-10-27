"""Build the built-in corpora (project_id null) through the platform API.

  uv run python scripts/import_builtin.py tatoeba [--parts 8]
  uv run python scripts/import_builtin.py ud --treebank en_ewt|zh_gsd
  uv run --with mwparserfromhell --with opencc-python-reimplemented \
      python scripts/import_builtin.py wiki --lang zh|en --n 1000

Login: CORPUS_EMAIL and CORPUS_PASSWORD from the environment, or --email with --password-stdin; the account
must be a platform admin. --base is the web entry (default http://127.0.0.1:8088); the Origin header is the
same URL and must be listed in PUBLIC_ORIGIN.

Downloads and generated upload files go to tmp/builtin/. --prepare-only stops before logging in. A built-in
corpus with the same name is reused: parts / splits whose documents already exist are skipped, so a run
interrupted by a failed job can be repeated. Uploads stay below the 500 MB nginx limit; each upload waits for
its import job before the next one is sent, so other users' jobs can run in between.

Sources and licenses (stored in Corpus.meta and written at the top of exports):
  tatoeba  all cmn and eng sentences of the official per-language exports and every direct cmn-eng link,
           CC BY 2.0 FR. One import holds whole link components, so every alignment stays inside one upload.
  ud       UD_English-EWT / UD_Chinese-GSD CoNLL-U (train, dev, test) from the latest UD GitHub release tag;
           the license line is read from the treebank README (both CC BY-SA 4.0).
  wiki     n articles sampled from the official pages-articles-multistream dump: index entries ranked by
           SHA256(seed:page_id), main-namespace, non-redirect, non-disambiguation pages taken in rank order;
           wikitext cleaned to plain paragraphs (templates, tables, references, files, categories removed);
           zh converted to Simplified Chinese with OpenCC t2s. CC BY-SA 4.0; each document keeps its page
           title, page id, revision id and revision URL.
"""

import argparse
import bz2
import csv
import hashlib
import heapq
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tmp" / "builtin"
UA = "CorpusDesktop-builtin-import/1.0 (research corpus platform; https://github.com/zhucue)"
MAX_UPLOAD = 450 * 1024 * 1024  # below the 500 MB nginx / API limit


def log(*args):
    print(f"[{datetime.now():%H:%M:%S}]", *args, flush=True)


def fmt_secs(s):
    s = int(s)
    return f"{s // 3600:d}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------- API client


class ApiError(RuntimeError):
    pass


class Api:
    def __init__(self, base: str):
        base = base.rstrip("/")
        self.http = httpx.Client(
            base_url=base + "/api", headers={"Origin": base}, timeout=900
        )

    def call(self, method, path, **kw):
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                err = r.json().get("error") or r.json()
            except ValueError:
                err = r.text[:300]
            raise ApiError(f"{method} {path} → {r.status_code} {err}")
        return r.json() if r.content else None

    def login(self, email, password):
        user = self.call(
            "POST", "/auth/login", json={"email": email, "password": password}
        )
        if not user.get("is_admin"):
            raise ApiError(f"{email} 不是平台管理员，不能建内置语料")
        return user

    def builtin(self, name):
        page = 1
        while True:
            res = self.call("GET", "/corpora", params={"page": page, "page_size": 200})
            for c in res["items"]:
                if c["project_id"] is None and c["name"] == name:
                    return c
            if page * 200 >= res["total"]:
                return None
            page += 1

    def ensure_corpus(self, name, language, description, meta):
        corpus = self.builtin(name)
        if corpus:
            log(f"沿用内置语料 {name} {corpus['id']} 状态 {corpus['status']}")
            return corpus
        corpus = self.call(
            "POST",
            "/corpora",
            json={
                "name": name,
                "language": language,
                "description": description,
                "meta": meta,
            },
        )
        log(f"已建内置语料 {name} {corpus['id']}")
        return corpus

    def documents(self, corpus_id):
        out, page = [], 1
        while True:
            res = self.call(
                "GET",
                f"/corpora/{corpus_id}/documents",
                params={"page": page, "page_size": 200},
            )
            out += res["items"]
            if page * 200 >= res["total"]:
                return out
            page += 1

    def upload(self, corpus_id, paths, metadata, language=None):
        size = sum(p.stat().st_size for p in paths)
        if size > MAX_UPLOAD:
            raise ApiError(f"单次上传 {size / 2**20:.0f} MB 超过上限，请增加分批数")
        data = {"metadata": json.dumps(metadata, ensure_ascii=False)}
        if language:
            data["language"] = language
        with ExitStack() as stack:
            files = [
                (
                    "files",
                    (
                        p.name,
                        stack.enter_context(open(p, "rb")),
                        "application/octet-stream",
                    ),
                )
                for p in paths
            ]
            return self.call(
                "POST", f"/corpora/{corpus_id}/documents", files=files, data=data
            )

    def wait_job(self, job_id, label, poll=5.0):
        started, shown, last = time.monotonic(), None, 0.0
        while True:
            job = self.call("GET", f"/jobs/{job_id}")
            p = job["progress"] or {}
            line = f"{label} {job['state']} {p.get('message') or ''} {p.get('done')}/{p.get('total')}"
            if (
                line != shown
                and time.monotonic() - last >= 30
                or job["state"] not in ("queued", "running")
            ):
                pct = f" {100 * p['done'] / p['total']:.1f}%" if p.get("total") else ""
                log(f"{line}{pct} 用时 {fmt_secs(time.monotonic() - started)}")
                shown, last = line, time.monotonic()
            if job["state"] == "succeeded":
                return job
            if job["state"] in ("failed", "cancelled"):
                raise ApiError(f"{label} {job['state']}: {job.get('error')}")
            time.sleep(poll)

    def wait_ready(self, corpus_id, label, poll=10.0):
        started, shown = time.monotonic(), None
        while True:
            c = self.call("GET", f"/corpora/{corpus_id}")
            if c["status"] != shown:
                log(f"{label} 语料状态 {c['status']}")
                shown = c["status"]
            if c["status"] == "ready":
                return c, time.monotonic() - started
            if c["status"] == "failed":
                raise ApiError(f"{label} 失败：{c['error']}")
            time.sleep(poll)


def connect(args):
    email = args.email or os.environ.get("CORPUS_EMAIL")
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = os.environ.get("CORPUS_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "需要管理员账号：设置 CORPUS_EMAIL 与 CORPUS_PASSWORD，或 --email 加 --password-stdin"
        )
    api = Api(args.base)
    api.login(email, password)
    return api


def import_parts(api, corpus, parts, key, language=None):
    """parts: [(value, [paths], metadata)]; documents carry metadata[key] = value. Returns timing rows."""
    done = {d["metadata"].get(key) for d in api.documents(corpus["id"])}
    rows = []
    for i, (value, paths, metadata) in enumerate(parts, 1):
        label = f"[{key}={value} {i}/{len(parts)}]"
        if value in done:
            log(f"{label} 已导入，跳过")
            continue
        t0 = time.monotonic()
        job = api.upload(corpus["id"], paths, {**metadata, key: value}, language)
        log(
            f"{label} 已上传 {sum(p.stat().st_size for p in paths) / 2**20:.1f} MB，导入任务 {job['id']}"
        )
        job = api.wait_job(job["id"], label)
        rows.append(
            {
                "part": value,
                "seconds": round(time.monotonic() - t0, 1),
                **(job["result"] or {}),
            }
        )
    corpus, index_wait = api.wait_ready(corpus["id"], "[索引]")
    return corpus, rows, index_wait


def report(name, corpus, rows, index_wait, started):
    total = time.monotonic() - started
    summary = {
        "corpus": name,
        "corpus_id": corpus["id"],
        "stats": corpus["stats"],
        "index_version": corpus["index_version"],
        "imports": rows,
        "last_index_wait_seconds": round(index_wait, 1),
        "total_seconds": round(total, 1),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    out = WORK / f"run-{re.sub(r'[^A-Za-z0-9_-]+', '_', name)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    s = corpus["stats"]
    log(
        f"完成 {name}：文档 {s['documents']:,}，句 {s['sentences']:,}，词 {s['tokens']:,}；"
        f"总用时 {fmt_secs(total)}；记录 {out.relative_to(ROOT)}"
    )


# ---------------------------------------------------------------- download


def download(url, path: Path, client=None):
    """GET url into path (kept for reruns); returns the Last-Modified date (YYYY-MM-DD) when present."""
    meta = path.with_name(path.name + ".json")
    if path.exists() and meta.exists():
        return json.loads(meta.read_text(encoding="utf-8")).get("last_modified")
    path.parent.mkdir(parents=True, exist_ok=True)
    client = client or httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=120
    )
    log(f"下载 {url}")
    tmp = path.with_name(path.name + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        modified = r.headers.get("last-modified")
        with open(tmp, "wb") as f:
            f.writelines(r.iter_bytes(1 << 20))
    tmp.replace(path)
    date = parsedate_to_datetime(modified).date().isoformat() if modified else None
    meta.write_text(
        json.dumps({"url": url, "last_modified": date, "bytes": path.stat().st_size}),
        encoding="utf-8",
    )
    return date


# ---------------------------------------------------------------- Tatoeba

TATOEBA = "https://downloads.tatoeba.org/exports/per_language/"
TATOEBA_FILES = {
    "cmn_sentences_detailed.tsv.bz2": "cmn/cmn_sentences_detailed.tsv.bz2",
    "eng_sentences_detailed.tsv.bz2": "eng/eng_sentences_detailed.tsv.bz2",
    "cmn-eng_links.tsv.bz2": "cmn/cmn-eng_links.tsv.bz2",
}


def tatoeba_prepare(src: Path | None, parts: int):
    src = src or WORK / "tatoeba"
    dates = [download(TATOEBA + rel, src / name) for name, rel in TATOEBA_FILES.items()]
    version = max(d for d in dates if d) if any(dates) else "unknown"
    sentences, skipped = {}, 0  # id → (lang, text)
    for name in ("cmn_sentences_detailed.tsv.bz2", "eng_sentences_detailed.tsv.bz2"):
        with bz2.open(src / name, "rt", encoding="utf-8", newline="\n") as f:
            for line in f:
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) < 3 or not fields[0].isdigit() or not fields[2].strip():
                    skipped += 1
                    continue
                sentences[int(fields[0])] = (fields[1], fields[2])
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    links = set()
    with bz2.open(src / "cmn-eng_links.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            a, b = (int(x) for x in line.split())
            if a in sentences and b in sentences and sentences[a][0] != sentences[b][0]:
                links.add((min(a, b), max(a, b)))
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups = defaultdict(list)
    for sid in sentences:
        groups[find(sid)].append(sid)
    # whole components in id order, cut into parts of about equal sentence counts
    target = len(sentences) / parts
    assignment, part, size = {}, 0, 0
    for root in sorted(groups):
        if size >= target * (part + 1) and part < parts - 1:
            part += 1
        for sid in groups[root]:
            assignment[sid] = part
        size += len(groups[root])
    out = src / f"parts-{parts}"
    out.mkdir(exist_ok=True)
    lines = [{"cmn": [], "eng": [], "links": []} for _ in range(parts)]
    for sid in sorted(sentences):
        lang, text = sentences[sid]
        lines[assignment[sid]][lang].append(f"{sid}\t{lang}\t{text}\n")
    for a, b in sorted(links):
        assert assignment[a] == assignment[b]
        lines[assignment[a]]["links"].append(f"{a}\t{b}\n")
    counts = []
    names = {
        "cmn": "cmn_sentences.tsv",
        "eng": "eng_sentences.tsv",
        "links": "cmn-eng_links.tsv",
    }
    for k, part_lines in enumerate(lines):
        d = out / f"part-{k + 1:02d}"
        d.mkdir(exist_ok=True)
        for key, rows in part_lines.items():
            (d / names[key]).write_text("".join(rows), encoding="utf-8", newline="\n")
        counts.append(
            {"part": k + 1, **{key: len(rows) for key, rows in part_lines.items()}}
        )
    info = {
        "version": version,
        "sentences": len(sentences),
        "cmn": sum(c["cmn"] for c in counts),
        "eng": sum(c["eng"] for c in counts),
        "links": len(links),
        "skipped_rows": skipped,
        "parts": counts,
    }
    (out / "parts.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    log(
        f"Tatoeba {version}：句 {info['sentences']:,}（cmn {info['cmn']:,}，eng {info['eng']:,}），"
        f"直接链接 {info['links']:,}，空行跳过 {skipped}，分 {parts} 批"
    )
    return out, info


def cmd_tatoeba(args):
    started = time.monotonic()
    out, info = tatoeba_prepare(args.src, args.parts)
    if args.prepare_only:
        return
    api = connect(args)
    name = args.name or "Tatoeba 中英"
    meta = {
        "license": "CC BY 2.0 FR",
        "attribution": "Tatoeba (https://tatoeba.org) 贡献者；句子 ID 保留为外部 ID",
        "source_url": TATOEBA,
        "version": info["version"],
    }
    desc = (
        f"Tatoeba 官方导出（{info['version']}）全部中文与英文句子及中英直接互译链接："
        f"{info['cmn']:,} 中文句，{info['eng']:,} 英文句，{info['links']:,} 对。"
    )
    corpus = api.ensure_corpus(name, "zh", desc, meta)
    parts = [
        (k, sorted((out / f"part-{k:02d}").iterdir()), {})
        for k in range(1, args.parts + 1)
    ]
    corpus, rows, wait = import_parts(api, corpus, parts, "part")
    report(name, corpus, rows, wait, started)


# ---------------------------------------------------------------- UD

UD = {
    "en_ewt": ("UD_English-EWT", "en", "UD 英文 EWT"),
    "zh_gsd": ("UD_Chinese-GSD", "zh", "UD 中文 GSD"),
    "zh_gsdsimp": ("UD_Chinese-GSDSimp", "zh", "UD 中文 GSDSimp"),
}


def ud_release(repo, client):
    tags = client.get(
        f"https://api.github.com/repos/UniversalDependencies/{repo}/tags",
        params={"per_page": 100},
    )
    tags.raise_for_status()
    names = [t["name"] for t in tags.json() if re.fullmatch(r"r2\.\d+", t["name"])]
    if not names:
        raise SystemExit(f"{repo} 没有 r2.x 发布标签")
    return max(names, key=lambda n: int(n.split(".")[1]))


def cmd_ud(args):
    started = time.monotonic()
    repo, language, default_name = UD[args.treebank]
    client = httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=120
    )
    tag = args.release or ud_release(repo, client)
    raw = f"https://raw.githubusercontent.com/UniversalDependencies/{repo}/{tag}/"
    folder = WORK / "ud" / f"{args.treebank}-{tag}"
    readme = folder / "README.md"
    download(raw + "README.md", readme, client)
    m = re.search(r"(?mi)^License:\s*(.+)$", readme.read_text(encoding="utf-8"))
    license_ = m.group(1).strip() if m else "见 README"
    splits = []
    for split in ("train", "dev", "test"):
        path = folder / f"{args.treebank}-ud-{split}.conllu"
        download(raw + path.name, path, client)
        splits.append((split, [path], {}))
    log(f"{repo} {tag}：许可 {license_}")
    if args.prepare_only:
        return
    api = connect(args)
    name = args.name or default_name
    meta = {
        "license": license_,
        "attribution": f"Universal Dependencies {repo}（{tag}）；引用方式见 README",
        "source_url": f"https://github.com/UniversalDependencies/{repo}/tree/{tag}",
        "version": tag,
    }
    desc = f"Universal Dependencies {repo} {tag} 的 train / dev / test，保留人工分词、词性、词元与依存。"
    corpus = api.ensure_corpus(name, language, desc, meta)
    corpus, rows, wait = import_parts(api, corpus, splits, "split", language)
    report(name, corpus, rows, wait, started)


# ---------------------------------------------------------------- Wikipedia

DUMPS = "https://dumps.wikimedia.org/"
WIKI_SEED = "corpus-builtin-20261027"
NAMESPACE_LINK = re.compile(
    r"(?i)^\s*:?\s*(file|image|category|media|wikt|wiktionary|commons|s|q|n|v|voy|b|special|template|help|"
    r"portal|wikipedia|wp|user|talk|draft|module|"
    r"文件|檔案|档案|图像|圖像|分类|分類|维基|維基|模板|帮助|幫助|主题|主題|專題|专题|"
    r"[a-z]{2,3}(-[a-z]+)*)\s*:"
)
KEEP_TAGS = {
    "b",
    "i",
    "u",
    "s",
    "em",
    "strong",
    "sup",
    "sub",
    "span",
    "small",
    "big",
    "abbr",
    "nowiki",
    "font",
}
STOP_SECTIONS = {
    "en": {
        "references",
        "external links",
        "see also",
        "further reading",
        "notes",
        "bibliography",
        "sources",
        "citations",
        "footnotes",
        "notes and references",
        "works cited",
    },
    "zh": {
        "参考文献",
        "參考文獻",
        "参考资料",
        "參考資料",
        "外部链接",
        "外部連結",
        "参见",
        "參見",
        "注释",
        "註釋",
        "延伸阅读",
        "延伸閱讀",
        "相关条目",
        "相關條目",
        "参考",
        "參考",
        "脚注",
        "腳註",
        "来源",
        "來源",
        "外部連接",
    },
}
DISAMBIG = re.compile(
    r"(?i)\{\{\s*(disambig|disambiguation|dab|set index|hndis|geodis|消歧义|消歧義|disambig)\b"
)
VARIANT = re.compile(r"-\{(.*?)\}-", re.DOTALL)


def _variant(m):
    body = m.group(1)
    if "|" in body and re.match(
        r"^[A-Za-z]+\|", body
    ):  # flags like -{H|...}- or -{A|...}-
        body = body.split("|", 1)[1]
    pairs = re.findall(r"(zh(?:-[a-z]+)?)\s*:\s*([^;]*)", body)
    if pairs:
        values = dict(pairs)
        for key in ("zh-hans", "zh-cn", "zh-sg", "zh", "zh-hant", "zh-tw", "zh-hk"):
            if values.get(key, "").strip():
                return values[key].strip()
        return pairs[0][1].strip()
    return body


def clean_wikitext(text, lang):
    """Plain paragraphs from wikitext: drop templates, comments, tables, references and other tags, file /
    category / interlanguage links and everything from the reference sections on; keep link labels."""
    import mwparserfromhell
    from mwparserfromhell import nodes

    if lang == "zh":
        text = VARIANT.sub(_variant, text)
    code = mwparserfromhell.parse(text)
    stop = STOP_SECTIONS[lang]
    out = []

    def walk(wikicode, top=False):
        for node in wikicode.nodes:
            if (
                top
                and isinstance(node, nodes.Heading)
                and node.title.strip_code().strip().lower() in stop
            ):
                break
            if isinstance(node, nodes.Text):
                out.append(str(node))
            elif isinstance(node, nodes.HTMLEntity):
                out.append(node.normalize())
            elif isinstance(node, nodes.Wikilink):
                if NAMESPACE_LINK.match(str(node.title)):
                    continue
                walk(node.text if node.text is not None else node.title)
            elif isinstance(node, nodes.ExternalLink):
                if node.title is not None and node.brackets:
                    walk(node.title)
            elif isinstance(node, nodes.Heading):
                out.append("\n")
                walk(node.title)
                out.append("\n")
            elif isinstance(node, nodes.Tag):
                tag = str(node.tag).lower()
                if (
                    tag in KEEP_TAGS
                    and node.contents is not None
                    and not node.self_closing
                ):
                    walk(node.contents)
                elif tag in ("br", "p") or tag in ("li", "dd", "dt"):
                    out.append("\n")
            # templates, arguments, comments, tables and other tags are dropped

    walk(code, top=True)
    paras = []
    for line in "".join(out).split("\n"):
        line = re.sub(r"__[A-Z]+__", "", line)
        line = re.sub(r"\s*\|\s*[\w\- ]+=.*$", "", line)  # leftover template parameters
        line = re.sub(r"[ \t 　]+", " ", line).strip()
        line = re.sub(r"'{2,}", "", line)
        line = re.sub(r"\(\s*[,;，；、]?\s*\)|（\s*[,;，；、]?\s*）", "", line)
        line = re.sub(r"([（(])\s*[,;，；、]\s*", r"\1", line)
        line = re.sub(r" +([,.;:!?，。；：！？、])", r"\1", line)
        line = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]", r"\1", line)
        line = line.strip(" |")
        # malformed templates / tables that the parser left as text: drop the paragraph
        if (
            not line
            or line.startswith("!")
            or re.search(r"\{\{|\}\}|\[\[|\]\]|\||\{\}", line)
        ):
            continue
        if lang == "zh" and len(line) < 4 or lang == "en" and len(line.split()) < 3:
            continue  # headings, captions, list fragments
        paras.append(line)
    return "\n".join(paras)


def wiki_files(wiki, date, client):
    if date == "latest":
        rss = client.get(
            f"{DUMPS}{wiki}/latest/{wiki}-latest-pages-articles-multistream-index.txt.bz2-rss.xml"
        )
        rss.raise_for_status()
        date = re.search(rf"{wiki}/(\d{{8}})", rss.text).group(1)
    status = client.get(f"{DUMPS}{wiki}/{date}/dumpstatus.json")
    status.raise_for_status()
    job = status.json()["jobs"]["articlesmultistreamdumprecombine"]
    if job["status"] != "done":
        raise SystemExit(f"{wiki} {date} 多流合并文件未完成：{job['status']}")
    files = job["files"]
    dump = f"{wiki}-{date}-pages-articles-multistream.xml.bz2"
    index = f"{wiki}-{date}-pages-articles-multistream-index.txt.bz2"
    return (
        date,
        DUMPS + files[dump]["url"].lstrip("/"),
        DUMPS + files[index]["url"].lstrip("/"),
        files[index],
    )


def wiki_candidates(index_path, keep, seed):
    """The `keep` index entries with the lowest SHA256(seed:page_id), plus sorted stream offsets."""
    heap, offsets, last = [], [], None
    with bz2.open(index_path, "rt", encoding="utf-8") as f:
        for line in f:
            offset, page_id, title = line.rstrip("\n").split(":", 2)
            offset = int(offset)
            if offset != last:
                offsets.append(offset)
                last = offset
            rank = hashlib.sha256(f"{seed}:{page_id}".encode()).digest()
            item = (-int.from_bytes(rank[:8]), int(page_id), offset, title)
            if len(heap) < keep:
                heapq.heappush(heap, item)
            elif item[0] > heap[0][0]:
                heapq.heapreplace(heap, item)
    return [
        (pid, off, title) for _, pid, off, title in sorted(heap, reverse=True)
    ], offsets


def wiki_stream(client, url, start, end, wanted):
    for attempt in range(4):  # the dump server answers 429 / 503 when busy
        try:
            r = client.get(url, headers={"Range": f"bytes={start}-{end - 1}"})
        except httpx.TransportError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 206:
            break
        if r.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
            raise RuntimeError(f"Range 请求返回 {r.status_code}")
        time.sleep(5 * (attempt + 1))
    xml = bz2.decompress(r.content).decode("utf-8")
    root = ET.fromstring(f"<pages>{xml}</pages>")
    pages = {}
    for page in root.iter("page"):
        if int(page.findtext("id")) not in wanted:
            continue
        rev = page.find("revision")
        pages[int(page.findtext("id"))] = {
            "ns": page.findtext("ns"),
            "title": page.findtext("title"),
            "redirect": page.find("redirect") is not None,
            "revision_id": int(rev.findtext("id")) if rev is not None else None,
            "timestamp": rev.findtext("timestamp") if rev is not None else None,
            "text": (rev.findtext("text") or "") if rev is not None else "",
        }
    return pages, len(r.content)


def wiki_prepare(lang, n, seed, date):
    wiki = f"{lang}wiki"
    client = httpx.Client(
        headers={"User-Agent": UA}, follow_redirects=True, timeout=120
    )
    date, dump_url, index_url, index_meta = wiki_files(wiki, date, client)
    folder = WORK / "wiki" / f"{wiki}-{date}"
    index_path = folder / Path(index_url).name
    download(index_url, index_path, client)
    if hashlib.sha1(index_path.read_bytes()).hexdigest() != index_meta["sha1"]:
        raise SystemExit("索引文件 SHA1 与 dumpstatus.json 不一致")
    out = folder / f"{wiki}-{date}-sample-{n}.csv"
    if out.exists():
        log(f"沿用 {out.relative_to(ROOT)}")
        return out, date, dump_url
    log(f"排序索引 {index_path.name}")
    candidates, offsets = wiki_candidates(index_path, n * 25, seed)
    converter = None
    if lang == "zh":
        import opencc

        converter = opencc.OpenCC("t2s")
    wanted = {pid for pid, _, _ in candidates}
    dump_size = int(client.head(dump_url).headers["content-length"])

    def fetch(offset):
        k = bisect_right(offsets, offset)
        end = offsets[k] if k < len(offsets) else dump_size
        return offset, *wiki_stream(client, dump_url, offset, end, wanted)

    rows, cache, fetched, nbytes, skipped = [], {}, 0, 0, defaultdict(int)
    pool = ThreadPoolExecutor(
        3
    )  # dumps.wikimedia.org asks for only a few connections per client
    for i, (page_id, offset, _) in enumerate(candidates):
        if len(rows) >= n:
            break
        if (
            offset not in cache
        ):  # fetch the streams of the next candidates together, keep rank order
            todo = list(
                dict.fromkeys(o for _, o, _ in candidates[i : i + 30] if o not in cache)
            )
            for off, pages, size in pool.map(fetch, todo):
                cache[off] = pages
                fetched += 1
                nbytes += size
            log(
                f"已取 {fetched} 个流（{nbytes / 2**20:.0f} MB），入选 {len(rows)}，跳过 {dict(skipped)}"
            )
        page = cache[offset].get(page_id)
        if not page or page["ns"] != "0" or page["redirect"]:
            skipped["非条目或重定向"] += 1
            continue
        if DISAMBIG.search(page["text"]):
            skipped["消歧义"] += 1
            continue
        try:
            text = clean_wikitext(page["text"], lang)
        except Exception:  # noqa: BLE001 — malformed wikitext: skip the page, keep sampling
            skipped["解析失败"] += 1
            continue
        title = page["title"]
        if converter:
            text, title_s = converter.convert(text), converter.convert(title)
        else:
            title_s = title
        if len(text) < (200 if lang == "zh" else 500):
            skipped["清洗后过短"] += 1
            continue
        rows.append(
            {
                "text": text,
                "title": title_s,
                "language": lang,
                "page_title": title,
                "page_id": page_id,
                "revision_id": page["revision_id"],
                "revision_time": page["timestamp"],
                "url": f"https://{lang}.wikipedia.org/w/index.php?oldid={page['revision_id']}",
            }
        )
    if len(rows) < n:
        raise SystemExit(f"只得到 {len(rows)} 篇，可调大候选数")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    info = {
        "wiki": wiki,
        "dump": date,
        "seed": seed,
        "articles": len(rows),
        "streams_fetched": fetched,
        "stream_bytes": nbytes,
        "skipped": dict(skipped),
        "characters": sum(len(r["text"]) for r in rows),
    }
    out.with_suffix(".json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        f"{wiki} {date}：入选 {len(rows)} 篇，{info['characters']:,} 字符；跳过 {dict(skipped)}"
    )
    return out, date, dump_url


def cmd_wiki(args):
    started = time.monotonic()
    path, date, dump_url = wiki_prepare(args.lang, args.n, args.seed, args.dump)
    if args.prepare_only:
        return
    api = connect(args)
    zh = args.lang == "zh"
    name = args.name or ("维基百科中文" if zh else "维基百科英文") + f" {args.n} 篇"
    meta = {
        "license": "CC BY-SA 4.0",
        "attribution": (
            f"Wikipedia 贡献者；{args.lang}wiki {date} 官方转储抽样，"
            "清洗为纯文本（删去模板、表格、参考文献、文件与分类链接）"
            + ("，并以 OpenCC 转为简体" if zh else "")
            + "；每篇文档记录页面标题、页面 ID 与修订版本链接"
        ),
        "source_url": dump_url.rsplit("/", 1)[0] + "/",
        "version": date,
    }
    desc = (
        f"从 {args.lang}wiki {date} pages-articles-multistream 转储按 SHA256(种子:页面 ID) "
        f"抽取 {args.n} 篇条目（不含重定向与消歧义页），清洗为纯文本段落。"
    )
    corpus = api.ensure_corpus(name, args.lang, desc, meta)
    corpus, rows, wait = import_parts(
        api, corpus, [(date, [path], {})], "dump", args.lang
    )
    report(name, corpus, rows, wait, started)


# ---------------------------------------------------------------- main


def main():
    parser = argparse.ArgumentParser(description="导入内置语料")
    parser.add_argument(
        "--base", default=os.environ.get("CORPUS_BASE", "http://127.0.0.1:8088")
    )
    parser.add_argument("--email", help="管理员邮箱（默认取 CORPUS_EMAIL）")
    parser.add_argument(
        "--password-stdin", action="store_true", help="从标准输入读取密码"
    )
    parser.add_argument(
        "--prepare-only", action="store_true", help="只下载并生成上传文件"
    )
    parser.add_argument("--name", help="语料库名称（默认按来源命名）")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tatoeba", help="Tatoeba 中英完整句子与直接链接")
    t.add_argument(
        "--src",
        type=Path,
        help="已下载的官方导出目录（默认 tmp/builtin/tatoeba，缺文件时下载）",
    )
    t.add_argument(
        "--parts", type=int, default=8, help="分批数（每批一次上传与导入任务）"
    )
    u = sub.add_parser("ud", help="UD 树库 CoNLL-U")
    u.add_argument("--treebank", choices=sorted(UD), required=True)
    u.add_argument("--release", help="发布标签，如 r2.16（默认取最新）")
    w = sub.add_parser("wiki", help="维基百科条目抽样")
    w.add_argument("--lang", choices=["zh", "en"], required=True)
    w.add_argument("--n", type=int, default=1000)
    w.add_argument("--seed", default=WIKI_SEED)
    w.add_argument("--dump", default="latest", help="转储日期 YYYYMMDD（默认最新）")
    args = parser.parse_args()
    {"tatoeba": cmd_tatoeba, "ud": cmd_ud, "wiki": cmd_wiki}[args.command](args)


if __name__ == "__main__":
    main()
