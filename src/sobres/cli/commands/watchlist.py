"""``sobres watchlist`` — named symbol lists."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from sobres.cli.context import Context
from sobres.core.errors import UsageError
from sobres.registry import Params, TickerList, positional, register
from sobres.results import MessageResult, RecordsResult


class WatchlistAddParams(Params):
    name: str = positional(description="Watchlist name, e.g. tech.")
    symbols: TickerList = positional(description="Symbols to add.")


@register(
    "watchlist.add",
    "Add symbols to a watchlist, creating it if absent; duplicates are no-ops.",
    result=MessageResult,
    emits_data=False,
)
def watchlist_add(p: WatchlistAddParams, ctx: Context) -> MessageResult:
    before = ctx.storage.watchlists.get(p.name)
    record = ctx.storage.watchlists.add(p.name, p.symbols)
    added = len(record.symbols) - (len(before.symbols) if before else 0)
    return MessageResult(
        message=f"watchlist {p.name!r}: added {added}, now {len(record.symbols)} symbols",
        detail={"symbols": ", ".join(record.symbols)},
    )


class WatchlistRemoveParams(Params):
    name: str = positional(description="Watchlist name.")
    symbols: TickerList = positional(description="Symbols to remove.")


@register(
    "watchlist.remove", "Remove symbols from a watchlist.", result=MessageResult, emits_data=False
)
def watchlist_remove(p: WatchlistRemoveParams, ctx: Context) -> MessageResult:
    record = ctx.storage.watchlists.remove(p.name, p.symbols)
    if record is None:
        raise UsageError(f"no watchlist named {p.name!r}")
    return MessageResult(
        message=f"watchlist {p.name!r}: now {len(record.symbols)} symbols",
        detail={"symbols": ", ".join(record.symbols)},
    )


class WatchlistListParams(Params):
    pass


@register("watchlist.list", "List watchlists.", result=RecordsResult)
def watchlist_list(p: WatchlistListParams, ctx: Context) -> RecordsResult:
    rows: list[dict[str, Any]] = [
        {
            "name": w.name,
            "symbols": len(w.symbols),
            "updated_at": w.updated_at.isoformat() if w.updated_at else "",
        }
        for w in ctx.storage.watchlists.list()
    ]
    return RecordsResult(rows=rows, columns=["name", "symbols", "updated_at"])


class WatchlistShowParams(Params):
    name: str = positional(description="Watchlist name.")


@register("watchlist.show", "Show a watchlist's symbols.", result=RecordsResult)
def watchlist_show(p: WatchlistShowParams, ctx: Context) -> RecordsResult:
    record = ctx.storage.watchlists.get(p.name)
    if record is None:
        raise UsageError(f"no watchlist named {p.name!r}")
    rows: list[dict[str, Any]] = [{"symbol": s} for s in record.symbols]
    return RecordsResult(rows=rows, columns=["symbol"])


class WatchlistDeleteParams(Params):
    name: str = positional(description="Watchlist name.")
    yes: bool = Field(default=False, description="Skip the confirmation prompt.")


@register("watchlist.delete", "Delete a watchlist.", result=MessageResult, emits_data=False)
def watchlist_delete(p: WatchlistDeleteParams, ctx: Context) -> MessageResult:
    if ctx.storage.watchlists.get(p.name) is None:
        raise UsageError(f"no watchlist named {p.name!r}")
    if not p.yes and not ctx.ask_confirm(f"Delete watchlist {p.name!r}?"):
        raise UsageError("delete cancelled", hint="pass --yes to skip the prompt")
    ctx.storage.watchlists.delete(p.name)
    return MessageResult(message=f"deleted watchlist {p.name!r}")
