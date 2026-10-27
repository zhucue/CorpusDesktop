"""Catalog baseline fidelity and input/cursor boundaries without a database."""

import importlib.util
import json
import re
import unittest
from pathlib import Path

from pydantic import ValidationError

from contracts.catalog import (
    CatalogCreate,
    CatalogMetadata,
    CatalogUpdate,
    SourceCapabilities,
    SourceVersionView,
)
from services.api.catalog import make_cursor, read_cursor
from services.api.errors import ApiError


class CatalogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = json.loads(
            Path("services/api/catalog_seed.json").read_text(encoding="utf-8")
        )

    def test_exact_46_baseline_rows_and_distinct_registration(self):
        baseline = Path("doc/product-design.md").read_text(encoding="utf-8")
        rows = re.findall(
            r"^\| \[(D\d\d) (.*?)\]\((.*?)\) \| (.*?) \| (.*?) \| (.*?) \|$",
            baseline,
            re.MULTILINE,
        )
        self.assertEqual([r[0] for r in rows], [f"D{i:02}" for i in range(1, 47)])
        self.assertEqual(
            [r["source_id"] for r in self.seed["items"]], [r[0] for r in rows]
        )
        for item, (sid, name, url, materials, route, boundary) in zip(
            self.seed["items"], rows, strict=True
        ):
            with self.subTest(source_id=sid):
                meta = CatalogMetadata.model_validate(item["metadata"])
                self.assertIn(item["baseline_row"], baseline)
                self.assertEqual(
                    (
                        meta.name,
                        meta.official_url,
                        meta.materials,
                        meta.access_route,
                        meta.boundary,
                    ),
                    (name, url, materials, route, boundary),
                )
                self.assertTrue(meta.publisher and meta.categories and meta.languages)
                for ref in item["evidence_refs"]:
                    self.assertTrue(Path(ref).is_file())
        self.assertEqual(self.seed["items"][15]["metadata"]["entry_kind"], "aggregator")
        self.assertEqual(self.seed["items"][39]["metadata"]["entry_kind"], "publisher")
        self.assertEqual(self.seed["items"][11]["metadata"]["entry_kind"], "dataset")

    def test_catalog_write_cannot_enable_license_production_or_inject_version(self):
        body = {**self.seed["items"][11]["metadata"], "source_id": "custom-1"}
        self.assertEqual(CatalogCreate(**body).source_id, "custom-1")
        for key, value in (
            ("license_status", "approved"),
            ("capabilities", {"export": True}),
            ("evidence_refs", ["fake"]),
            ("integration_status", "experimental_evidence"),
            ("versions", [{"state": "READY"}]),
        ):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CatalogCreate(**body, **{key: value})
        with self.assertRaises(ValidationError):
            CatalogUpdate(**self.seed["items"][0]["metadata"], expected_revision=0)
        self.assertEqual(
            SourceCapabilities().model_dump(),
            {
                "discover": True,
                "remote_query": False,
                "fulltext_analysis": False,
                "export": False,
                "model_egress": False,
            },
        )

    def test_published_version_requires_fixed_index_and_snapshot_identity(self):
        with self.assertRaises(ValidationError):
            SourceVersionView(release_id="00000000-0000-0000-0000-000000000001",
                              version="legacy", published_at="2026-10-17T00:00:00Z",
                              manifest_sha256="a" * 64)
        required = {name for name, value in SourceVersionView.model_fields.items() if value.is_required()}
        self.assertTrue({"source_snapshot_id", "index_id", "acquisition_id", "policy_revision",
                         "current_policy_revision", "available", "searchable", "counts", "quality"} <= required)

    def test_bounded_metadata_and_reference_url(self):
        metadata = self.seed["items"][0]["metadata"]
        for patch in (
            {"official_url": "javascript:alert(1)"},
            {"official_url": "file:///secret"},
            {"official_url": "https://user:password@example.test"},
            {"categories": ["a", "a"]},
            {"languages": ["a"] * 21},
            {"name": " "},
            {"boundary": "a" * 4001},
        ):
            with self.subTest(patch=list(patch)), self.assertRaises(ValidationError):
                CatalogMetadata(**{**metadata, **patch})
        with self.assertRaises(ValidationError):
            CatalogCreate(**metadata, source_id="../x")

    def test_cursor_bound_to_filter_scope_and_rejects_malformed(self):
        filters = {"q": "Tatoeba", "category": "parallel"}
        cursor = make_cursor("D12", filters)
        self.assertEqual(read_cursor(cursor, filters), "D12")
        for value, args in (
            (cursor, {"q": "different"}),
            ("not_base64", filters),
            ("e30=", filters),
            ("WzEsMl0=", filters),
        ):
            with self.subTest(value=value), self.assertRaises(ApiError):
                read_cursor(value, args)

    def test_frozen_seed_accepts_checkout_newlines_but_rejects_data_change(self):
        spec = importlib.util.spec_from_file_location(
            "catalog_migration",
            "services/api/migrations/versions/0004_source_catalog.py",
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        raw = (
            Path("services/api/catalog_seed.json").read_bytes().replace(b"\r\n", b"\n")
        )
        self.assertEqual(
            migration.decode_seed(raw),
            migration.decode_seed(raw.replace(b"\n", b"\r\n")),
        )
        with self.assertRaises(RuntimeError):
            migration.decode_seed(raw.replace(b'"Tatoeba"', b'"Different"', 1))
