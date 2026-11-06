"""Local data volume layout: uploads, document texts, CWB indexes, exports."""

import os
from pathlib import Path
from uuid import UUID

from services.api.db import data_dir


def upload_dir(job_id):
    return data_dir() / "uploads" / str(job_id)


def corpus_dir(corpus_id):
    return data_dir() / "corpora" / str(corpus_id)


def text_path(corpus_id, document_id):
    return corpus_dir(corpus_id) / "texts" / f"{document_id}.txt"


def index_dir(corpus_id):
    return corpus_dir(corpus_id) / "index"


def corpus_key(corpus_id):
    return "C" + UUID(str(corpus_id)).hex.upper()


def export_path(job_id, fmt):
    return data_dir() / "exports" / f"{job_id}.{fmt}"


def stats_path(stat_id):
    return data_dir() / "stats" / f"{stat_id}.json"


def kb_dir(document_id):
    """Knowledge base document files: the upload (source.<ext>) and the extracted text (text.txt)."""
    return data_dir() / "kb" / str(document_id)


def dir_bytes(path) -> int:
    """Size of the files under path, or of the file itself (0 when missing)."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total
