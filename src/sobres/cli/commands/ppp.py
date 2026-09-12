"""``sobres ppp`` — what a currency buys, never what it will trade for.

Adapters only: PPP factors from the configured provider, market rates from
the ECB, price indices from FRED, real effective rates from the BIS, the
arithmetic from ``core/ppp.py``. Every output carries the framing that PPP is a
long-run relationship with little short-run predictive power.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field, model_validator

from sobres.cli.context import Context
from sobres.core import goals as g
from sobres.core import ppp as pm
from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.data.currency import CurrencyPair
from sobres.registry import Currency, Params, positional, register
from sobres.results import FrameResult, Provenance, RecordsResult, Result
from sobres.settings import PPP_STALE_YEARS

CPI_SERIES: dict[str, str] = {"USD": "CPIAUCSL", "GBP": "GBRCPIALLMINMEI"}
REER_AREA: dict[str, str] = {"USA": "US", "GBR": "GB", "JPN": "JP", "EMU": "XM", "MEX": "MX"}


class PppReport(Result):
    report: ClassVar[bool] = True

    def header_lines(self) -> list[str]:
        return [pm.PPP_FRAMING, *super().header_lines()]


def _figures(ctx: Context, countries: list[str]) -> tuple[dict[str, pm.PppFigure], list[str]]:
    """Absolute PPP factors for each country from the configured provider, with staleness notes."""
    provider = ctx.ppp_provider()
    codes = [pm.country(c)[2] for c in countries]
    frame = provider.get_ppp(codes, date(2010, 1, 1), ctx.today())
    vintages = frame.attrs.get("vintage", {})
    threshold = int(ctx.config.get(PPP_STALE_YEARS.key) or pm.DEFAULT_STALE_YEARS)
    out: dict[str, pm.PppFigure] = {}
    notes: list[str] = []
    for country, code in zip(countries, codes, strict=True):
        series = frame[code].dropna()
        v = vintages.get(code, {})
        vintage = pm.Vintage(
            benchmark_year=int(v.get("benchmark_year", series.index[-1].year)),
            reference_period=str(v.get("reference_period", "")),
            release_date=str(v.get("release_date", "unknown")),
            source=str(v.get("source", provider.name)),
        )
        name, currency, _ = pm.country(country)
        out[country] = pm.PppFigure(country, currency, float(series.iloc[-1]), "USD", vintage)
        line = (
            f"{country} ({name}): {vintage.source}, benchmark {vintage.benchmark_year}, "
            f"reference {vintage.reference_period}, released {vintage.release_date}"
        )
        if vintage.is_stale(ctx.today(), threshold):
            line += (
                f" — STALE: {vintage.age_years(ctx.today()):.1f} years old (threshold {threshold})"
            )
        notes.append(line)
    return out, notes


def _market_rate(ctx: Context, base: str, quote: str, on: date) -> tuple[float, str]:
    if base == quote:
        return 1.0, "identity"
    provider = ctx.fx_provider()
    table = provider.rates_table([base, quote], on - pd.Timedelta(days=45), on)
    rate = table.rate(CurrencyPair(base, quote), on)
    used = table.carry_forwards[-1]["from"] if table.carry_forwards else on.isoformat()
    return rate, f"{table.source} on {used}"


# --------------------------------------------------------------------------- #
# ppp compare
# --------------------------------------------------------------------------- #


class CompareParams(Params):
    base: Currency = Field(default="USD", description="Base currency (or ISO3 country).")
    vs: list[str] = Field(min_length=1, description="Currencies or ISO3 countries to compare.")
    on: date | None = Field(default=None, description="Market-rate date (default: today).")


class Comparison(PppReport, RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {
        "currency": "text",
        "country": "text",
        "verdict": "text",
    }
    base: str
    method: str
    vintages: list[str]

    def header_lines(self) -> list[str]:
        return [
            *super().header_lines(),
            f"method: absolute PPP (published conversion factors), gap = market / PPP - 1, "
            f"rates as units of currency per one {self.base}",
            pm.PERSISTENT_GAP_NOTE,
            *self.vintages,
        ]


@register(
    "ppp.compare",
    "Market rate against the PPP rate for each currency: the valuation gap, in words.",
    result=Comparison,
)
def compare(p: CompareParams, ctx: Context) -> Comparison:
    on = p.on or ctx.today()
    base_country = pm.country_for_currency(p.base)
    targets = [pm.country_for_currency(v) for v in p.vs]
    figures, vintages = _figures(ctx, [base_country, *targets])
    base_fig = figures[base_country]
    rows = []
    for raw, country in zip(p.vs, targets, strict=True):
        fig = figures[country]
        ppp = pm.ppp_rate(fig, base_fig)
        market, source = _market_rate(ctx, base_fig.currency, fig.currency, on)
        gap = pm.valuation_gap(base_fig.currency, fig.currency, market, ppp)
        rows.append(
            {
                "currency": fig.currency,
                "country": country,
                "market_rate": market,
                "ppp_rate": ppp,
                "gap": gap.gap,
                "verdict": gap.statement,
                "rate_source": source,
            }
        )
        _ = raw
    return Comparison(
        rows=rows,
        columns=["currency", "country", "market_rate", "ppp_rate", "gap", "verdict", "rate_source"],
        base=base_fig.currency,
        method="absolute",
        vintages=vintages,
        provenance=Provenance(provider=ctx.ppp_provider().name, end=on.isoformat()),
    )


# --------------------------------------------------------------------------- #
# ppp relative / ppp real
# --------------------------------------------------------------------------- #


class RelativeParams(Params):
    pair: str = positional(description="Currency pair, e.g. USDGBP (units of quote per base).")
    anchor: date = Field(description="Anchor date; relative PPP says nothing about the level.")
    end: date | None = Field(default=None, description="Last date (default: today).")


class RelativePath(PppReport, FrameResult):
    pair: str
    anchor: str
    anchor_rate: float
    indices: dict[str, str]

    def header_lines(self) -> list[str]:
        return [
            *super().header_lines(),
            f"method: relative PPP from the anchor {self.anchor} at {self.anchor_rate:.6f}; "
            "the level is the anchor's, only the drift is implied",
            "price indices: " + ", ".join(f"{k} FRED {v}" for k, v in self.indices.items()),
            "columns: market rate, the relative-PPP-implied rate, and the real exchange rate "
            "(nominal adjusted by the price-level ratio, index base = anchor)",
        ]


def _cpi(ctx: Context, currency: str, start: date, end: date) -> pd.Series:
    series_id = CPI_SERIES.get(currency)
    if series_id is None:
        raise InsufficientDataError(
            f"no consumer price index is configured for {currency}",
            hint="known: " + ", ".join(f"{k} ({v})" for k, v in CPI_SERIES.items()),
        )
    frame = ctx.macro_provider().get_series([series_id], start, end)
    return pd.Series(frame[series_id].dropna())


@register(
    "ppp.relative",
    "Relative PPP: the rate path implied by the inflation differential since an anchor date.",
    result=RelativePath,
)
def relative(p: RelativeParams, ctx: Context) -> RelativePath:
    pair = CurrencyPair.parse(p.pair)
    end = p.end or ctx.today()
    home = _cpi(ctx, pair.base, p.anchor - pd.Timedelta(days=45), end)
    foreign = _cpi(ctx, pair.quote, p.anchor - pd.Timedelta(days=45), end)
    provider = ctx.fx_provider()
    table = provider.rates_table([pair.base, pair.quote], p.anchor - pd.Timedelta(days=45), end)
    market = table.series(pair).dropna()
    anchor_rate = table.rate(pair, p.anchor)
    implied = pm.relative_ppp(anchor_rate, home, foreign, p.anchor)
    monthly_market = market.resample("ME").last()
    real = pm.real_exchange_rate(
        monthly_market, home.resample("ME").last(), foreign.resample("ME").last()
    )
    frame = pd.DataFrame(
        {"market": monthly_market, "relative_ppp": implied.resample("ME").last(), "real_rate": real}
    )
    frame = frame.loc[str(p.anchor) :].dropna(how="all")
    frame.index.name = "date"
    pm.combine_guard(None, implied)
    return RelativePath(
        frame=frame,
        pair=pair.code,
        anchor=p.anchor.isoformat(),
        anchor_rate=anchor_rate,
        indices={pair.base: CPI_SERIES[pair.base], pair.quote: CPI_SERIES[pair.quote]},
        provenance=Provenance(
            provider=provider.name, start=p.anchor.isoformat(), end=end.isoformat()
        ),
    )


# --------------------------------------------------------------------------- #
# ppp reer
# --------------------------------------------------------------------------- #


class ReerParams(Params):
    countries: list[str] = positional(description="ISO3 countries (USA GBR JPN EMU MEX).")
    start: date = Field(default=date(2015, 1, 1), description="First month.")
    end: date | None = Field(default=None, description="Last month (default: today).")


class ReerTable(PppReport, FrameResult):
    def header_lines(self) -> list[str]:
        return [
            *super().header_lines(),
            "real effective exchange rates as published by the BIS (broad basket, CPI-based, "
            "2020 = 100); no trade weights are constructed here",
        ]


@register("ppp.reer", "BIS real effective exchange rates, taken as published.", result=ReerTable)
def reer(p: ReerParams, ctx: Context) -> ReerTable:
    areas = []
    for c in p.countries:
        code = pm.country(c)[2]
        if code not in REER_AREA:
            raise InsufficientDataError(
                f"no BIS REER area is mapped for {code}",
                hint="known: " + ", ".join(sorted(REER_AREA)),
            )
        areas.append(REER_AREA[code])
    frame = ctx.reer_provider().get_reer(areas, p.start, p.end or ctx.today())
    frame.columns = [c for c in p.countries]
    return ReerTable(
        frame=frame,
        provenance=Provenance.from_attrs(
            frame.attrs,
            start=str(frame.index.min().date()) if len(frame) else None,
            end=str(frame.index.max().date()) if len(frame) else None,
        ),
    )


# --------------------------------------------------------------------------- #
# ppp adjust-goal
# --------------------------------------------------------------------------- #


class AdjustGoalParams(Params):
    goal: str | None = Field(
        default=None, description="A goal saved with `sobres plan ... --save-goal`."
    )
    target: float | None = Field(default=None, gt=0, description="Or a target amount directly.")
    origin: str = Field(default="USA", description="ISO3 country the goal was priced in.")
    to: str = Field(description="ISO3 destination country.")
    monthly: float | None = Field(default=None, description="Monthly contribution (with --target).")
    current: float = Field(default=0.0, ge=0, description="Current balance (with --target).")
    return_: float | None = Field(
        default=None,
        alias="return",
        description="Annual return for the years-to-goal effect (default 7%).",
    )
    on: date | None = Field(default=None, description="Market-rate date (default: today).")

    @model_validator(mode="after")
    def _one_source(self) -> AdjustGoalParams:
        if (self.goal is None) == (self.target is None):
            raise ValueError("give exactly one of --goal <name> or --target <amount>")
        return self


class AdjustedGoal(PppReport, RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"metric": "text", "unit": "text"}
    origin: str
    destination: str
    basis: str
    vintages: list[str]

    def header_lines(self) -> list[str]:
        return [
            *super().header_lines(),
            f"goal priced in {self.origin}, restated at {self.destination}'s price level: "
            f"{self.basis}",
            pm.BASKET_NOTE,
            pm.NOT_MODELED_NOTE,
            pm.FX_RISK_NOTE,
            *self.vintages,
        ]


def _row(metric: str, value: Any, unit: str) -> dict[str, Any]:
    return {"metric": metric, "value": value, "unit": unit}


@register(
    "ppp.adjust_goal",
    "Restate a goal at another country's price level, beside the market-rate figure.",
    result=AdjustedGoal,
)
def adjust_goal(p: AdjustGoalParams, ctx: Context) -> AdjustedGoal:
    on = p.on or ctx.today()
    if p.goal is not None:
        record = ctx.storage.goals.get(p.goal)
        if record is None:
            raise UsageError(
                f"no saved goal named {p.goal!r}",
                hint="save one with: sobres plan ... --save-goal NAME",
            )
        params = dict(record.params)
        target = float(params["target"])
        monthly = params.get("monthly")
        current = float(params.get("current", 0.0))
        annual = float(params.get("annual_return", p.return_ if p.return_ is not None else 0.07))
        kind = record.kind
    else:
        assert p.target is not None
        annual = 0.07 if p.return_ is None else float(p.return_)
        target, monthly, current, kind = p.target, p.monthly, p.current, "goal"
    figures, vintages = _figures(ctx, [p.origin, p.to])
    origin, dest = figures[p.origin], figures[p.to]
    market, source = _market_rate(ctx, origin.currency, dest.currency, on)
    restated = pm.restate_goal(target, origin, dest, market)
    rows = [
        _row("original_target", target, origin.currency),
        _row("ppp_factor", restated.ppp_factor, f"{dest.currency} per {origin.currency} at PPP"),
        _row("adjusted_target", restated.adjusted, f"{dest.currency} at PPP"),
        _row("at_market_rate", restated.at_market_rate, f"{dest.currency} at {source}"),
        _row("market_rate", market, f"{dest.currency} per {origin.currency}"),
        _row(
            "ppp_vs_market",
            restated.adjusted / restated.at_market_rate - 1.0,
            "adjusted over market-rate figure, minus one",
        ),
    ]
    # Effect on the plan: the same contributions in origin currency, converted at the market
    # rate, against the PPP-adjusted target — years to goal before and after.
    if monthly is not None and float(monthly) > 0:
        rate = g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"])
        before = g.periods_to_target(target, current, float(monthly), rate)
        after = g.periods_to_target(
            restated.adjusted, current * market, float(monthly) * market, rate
        )
        rows += [
            _row("months_to_goal_original", before, "months"),
            _row("months_to_goal_adjusted", after, "months"),
            _row(
                "projected_date_original",
                str((pd.Timestamp(ctx.today()) + pd.DateOffset(months=round(before))).date()),
                "date",
            ),
            _row(
                "projected_date_adjusted",
                str((pd.Timestamp(ctx.today()) + pd.DateOffset(months=round(after))).date()),
                "date",
            ),
        ]
    return AdjustedGoal(
        rows=rows,
        columns=["metric", "value", "unit"],
        origin=p.origin,
        destination=p.to,
        basis=restated.basis + f" (kind: {kind})",
        vintages=vintages,
        provenance=Provenance(provider=ctx.ppp_provider().name, end=on.isoformat()),
    )
