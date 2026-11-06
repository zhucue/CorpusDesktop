"""P10 job plumbing: tidy CSV exports download as zip; job summaries of the new kinds and methods."""

import io
import uuid
import zipfile
from datetime import UTC, datetime


def _job(owner, project, kind, params, result=None):
    from services.api.db import transaction
    from services.api.models import Job

    with transaction() as db:
        job = Job(
            kind=kind,
            params=params,
            owner_id=uuid.UUID(owner.user_id),
            project_id=uuid.UUID(project["id"]),
            state="succeeded",
            result=result,
            finished_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
        return str(job.id)


def test_tidy_zip_download(owner, project):
    from services.api.storage import export_path

    job = _job(
        owner,
        project,
        "export",
        {"source": "tidy", "format": "zip", "table_format": "csv"},
        {"filename": "整洁数据.zip", "rows": 1},
    )
    path = export_path(job, "zip")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tidy_data.csv", "document_id\nd1\n")
    r = owner.get(f"/api/jobs/{job}/download")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["tidy_data.csv"]
    assert owner.get(f"/api/jobs/{job}").json()["summary"] == "整洁数据 · ZIP"


def test_new_job_summaries(owner, project):
    corpus = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "zh"},
    ).json()
    embed = _job(owner, project, "embed_corpus", {"corpus_id": corpus["id"]})
    assert owner.get(f"/api/jobs/{embed}").json()["summary"] == "作文"
    scope = {"corpus_id": corpus["id"]}
    for method, name in (
        ("text_metrics", "文本指标"),
        ("vocab_profile", "词汇等级"),
        ("word_sketch", "词汇画像"),
        ("sketch_diff", "近义词对比"),
    ):
        job = _job(owner, project, "stats", {"method": method, "scope": scope})
        assert owner.get(f"/api/jobs/{job}").json()["summary"] == f"{name} · 作文"
    items = [{"label": "a", "scope": scope}, {"label": "b", "scope": scope}]
    job = _job(owner, project, "stats", {"method": "compare", "items": items})
    assert owner.get(f"/api/jobs/{job}").json()["summary"] == "对比 · 2 项"
