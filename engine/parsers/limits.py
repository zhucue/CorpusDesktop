"""Unpacked-size limits for compressed uploads (contracts/p11.md §三 2), shared by corpus import and the
knowledge base.

DOCX / XLSX (zip): before parsing, the sum of the members' declared sizes must not exceed MAX_UNPACKED_BYTES
(default 500 MB) and the member count MAX_UNPACKED_FILES (default 10,000). Python's zipfile stops each member
at its declared size, so the declared sum bounds what python-docx and openpyxl can inflate.
.bz2 (Tatoeba TSV): the decompressed stream is counted while it is read, same byte limit.
PDF (streams are inflated page by page inside pypdf, which caps each stream): at most MAX_PDF_PAGES pages
(default 5,000) and at most MAX_UNPACKED_BYTES of extracted text.
Over a limit: `error(f"{name} 文件解压后过大（…）")`.
"""

import bz2
import io
import os
import zipfile

MB = 1024 * 1024
TOO_LARGE = "文件解压后过大"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def max_unpacked_bytes() -> int:
    return _int_env("MAX_UNPACKED_BYTES", 500 * MB)


def max_unpacked_files() -> int:
    return _int_env("MAX_UNPACKED_FILES", 10_000)


def max_pdf_pages() -> int:
    return _int_env("MAX_PDF_PAGES", 5_000)


def _mb(n: int) -> str:
    return f"{n / MB:g} MB" if n >= MB else f"{n} 字节"


def too_large(name: str, limit: int, error=ValueError):
    return error(f"{name} {TOO_LARGE}（超过 {_mb(limit)}）")


def check_zip(source, name: str, error=ValueError) -> None:
    """source: path or binary file object of a zip container (DOCX, XLSX). A file that is not a zip is left
    to the parser, which reports it in its own words."""
    try:
        with zipfile.ZipFile(source) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return
    finally:
        if hasattr(source, "seek"):
            source.seek(0)
    files = max_unpacked_files()
    if len(infos) > files:
        raise error(f"{name} {TOO_LARGE}（超过 {files} 个文件）")
    limit = max_unpacked_bytes()
    if sum(i.file_size for i in infos) > limit:
        raise too_large(name, limit, error)


class _Counted(io.RawIOBase):
    """Decompressed bytes of a bz2 file, failing once more than `limit` bytes have been read."""

    def __init__(self, raw, name: str, limit: int, error):
        self.raw, self.name_, self.limit, self.error, self.total = (
            raw,
            name,
            limit,
            error,
            0,
        )

    def readable(self):
        return True

    def readinto(self, b):
        data = self.raw.read(len(b))
        self.total += len(data)
        if self.total > self.limit:
            raise too_large(self.name_, self.limit, self.error)
        b[: len(data)] = data
        return len(data)

    def close(self):
        self.raw.close()
        super().close()


def open_bz2_text(path, name: str, error=ValueError, **text_args):
    """bz2 file as text (TextIOWrapper arguments in text_args), limited to MAX_UNPACKED_BYTES decompressed."""
    raw = _Counted(bz2.open(path, "rb"), name, max_unpacked_bytes(), error)  # noqa: SIM115
    return io.TextIOWrapper(io.BufferedReader(raw), **text_args)
