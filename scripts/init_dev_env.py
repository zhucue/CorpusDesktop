"""Append missing local Compose secrets outside tmp without printing any values."""

import secrets
import socket
from pathlib import Path

target = Path(__file__).resolve().parents[1] / "deploy/.env"
existing = target.read_text(encoding="utf-8") if target.exists() else ""
names = {line.partition("=")[0] for line in existing.splitlines() if "=" in line}
missing = [
    name
    for name in (
        "CORPUS_DB_PASSWORD",
        "CORPUS_APP_DB_PASSWORD",
        "CORPUS_OWNER_DB_PASSWORD",
        "CORPUS_WORKER_DB_PASSWORD",
        "CORPUS_BROKER_PASSWORD",
        "CORPUS_S3_PASSWORD",
        "CORPUS_AGENT_HOST_KEY",
    )
    if name not in names
]
with target.open("a", encoding="utf-8") as output:
    if existing and not existing.endswith("\n"):
        output.write("\n")
    for name in missing:
        output.write(f"{name}={secrets.token_hex(24)}\n")
    if "CORPUS_HTTP_PORT" not in names:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        output.write(f"CORPUS_HTTP_PORT={port}\n")
print(
    f"Local environment ready; added {len(missing)} missing secret settings, existing values preserved"
)
