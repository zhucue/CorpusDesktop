"""Local data volume layout: uploads, document texts, CWB indexes, exports."""

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
