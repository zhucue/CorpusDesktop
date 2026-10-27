"""Document → blocks `{text, locator}` plus file metadata.

pdf: one block per page (pypdf), locator {page} (1-based). docx: one block per paragraph, locator
{heading_path} from Heading / 标题 / Title styles. md / txt: one block per paragraph (blank-line separated),
locator {line} (1-based) plus {heading_path} under ATX headings (`# …`). url: fetched with httpx (http/https,
no private / loopback / link-local addresses, ≤ 10 MB, ≤ 5 redirects), main text by trafilatura as Markdown, then parsed as md.
Heading lines are not block text; they only set the path.
"""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zipfile import BadZipFile

KINDS = ("pdf", "docx", "md", "txt", "url")
MAX_FETCH = 10 * 1024 * 1024
# Internal ranges a URL import must not reach (container network, host, metadata services). 198.18.0.0/15 is
# allowed: the fake-IP DNS of outbound proxies answers from it.
_BLOCKED = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/3",
        "::/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")
_DOCX_HEADING = re.compile(r"^(?:Heading|标题)\s*(\d)$", re.IGNORECASE)


class ParseError(ValueError):
    pass


def kind_of(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    return {
        ".pdf": "pdf",
        ".docx": "docx",
        ".md": "md",
        ".markdown": "md",
        ".txt": "txt",
    }.get(suffix)


def parse(source, kind: str) -> tuple[list[dict], dict]:
    """source: a file path, or for kind url the URL. Returns (blocks, meta)."""
    if kind == "pdf":
        return _pdf(Path(source))
    if kind == "docx":
        return _docx(Path(source))
    if kind in ("md", "txt"):
        return markdown(_read(Path(source))), {}
    if kind == "url":
        return html(fetch(source), source)
    raise ParseError(f"不支持的类型：{kind}")


def _read(path: Path) -> str:
    try:
        raw = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ParseError(f"{path.name} 不是 UTF-8 编码") from e
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def _join_lines(text: str) -> str:
    """PDF line breaks inside a paragraph: dropped between CJK characters, a space otherwise (a hyphen
    before a lower-case continuation is removed); blank lines separate paragraphs."""
    paras = []
    for para in re.split(r"\n\s*\n", text):
        out = ""
        for line in (x.strip() for x in para.split("\n")):
            if not line:
                continue
            if out and not (_CJK.match(out[-1]) and _CJK.match(line[0])):
                if out.endswith("-") and line[0].islower():
                    out = out[:-1]
                else:
                    out += " "
            out += line
        if out:
            paras.append(out)
    return "\n".join(paras)


def _pdf(path: Path):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(path)
        blocks = []
        for i, page in enumerate(reader.pages, 1):
            text = _join_lines(page.extract_text() or "")
            if text:
                blocks.append({"text": text, "locator": {"page": i}})
        info = reader.metadata or {}
        meta = {"pages": len(reader.pages)}
    except (PdfReadError, ValueError, KeyError) as e:
        raise ParseError(f"{path.name} 无法解析：{e}") from e
    for key, name in (("/Title", "title"), ("/Author", "author")):
        value = str(info.get(key) or "").strip()
        if value:
            meta[name] = value
    if not blocks:
        raise ParseError(f"{path.name} 没有可提取的文字（可能是扫描件）")
    return blocks, meta


def _heading_locator(path_, **extra):
    return {**({"heading_path": list(path_)} if path_ else {}), **extra}


def _docx(path: Path):
    from docx import Document
    from docx.opc.exceptions import PackageNotFoundError

    try:
        doc = Document(str(path))
    except (PackageNotFoundError, BadZipFile, KeyError, ValueError) as e:
        raise ParseError(f"{path.name} 不是有效的 DOCX") from e
    path_, blocks = [], []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = p.style.name if p.style is not None else ""
        m = _DOCX_HEADING.match(style)
        level = int(m.group(1)) if m else (1 if style == "Title" else 0)
        if level:
            path_ = path_[: level - 1] + [text]
            continue
        blocks.append({"text": text, "locator": _heading_locator(path_)})
    meta = {}
    props = doc.core_properties
    if (props.title or "").strip():
        meta["title"] = props.title.strip()
    if (props.author or "").strip():
        meta["author"] = props.author.strip()
    return blocks, meta


def markdown(text: str) -> list[dict]:
    """Paragraph blocks of Markdown / plain text with {line[, heading_path]}; a fenced code block stays whole."""
    path_, blocks, buf, start, fence = [], [], [], 0, False

    def flush():
        para = "\n".join(buf).strip()
        if para:
            blocks.append(
                {"text": para, "locator": _heading_locator(path_, line=start)}
            )
        buf.clear()

    for n, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path_ = path_[: level - 1] + [m.group(2)]
            continue
        if not line.strip() and not fence:
            flush()
            continue
        if not buf:
            start = n
        buf.append(line)
    flush()
    return blocks


# ---------------------------------------------------------------- url


def check_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ParseError("URL 须以 http:// 或 https:// 开头")
    return url


def _blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_link_local or any(ip in net for net in _BLOCKED)


def _check_public(host: str):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ParseError(f"无法解析域名：{host}") from e
    if any(_blocked(info[4][0]) for info in infos):
        raise ParseError("只能导入公网地址")


def check_public_url(url: str) -> str:
    """Request-time check: http(s) URL whose host is not a private, loopback, link-local, CGNAT or multicast
    address (literal or resolved). A name that does not resolve here passes; the worker checks again on fetch."""
    url = check_url(url)
    host = urlsplit(url).hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked(host):
            raise ParseError("只能导入公网地址")
        return url
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return url
    if any(_blocked(info[4][0]) for info in infos):
        raise ParseError("只能导入公网地址")
    return url


def normalize_url(url: str) -> str:
    """Comparable form of a URL: lower-case scheme and host, no default port, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and (scheme, port) not in (("http", 80), ("https", 443)):
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{scheme}://{host}{path}{query}"


def fetch(url: str) -> bytes:
    import httpx

    url = check_url(url)
    headers = {
        "User-Agent": "CorpusWorkbench/1.0 (knowledge base URL import) python-httpx"
    }
    try:
        with httpx.Client(timeout=30, headers=headers) as client:
            for _ in range(6):
                _check_public(urlsplit(url).hostname)
                with client.stream("GET", url) as r:
                    if r.is_redirect:
                        url = check_url(urljoin(url, r.headers.get("location", "")))
                        continue
                    if r.status_code >= 400:
                        raise ParseError(f"网页返回 HTTP {r.status_code}")
                    body = bytearray()
                    for part in r.iter_bytes():
                        body += part
                        if len(body) > MAX_FETCH:
                            raise ParseError("网页超过 10 MB")
                    return bytes(body)  # trafilatura detects the encoding
    except httpx.HTTPError as e:
        raise ParseError(f"网页下载失败：{e}") from e
    raise ParseError("重定向次数过多")


def html(page: str | bytes, url: str | None = None) -> tuple[list[dict], dict]:
    import trafilatura

    text = trafilatura.extract(
        page,
        url=url,
        output_format="markdown",
        include_formatting=True,
        include_comments=False,
        include_tables=True,
    )
    if not text or not text.strip():
        raise ParseError("网页中没有可提取的正文")
    meta = {}
    info = trafilatura.extract_metadata(page, default_url=url)
    if info is not None:
        for key in ("title", "author", "sitename", "date"):
            value = getattr(info, key, None)
            if value:
                meta[key] = str(value)
    return markdown(text), meta
