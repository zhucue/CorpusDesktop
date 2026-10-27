import os

import pytest

from pipelines.security.rls_probe import run_probe


def test_isolated_postgres_rls():
    url = os.getenv("CORPUS_RLS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires explicit CORPUS_RLS_TEST_DATABASE_URL for isolated PostgreSQL role/schema experiment")
    result = run_probe(url)
    assert result["status"] == "passed"
    assert result["cleanup"] is True
    assert len(result["checks"]) == 8
