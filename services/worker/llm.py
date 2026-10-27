"""Chat model for worker jobs (summaries, term drafts): the agent's OpenAI-compatible endpoint.

MODEL_BASE_URL / MODEL_API_KEY / MODEL_ID; MODEL_API openai-completions (default, POST /chat/completions) or
openai-responses (POST /responses). One retry on timeouts, 429 and 5xx. Reasoning blocks (<think>…</think>)
are removed. Errors never include the key.
"""

import json
import os
import re
import time

import httpx

from services.worker.main import JobFailed

TIMEOUT = 300
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _env(name):
    return (os.environ.get(name) or "").strip()


def configured() -> bool:
    return bool(_env("MODEL_BASE_URL") and _env("MODEL_ID"))


def model_id() -> str:
    return _env("MODEL_ID")


def _request(url, body, headers):
    for attempt in (1, 2):
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=TIMEOUT)
        except httpx.TransportError as e:
            if attempt == 2:
                raise JobFailed(
                    "MODEL_ERROR", f"对话模型连接失败：{type(e).__name__}"
                ) from e
            time.sleep(3)
            continue
        if (r.status_code == 429 or r.status_code >= 500) and attempt == 1:
            time.sleep(3)
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
        raise JobFailed("MODEL_ERROR", "对话模型返回格式不正确") from e
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
