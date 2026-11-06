"""Chat model for worker jobs (summaries, term drafts): the agent's OpenAI-compatible endpoint.

MODEL_BASE_URL / MODEL_API_KEY / MODEL_ID; MODEL_API openai-completions (default, POST /chat/completions) or
openai-responses (POST /responses). Up to two retries on connection errors, 429 and 5xx, after 2 s and 6 s or
the Retry-After the server sends (at most 60 s; a cancelled job stops waiting within a second); no retry
after a read timeout. Reasoning blocks (<think>…</think>)
are removed. Errors never include the key.

Usage (contracts/p9.md §二): every answered call inserts one llm_usage row with the response `usage` (chat
completions prompt / completion tokens, responses input / output tokens). Without usage the tokens are
estimated as characters / 2 and the source gets ":estimated". The row carries the job bound with job(run):
job_id, user_id = job owner, project_id; source = the job kind (preannotate, kb_summarize, kb_extract) or the
one set with source() (align), "other" outside a job. A failed insert is logged and does not fail the job.
"""

import contextlib
import contextvars
import email.utils
import json
import logging
import os
import re
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import text as sql

from services.api.db import transaction
from services.worker.main import Cancelled, JobFailed

log = logging.getLogger("worker")

TIMEOUT = 300
RETRY_DELAYS = (2, 6)  # seconds before the first and second retry
RETRY_AFTER_MAX = 60
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
SOURCES = ("preannotate", "kb_summarize", "kb_extract")
_RUN = contextvars.ContextVar("llm_run", default=None)
_SOURCE = contextvars.ContextVar("llm_source", default=None)


@contextlib.contextmanager
def job(run):
    """Model calls inside the block are recorded for this job (services.worker.main.Run)."""
    token = _RUN.set(run)
    try:
        yield
    finally:
        _RUN.reset(token)


@contextlib.contextmanager
def source(name):
    """Model calls inside the block are recorded under this source (e.g. align)."""
    token = _SOURCE.set(name)
    try:
        yield
    finally:
        _SOURCE.reset(token)


def _tokens(usage):
    """(prompt, completion, total) from a usage object, or None without usable numbers."""
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return prompt, completion, total if isinstance(total, int) else prompt + completion


def record_usage(data, prompt_text, answer):
    """Insert the llm_usage row of one answered call."""
    run = _RUN.get()
    name = _SOURCE.get() or (
        run.kind if run is not None and run.kind in SOURCES else "other"
    )
    counts = _tokens(data.get("usage") if isinstance(data, dict) else None)
    if counts is None:
        prompt, completion = -(-len(prompt_text) // 2), -(-len(answer) // 2)
        counts, name = (prompt, completion, prompt + completion), f"{name}:estimated"
    row = {
        "user_id": run.owner_id if run else None,
        "project_id": run.project_id if run else None,
        "job_id": run.id if run else None,
        "source": name,
        "model": model_id(),
        "prompt": counts[0],
        "completion": counts[1],
        "total": counts[2],
    }
    try:
        with transaction() as db:
            db.execute(
                sql(
                    "INSERT INTO llm_usage (user_id, project_id, job_id, source, model,"
                    " prompt_tokens, completion_tokens, total_tokens)"
                    " VALUES (:user_id, :project_id, :job_id, :source, :model,"
                    " :prompt, :completion, :total)"
                ),
                row,
            )
    except Exception:
        log.exception("recording model usage failed: %s", row)


def _env(name):
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_env("MODEL_BASE_URL") and _env("MODEL_ID"))


def model_id() -> str:
    return _env("MODEL_ID")


def _retry_after(r) -> float | None:
    """Seconds from a Retry-After header (seconds or HTTP date), at most RETRY_AFTER_MAX; None without one."""
    value = (r.headers.get("retry-after") or "").strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return min(max(seconds, 0.0), RETRY_AFTER_MAX)


def _wait(seconds):
    """Sleep before a retry; inside a job, checked against cancellation every second (Cancelled at once)."""
    run = _RUN.get()
    if run is None:
        time.sleep(seconds)
        return
    end = time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        if run.cancel.wait(min(1.0, left)) or run.poll():
            raise Cancelled


def _request(url, body, headers):
    """POST with at most len(RETRY_DELAYS) retries on connection errors, 429 and 5xx (Retry-After wins over
    the fixed delay); a read timeout is not retried (TIMEOUT already passed). The last error is reported as
    it happened."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        last = attempt == len(RETRY_DELAYS)
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except httpx.ReadTimeout as e:
            raise JobFailed("MODEL_ERROR", f"对话模型 {TIMEOUT} 秒内没有响应") from e
        except httpx.TransportError as e:
            if last:
                raise JobFailed(
                    "MODEL_ERROR", f"对话模型连接失败：{type(e).__name__}"
                ) from e
            _wait(RETRY_DELAYS[attempt])
            continue
        if (r.status_code == 429 or r.status_code >= 500) and not last:
            wait = _retry_after(r)
            _wait(RETRY_DELAYS[attempt] if wait is None else wait)
            continue
        if r.status_code >= 400:
            raise JobFailed(
                "MODEL_ERROR", f"对话模型返回 HTTP {r.status_code}：{r.text[:200]}"
            )
        try:
            return r.json()
        except ValueError as e:
            raise JobFailed("MODEL_ERROR", "对话模型返回的不是 JSON") from e


def chat(system: str, user: str, temperature=0.2) -> str:
    if not configured():
        raise JobFailed(
            "MODEL_UNAVAILABLE", "未配置对话模型（MODEL_BASE_URL / MODEL_ID）"
        )
    base = _env("MODEL_BASE_URL").rstrip("/")
    headers = (
        {"Authorization": f"Bearer {_env('MODEL_API_KEY')}"}
        if _env("MODEL_API_KEY")
        else {}
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        if _env("MODEL_API") == "openai-responses":
            data = _request(
                f"{base}/responses",
                {"model": model_id(), "input": messages, "temperature": temperature},
                headers,
            )
            text = data.get("output_text") or "".join(
                part.get("text", "")
                for item in data.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
            )
        else:
            data = _request(
                f"{base}/chat/completions",
                {"model": model_id(), "messages": messages, "temperature": temperature},
                headers,
            )
            text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        record_usage(data, system + user, "")  # answered, so the tokens were spent
        raise JobFailed("MODEL_ERROR", "对话模型返回格式不正确") from e
    record_usage(data, system + user, text)
    text = _THINK.sub("", text).strip()
    if not text:
        raise JobFailed("MODEL_ERROR", "对话模型没有返回内容")
    return text


def json_array(text: str) -> list:
    """The first JSON array in a model answer (code fences allowed)."""
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise JobFailed("MODEL_ERROR", "对话模型没有返回 JSON 数组")
    try:
        value = json.loads(text[start : end + 1])
    except ValueError as e:
        raise JobFailed("MODEL_ERROR", f"对话模型返回的 JSON 无法解析：{e}") from e
    if not isinstance(value, list):
        raise JobFailed("MODEL_ERROR", "对话模型没有返回 JSON 数组")
    return value
