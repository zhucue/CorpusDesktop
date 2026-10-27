"""Local CPU inference. No hub client, model API, or automatic downloads are used."""

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from time import perf_counter

from pipelines.alignment.algorithm import align, evaluate, validate_segments
from pipelines.alignment.download_model import selected_model, verify_files


class ModelUnavailable(RuntimeError):
    pass


def run_local(dataset, directory):
    model = selected_model()
    if not verify_files(directory, model):
        raise ModelUnavailable("MODEL_UNAVAILABLE: missing or checksum-mismatched local files")
    try:
        import numpy as np
        import onnxruntime as ort
        from jsonschema import validate
        from tokenizers import Tokenizer
    except ImportError as error:
        raise ModelUnavailable("MODEL_UNAVAILABLE: install isolated alignment requirements") from error
    schema = json.loads(Path(__file__).with_name("input.schema.json").read_text(encoding="utf-8"))
    validate(dataset, schema)
    validate_segments(dataset["source"], dataset["target"])
    tokenizer = Tokenizer.from_file(str(Path(directory) / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    segments = dataset["source"] + dataset["target"]
    encodings = tokenizer.encode_batch([segment["text"] for segment in segments])
    for segment, encoding in zip(segments, encodings, strict=True):
        if len(encoding.ids) > model["max_tokens"]:
            raise ValueError(f"SEGMENT_TOO_LONG: {segment['id']} has {len(encoding.ids)} tokens; maximum {model['max_tokens']}. Re-segment explicitly; no silent truncation.")
    options = ort.SessionOptions()
    ort.disable_telemetry_events()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    started = perf_counter()
    session = ort.InferenceSession(str(Path(directory) / model["files"][0]["path"]), sess_options=options, providers=["CPUExecutionProvider"])
    loaded = perf_counter()
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
    vectors = []
    for offset in range(0, len(segments), 16):
        encoded = tokenizer.encode_batch([segment["text"] for segment in segments[offset:offset + 16]])
        arrays = {
            "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
            "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
            "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
        }
        token_vectors = session.run(None, {item.name: arrays[item.name] for item in session.get_inputs()})[0]
        if token_vectors.ndim != 3 or token_vectors.shape[2] != model["dimension"]:
            raise ModelUnavailable("MODEL_UNAVAILABLE: unexpected ONNX output shape")
        mask = arrays["attention_mask"][..., None]
        pooled = (token_vectors * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
        pooled /= np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
        vectors.extend(pooled)
    encoded_at = perf_counter()
    n, m = len(dataset["source"]), len(dataset["target"])
    similarities = np.clip(np.asarray(vectors[:n]) @ np.asarray(vectors[n:]).T, -1, 1).tolist() if n and m else [[] for _ in range(n)]
    result = align(dataset["source"], dataset["target"], similarities)
    method = {
        "algorithm": result["recipe"], "model_id": model["id"], "revision": model["revision"],
        "files": model["files"], "pooling": model["pooling"], "max_tokens": model["max_tokens"],
        "segmentation_recipe": dataset["segmentation_recipe"], "source_language": dataset["source_language"],
        "target_language": dataset["target_language"], "threads": {"intra_op": 2, "inter_op": 1},
        "packages": {name: importlib.metadata.version(name) for name in ("onnxruntime", "tokenizers", "numpy")},
    }
    method_digest = hashlib.sha256(json.dumps(method, sort_keys=True).encode()).hexdigest()
    dataset_digest = hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    for pair in result["pairs"]:
        pair["candidate_id"] = hashlib.sha256(f"{method_digest}:{dataset_digest}:{pair['source_id']}:{pair['target_id']}".encode()).hexdigest()
    result.update({
        "status": {"constructed_smoke": "completed_smoke", "public_benchmark": "completed_public_benchmark", "domain_gold": "completed_evaluation"}[dataset["dataset_kind"]],
        "quality": evaluate(result, dataset), "method_manifest": method, "method_sha256": method_digest,
        "input_sha256": dataset_digest, "snapshot_id": dataset["snapshot_id"], "block_id": dataset["block_id"],
        "similarities": similarities, "truncated_segments": [],
        "network_mode": "local_files_only_no_application_network_calls",
        "onnx_telemetry": "disabled", "network_capture_verified": False,
        "runtime": {"python": platform.python_version(), "system": platform.platform(), "processor": platform.processor(), "model_load_seconds": loaded - started, "encode_seconds": encoded_at - loaded, "segment_count": len(segments), "peak_memory": "not_measured"},
    })
    return result


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, default=Path("tmp/alignment-s0/model"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = run_local(json.loads(arguments.input.read_text(encoding="utf-8")), arguments.model_directory)
    except ModelUnavailable as error:
        report = {"status": "MODEL_UNAVAILABLE", "reason": str(error), "quality_status": "NOT_VALIDATED"}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(arguments.output)}, ensure_ascii=False))
    if report["status"] == "MODEL_UNAVAILABLE":
        sys.exit(2)
