"""Explicit server model identity; no credentials or network discovery."""

import hashlib
import json
import os
import re
from urllib.parse import urlsplit

from services.api.errors import ApiError

CONFIG_ID = "local-fixture-v1"
ACTIVE_SECONDS = 900
WAIT_SECONDS = 86400
FIXTURE_MANIFEST = {
    "sdk_package": "@earendil-works/pi-coding-agent",
    "sdk_version": "1.3.0",
    "session_version": 3,
    "host_policy": "corpus-k09-linear-v1",
    "provider": "corpus-s1-fixed",
    "model": "fixed-project-v1",
    "tool_schema": "s3-outcomes-tools-v1",
    "resource_config": "corpus-empty-resources-v1",
}


def _integer(name, default, minimum, maximum):
    value = os.environ.get("AGENT_MODEL_" + name, str(default))
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Invalid integer configuration")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError("Integer configuration outside supported range")
    return number


def _ascii(value):
    if not isinstance(value, str) or not value.isascii():
        raise ValueError("Invalid model configuration text")
    value = value.strip(" \t\n\r\v\f")
    if (
        not value
        or not value.isascii()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("Invalid model configuration text")
    return value


def model_config():
    """Shared v1 digest input; never includes API keys or arbitrary headers."""
    api = _ascii(os.environ.get("AGENT_MODEL_API", ""))
    if api not in {"openai-completions", "openai-responses"}:
        raise ValueError("Unsupported model protocol")
    base_url = _ascii(os.environ.get("AGENT_MODEL_BASE_URL", ""))
    model = _ascii(os.environ.get("AGENT_MODEL_ID", ""))
    allow = os.environ.get("AGENT_MODEL_ALLOW_LOOPBACK_HTTP", "false")
    if allow not in {"true", "false"}:
        raise ValueError("Invalid loopback flag")
    allow_http = allow == "true"
    if any(c.isspace() for c in base_url) or any(c in base_url for c in "\\?#"):
        raise ValueError("Invalid endpoint")
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        raise ValueError("Explicit endpoint scheme required")
    authority = base_url.split("://", 1)[1].split("/", 1)[0]
    if "@" in authority:
        raise ValueError("Endpoint user information is forbidden")
    url = urlsplit(base_url)
    if not url.hostname or url.username is not None or url.password is not None:
        raise ValueError("Invalid endpoint")
    _ = url.port  # Reject malformed ports before any request can be accepted.
    # Literal spelling prevents WHATWG/Python disagreement on short/decimal IPs.
    raw_host = (
        authority.split("]", 1)[0] + "]"
        if authority.startswith("[")
        else authority.split(":", 1)[0]
    )
    loopback = raw_host.lower() in {"localhost", "127.0.0.1", "[::1]"}
    if url.scheme != "https" and not (url.scheme == "http" and allow_http and loopback):
        raise ValueError("Endpoint transport is not allowed")
    base_url = base_url.rstrip("/")
    context = _integer("CONTEXT_WINDOW", 8192, 1024, 1048576)
    output = _integer("MAX_OUTPUT_TOKENS", 1024, 1, context)
    timeout = _integer("REQUEST_TIMEOUT_MS", 60000, 1000, 120000)
    identity = [
        "openai-compatible-v1",
        api,
        base_url,
        model,
        context,
        output,
        timeout,
        allow_http,
    ]
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "config_id": "openai-" + digest[:48],
        "manifest": {
            **FIXTURE_MANIFEST,
            "host_policy": "corpus-k09-openai-v1",
            "provider": "corpus-openai-compatible",
            "model": model,
            "resource_config": "corpus-explicit-resources-v1",
            "model_api": api,
            "model_config_sha256": digest,
        },
    }


def manifest_config_id(manifest):
    """Validate historical identity independently of today's selected endpoint."""
    if manifest == FIXTURE_MANIFEST:
        return CONFIG_ID
    expected = {
        **FIXTURE_MANIFEST,
        "host_policy": "corpus-k09-openai-v1",
        "provider": "corpus-openai-compatible",
        "resource_config": "corpus-explicit-resources-v1",
    }
    if not isinstance(manifest, dict) or set(manifest) != set(expected) | {
        "model_api",
        "model_config_sha256",
    }:
        raise ValueError("Unsupported archive configuration")
    if any(manifest[k] != v for k, v in expected.items() if k != "model"):
        raise ValueError("Unsupported archive configuration")
    if _ascii(manifest["model"]) != manifest["model"]:
        raise ValueError("Invalid archive model")
    if manifest["model_api"] not in {"openai-completions", "openai-responses"}:
        raise ValueError("Unsupported archive protocol")
    digest = manifest["model_config_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid archive identity")
    return "openai-" + digest[:48]


def runtime_view():
    mode = os.environ.get("AGENT_RUNTIME_MODE", "unconfigured")
    config_id, manifest = None, None
    reason = "MODEL_NOT_CONFIGURED"
    if mode == "fixture":
        config_id, manifest, reason = CONFIG_ID, dict(FIXTURE_MANIFEST), None
    elif mode == "openai-compatible":
        try:
            configured = model_config()
            config_id, manifest, reason = (
                configured["config_id"],
                configured["manifest"],
                None,
            )
        except (ValueError, TypeError, AttributeError):
            reason = "MODEL_CONFIGURATION_INVALID"
    elif mode != "unconfigured":
        mode, reason = "unconfigured", "MODEL_NOT_CONFIGURED"
    return {
        "mode": mode,
        "production_ready": False,
        "fixture_enabled": mode == "fixture",
        "can_submit": config_id is not None,
        "config_id": config_id,
        "reason": reason,
        "runtime_manifest": manifest,
    }


def require_runtime(config_id=None):
    view = runtime_view()
    if not view["can_submit"]:
        raise ApiError(
            503, "AGENT_RUNTIME_UNAVAILABLE", "Model configuration is unavailable"
        )
    if config_id is not None and config_id != view["config_id"]:
        raise ApiError(
            503, "AGENT_RUNTIME_UNAVAILABLE", "Run model configuration is not active"
        )
    return view["runtime_manifest"]


def continuation_message(run):
    if not run.resume_checkpoint_id:
        return None
    reports = [
        {"tool": item["report_tool"], "arguments": item["report_arguments"]}
        for item in run.waiting_jobs
    ]
    return (
        f"Resume waiting jobs for run {run.id}, epoch {run.lease_epoch}. "
        "Read these server-bound task reports before continuing: "
        + json.dumps(reports, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
