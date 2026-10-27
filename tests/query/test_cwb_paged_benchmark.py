"""Regression for a Windows bind-mount report replacement failure observed live."""

import unittest
from unittest.mock import Mock, patch

from pipelines.query.cwb_paged_benchmark import _replace_report


class ReportReplacementTests(unittest.TestCase):
    @patch("pipelines.query.cwb_paged_benchmark.time.sleep")
    def test_transient_reader_lock_retries_then_publishes(self, sleep):
        pending = Mock()
        pending.replace.side_effect = [PermissionError("reader lock"), None]
        _replace_report(pending, "report.json")
        self.assertEqual(pending.replace.call_count, 2)
        sleep.assert_called_once_with(0.05)

    @patch("pipelines.query.cwb_paged_benchmark.time.sleep")
    def test_persistent_lock_is_bounded_and_still_fails(self, sleep):
        pending = Mock()
        pending.replace.side_effect = PermissionError("persistent lock")
        with self.assertRaises(PermissionError):
            _replace_report(pending, "report.json")
        self.assertEqual(pending.replace.call_count, 5)
        self.assertLess(sum(call.args[0] for call in sleep.call_args_list), 1)

    @patch("pipelines.query.cwb_paged_benchmark.time.sleep")
    def test_other_io_errors_are_not_retried(self, sleep):
        pending = Mock()
        pending.replace.side_effect = OSError("disk failure")
        with self.assertRaises(OSError):
            _replace_report(pending, "report.json")
        sleep.assert_not_called()
