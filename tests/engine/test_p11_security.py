"""P11 security (contracts/p11.md §三 2–3): unpacked-size limits of compressed uploads and URL import pinned
to the checked address (DNS rebinding), with a fake resolver and a mock transport (no network)."""

import bz2
import io
import socket
import zipfile
from pathlib import Path

import httpx
import pytest

from engine import parsers
from engine.kb import parse as kbparse
from engine.parsers import table

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _bomb_docx(path: Path, size: int) -> Path:
    """A DOCX-shaped zip whose single member inflates to `size` zero bytes (a few KB on disk)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        with z.open("word/document.xml", "w") as f:
            chunk = b"\0" * (1024 * 1024)
            for _ in range(size // len(chunk)):
                f.write(chunk)
    return path


def test_docx_bomb_rejected_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UNPACKED_BYTES", str(8 * 1024 * 1024))
    bomb = _bomb_docx(tmp_path / "bomb.docx", 16 * 1024 * 1024)
    assert bomb.stat().st_size < 200_000
    with pytest.raises(parsers.ParseError, match="bomb.docx 文件解压后过大"):
        parsers.parse(bomb, language="zh", metadata={})
    with pytest.raises(kbparse.ParseError, match="文件解压后过大"):
        kbparse.parse(bomb, "docx")


def test_zip_member_count_and_real_files(tmp_path, monkeypatch):
    many = tmp_path / "many.xlsx"
    with zipfile.ZipFile(many, "w") as z:
        for i in range(30):
            z.writestr(f"x/{i}.xml", "<a/>")
    monkeypatch.setenv("MAX_UNPACKED_FILES", "20")
    with pytest.raises(parsers.ParseError, match="超过 20 个文件"):
        table.preview(many.read_bytes(), "many.xlsx", partial=False)
    monkeypatch.delenv("MAX_UNPACKED_FILES")
    # ordinary files pass with the defaults
    doc = parsers.parse(FIXTURES / "sample.docx", language="zh", metadata={})[0][0]
    assert doc.text
    assert kbparse.parse(FIXTURES / "kb-sample.docx", "docx")[0]


def test_pdf_page_and_text_limits(monkeypatch):
    monkeypatch.setenv("MAX_PDF_PAGES", "1")
    with pytest.raises(kbparse.ParseError, match="超过 1 页"):
        kbparse.parse(FIXTURES / "kb-sample.pdf", "pdf")
    with pytest.raises(parsers.ParseError, match="文件解压后过大"):
        parsers.parse(FIXTURES / "kb-sample.pdf", language="en", metadata={})
    monkeypatch.setenv("MAX_PDF_PAGES", "5000")
    monkeypatch.setenv("MAX_UNPACKED_BYTES", "100")
    with pytest.raises(kbparse.ParseError, match="超过 100 字节"):
        kbparse.parse(FIXTURES / "kb-sample.pdf", "pdf")


def test_bz2_stream_limit(tmp_path, monkeypatch):
    rows = "".join(f"{i}\teng\tSentence number {i}.\n" for i in range(1, 2000))
    path = tmp_path / "eng_sentences.tsv.bz2"
    path.write_bytes(bz2.compress(rows.encode()))
    docs, _ = parsers.parse(path, language=None, metadata={})
    assert len(docs[0].sentences) == 1999
    monkeypatch.setenv("MAX_UNPACKED_BYTES", "10000")
    with pytest.raises(
        parsers.ParseError, match="eng_sentences.tsv.bz2 文件解压后过大"
    ):
        parsers.parse(path, language=None, metadata={})


def test_xlsx_preview_bytes_checked(monkeypatch):
    from openpyxl import Workbook

    buf = io.BytesIO()
    wb = Workbook()
    wb.active.append(["text"])
    wb.active.append(["hello"])
    wb.save(buf)
    data = buf.getvalue()
    assert table.preview(data, "a.xlsx", partial=False)["columns"] == ["text"]
    monkeypatch.setenv("MAX_UNPACKED_BYTES", "500")
    with pytest.raises(parsers.ParseError, match="文件解压后过大"):
        table.preview(data, "a.xlsx", partial=False)


# ---- URL import: DNS rebinding ----


class Resolver:
    """getaddrinfo stand-in: answers[host] is a list of address lists, one per call (the last repeats)."""

    def __init__(self, **answers):
        self.answers = {k.replace("_", "."): v for k, v in answers.items()}
        self.calls = []

    def __call__(self, host, port, *args, **kwargs):
        self.calls.append(host)
        seq = self.answers[host]
        ips = seq[min(self.calls.count(host) - 1, len(seq) - 1)]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]


PAGE = b"<html><body><article><p>Corpus page.</p></article></body></html>"


def _transport(seen, routes=None):
    def handler(request):
        seen.append(request)
        location = (routes or {}).get(request.url.path)
        if location:
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, content=PAGE)

    return httpx.MockTransport(handler)


def test_connects_to_the_checked_address_with_host_and_sni():
    # first answer public, any later answer internal: the fetch must use the first one only
    resolver = Resolver(example_org=[["93.184.216.34"], ["127.0.0.1"]])
    seen = []
    body = kbparse.fetch(
        "https://example.org/a?x=1#frag", resolver=resolver, transport=_transport(seen)
    )
    assert body == PAGE
    assert resolver.calls == ["example.org"]
    [req] = seen
    assert req.url.host == "93.184.216.34" and req.url.path == "/a"
    assert req.headers["host"] == "example.org"
    assert req.extensions["sni_hostname"] == "example.org"


def test_rebinding_to_internal_address_is_refused():
    # the api's request-time check saw a public address; at fetch time the name points inside
    resolver = Resolver(rebind_test=[["93.184.216.34"], ["10.0.0.7"]])
    assert kbparse.check_public_url("http://rebind.test/", resolver=resolver)
    seen = []
    with pytest.raises(kbparse.ParseError, match="只能导入公网地址"):
        kbparse.fetch(
            "http://rebind.test/", resolver=resolver, transport=_transport(seen)
        )
    assert seen == []


def test_any_internal_answer_is_refused():
    resolver = Resolver(mixed_test=[["93.184.216.34", "192.168.1.5"]])
    seen = []
    with pytest.raises(kbparse.ParseError, match="只能导入公网地址"):
        kbparse.fetch(
            "http://mixed.test/", resolver=resolver, transport=_transport(seen)
        )
    assert seen == []


def test_each_redirect_hop_is_checked_and_pinned():
    resolver = Resolver(
        a_test=[["93.184.216.34"]],
        b_test=[["93.184.216.35"]],
        c_test=[["169.254.169.254"]],
    )
    seen = []
    routes = {"/start": "http://b.test:8080/next", "/next": "http://c.test/meta"}
    with pytest.raises(kbparse.ParseError, match="只能导入公网地址"):
        kbparse.fetch(
            "http://a.test/start", resolver=resolver, transport=_transport(seen, routes)
        )
    assert [(r.url.host, r.url.port, r.headers["host"]) for r in seen] == [
        ("93.184.216.34", None, "a.test"),
        ("93.184.216.35", 8080, "b.test:8080"),
    ]
    assert "sni_hostname" not in seen[0].extensions  # plain http
