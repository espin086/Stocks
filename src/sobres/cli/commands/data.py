"""``sobres data`` — the data layer, exposed so inputs can be inspected."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from sobres.cli.context import Context
from sobres.core.errors import UsageError
from sobres.data.base import FactorFrequency, FactorModel, PriceField
from sobres.registry import CurrencyPairList, Params, SeriesList, TickerList, positional, register
from sobres.results import FactorTable, FxTable, MacroTable, PriceTable, Provenance


class _Window(Params):
    start: date = Field(description="First date, YYYY-MM-DD.")
    end: date | None = Field(default=None, description="Last date (default: today).")

    @model_validator(mode="after")
    def _ordered(self) -> _Window:
        if self.end is not None and self.end < self.start:
            raise ValueError(f"end {self.end} precedes start {self.start}")
        return self


class PricesParams(_Window):
    tickers: TickerList = positional(description="Ticker symbols, e.g. AAPL MSFT NESN.SW.")
    field: PriceField = Field(
        default="adj_close",
        description="Price field; adj_close is split- and dividend-adjusted (total return).",
    )


@register(
    "data.prices",
    "Fetch and cache daily prices for one or more tickers.",
    result=PriceTable,
    uses_providers=True,
)
def prices(p: PricesParams, ctx: Context) -> PriceTable:
    end = p.end or ctx.today()
    frame = ctx.price_provider().get_prices(p.tickers, p.start, end, p.field)
    prov = Provenance.from_attrs(frame.attrs, start=p.start.isoformat(), end=end.isoformat())
    return PriceTable(frame=frame, provenance=prov)


class MacroParams(_Window):
    series: SeriesList = positional(description="FRED series ids, e.g. DGS10 CPIAUCSL.")


@register(
    "data.macro",
    "Fetch and cache FRED macro series (needs a free FRED API key).",
    result=MacroTable,
    uses_providers=True,
)
def macro(p: MacroParams, ctx: Context) -> MacroTable:
    end = p.end or ctx.today()
    frame = ctx.macro_provider().get_series(p.series, p.start, end)
    prov = Provenance.from_attrs(frame.attrs, start=p.start.isoformat(), end=end.isoformat())
    return MacroTable(frame=frame, provenance=prov)


class FactorsParams(Params):
    model: FactorModel = Field(default="ff5", description="Factor model.")
    frequency: FactorFrequency = Field(default="monthly", description="Observation frequency.")
    start: date | None = Field(default=None, description="First date (default: full history).")
    end: date | None = Field(default=None, description="Last date (default: latest).")


@register(
    "data.factors",
    "Fetch and cache Fama-French factor returns from the Ken French Data Library.",
    result=FactorTable,
    uses_providers=True,
)
def factors(p: FactorsParams, ctx: Context) -> FactorTable:
    frame = ctx.factor_provider().get_factors(p.model, p.frequency, p.start, p.end)
    prov = Provenance.from_attrs(
        frame.attrs,
        start=str(frame.index.min().date()) if len(frame) else None,
        end=str(frame.index.max().date()) if len(frame) else None,
        notes=["values are decimal returns (Ken French publishes percent)"],
    )
    return FactorTable(frame=frame, provenance=prov, model=p.model, frequency=p.frequency)


class FxParams(_Window):
    pairs: CurrencyPairList = positional(
        description="Currency pairs as EURUSD or EUR/USD: units of quote per one base."
    )
    source: Literal["ecb"] = Field(default="ecb", description="Rate source.")

    @model_validator(mode="after")
    def _pairs_valid(self) -> FxParams:
        for pair in self.pairs:
            cleaned = pair.replace("/", "").replace("-", "")
            if len(cleaned) != 6 or not cleaned.isalpha():
                raise ValueError(f"pair {pair!r} must be six letters like EURUSD or EUR/USD")
        return self


@register(
    "data.fx",
    "Fetch and cache daily exchange rates (ECB reference rates, keyless).",
    result=FxTable,
    uses_providers=True,
)
def fx(p: FxParams, ctx: Context) -> FxTable:
    end = p.end or ctx.today()
    provider = ctx.fx_provider()
    pairs = [pair.replace("/", "").replace("-", "").upper() for pair in p.pairs]
    frame = provider.get_rates(pairs, p.start, end)
    if frame.empty:
        raise UsageError("no rates in the requested window", hint="widen --start/--end")
    prov = Provenance.from_attrs(
        frame.attrs,
        start=p.start.isoformat(),
        end=end.isoformat(),
        notes=[
            f"rates are units of quote per one base; source base currency {provider.base_currency}"
        ],
    )
    return FxTable(frame=frame, provenance=prov, base=provider.base_currency)
