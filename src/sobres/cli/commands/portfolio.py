"""``sobres portfolio`` — save, list, show and delete named portfolios."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from sobres.cli.context import Context
from sobres.core.errors import StorageConflictError, UsageError
from sobres.data.storage.base import PortfolioRecord
from sobres.registry import Params, TickerList, Weights, positional, register
from sobres.results import MessageResult, RecordsResult


class PortfolioSaveParams(Params):
    name: str = positional(description="Portfolio name, e.g. core.")
    tickers: TickerList = Field(description="Ticker symbols.")
    weights: Weights = Field(
        default_factory=list, description="Optional weights, one per ticker, summing to 1."
    )
    force: bool = Field(default=False, description="Replace an existing portfolio of this name.")

    @model_validator(mode="after")
    def _weights_valid(self) -> PortfolioSaveParams:
        if self.weights:
            if len(self.weights) != len(self.tickers):
                raise ValueError(f"{len(self.weights)} weights for {len(self.tickers)} tickers")
            total = sum(self.weights)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"weights sum to {total:.6f}, not 1.0")
        return self


@register(
    "portfolio.save",
    "Save a named portfolio (tickers, optionally weights).",
    result=MessageResult,
    emits_data=False,
)
def portfolio_save(p: PortfolioSaveParams, ctx: Context) -> MessageResult:
    record = PortfolioRecord(
        name=p.name, tickers=tuple(p.tickers), weights=tuple(p.weights) if p.weights else None
    )
    try:
        saved = ctx.storage.portfolios.save(record, force=p.force)
    except StorageConflictError:
        raise UsageError(
            f"a portfolio named {p.name!r} already exists",
            hint="pass --force to replace it, or choose another name",
        ) from None
    kind = "weighted" if saved.weights else "unweighted universe"
    return MessageResult(
        message=f"saved portfolio {saved.name!r}: {saved.holdings} holdings ({kind})",
        detail={"tickers": ", ".join(saved.tickers)},
    )


class PortfolioListParams(Params):
    pass


@register("portfolio.list", "List saved portfolios.", result=RecordsResult)
def portfolio_list(p: PortfolioListParams, ctx: Context) -> RecordsResult:
    rows: list[dict[str, Any]] = [
        {
            "name": r.name,
            "holdings": r.holdings,
            "weighted": r.weights is not None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in ctx.storage.portfolios.list()
    ]
    return RecordsResult(rows=rows, columns=["name", "holdings", "weighted", "updated_at"])


class PortfolioShowParams(Params):
    name: str = positional(description="Portfolio name.")


@register("portfolio.show", "Show a saved portfolio's holdings.", result=RecordsResult)
def portfolio_show(p: PortfolioShowParams, ctx: Context) -> RecordsResult:
    record = resolve_portfolio(p.name, ctx)
    weights = record.weights or (None,) * record.holdings
    rows: list[dict[str, Any]] = [
        {"ticker": t, "weight": w} for t, w in zip(record.tickers, weights, strict=True)
    ]
    return RecordsResult(rows=rows, columns=["ticker", "weight"])


class PortfolioDeleteParams(Params):
    name: str = positional(description="Portfolio name.")
    yes: bool = Field(default=False, description="Skip the confirmation prompt.")


@register("portfolio.delete", "Delete a saved portfolio.", result=MessageResult, emits_data=False)
def portfolio_delete(p: PortfolioDeleteParams, ctx: Context) -> MessageResult:
    resolve_portfolio(p.name, ctx)
    if not p.yes and not ctx.ask_confirm(f"Delete portfolio {p.name!r}?"):
        raise UsageError("delete cancelled", hint="pass --yes to skip the prompt")
    ctx.storage.portfolios.delete(p.name)
    return MessageResult(message=f"deleted portfolio {p.name!r}")


def resolve_portfolio(name: str, ctx: Context) -> PortfolioRecord:
    record = ctx.storage.portfolios.get(name)
    if record is None:
        known = ", ".join(r.name for r in ctx.storage.portfolios.list()) or "none saved yet"
        raise UsageError(f"no portfolio named {name!r}", hint=f"saved portfolios: {known}")
    return record
