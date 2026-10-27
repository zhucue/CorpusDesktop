"""Manual capability discovery matches fixed source/project authorization scopes."""

import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from contracts.releases import RELEASE_INPUTS
from services.api import main
from services.api.auth import Actor
from services.api.errors import ApiError


class ReleaseCapabilitiesTests(unittest.TestCase):
    def test_account_and_platform_have_only_their_release_actions(self):
        for admin in (False, True):
            actor = Actor(uuid4(), "fixture@example.test", admin, "")
            value = main.my_capabilities(actor)
            expected = {"releases.get"}
            if admin:
                expected |= {"policies.get", "policies.update", "releases.publish"}
            self.assertEqual(
                set(value["manual_actions"]) & set(RELEASE_INPUTS), expected
            )
            self.assertEqual(value["available_tools"], [])

    def test_project_role_filters_mount_writes_and_never_adds_platform_privilege(self):
        for role in ("owner", "editor", "viewer"):
            for admin in (False, True):
                actor = Actor(uuid4(), "fixture@example.test", admin, "")
                permissions = SimpleNamespace(
                    upload=role != "viewer", manage_members=role == "owner"
                )
                with (
                    patch.object(main, "transaction", return_value=nullcontext(None)),
                    patch.object(
                        main.projects, "require_project", return_value=object()
                    ),
                    patch.object(
                        main.projects,
                        "view",
                        return_value=SimpleNamespace(permissions=permissions),
                    ),
                ):
                    value = main.my_capabilities(actor, uuid4())
                expected = {
                    "releases.get",
                    "mounts.list",
                    "mounts.get",
                    "mounts.manifest",
                }
                if role != "viewer":
                    expected |= {"mounts.create", "mounts.remove"}
                self.assertEqual(
                    set(value["manual_actions"]) & set(RELEASE_INPUTS), expected
                )
                self.assertEqual(value["available_tools"], [])

    def test_administrator_without_project_membership_has_no_project_capability_view(
        self,
    ):
        actor = Actor(uuid4(), "fixture@example.test", True, "")
        with (
            patch.object(main, "transaction", return_value=nullcontext(None)),
            patch.object(
                main.projects,
                "require_project",
                side_effect=ApiError(404, "PROJECT_NOT_FOUND", "Project not found"),
            ),
            self.assertRaises(ApiError),
        ):
            main.my_capabilities(actor, uuid4())
