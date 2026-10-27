"""Explicit public model download only. Never accepts research material or credentials."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("model-candidates.json")


def selected_model():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return next(item for item in manifest["candidates"] if item["id"] == manifest["selected_for_smoke"])


def verify_files(directory, model):
    for item in model["files"]:
        path = Path(directory) / item["path"]
        if not path.is_file() or path.stat().st_size != item["size"]:
            return False
        with path.open("rb") as data:
            if hashlib.file_digest(data, "sha256").hexdigest() != item["sha256"]:
                return False
    return True


def download(directory):
    directory = Path(directory).resolve()
    if not directory.is_relative_to(ROOT / "tmp"):
        raise ValueError("Downloads must remain under repository tmp/")
    model = selected_model()
    for item in model["files"]:
        path = directory / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size == item["size"]:
            with path.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() == item["sha256"]:
                    continue
        url = f"https://huggingface.co/{model['id']}/resolve/{model['revision']}/{item['path']}"
        partial = path.with_suffix(path.suffix + ".partial")
        digest = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > item["size"]:
                    raise ValueError("MODEL_DOWNLOAD_SIZE_MISMATCH")
                output.write(chunk)
                digest.update(chunk)
        if count != item["size"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("MODEL_DOWNLOAD_HASH_MISMATCH")
        partial.replace(path)
    return {"status": "downloaded_and_verified", "model_id": model["id"], "revision": model["revision"], "bytes": sum(item["size"] for item in model["files"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / "tmp/alignment-s0/model")
    print(json.dumps(download(parser.parse_args().directory), indent=2))
