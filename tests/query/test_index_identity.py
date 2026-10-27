"""Real small index files exercise the S0 contract, not production permissions."""

import copy
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from pipelines.query.engine import PositionIndex, Revision
from pipelines.query.index_identity import (
    IndexIdentity,
    IndexQuotaExceeded,
    IndexRequest,
    SourceIndex,
    check_storage_quota,
    content_digest,
    decide_index,
    measured_artifact_bytes,
    member_from_revision,
)

ROOT = Path(__file__).resolve().parents[2]


def revisions():
    return [Revision(f"r{i}", text, [(0, len(text))], [(0, len(text))],
                     [{"start": 0, "end": len(text), "attrs": {"form": text}}], {"source": "fixture"})
            for i, text in enumerate(("甲😀乙", "ab"))]


def identity(items=None):
    items = revisions() if items is None else items
    return IndexIdentity("PositionIndex", "s0-v1", "character", {"form": "none", "casefold": False},
                         content_digest({"segmentation": "fixture-v1"}),
                         tuple(member_from_revision(r) for r in items), "metadata-v1",
                         content_digest([{r.revision_id: r.metadata} for r in items]))


def file_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in directory.iterdir() if path.is_file()}


class IndexIdentityTests(unittest.TestCase):
    def test_every_query_relevant_identity_component_invalidates_reuse(self):
        base = identity()
        changed_members = [
            tuple(reversed(base.members)),
            (replace(base.members[0], revision_id="new-revision"), base.members[1]),
            (replace(base.members[0], text_sha256=content_digest("new text")), base.members[1]),
            (replace(base.members[0], token_layer_sha256=content_digest("different tokens")), base.members[1]),
            (replace(base.members[0], segment_map_sha256=content_digest("new sentences")), base.members[1]),
        ]
        changed = [replace(base, **values) for values in [
            {"engine": "CWB"}, {"engine_version": "s0-v2"}, {"unit": "token"},
            {"normalization": {"form": "NFC", "casefold": False}},
            {"recipe_sha256": content_digest("different recipe")},
            {"metadata_manifest_ref": "metadata-v2"}, {"metadata_sha256": content_digest("different filters")},
        ]] + [replace(base, members=members) for members in changed_members]
        assert all(candidate.key() != base.key() for candidate in changed)
        assert replace(base, normalization={"casefold": False, "form": "none"}).key() == base.key()
        assert content_digest("é") != content_digest("e\u0301")


    def test_actual_token_attributes_coordinates_and_metadata_are_covered(self):
        original = revisions()
        changed = copy.deepcopy(original)
        changed[0].tokens[0]["attrs"]["pos"] = "N"
        assert identity(changed).key() != identity(original).key()
        changed = copy.deepcopy(original)
        changed[0].tokens[0]["end"] -= 1
        assert identity(changed).key() != identity(original).key()
        changed = copy.deepcopy(original)
        changed[0].metadata["language"] = "zh"
        assert identity(changed).key() != identity(original).key()


    def test_two_projects_reuse_full_source_but_authorization_is_checked_every_time(self):
        base = identity()
        source = SourceIndex("published-index", "release-1", base)
        authorized = {("p1", "s1"), ("p2", "s2")}
        calls = []

        def authorize(request):
            calls.append(("authorize", request.project_id))
            # A trusted fixture stand-in for checking persisted mounts and snapshot.
            if (request.project_id, request.snapshot_id) not in authorized or request.identity.key() != base.key():
                raise PermissionError("PROJECT_SCOPE_DENIED")

        def lookup(release):
            calls.append(("lookup", release))
            return source

        first = IndexRequest("p1", "s1", "source_full", "release-1", base)
        second = replace(first, project_id="p2", snapshot_id="s2")
        a = decide_index(first, authorize=authorize, lookup_source=lookup)
        b = decide_index(second, authorize=authorize, lookup_source=lookup)
        assert a.action == b.action == "reuse"
        assert a.key == b.key and a.index_id == b.index_id == "published-index"
        assert a.project_id != b.project_id
        authorized.remove(("p2", "s2"))
        with self.assertRaisesRegex(PermissionError, "PROJECT_SCOPE_DENIED"):
            decide_index(second, authorize=authorize, lookup_source=lookup)
        assert calls == [("authorize", "p1"), ("lookup", "release-1"),
                         ("authorize", "p2"), ("lookup", "release-1"), ("authorize", "p2")]
        with self.assertRaisesRegex(ValueError, "AUTHORIZATION_CALLBACK"):
            decide_index(first, authorize=lambda _: True, lookup_source=lookup)


    def test_changed_full_source_and_no_published_index_require_build(self):
        base = identity()
        request = IndexRequest("p1", "s1", "source_full", "release-1", base)
        for source in (None, SourceIndex("old-index", "release-1", replace(base, engine_version="old"))):
            decision = decide_index(request, authorize=lambda _: None, lookup_source=lambda _, source=source: source)
            assert decision.action == "build_required"
            assert decision.index_id is None


    def check_build_cost(self, kind):
        parent = ROOT / "tmp/query-s0"
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=f"index-identity-{kind}-", dir=parent))
        source_path, candidate_path = directory / "source", directory / "candidate"
        source_revisions = revisions()
        PositionIndex(source_revisions).save(source_path)
        previous = file_hashes(source_path)
        candidate_revisions = source_revisions[:1] if kind == "subset" else source_revisions + [
            Revision("private-r3", "私有", [(0, 2)], [(0, 2)], [], {"source": "private"})]
        request = IndexRequest("p1", "derived-snapshot", kind, "release-1", identity(candidate_revisions))

        def no_lookup(_):
            self.fail("Subset/mixed may not reuse or probe the source index")

        assert decide_index(request, authorize=lambda _: None, lookup_source=no_lookup).action == "build_required"
        # Deliberately optimistic preflight cannot stand in for measured admission.
        check_storage_quota(cost_bytes=1, used_bytes=0, limit_bytes=1, basis="estimate")
        PositionIndex(candidate_revisions).save(candidate_path)
        actual = measured_artifact_bytes(candidate_path)
        assert actual == sum((candidate_path / name).stat().st_size for name in ("revisions.jsonl", "postings.bin", "vocabulary.json"))
        assert actual > 1
        with self.assertRaises(IndexQuotaExceeded) as refused:
            check_storage_quota(cost_bytes=actual, used_bytes=0, limit_bytes=1, basis="measured")
        assert refused.exception.cost_bytes == actual and refused.exception.basis == "measured"
        assert file_hashes(source_path) == previous
        assert check_storage_quota(cost_bytes=actual, used_bytes=7, limit_bytes=actual+7, basis="measured")["remaining_after_bytes"] == 0
        with self.assertRaises(IndexQuotaExceeded):
            check_storage_quota(cost_bytes=actual, used_bytes=8, limit_bytes=actual+7, basis="measured")


    def test_invalid_identity_and_quota_values_are_rejected(self):
        base = identity()
        with self.assertRaisesRegex(ValueError, "UNIQUE"):
            replace(base, members=base.members + base.members[:1]).key()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            replace(base, recipe_sha256="not-a-digest").key()
        with self.assertRaises(ValueError):
            content_digest({1: "ambiguous object key"})
        with self.assertRaises(ValueError):
            content_digest(float("nan"))
        for invalid in (-1, True, 1.5):
            with self.assertRaisesRegex(ValueError, "INVALID_QUOTA"):
                check_storage_quota(cost_bytes=invalid, used_bytes=0, limit_bytes=10, basis="estimate")

    def test_subset_build_cost_and_quota(self):
        self.check_build_cost("subset")

    def test_mixed_build_cost_and_quota(self):
        self.check_build_cost("mixed")


if __name__ == "__main__":
    unittest.main()
