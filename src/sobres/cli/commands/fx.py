"""``sobres fx`` — rates, conversion, currency attribution and hedging. Never a forecast.

Adapters only: the ECB provider quotes rates, FRED supplies short-term rates
for the hedge, the fx core module does the arithmetic. Every hedged figure carries
the covered-interest-parity caveat; no subcommand projects a rate.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field, model_validator

from sobres.cli.commands.optimize import UniverseParams, resolve_symbols
from sobres.cli.context import Context
from sobres.core import fx as fxm
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.returns import apply_nan_policy, simple_returns
from sobres.core.risk import risk_metrics
from sobres.data.currency import CurrencyPair, FxRates, convert, frame_currencies, fx_returns
from sobres.registry import Currency, CurrencyPairList, Params, Weights, positional, register
from sobres.results import FrameResult, Provenance, RecordsResult, Result

# Short-term (3-month) rates on FRED, decimal-annual after /100; the hedge needs both legs.
SHORT_RATE_SERIES: dict[str, str] = {
    "USD": "DTB3",
    "GBP": "IR3TIB01GBM156N",
    "EUR": "IR3TIB01EZM156N",
    "JPY": "IR3TIB01JPM156N",
    "CHF": "IR3TIB01CHM156N",
    "CAD": "IR3TIB01CAM156N",
    "AUD": "IR3TIB01AUM156N",
}


class FxReport(Result):
    report: ClassVar[bool] = True


# --------------------------------------------------------------------------- #
# fx rates / fx convert
# --------------------------------------------------------------------------- #


class RatesParams(Params):
    pairs: CurrencyPairList = positional(
        description="Currency pairs as EURUSD or EUR/USD: units of quote per one base."
    )
    start: date = Field(description="First date, YYYY-MM-DD.")
    end: date | None = Field(default=None, description="Last date (default: today).")


class RatesTable(FrameResult):
    default_kind: ClassVar[str] = "rate"
    base: str


@register("fx.rates", "Daily exchange rates for one or more pairs.", result=RatesTable)
def rates(p: RatesParams, ctx: Context) -> RatesTable:
    provider = ctx.fx_provider()
    frame = provider.get_rates(list(p.pairs), p.start, p.end or ctx.today())
    carried = [str(d.date()) for d in frame.index[frame.isna().any(axis=1)]]
    prov = Provenance.from_attrs(
        frame.attrs,
        start=str(frame.index.min().date()) if len(frame) else None,
        end=str(frame.index.max().date()) if len(frame) else None,
        notes=[
            f"rates are units of quote per one base; source base currency {provider.base_currency}",
            *(["no quote on: " + ", ".join(carried[:10])] if carried else []),
        ],
    )
    return RatesTable(frame=frame, provenance=prov, base=provider.base_currency)


class ConvertParams(Params):
    amount: float = positional(description="Amount in the source currency.")
    from_ccy: Currency = Field(alias="from", description="Source currency code.")
    to_ccy: Currency = Field(alias="to", description="Target currency code.")
    on: date | None = Field(default=None, description="Rate date (default: today).")


class Conversion(RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"item": "text", "value": "text"}
    amount: float
    converted: float
    rate: float
    rate_date: str
    carried_forward_from: str | None
    source: str

    def header_lines(self) -> list[str]:
        lines = [
            f"{self.amount:,.2f} -> {self.converted:,.2f} at {self.rate:.6f} on {self.rate_date} "
            f"({self.source})"
        ]
        if self.carried_forward_from:
            lines.append(
                f"no quote on {self.rate_date}: the rate was carried forward from "
                f"{self.carried_forward_from}"
            )
        return [*lines, *super().header_lines()]


@register("fx.convert", "Convert an amount between currencies at a dated rate.", result=Conversion)
def convert_amount(p: ConvertParams, ctx: Context) -> Conversion:
    on = p.on or ctx.today()
    provider = ctx.fx_provider()
    pair = CurrencyPair(p.from_ccy, p.to_ccy)
    start = date(on.year, on.month, 1) - pd.Timedelta(days=45)
    frame = provider.get_rates([pair], start, on)
    table = FxRates(frame, provider.base_currency, source=f"{provider.name} reference rates")
    if pair.base == pair.quote:
        rate_used, carried = 1.0, None
    else:
        # The table has the pair's own column; ask for it directly through the base.
        table = FxRates(
            provider.rates_table([pair.base, pair.quote], start, on).frame,
            provider.base_currency,
            source=f"{provider.name} reference rates",
        )
        rate_used = table.rate(pair, on)
        carried = table.carry_forwards[-1]["from"] if table.carry_forwards else None
    converted = convert(p.amount, p.from_ccy, p.to_ccy, on=on, rates=table)
    rows = [
        {"item": "amount", "value": f"{p.amount:,.2f} {p.from_ccy}"},
        {"item": "converted", "value": f"{converted:,.2f} {p.to_ccy}"},
        {"item": "rate", "value": f"{rate_used:.6f} {p.to_ccy} per {p.from_ccy}"},
        {"item": "rate_date", "value": carried or on.isoformat()},
        {"item": "source", "value": table.source},
    ]
    return Conversion(
        rows=rows,
        columns=["item", "value"],
        amount=p.amount,
        converted=converted,
        rate=rate_used,
        rate_date=on.isoformat(),
        carried_forward_from=carried,
        source=table.source,
        provenance=Provenance(provider=provider.name, start=str(start), end=on.isoformat()),
    )


# --------------------------------------------------------------------------- #
# fx attribution
# --------------------------------------------------------------------------- #


class AttributionParams(UniverseParams):
    weights: Weights = Field(default_factory=list, description="Portfolio weights (default equal).")
    base: Currency = Field(description="Base currency the return is measured in.")

    @model_validator(mode="after")
    def _weights_match(self) -> AttributionParams:
        if self.weights and self.tickers and len(self.weights) != len(self.tickers):
            raise ValueError(f"{len(self.weights)} weights for {len(self.tickers)} tickers")
        return self


class Attribution(FxReport, RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"ticker": "text", "currency": "text"}
    base: str
    risk: dict[str, Any]

    def header_lines(self) -> list[str]:
        r = self.risk
        corr = ", ".join(
            f"{k} {v:+.2f}"
            for k, v in r["correlations"].items()
            if v == v  # skip NaN
        )
        exposure = ", ".join(f"{k} {v:.1%}" for k, v in r["exposures"].items())
        return [
            f"returns measured in {self.base}; total = local + fx + (local times fx), "
            "the cross term shown on its own",
            f"volatility in {self.base} {r['total_volatility']:.2%}; with currencies held fixed "
            f"{r['local_volatility']:.2%}; currency contribution {r['currency_contribution']:+.2%} "
            "(not additive: it depends on the correlations below)",
            f"local-return vs currency correlation: {corr or 'none (single currency)'}",
            f"net currency exposure: {exposure}",
            *super().header_lines(),
        ]


def _local_and_fx(
    p: UniverseParams, ctx: Context, base: str
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], str, Provenance]:
    """Local returns, per-asset currency returns against ``base``, and the currency map."""
    end = p.end or ctx.today()
    tickers, _ = resolve_symbols(p, ctx)
    prices = ctx.price_provider().get_prices(tickers, p.start, end)
    currencies = frame_currencies(prices)
    from sobres.data.gaps import apply_fill_policy

    filled = apply_fill_policy(prices, p.fill)
    local = pd.DataFrame(apply_nan_policy(simple_returns(filled), "drop"))
    frequency = "daily"
    from sobres.core.conventions import infer_frequency

    frequency = infer_frequency(pd.DatetimeIndex(local.index))
    foreign = sorted({c for c in currencies.values() if c != base})
    fx = pd.DataFrame(0.0, index=local.index, columns=local.columns)
    source = "no conversion needed"
    if foreign:
        provider = ctx.fx_provider()
        table = provider.rates_table([*foreign, base], p.start, end)
        source = table.source
        for column in local.columns:
            ccy = currencies.get(column, base)
            if ccy != base:
                # base per one unit of the asset's currency: a stronger local currency is a gain.
                series = fx_returns(table, CurrencyPair(ccy, base), pd.DatetimeIndex(local.index))
                fx[column] = series.fillna(0.0).to_numpy()
    provenance = Provenance.from_attrs(
        prices.attrs,
        start=str(local.index.min().date()),
        end=str(local.index.max().date()),
        notes=[f"currency returns from {source}"],
    )
    provenance.currency = base
    return local, fx, currencies, frequency, provenance


@register(
    "fx.attribution",
    "Split each asset's base-currency return into local, currency and cross components.",
    result=Attribution,
)
def attribution(p: AttributionParams, ctx: Context) -> Attribution:
    local, fx, currencies, frequency, provenance = _local_and_fx(p, ctx, p.base)
    tickers = list(local.columns)
    weights = (
        dict(zip(tickers, p.weights, strict=True))
        if p.weights
        else {t: 1.0 / len(tickers) for t in tickers}
    )
    rows = []
    components: dict[str, fxm.Decomposition] = {}
    for t in tickers:
        per_period = fxm.decompose_return(local[t], fx[t])
        d = fxm.compound_decomposition(per_period)
        components[t] = d
        rows.append(
            {
                "ticker": t,
                "currency": currencies.get(t, p.base),
                "local": d.local,
                "fx": d.fx,
                "cross": d.cross,
                "total": d.total,
                "weight": weights[t],
            }
        )
    port = fxm.aggregate(components, weights)
    rows.append(
        {
            "ticker": "portfolio",
            "currency": p.base,
            "local": port.local,
            "fx": port.fx,
            "cross": port.cross,
            "total": port.total,
            "weight": 1.0,
        }
    )
    risk = fxm.currency_risk(local, fx, weights, currencies, p.base, frequency)
    return Attribution(
        rows=rows,
        columns=["ticker", "currency", "local", "fx", "cross", "total", "weight"],
        base=p.base,
        risk={
            "total_volatility": risk.total_volatility,
            "local_volatility": risk.local_volatility,
            "currency_contribution": risk.currency_contribution,
            "correlations": risk.correlations,
            "exposures": risk.exposures,
        },
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# fx hedge
# --------------------------------------------------------------------------- #


class HedgeParams(AttributionParams):
    compare: str = Field(default="unhedged", description="What to compare against (unhedged).")


class HedgeComparison(FxReport, RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"metric": "text"}
    base: str
    hedge_effect: float
    rates_used: dict[str, str]

    def header_lines(self) -> list[str]:
        rates = ", ".join(f"{k}: FRED {v}" for k, v in self.rates_used.items())
        return [
            f"hedged versus unhedged portfolio returns in {self.base}; short-term rates: {rates}",
            fxm.HEDGE_NOTE,
            f"cumulative hedged minus unhedged over the window: {self.hedge_effect:+.2%} "
            f"({'the hedge helped' if self.hedge_effect > 0 else 'the hedge cost'})",
            *super().header_lines(),
        ]


def short_rates(
    ctx: Context, currencies: list[str], start: date, end: date
) -> dict[str, pd.Series]:
    """Decimal annual 3-month rates per currency from FRED; a missing series is loud."""
    out: dict[str, pd.Series] = {}
    for ccy in currencies:
        series_id = SHORT_RATE_SERIES.get(ccy)
        if series_id is None:
            raise InsufficientDataError(
                f"no short-term rate series is known for {ccy}",
                hint="known currencies: " + ", ".join(sorted(SHORT_RATE_SERIES)),
            )
        try:
            frame = ctx.macro_provider().get_series([series_id], start, end)
        except Exception as exc:
            raise InsufficientDataError(
                f"short-term rates for {ccy} (FRED {series_id}) are unavailable over the window: "
                f"{type(exc).__name__}: {exc}",
                hint="the hedge cannot be constructed without both legs; an unhedged result is "
                "not returned in its place",
            ) from exc
        series = frame[series_id].dropna() / 100.0
        if series.empty:
            raise InsufficientDataError(
                f"no observations of {ccy} short-term rates (FRED {series_id}) over the window",
                hint="widen --start/--end",
            )
        out[ccy] = series
    return out


def hedged_universe(
    p: UniverseParams, ctx: Context, base: str
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], str, dict[str, str]]:
    """Unhedged (converted) and hedged return frames for a universe, with the rates used."""
    local, fx, currencies, frequency, _ = _local_and_fx(p, ctx, base)
    end = p.end or ctx.today()
    foreign = sorted({c for c in currencies.values() if c != base})
    rates = short_rates(ctx, [base, *foreign], p.start, end)
    unhedged = pd.DataFrame(
        (1.0 + local.to_numpy()) * (1.0 + fx.to_numpy()) - 1.0,
        index=local.index,
        columns=local.columns,
    )
    hedged = local.copy()
    for column in local.columns:
        ccy = currencies.get(column, base)
        if ccy != base:
            hedged[column] = fxm.hedged_returns(local[column], rates[base], rates[ccy], frequency)
    used = {c: SHORT_RATE_SERIES[c] for c in [base, *foreign]}
    return unhedged, hedged.dropna(), currencies, frequency, used


@register(
    "fx.hedge",
    "Risk panels for hedged and unhedged returns side by side, and what the hedge cost.",
    result=HedgeComparison,
)
def hedge(p: HedgeParams, ctx: Context) -> HedgeComparison:
    if p.compare != "unhedged":
        raise UsageError("--compare accepts only: unhedged")
    unhedged, hedged, _currencies, frequency, used = hedged_universe(p, ctx, p.base)
    tickers = list(unhedged.columns)
    weights = (
        dict(zip(tickers, p.weights, strict=True))
        if p.weights
        else {t: 1.0 / len(tickers) for t in tickers}
    )
    w = pd.Series(weights)
    port_u = pd.Series(unhedged[tickers].to_numpy() @ w.to_numpy(), index=unhedged.index)
    port_h = pd.Series(hedged[tickers].to_numpy() @ w.to_numpy(), index=hedged.index)
    from sobres.cli.commands.optimize import resolve_risk_free

    rf, _source = resolve_risk_free(p.risk_free, p.start, p.end or ctx.today(), ctx)
    panel_u = risk_metrics(port_u, rf, frequency)
    panel_h = risk_metrics(port_h, rf, frequency)
    rows = []
    for key, hv in panel_h.as_dict().items():
        if key in ("frequency", "risk_free"):
            continue
        rows.append({"metric": key, "hedged": hv, "unhedged": panel_u.as_dict()[key]})
    return HedgeComparison(
        rows=rows,
        columns=["metric", "hedged", "unhedged"],
        base=p.base,
        hedge_effect=fxm.hedge_cost(port_h, port_u),
        rates_used=used,
        provenance=Provenance(
            currency=p.base,
            start=str(hedged.index.min().date()),
            end=str(hedged.index.max().date()),
            notes=[f"risk-free rate {rf:.4%} ({_source})"],
        ),
    )
