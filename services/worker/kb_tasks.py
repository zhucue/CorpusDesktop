"""Knowledge base jobs (contracts/p4.md §四): kb_import, kb_summarize, kb_extract and the kb_terms / kb_note exports."""

import csv
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt
from lxml import etree
from sqlalchemy import delete, func, insert, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from engine import stats
from engine.kb import chunk as kbchunk
from engine.kb import embed
from engine.kb import parse as kbparse
from engine.kb import terms as kbterms
from engine.kb import text as kbtext
from services.api.db import session, transaction
from services.api.effective import scope_clauses
from services.api.metadata import field_types
from services.api.models import (
    Corpus,
    Document,
    KbChunk,
    KbDocument,
    KbTerm,
    NoteRef,
    Sentence,
    SentenceAlignment,
    Token,
    User,
)
from services.api.search import Scope, resolve_scope, scope_filter
from services.api.storage import corpus_key, export_path, index_dir, kb_dir
from services.worker import llm
from services.worker.main import JobFailed, log

INSERT_BATCH = 200
SUMMARY_PART = 12000
SUMMARY_PARTS = 8
LITERATURE_CHARS = 15000
ALIGN_BATCH = 5000


def _kb_doc(db, document_id, lock=False) -> KbDocument:
    doc = db.get(KbDocument, document_id, with_for_update=lock)
    if not doc:
        raise JobFailed("DOCUMENT_DELETED", "文档已删除")
    return doc


def _doc_text(doc) -> str:
    if doc.kind in ("note", "guideline"):
        return doc.body or ""
    try:
        return Path(doc.text_path).read_text(encoding="utf-8") if doc.text_path else ""
    except FileNotFoundError:
        return ""


# ---- import ----


def _parse(kind, body, file_path, source):
    if kind in ("note", "guideline"):
        return kbparse.markdown(body or ""), {}
    if kind == "url":
        return kbparse.parse(source, "url")
    return kbparse.parse(file_path, kbparse.kind_of(file_path) or "txt")


def _embed(run, chunks):
    """Vectors and model name, or (None, None, reason) when the model is not available."""
    if not chunks:
        return None, None, None
    try:
        started = time.monotonic()
        embed.load(download=True)
        if time.monotonic() - started > 5:
            log.info("embedding model ready in %.1f s", time.monotonic() - started)
        vectors = []
        for i in range(0, len(chunks), embed.BATCH):
            run.progress(i, len(chunks), "向量化")
            vectors += embed.embed([c["text"] for c in chunks[i : i + embed.BATCH]])
        return vectors, embed.model_name(), None
    except embed.EmbedUnavailable as e:
        log.warning("embedding unavailable: %s", e)
        return None, None, str(e)


def run_kb_import(run):
    """Parse → chunk → embed → replace the document's chunks. Without an embedding model the chunks are kept
    for keyword search, the document is ready and `error` says why vectors are missing."""
    doc_id = uuid.UUID(run.params["document_id"])
    try:
        with transaction() as db:
            doc = _kb_doc(db, doc_id, lock=True)
            doc.status, doc.error = "parsing", None
            kind, body, file_path, source = (
                doc.kind,
                doc.body,
                doc.file_path,
                doc.source,
            )
        run.progress(0, None, "解析")
        try:
            blocks, meta = _parse(kind, body, file_path, source)
        except kbparse.ParseError as e:
            raise JobFailed("PARSE_ERROR", str(e)) from e
        chunks = kbchunk.chunk(blocks)
        if not chunks and kind not in ("note", "guideline"):
            raise JobFailed("EMPTY_DOCUMENT", "文档中没有可提取的文字")
        text_path = None
        if kind not in ("note", "guideline"):
            text_path = kb_dir(doc_id) / "text.txt"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(
                "\n\n".join(b["text"] for b in blocks), encoding="utf-8", newline="\n"
            )
        with transaction() as db:
            _kb_doc(db, doc_id).status = "embedding"
        vectors, model, warning = _embed(run, chunks)
        tsvs = [kbtext.tsv_text(c["text"]) for c in chunks]
        with transaction() as db:
            run.lock(db)
            doc = _kb_doc(db, doc_id, lock=True)
            db.execute(delete(KbChunk).where(KbChunk.document_id == doc_id))
            rows = [
                {
                    "document_id": doc_id,
                    "ordinal": i,
                    "text": c["text"],
                    "locator": c["locator"],
                    "embedding": vectors[i] if vectors else None,
                    "embed_model": model,
                    "tsv": func.to_tsvector(
                        literal_column("'simple'::regconfig"), tsvs[i]
                    ),
                }
                for i, c in enumerate(chunks)
            ]
            for i in range(0, len(rows), INSERT_BATCH):
                db.execute(insert(KbChunk).values(rows[i : i + INSERT_BATCH]))
            if kind == "url" and meta.get("title") and doc.title == doc.source:
                doc.title = meta["title"][:500]
            doc.meta = {
                **doc.meta,
                **{k: v for k, v in meta.items() if k not in doc.meta or k == "pages"},
            }
            doc.text_path = str(text_path) if text_path else None
            doc.chunk_count = len(chunks)
            doc.status = "ready"
            doc.error = (
                f"向量化未完成，仅支持关键词检索：{warning}" if warning else None
            )
            result = {
                "document_id": str(doc_id),
                "chunks": len(chunks),
                "embed_model": model,
            }
            if warning:
                result["warning"] = "EMBED_UNAVAILABLE"
            run.succeed(db, result)
    except BaseException as e:
        message = getattr(e, "message", None) or str(e)[:500] or "导入已取消"
        with transaction() as db:
            doc = db.get(KbDocument, doc_id, with_for_update=True)
            if doc and doc.status != "ready":
                doc.status = "ready" if doc.chunk_count else "failed"
                doc.error = message
        raise


# ---- summarize ----

SUMMARY_SYSTEM = "你是语言学与翻译研究助手。只依据给出的文本写摘要，不补充文本中没有的信息。直接输出摘要正文，不加标题。"
SUMMARY_PROMPT = "请用中文为下面的{what}写一段 200–400 字的摘要，概括研究问题、方法、材料和主要结论。\n\n标题：{title}\n\n{text}"
PART_PROMPT = "下面是一篇{what}的第 {i}/{n} 部分。请用中文列出这一部分的要点（不超过 300 字）。\n\n标题：{title}\n\n{text}"
COMBINE_PROMPT = "下面是一篇{what}各部分的要点。请据此用中文写一段 200–400 字的整体摘要，概括研究问题、方法、材料和主要结论。\n\n标题：{title}\n\n{text}"


def run_kb_summarize(run):
    doc_id = uuid.UUID(run.params["document_id"])
    with session() as db:
        doc = _kb_doc(db, doc_id)
        title, kind = doc.title, doc.kind
        text = _doc_text(doc)
        if not text.strip():
            text = "\n".join(
                db.scalars(
                    select(KbChunk.text)
                    .where(KbChunk.document_id == doc_id)
                    .order_by(KbChunk.ordinal)
                )
            )
    if not text.strip():
        raise JobFailed("DOCUMENT_NOT_READY", "文档没有可摘要的文字")
    what = {"note": "研究笔记", "guideline": "标注规范"}.get(kind, "文献")
    parts = [text[i : i + SUMMARY_PART] for i in range(0, len(text), SUMMARY_PART)][
        :SUMMARY_PARTS
    ]
    run.progress(0, len(parts) + (len(parts) > 1), "摘要")
    if len(parts) == 1:
        summary = llm.chat(
            SUMMARY_SYSTEM, SUMMARY_PROMPT.format(what=what, title=title, text=parts[0])
        )
    else:
        notes = []
        for i, part in enumerate(parts, 1):
            notes.append(
                llm.chat(
                    SUMMARY_SYSTEM,
                    PART_PROMPT.format(
                        what=what, i=i, n=len(parts), title=title, text=part
                    ),
                )
            )
            run.progress(i, len(parts) + 1, "摘要")
        summary = llm.chat(
            SUMMARY_SYSTEM,
            COMBINE_PROMPT.format(what=what, title=title, text="\n\n".join(notes)),
        )
    with transaction() as db:
        run.lock(db)
        doc = _kb_doc(db, doc_id, lock=True)
        doc.meta = {
            **doc.meta,
            "summary": summary,
            "summary_source": "model",
            "summary_model": llm.model_id(),
            "summary_truncated": len(text) > SUMMARY_PART * SUMMARY_PARTS,
        }
        run.succeed(db, {"document_id": str(doc_id), "chars": len(summary)})


# ---- term extraction ----

TERMS_SYSTEM = (
    "你是术语学与翻译研究助手。只输出 JSON 数组，不输出其他文字。每个元素为 "
    '{"term": 术语原文, "language": "zh" 或 "en" 等语言代码, "translations": [{"language": 语言代码, "text": 译名}], '
    '"definition": 一句话定义（用中文）, "domain": 领域}。不确定的字段用 null；不要编造原文中没有依据的术语。'
)
CANDIDATES_PROMPT = (
    "下面是从语料中按词性模式统计出的候选术语（含频次与对齐语料中的候选译名）。"
    "请挑出其中真正的领域术语（不超过 {top} 条），给出规范的译名、简短定义和领域，剔除普通搭配。\n\n{items}"
)
LITERATURE_PROMPT = "请从下面的文献中抽取不超过 {top} 条领域术语，给出另一种语言（中文或英文）的译名、简短定义和领域。\n\n标题：{title}\n\n{text}"


def _aligned_pairs(db, corpus, filt, fields):
    """Aligned sentence pairs of the scope (filter on the source side) as terms.translate() takes them,
    plus {sentence id: (text, document_id, start_cp, end_cp, title)} for examples."""
    src = aliased(Sentence)
    ids = db.execute(
        select(SentenceAlignment.src_sentence_id, SentenceAlignment.tgt_sentence_id)
        .join(src, src.id == SentenceAlignment.src_sentence_id)
        .join(Document, Document.id == src.document_id)
        .where(*scope_clauses(corpus, filt, fields))
    ).all()
    needed = sorted({i for pair in ids for i in pair})
    info, toks = {}, {}
    for k in range(0, len(needed), ALIGN_BATCH):
        batch = needed[k : k + ALIGN_BATCH]
        for sid, text, doc_id, a, b, lang, title in db.execute(
            select(
                Sentence.id,
                Sentence.text,
                Sentence.document_id,
                Sentence.start_cp,
                Sentence.end_cp,
                Document.language,
                Document.title,
            )
            .join(Document, Document.id == Sentence.document_id)
            .where(Sentence.id.in_(batch))
        ):
            info[sid] = (text, doc_id, a, b, lang, title)
        for sid, form, pos, lemma in db.execute(
            select(Token.sentence_id, Token.form, Token.pos, Token.lemma)
            .where(Token.sentence_id.in_(batch))
            .order_by(Token.sentence_id, Token.idx)
        ):
            toks.setdefault(sid, []).append((form, pos, lemma))
    pairs = [
        ((info[s][4], toks.get(s, []), s), (info[t][4], toks.get(t, []), t))
        for s, t in ids
        if s in info and t in info
    ]
    return pairs, info


def _clean_drafts(items, source):
    drafts, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("term"), str):
            continue
        term = item["term"].strip()[:200]
        language = (
            kbterms.lang_code(item.get("language"))
            if isinstance(item.get("language"), str)
            else ""
        )
        language = language or ("zh" if re.search(r"[一-鿿]", term) else "en")
        if not term or (term, language) in seen:
            continue
        seen.add((term, language))
        translations = [
            {
                "language": kbterms.lang_code(t["language"]),
                "text": t["text"].strip()[:500],
            }
            for t in item.get("translations") or []
            if isinstance(t, dict)
            and isinstance(t.get("language"), str)
            and isinstance(t.get("text"), str)
            and t["text"].strip()
        ]
        definition = (
            item.get("definition") if isinstance(item.get("definition"), str) else None
        )
        domain = item.get("domain") if isinstance(item.get("domain"), str) else None
        drafts.append(
            {
                "term": term,
                "language": language,
                "translations": translations[:20],
                "definition": definition[:5000] if definition else None,
                "domain": domain[:200] if domain else None,
                "examples": [],
                "source": source,
            }
        )
    return drafts


def _corpus_candidates(run, p):
    with session() as db:
        user = db.get(User, run.owner_id)
        scope = Scope.model_validate(p["scope"])
        corpus, restrict = resolve_scope(db, scope, user)
        target = stats.Scope(index_dir(corpus.id), corpus_key(corpus.id), restrict)
        filt = scope_filter(db, scope)
        fields = field_types(db, corpus.id) if filt else {}
        language, parallel, name = corpus.language, corpus.parallel, corpus.name
    run.progress(0, None, "统计候选")
    languages = [kbterms.lang_code(p["language"])] if p.get("language") else None
    try:
        pairs, unigrams = kbterms.scan_scope(target)
    except ValueError as e:
        raise JobFailed("STATS_INVALID", str(e)) from e
    cands = kbterms.rank(pairs, unigrams, p["top"], p["min_freq"], languages, language)
    info = {}
    if parallel and cands:
        run.progress(0, None, "对齐译名")
        with session() as db:
            corpus = db.get(Corpus, corpus.id)
            aligned, info = _aligned_pairs(db, corpus, filt, fields)
        kbterms.translate(cands, aligned)
    return cands, info, name


def _candidate_draft(c, info, name):
    examples = []
    if c.example in info:
        text, doc_id, a, b, _, title = info[c.example]
        examples.append(
            {
                "text": text,
                "source": f"{name}《{title}》",
                "document_id": str(doc_id),
                "start_cp": a,
                "end_cp": b,
            }
        )
    return {
        "term": c.term,
        "language": c.language,
        "translations": [
            {"language": t["language"], "text": t["text"]} for t in c.translations
        ],
        "definition": None,
        "domain": None,
        "examples": examples,
        "source": "corpus",
    }


def _literature_drafts(run, p):
    with session() as db:
        docs = [
            (d.title, _doc_text(d))
            for d in db.scalars(
                select(KbDocument).where(KbDocument.id.in_(p["document_ids"]))
            )
        ]
    drafts = []
    for i, (title, text) in enumerate(docs):
        run.progress(i, len(docs), "抽取术语")
        answer = llm.chat(
            TERMS_SYSTEM,
            LITERATURE_PROMPT.format(
                top=min(p["top"], 50), title=title, text=text[:LITERATURE_CHARS]
            ),
        )
        drafts += _clean_drafts(llm.json_array(answer), "model")
    return drafts


def run_kb_extract(run):
    p = run.params
    project_id = uuid.UUID(p["project_id"])
    if p["source"] == "literature":
        drafts = _literature_drafts(run, p)
    else:
        cands, info, name = _corpus_candidates(run, p)
        if p["method"] == "model" and cands:
            run.progress(0, None, "模型整理")
            items = "\n".join(
                f"- {c.term}（{c.language}，{c.pattern}，频次 {c.freq}"
                + (f"，候选译名 {c.translations[0]['text']}" if c.translations else "")
                + "）"
                for c in cands
            )
            answer = llm.chat(
                TERMS_SYSTEM, CANDIDATES_PROMPT.format(top=p["top"], items=items)
            )
            drafts = _clean_drafts(llm.json_array(answer), "model")
        else:
            drafts = [_candidate_draft(c, info, name) for c in cands]
    created = 0
    with transaction() as db:
        run.lock(db)
        base = datetime.now(UTC)
        for i, d in enumerate(
            drafts
        ):  # created_at decreases with rank: newest-first lists keep the ranking
            stmt = (
                pg_insert(KbTerm)
                .values(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    status="draft",
                    created_by=run.owner_id,
                    created_at=base - timedelta(milliseconds=i),
                    updated_at=base,
                    **d,
                )
                .on_conflict_do_nothing(constraint="uq_kb_terms_term")
                .returning(KbTerm.id)
            )
            created += db.execute(stmt).scalar() is not None
        run.succeed(
            db,
            {
                "created": created,
                "skipped": len(drafts) - created,
                "candidates": len(drafts),
            },
        )


# ---- exports ----


def _finish(run, path, filename, extra=None):
    with transaction() as db:
        run.lock(db)
        run.succeed(db, {**(extra or {}), "filename": filename})


def _stamp():
    return f"{datetime.now():%Y%m%d-%H%M}"


TBX_NS = "urn:iso:std:iso:30042:ed-2"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def write_tbx(path, terms):
    """TBX-Basic (TBX v3 DCA): one conceptEntry per term, a langSec for the term and one per translation
    language; definition and domain on the entry's language / concept level, examples as context."""
    root = etree.Element(
        "tbx",
        nsmap={None: TBX_NS},
        attrib={"style": "dca", "type": "TBX-Basic", XML_LANG: "zh"},
    )
    header = etree.SubElement(root, "tbxHeader")
    desc = etree.SubElement(etree.SubElement(header, "fileDesc"), "sourceDesc")
    etree.SubElement(desc, "p").text = "Corpus workbench term base export"
    body = etree.SubElement(etree.SubElement(root, "text"), "body")
    for n, t in enumerate(terms, 1):
        entry = etree.SubElement(body, "conceptEntry", id=f"c{n}")
        if t.domain:
            etree.SubElement(entry, "descrip", type="subjectField").text = t.domain
        sec = etree.SubElement(entry, "langSec", {XML_LANG: t.language})
        if t.definition:
            etree.SubElement(sec, "descrip", type="definition").text = t.definition
        term_sec = etree.SubElement(sec, "termSec")
        etree.SubElement(term_sec, "term").text = t.term
        if t.status == "confirmed":
            etree.SubElement(
                term_sec, "termNote", type="administrativeStatus"
            ).text = "preferredTerm-admn-sts"
        for e in t.examples[:5]:
            etree.SubElement(term_sec, "descrip", type="context").text = e.get(
                "text", ""
            )
        by_lang = {}
        for tr in t.translations:
            by_lang.setdefault(tr["language"], []).append(tr["text"])
        for lang, texts in by_lang.items():
            tsec = etree.SubElement(entry, "langSec", {XML_LANG: lang})
            for text in texts:
                etree.SubElement(etree.SubElement(tsec, "termSec"), "term").text = text
    etree.ElementTree(root).write(
        str(path), xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def run_export_terms(run):
    from services.worker.tasks import _write_xlsx

    p = run.params
    with session() as db:
        stmt = select(KbTerm).where(KbTerm.project_id == uuid.UUID(p["project_id"]))
        if p.get("status"):
            stmt = stmt.where(KbTerm.status == p["status"])
        terms = db.scalars(stmt.order_by(KbTerm.language, KbTerm.term)).all()
    fmt = p["format"]
    path = export_path(run.id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "tbx":
        write_tbx(path, terms)
    else:
        header = ["术语", "语言", "译名", "定义", "领域", "例句", "来源", "状态"]
        rows = [
            [
                t.term,
                t.language,
                "；".join(f"{x['language']}: {x['text']}" for x in t.translations),
                t.definition,
                t.domain,
                "\n".join(
                    f"{e.get('text', '')}（{e.get('source', '')}）" for e in t.examples
                ),
                t.source,
                {"draft": "草稿", "confirmed": "已确认"}[t.status],
            ]
            for t in terms
        ]
        if fmt == "csv":
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows([header, *rows])
        else:
            _write_xlsx(path, header, rows, "术语表")
    _finish(run, path, f"术语表-{_stamp()}.{fmt}", {"rows": len(terms)})


_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _plain(s):
    return s.replace("**", "").replace("__", "").replace("`", "")


def _ref_lines(kind, ref):
    label = {
        "search": "检索",
        "stat": "统计",
        "evidence": "证据",
        "chunk": "知识片段",
        "term": "术语",
    }[kind]
    lines = []
    head = (
        ref.get("title")
        or ref.get("term")
        or ref.get("name")
        or ref.get("method")
        or ""
    )
    if ref.get("text"):
        lines.append(ref["text"])
    if ref.get("source") or head:
        lines.append(f"出处：{ref.get('source') or head}")
    if ref.get("locator"):
        loc = ref["locator"]
        where = (
            f"第 {loc['page']} 页"
            if loc.get("page")
            else " / ".join(loc.get("heading_path") or [])
        )
        if where:
            lines.append(f"位置：{where}")
    query = ref.get("search_query") or ref.get("query")
    if query:
        lines.append(f"查询式：{query}")
    return label, lines


def _write_note_docx(path, title, body, refs):
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    def heading(text, size):
        run_ = doc.add_paragraph().add_run(text)
        run_.bold, run_.font.size = True, Pt(size)

    heading(title, 16)
    fence = False
    for line in body.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            heading(_plain(m.group(2)), max(11, 16 - len(m.group(1))))
        elif not line.strip():
            continue
        elif line.lstrip().startswith(">") and not fence:
            if not line.lstrip()[1:].strip():
                continue
            p = doc.add_paragraph(_plain(line.lstrip()[1:].strip()))
            p.paragraph_format.left_indent = Pt(21)
        elif _LIST.match(line) and not fence:
            doc.add_paragraph("• " + _plain(_LIST.sub("", line, count=1)))
        else:
            doc.add_paragraph(line if fence else _plain(line))
    if refs:
        heading("引用", 14)
        for i, r in enumerate(refs, 1):
            label, lines = _ref_lines(r.kind, r.ref)
            doc.add_paragraph(f"{i}. [{label}] " + (lines[0] if lines else ""))
            for line in lines[1:]:
                doc.add_paragraph(line).paragraph_format.left_indent = Pt(21)
    doc.save(path)


def _note_md(title, body, refs):
    out = body if body.lstrip().startswith("# ") else f"# {title}\n\n{body}"
    if refs:
        out = out.rstrip() + "\n\n## 引用\n\n"
        for i, r in enumerate(refs, 1):
            label, lines = _ref_lines(r.kind, r.ref)
            out += (
                f"{i}. [{label}] "
                + (lines[0].replace("\n", " ") if lines else "")
                + "\n"
            )
            out += "".join(f"   - {line}\n" for line in lines[1:])
    return out


def run_export_note(run):
    p = run.params
    with session() as db:
        doc = _kb_doc(db, uuid.UUID(p["document_id"]))
        title, body = doc.title, doc.body or ""
        refs = db.scalars(
            select(NoteRef).where(NoteRef.note_id == doc.id).order_by(NoteRef.id)
        ).all()
    fmt = p["format"]
    path = export_path(run.id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "docx":
        _write_note_docx(path, title, body, refs)
    else:
        path.write_text(_note_md(title, body, refs), encoding="utf-8", newline="\n")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60] or "笔记"
    _finish(run, path, f"{safe}-{_stamp()}.{fmt}", {"refs": len(refs)})
