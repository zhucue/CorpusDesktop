"""Document metadata fields and subcorpus filters.

A field is `number` when every non-null value in the corpus is a JSON number; that is
what engine.cwb.build zero-pads for range filters.
"""

from sqlalchemy import Numeric, and_, cast, false, func, select, text

from services.api.errors import ApiError
from services.api.models import Document

VALUES_LIMIT = 100

FIELDS_SQL = text(
    """
    SELECT e.key,
           bool_and(jsonb_typeof(e.value) = 'number') AS numeric,
           count(DISTINCT e.value #>> '{}') AS distinct_values
    FROM documents d, jsonb_each(d.metadata) e
    WHERE d.corpus_id = :corpus_id AND jsonb_typeof(e.value) <> 'null'
    GROUP BY e.key
    ORDER BY e.key
    """
)

VALUES_SQL = text(
    """
    SELECT DISTINCT d.metadata ->> :key AS v
    FROM documents d
    WHERE d.corpus_id = :corpus_id AND d.metadata ->> :key IS NOT NULL
    """
)


def field_types(db, corpus_id) -> dict[str, str]:
    rows = db.execute(FIELDS_SQL, {"corpus_id": corpus_id})
    return {key: "number" if numeric else "string" for key, numeric, _ in rows}


def metadata_fields(db, corpus_id):
    fields = []
    for key, numeric, distinct in db.execute(FIELDS_SQL, {"corpus_id": corpus_id}):
        item = {"field": key, "type": "number" if numeric else "string"}
        if distinct <= VALUES_LIMIT:
            values = db.scalars(VALUES_SQL, {"corpus_id": corpus_id, "key": key}).all()
            item["values"] = (
                sorted((float(v) if "." in v else int(v)) for v in values)
                if numeric
                else sorted(values)
            )
        fields.append(item)
    return fields


def _scalar_ok(value, kind):
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, str)


def validate_filter(filter_, fields):
    """Raise 422 unless filter matches `{field: value | [values] | {gte, lte}}`."""
    if not isinstance(filter_, dict):
        raise ApiError(422, "INVALID_FILTER", "筛选条件须为对象")
    for field, cond in filter_.items():
        kind = fields.get(field)
        if kind is None:
            raise ApiError(422, "INVALID_FILTER", f"未知元数据字段：{field}")
        if isinstance(cond, list):
            ok = bool(cond) and all(_scalar_ok(v, kind) for v in cond)
        elif isinstance(cond, dict):
            ok = (
                kind == "number"
                and bool(cond)
                and set(cond) <= {"gte", "lte"}
                and all(_scalar_ok(v, kind) for v in cond.values())
            )
        else:
            ok = _scalar_ok(cond, kind)
        if not ok:
            raise ApiError(422, "INVALID_FILTER", f"字段 {field} 的条件格式不正确")


def filter_clause(filter_, fields):
    clauses = []
    for field, cond in filter_.items():
        raw = Document.meta[field].astext
        number = fields[field] == "number"
        col = cast(raw, Numeric) if number else raw
        if isinstance(cond, list):
            clauses.append(col.in_([v if number else str(v) for v in cond]))
        elif isinstance(cond, dict):
            if "gte" in cond:
                clauses.append(col >= cond["gte"])
            if "lte" in cond:
                clauses.append(col <= cond["lte"])
        else:
            clauses.append(col == cond)
    return and_(*clauses)


def subcorpus_stats(db, sub):
    fields = field_types(db, sub.corpus_id)
    where = [Document.corpus_id == sub.corpus_id]
    if all(f in fields for f in sub.filter):
        where.append(filter_clause(sub.filter, fields))
    else:
        where.append(false())  # a filtered field no longer exists: nothing matches
    docs, sentences, tokens = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Document.sentence_count), 0),
            func.coalesce(func.sum(Document.token_count), 0),
        ).where(*where)
    ).one()
    return {"documents": docs, "sentences": int(sentences), "tokens": int(tokens)}
