"""Chat-model usage and the monthly per-user quota (contracts/p9.md §二).

Rows of llm_usage are written by the worker (services/worker/llm.py) and the agent service. The api checks
the quota when a model-backed job is started (LLM pre-annotation, KB summary, literature / model term
extraction, and their retries); the agent service checks it itself for new messages. Months are calendar
months in the server's local time zone."""

import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from services.api.access import require_admin
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError
from services.api.models import LlmUsage, Project, User

router = APIRouter(prefix="/api")

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def monthly_limit() -> int | None:
    """LLM_MONTHLY_TOKENS_PER_USER; 0 or unset = no limit."""
    value = int((os.environ.get("LLM_MONTHLY_TOKENS_PER_USER") or "0").strip() or 0)
    return value if value > 0 else None


def month_range(month: str | None = None) -> tuple[str, datetime, datetime]:
    """("YYYY-MM", start, end) of the given or the current month, local time zone."""
    now = datetime.now().astimezone()
    if month:
        year, mon = map(int, month.split("-"))
    else:
        year, mon = now.year, now.month
    start = datetime(year, mon, 1).astimezone()
    end = datetime(year + (mon == 12), mon % 12 + 1, 1).astimezone()
    return f"{year:04d}-{mon:02d}", start, end


def _in_month(start, end):
    return [LlmUsage.created_at >= start, LlmUsage.created_at < end]


def monthly_total(db, user_id) -> int:
    _, start, end = month_range()
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LlmUsage.total_tokens), 0)).where(
                LlmUsage.user_id == user_id, *_in_month(start, end)
            )
        )
    )


def check_quota(db, user):
    """429 LLM_QUOTA_EXCEEDED once the user's tokens this month reach the limit. Call before starting a
    model-backed job; running jobs are not stopped."""
    limit = monthly_limit()
    if limit is not None and monthly_total(db, user.id) >= limit:
        raise ApiError(
            429,
            "LLM_QUOTA_EXCEEDED",
            f"本月模型用量已达上限（{limit} token），请联系管理员",
        )


def _base_source():
    """agent:estimated counts as agent."""
    return func.split_part(LlmUsage.source, ":", 1)


@router.get("/me/llm-usage")
def my_usage(user: CurrentUser, db: Db):
    month, start, end = month_range()
    source = _base_source()
    rows = db.execute(
        select(source, func.sum(LlmUsage.total_tokens))
        .where(LlmUsage.user_id == user.id, *_in_month(start, end))
        .group_by(source)
        .order_by(func.sum(LlmUsage.total_tokens).desc(), source)
    ).all()
    by_source = [{"source": s, "total_tokens": int(n)} for s, n in rows]
    return {
        "month": month,
        "total_tokens": sum(x["total_tokens"] for x in by_source),
        "limit": monthly_limit(),
        "by_source": by_source,
    }


@router.get("/admin/llm-usage")
def admin_usage(
    user: CurrentUser,
    db: Db,
    month: Month = None,
    group: Literal["user", "project"] = "user",
):
    """Totals of the month by user (name = email) or project (name = project name); key null = rows whose
    user or project is gone or was never set."""
    require_admin(user)
    month, start, end = month_range(month)
    if group == "user":
        key, name, join = (
            LlmUsage.user_id,
            User.email,
            (User, User.id == LlmUsage.user_id),
        )
    else:
        key, name, join = (
            LlmUsage.project_id,
            Project.name,
            (Project, Project.id == LlmUsage.project_id),
        )
    total = func.sum(LlmUsage.total_tokens)
    rows = db.execute(
        select(
            key,
            name,
            total,
            func.sum(LlmUsage.prompt_tokens),
            func.sum(LlmUsage.completion_tokens),
            func.count(),
        )
        .outerjoin(*join)
        .where(*_in_month(start, end))
        .group_by(key, name)
        .order_by(total.desc(), name)
    ).all()
    items = [
        {
            "key": k,
            "name": n,
            "total_tokens": int(t),
            "prompt_tokens": int(p),
            "completion_tokens": int(c),
            "calls": calls,
        }
        for k, n, t, p, c, calls in rows
    ]
    return {
        "month": month,
        "items": items,
        "total": len(items),
        "total_tokens": sum(x["total_tokens"] for x in items),
    }
