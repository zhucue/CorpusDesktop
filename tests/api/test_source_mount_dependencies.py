"""The context gate locks sources consistently before resolving any manifest."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from services.api import source_mounts


class MountDependenciesTests(unittest.TestCase):
    def test_opposite_mount_ids_still_lock_sources_in_source_order(self):
        ids = sorted([uuid4(), uuid4()])
        records = {
            ids[0]: SimpleNamespace(id=ids[0], source_snapshot_id="Z"),
            ids[1]: SimpleNamespace(id=ids[1], source_snapshot_id="A"),
        }
        for ordered in (ids, list(reversed(ids))):
            events = []
            with (
                patch.object(
                    source_mounts,
                    "project",
                    side_effect=lambda *_, events=events: events.append("project"),
                ),
                patch.object(
                    source_mounts,
                    "load",
                    side_effect=lambda _db, _project, ident: records[ident],
                ),
                patch.object(
                    source_mounts,
                    "release_for",
                    side_effect=lambda _, snapshot: SimpleNamespace(source_id=snapshot),
                ),
                patch.object(
                    source_mounts.releases,
                    "source",
                    side_effect=lambda _, source, events=events: events.append(source),
                ),
                patch.object(
                    source_mounts,
                    "resolve_mount",
                    side_effect=lambda *_, events=events: events.append("resolve"),
                ),
            ):
                source_mounts.check_manifest_dependencies(
                    None, uuid4(), uuid4(), [str(x) for x in ordered]
                )
            self.assertEqual(events, ["project", "A", "Z", "resolve", "resolve"])
