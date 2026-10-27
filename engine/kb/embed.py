"""Text embeddings (contracts/p4.md §二), unit length so cosine distance = 1 − dot product.

EMBED_PROVIDER=local (default): sentence-transformers EMBED_MODEL (default paraphrase-multilingual-MiniLM-L12-v2
at the pinned revision EMBED_REVISION) on CPU, cached under MODELS_DIR. The worker may download it
(download=True); the API only loads files already in the cache, so a missing model degrades search instead of
blocking a request. EMBED_PROVIDER=openai: POST {EMBED_BASE_URL}/embeddings with EMBED_API_KEY / EMBED_MODEL;
EMBED_DIM must equal DIM (the kb_chunks.embedding column). Any failure raises EmbedUnavailable.
"""

import math
import os
import threading

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
DIM = 384
BATCH = 64

_lock = threading.Lock()
_models = {}


class EmbedUnavailable(RuntimeError):
    pass


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def remote() -> bool:
    return _env("EMBED_PROVIDER", "local").lower() == "openai"


def model_name() -> str:
    """Value stored in kb_chunks.embed_model; vector search only compares chunks of the current model."""
    if remote():
        return "openai:" + _env("EMBED_MODEL")
    return _env("EMBED_MODEL", DEFAULT_MODEL)


def _local(download: bool):
    name = model_name()
    with _lock:
        if name not in _models:
            try:
                from sentence_transformers import SentenceTransformer

                revision = _env("EMBED_REVISION") or (
                    DEFAULT_REVISION if name == DEFAULT_MODEL else None
                )
                model = SentenceTransformer(
                    name,
                    device="cpu",
                    cache_folder=_env("MODELS_DIR") or None,
                    revision=revision,
                    local_files_only=not download,
                )
            except (
                Exception
            ) as e:  # missing files, network, bad name: all mean "not available"
                raise EmbedUnavailable(f"向量模型不可用：{str(e)[:300]}") from e
            dim = (
                getattr(model, "get_embedding_dimension", None)
                or model.get_sentence_embedding_dimension
            )()
            if dim != DIM:
                raise EmbedUnavailable(f"向量维度 {dim} 与库表 vector({DIM}) 不一致")
            _models[name] = model
        return _models[name]


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _remote(texts):
    import httpx

    base, model = _env("EMBED_BASE_URL").rstrip("/"), _env("EMBED_MODEL")
    if not base or not model:
        raise EmbedUnavailable("未配置 EMBED_BASE_URL 或 EMBED_MODEL")
    dim = int(_env("EMBED_DIM", str(DIM)))
    if dim != DIM:
        raise EmbedUnavailable(f"EMBED_DIM={dim} 与库表 vector({DIM}) 不一致")
    body = {"model": model, "input": texts}
    if _env("EMBED_DIM"):
        body["dimensions"] = dim
    key = _env("EMBED_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = httpx.post(f"{base}/embeddings", json=body, headers=headers, timeout=120)
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        vecs = [d["embedding"] for d in data]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        raise EmbedUnavailable(f"远程向量服务失败：{str(e)[:300]}") from e
    if len(vecs) != len(texts) or any(len(v) != DIM for v in vecs):
        raise EmbedUnavailable("远程向量服务返回的数量或维度不正确")
    return [_normalize(v) for v in vecs]


def load(download=True):
    """Make sure the model is usable (local: load or download it). Raises EmbedUnavailable."""
    if not remote():
        _local(download)


def embed(texts: list[str], download=True) -> list[list[float]]:
    if not texts:
        return []
    if remote():
        return [
            v
            for i in range(0, len(texts), BATCH)
            for v in _remote(texts[i : i + BATCH])
        ]
    model = _local(download)
    vecs = model.encode(
        texts,
        batch_size=BATCH,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vecs]
