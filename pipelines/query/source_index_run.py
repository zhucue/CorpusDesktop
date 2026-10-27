"""Explicit full-input Linux build receipt. Not a publication endpoint."""
import argparse
import hashlib
import json
import os
import platform
import resource
import time
from pathlib import Path

from pipelines.query.source_index import build, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output / "source"
    source.mkdir()
    hashes = {}
    for name in ("source_index.py", "source_recipe.py", "source_reader.py", "source_index_run.py", "source-index-requirements.txt", "source-index-build-requirements.txt", "source-index-dependencies.json"):
        raw = Path(__file__).with_name(name).read_bytes()
        (source / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    last, previous_stage = 0, None
    stages = []

    def callback(event):
        nonlocal last, previous_stage
        now = time.monotonic()
        if previous_stage != event["stage"]:
            stages.append({"stage": event["stage"], "elapsed_seconds": now - started})
            previous_stage = event["stage"]
        (args.output / "progress.json").write_text(json.dumps(event), encoding="utf-8")
        if now - last > 30:
            print(json.dumps(event), flush=True)
            last = now

    started = time.monotonic()
    result = {"status": "failed", "source_sha256": hashes, "input_sqlite_sha256": digest(args.input),
              "input_manifest_sha256": digest(args.input_manifest), "formal_acceptance": False,
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "cpu_max": Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                              "memory_max": Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                              "storage": "Windows workspace bind mount; shared Docker Desktop host"}}
    try:
        built = build(args.input, args.output / "build", result["input_manifest_sha256"], callback)
        result.update(status="passed", manifest=built["manifest"], artifacts=[{**a, "path": str(a["path"])} for a in built["artifacts"]])
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "code": getattr(exc, "code", str(exc))}
        raise
    finally:
        result.update(wall_seconds=time.monotonic() - started, stages=stages,
                      parent_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      child_peak_rss_bytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
                      cgroup_peak_bytes_including_cache=Path('/sys/fs/cgroup/memory.peak').read_text().strip(), pid=os.getpid())
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "seconds": result["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
