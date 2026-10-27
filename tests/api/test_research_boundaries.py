"""Runtime query subset and terminal page semantics without requiring CWB."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from services.api import research
from services.api.errors import ApiError


class ResearchContractTests(unittest.TestCase):
    def test_manual_input_rejects_token_context_and_runtime_rejects_large_ast(self):
        ast = {
            "dsl_version": "corpus-query/v1",
            "unit": "character",
            "within": "sentence",
            "overlap": "all",
            "pattern": {"type": "literal", "value": "a"},
        }
        with self.assertRaises(ValidationError):
            research.QueryInput(snapshot_id=uuid4(), query=ast, context_tokens=40)
        ast["pattern"]["value"] = "a" * 65537
        with self.assertRaises(ApiError) as error:
            research.validate_query(ast)
        self.assertEqual(error.exception.code, "QUERY_UNSUPPORTED")

    def test_failed_or_cancelled_without_preview_never_returns_pending(self):
        for state in ("FAILED", "CANCELLED"):
            run = SimpleNamespace(
                project_id=uuid4(),
                snapshot_id=uuid4(),
                page_size=50,
                state=state,
                first_page=None,
                error=None,
            )
            with patch.object(
                research, "resolve_snapshot", return_value=(None, None, None)
            ):
                with self.assertRaises(ApiError) as error:
                    research.page_data(None, uuid4(), run, None, None)
                self.assertEqual(error.exception.code, "QUERY_" + state)
