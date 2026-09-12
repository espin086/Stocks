"""``sobres cache`` — cached observations only; the wider ``db`` group is 0003."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from sobres.cli.context import Context
from sobres.core.errors import UsageError
from sobres.registry import Params, register
from sobres.results import MessageResult, RecordsResult


class CacheInfoParams(Params):
    pass


@register(
    "cache.info", "Show cache size on disk, entry count and oldest entry age.", result=RecordsResult
)
def info(p: CacheInfoParams, ctx: Context) -> RecordsResult:
    stats = ctx.storage.observations.cache_stats()
    age_days = (
        (datetime.now(UTC) - stats.oldest_fetch).days if stats.oldest_fetch is not None else None
    )
    rows: list[dict[str, Any]] = [
        {"metric": "location", "value": ctx.storage.location},
        {"metric": "size_bytes", "value": stats.size_bytes},
        {"metric": "entries", "value": stats.entries},
        {"metric": "series", "value": stats.series},
        {"metric": "oldest_entry_age_days", "value": age_days},
    ]
    return RecordsResult(rows=rows, columns=["metric", "value"])


class CacheClearParams(Params):
    yes: bool = Field(default=False, description="Skip the confirmation prompt.")
    provider: str | None = Field(
        default=None, description="Only clear one provider's observations."
    )


@register(
    "cache.clear",
    "Delete cached provider observations (never user-authored rows).",
    result=MessageResult,
    emits_data=False,
)
def clear(p: CacheClearParams, ctx: Context) -> MessageResult:
    scope = f"provider {p.provider}" if p.provider else "every provider"
    if not p.yes and not ctx.ask_confirm(f"Delete cached observations for {scope}?"):
        raise UsageError("cache clear cancelled", hint="pass --yes to skip the prompt")
    removed = ctx.storage.observations.clear_observations(p.provider)
    return MessageResult(
        message=f"removed {removed} cached rows for {scope}; portfolios, goals and runs untouched",
        detail={"removed": removed, "preserved": "portfolios, watchlists, goals, runs"},
    )
