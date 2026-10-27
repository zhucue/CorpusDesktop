"""Portable correctness tests for the persisted CWB benchmark coordinate path."""

import tempfile
import unittest
from pathlib import Path

from pipelines.query.benchmark import queries, revisions
from pipelines.query.cwb_benchmark import Coordinates, build_input, expected_count
from pipelines.query.reference_counts import count

ROOT = Path(__file__).resolve().parents[2]


class BenchmarkCorrectnessTests(unittest.TestCase):
    def directory(self):
        parent = ROOT / 'tmp/query-s0/benchmark-tests'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_weighted_oracle_matches_full_enumeration_including_partial_cycles(self):
        workload = list(queries('token', 20))
        for size in (1, 137, 2000, 4237):
            with self.subTest(size=size):
                actual, templates = build_input(self.directory(), size, 20261016)
                raw = [{'text': r.text, 'tokens': r.tokens} for r in revisions('token', size, 20261016)]
                self.assertEqual(actual['tokens'], size)
                for query in workload:
                    self.assertEqual(expected_count(query, templates, size), sum(count(query, r) for r in raw))

    def test_maps_every_hit_counts_documents_and_returns_ordered_actual_kwic(self):
        directory = self.directory()
        build_input(directory, 237, 20261016)
        coordinates = Coordinates(directory)
        self.addCleanup(coordinates.close)
        # Deliberately unordered, >50 spans: mapped counts include hits beyond page 1.
        spans = {(i, i + 1) for i in range(60)} | {(100, 102), (236, 237)}
        result = coordinates.page_and_counts(spans)
        self.assertEqual(result['total_hits'], 62)
        self.assertEqual(result['matched_documents'], 3)
        self.assertEqual(result['matched_segments'], 3)
        self.assertEqual(len(result['page']), 50)
        raw = next(revisions('token', 237, 20261016))
        for ordinal, row in enumerate(result['page']):
            self.assertEqual((row['revision_id'], row['start'], row['end']), ('0', ordinal * 4, ordinal * 4 + 3))
            self.assertEqual(row['match'], raw.text[row['start']:row['end']])
        with self.assertRaisesRegex(AssertionError, 'boundary'):
            coordinates.page_and_counts({(99, 101)})

    def test_empty_result_has_no_page_or_document(self):
        directory = self.directory()
        build_input(directory, 1, 20261016)
        coordinates = Coordinates(directory)
        self.addCleanup(coordinates.close)
        self.assertEqual(coordinates.page_and_counts(set()), {'total_hits': 0, 'matched_documents': 0, 'matched_segments': 0, 'page': []})
