"""S0 candidate: bounded canonical KWIC with separately completed exact counts."""

from pipelines.query.cwb import cqp_page_spans
from pipelines.query.engine import QueryError


def page_result(query, registry, coordinates, **options):
    if query.get("within") != "sentence":
        raise QueryError(
            "QUERY_UNSUPPORTED: paged count currently requires sentence scope"
        )
    spans = cqp_page_spans(query, registry, **options)
    # Coordinates maps the supplied page to persisted original text. Its local
    # page counts must never be published as full-corpus counts.
    page = coordinates.page_and_counts(spans)["page"]
    return {
        "spans": spans,
        "page": page,
        "total_hits": None,
        "matched_segments": None,
        "matched_documents": None,
        "count_status": "pending",
    }
