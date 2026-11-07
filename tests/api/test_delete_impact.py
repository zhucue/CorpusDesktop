"""P7 §二 delete impact (corpus / document) and §四 clearing one's own evidence."""

import uuid

import pytest

from tests.api.conftest import drain, upload

TEXT_A = "Language is a system.\nThe language of science."
TEXT_B = "Grammar rules apply.\nA language again."


def make_corpus(client, project, name, files):
    c = client.post(
        f"/api/projects/{project['id']}/corpora", json={"name": name, "language": "en"}
    ).json()
    upload(client, c["id"], files)
    drain()
    docs = client.get(f"/api/corpora/{c['id']}/documents").json()["items"]
    c["docs"] = {d["title"]: d["id"] for d in docs}
    return c


@pytest.fixture
def annotated(owner, project):
    """Corpus 作文 (documents a, b) with a pos, span, relation and empty layer, plus an alignment layer from
    another corpus whose target is 作文. Statuses mix model suggestions with human decisions."""
    from services.api.db import transaction
    from services.api.models import (
        AlignmentAnnotation,
        Annotation,
        AnnotationLayer,
        RelationAnnotation,
        SpanAnnotation,
    )

    c = make_corpus(owner, project, "作文", {"a.txt": TEXT_A, "b.txt": TEXT_B})
    other = make_corpus(owner, project, "译文", {"t.txt": "Une langue."})
    a, b = (uuid.UUID(c["docs"][k]) for k in ("a", "b"))
    t = uuid.UUID(other["docs"]["t"])
    me = uuid.UUID(owner.user_id)
    pid = uuid.UUID(project["id"])
    ids = {}
    with transaction() as db:

        def layer(name, kind, corpus_id, **extra):
            row = AnnotationLayer(
                project_id=pid,
                corpus_id=corpus_id,
                kind=kind,
                name=name,
                source_model="fake",
                status="ready",
                progress={},
                annotators=[me],
                created_by=me,
                **extra,
            )
            db.add(row)
            db.flush()
            ids[name] = str(row.id)
            return row

        cid = uuid.UUID(c["id"])
        pos = layer("词性", "pos", cid)
        for doc, i, status in [
            (a, 1, "suggested"),
            (a, 2, "confirmed"),
            (a, 3, "modified"),
            (b, 1, "rejected"),
            (b, 2, "suggested"),
        ]:
            db.add(
                Annotation(
                    layer_id=pos.id,
                    document_id=doc,
                    sentence_index=0,
                    token_index=i,
                    annotator_id=me,
                    label="NOUN",
                    source="model:fake",
                    status=status,
                )
            )
        span = layer("偏误", "span", cid)

        def mk_span(doc, start, status):
            s = SpanAnnotation(
                layer_id=span.id,
                annotator_id=me,
                document_id=doc,
                sentence_index=0,
                start_cp=start,
                end_cp=start + 2,
                label="X",
                source="model:fake",
                status=status,
            )
            db.add(s)
            db.flush()
            return s

        s1, s2, s3 = (
            mk_span(a, 0, "suggested"),
            mk_span(a, 4, "confirmed"),
            mk_span(b, 0, "modified"),
        )
        rel = layer("关系", "relation", cid, base_layer_id=span.id)
        for x, y, status in [(s1, s2, "confirmed"), (s3, s3, "suggested")]:
            db.add(
                RelationAnnotation(
                    layer_id=rel.id,
                    annotator_id=me,
                    from_span_id=x.id,
                    to_span_id=y.id,
                    label="R",
                    source="model:fake",
                    status=status,
                )
            )
        align = layer("对齐", "alignment", uuid.UUID(other["id"]), tgt_corpus_id=cid)
        db.add(
            AlignmentAnnotation(
                layer_id=align.id,
                annotator_id=me,
                src_document_id=t,
                src_sentence_index=0,
                tgt_document_id=a,
                tgt_sentence_index=0,
                source=f"human:{me}",
                status="confirmed",
            )
        )
        layer("空层", "pos", cid)
    c["layers"] = ids
    return c


def by_name(impact):
    return {x["name"]: x["human"] for x in impact["layers"]}


def test_corpus_delete_impact(owner, project, annotated, member):
    a = annotated["docs"]["a"]
    pin = owner.post(
        f"/api/projects/{project['id']}/evidence",
        json={
            "kind": "hit",
            "ref": {"document_id": a, "start_cp": 0, "end_cp": 8},
            "text": "Language",
            "source": "a",
        },
    ).json()
    owner.post(
        f"/api/projects/{project['id']}/evidence",
        json={"kind": "text", "text": "随手记", "source": "笔记"},
    )
    note = owner.post(
        f"/api/projects/{project['id']}/kb/documents",
        json={"kind": "note", "title": "笔记", "body": ""},
    ).json()
    r = owner.post(
        f"/api/kb/documents/{note['id']}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": pin["id"], **pin["ref"]}},
    )
    assert r.status_code == 200, r.text
    # the assistant (kb_save) refers to evidence by evidence_id only: still the same sentence
    other = owner.post(
        f"/api/projects/{project['id']}/kb/documents",
        json={"kind": "note", "title": "助手笔记", "body": ""},
    ).json()
    r = owner.post(
        f"/api/kb/documents/{other['id']}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": pin["id"]}, "append": False},
    )
    assert r.status_code == 200, r.text

    r = owner.get(f"/api/corpora/{annotated['id']}/delete-impact")
    assert r.status_code == 200, r.text
    impact = r.json()
    assert impact["documents"] == 2 and impact["sentences"] == 4
    # every layer on the corpus goes, the alignment layer whose target it is too; rejected counts as reviewed
    assert by_name(impact) == {"词性": 3, "偏误": 2, "关系": 1, "对齐": 1, "空层": 0}
    assert impact["human_annotations"] == 7
    assert impact["evidence"] == 1 and impact["kb_refs"] == 2

    doc_a = owner.get(f"/api/documents/{a}/delete-impact").json()
    assert doc_a["documents"] == 1 and doc_a["sentences"] == 2
    # only layers with rows in the document; the relation touching a's span counts
    assert by_name(doc_a) == {"词性": 2, "偏误": 1, "关系": 1, "对齐": 1}
    assert doc_a["human_annotations"] == 5
    assert doc_a["evidence"] == 1 and doc_a["kb_refs"] == 2

    doc_b = owner.get(f"/api/documents/{annotated['docs']['b']}/delete-impact").json()
    assert by_name(doc_b) == {"词性": 1, "偏误": 1, "关系": 0}
    assert doc_b["human_annotations"] == 2
    assert doc_b["evidence"] == 0 and doc_b["kb_refs"] == 0

    # same permission as deleting: editors may, annotators may not
    editor, annotator = member("editor"), member("annotator")
    assert (
        editor.get(f"/api/corpora/{annotated['id']}/delete-impact").status_code == 200
    )
    assert (
        annotator.get(f"/api/corpora/{annotated['id']}/delete-impact").status_code
        == 403
    )
    assert annotator.get(f"/api/documents/{a}/delete-impact").status_code == 403
    assert owner.get(f"/api/documents/{uuid.uuid4()}/delete-impact").status_code == 404


def test_clear_my_evidence(owner, project, member):
    annotator = member("annotator")
    url = f"/api/projects/{project['id']}/evidence"
    for client, n in ((owner, 3), (annotator, 2)):
        for i in range(n):
            r = client.post(
                url,
                json={"kind": "text", "text": f"{client.user_id}-{i}", "source": "s"},
            )
            assert r.status_code == 200, r.text
    assert owner.delete(url).status_code == 422  # mine=true is required
    r = owner.delete(url, params={"mine": "true"})
    assert r.status_code == 200 and r.json() == {"deleted": 3}
    items = owner.get(url).json()["items"]
    assert len(items) == 2 and {x["created_by"] for x in items} == {annotator.user_id}
    # a viewer may clear too; it only touches the viewer's own (none)
    assert member("viewer").delete(url, params={"mine": "true"}).json() == {
        "deleted": 0
    }
    assert annotator.delete(url, params={"mine": "true"}).json() == {"deleted": 2}
    assert owner.get(url).json()["total"] == 0
