"""``sobres analyze`` — a single-stock dashboard and factor-model regressions.

Adapters only: prices come from the price provider, factors from the Ken
French provider, the regression from ``core/factors.py``. Monthly is the
default frequency because that is how the factors are published; the asset's
daily prices are resampled to month-end before returns are taken, and the
dependent variable is ``r - RF`` with ``RF`` from the same factor file.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar, Literal

import pandas as pd
from pydantic import Field, model_validator

from sobres.cli.commands.optimize import IN_SAMPLE_NOTE, UniverseParams, load_universe
from sobres.cli.context import Context
from sobres.core import factors as fm
from sobres.core.returns import annualized_return, annualized_volatility, simple_returns
from sobres.core.risk import risk_metrics
from sobres.data.base import FactorModel
from sobres.data.gaps import FillPolicy
from sobres.data.yfinance_provider import FUNDAMENTALS_NOTE
from sobres.registry import Currency, Params, Ticker, TickerList, positional, register
from sobres.results import FrameResult, Provenance, RecordsResult, Result

Frequency = Literal["monthly", "daily"]
STAT_COLUMNS = ("coefficient", "se", "t", "p", "se_hac", "t_hac", "p_hac")


def _returns_at(prices: pd.DataFrame, frequency: Frequency) -> pd.DataFrame:
    if frequency == "monthly":
        return pd.DataFrame(fm.to_monthly_returns(prices))
    return pd.DataFrame(simple_returns(prices)).dropna(how="all")


def _factors(
    ctx: Context, model: str, frequency: Frequency, start: date, end: date
) -> pd.DataFrame:
    source: FactorModel = fm.MODEL_SOURCE[model]  # type: ignore[assignment]
    return ctx.factor_provider().get_factors(source, frequency, start, end)


# --------------------------------------------------------------------------- #
# analyze factors
# --------------------------------------------------------------------------- #


class FactorParams(Params):
    ticker: Ticker | None = positional(
        default=None, description="One ticker (or use --tickers for a comparison table)."
    )
    tickers: TickerList | None = Field(
        default=None, description="Several tickers for a comparison table (or use --portfolio)."
    )
    portfolio: str | None = Field(
        default=None, description="A saved portfolio's name in place of --tickers."
    )
    save_run: bool = Field(default=False, description="Record this run in the run history.")
    start: date = Field(description="First date, YYYY-MM-DD.")
    end: date | None = Field(default=None, description="Last date (default: today).")
    fill: FillPolicy = Field(description="Provider-gap policy: drop, ffill or raise. No default.")
    base: Currency | None = Field(
        default=None, description="Base currency for a multi-currency universe (e.g. USD)."
    )
    model: fm.Model = Field(default="ff3", description="Factor model.")
    frequency: Frequency = Field(
        default="monthly", description="Return frequency; monthly matches the published factors."
    )
    rolling: int | None = Field(
        default=None,
        ge=6,
        description="Window (in periods) for rolling loadings instead of one fit.",
    )
    hac_lags: int | None = Field(
        default=None,
        ge=0,
        description="Newey-West lag length; default: the Newey-West (1994) rule.",
    )

    @model_validator(mode="after")
    def _one_universe(self) -> FactorParams:
        given = [bool(self.ticker), bool(self.tickers), bool(self.portfolio)]
        if sum(given) != 1:
            raise ValueError("give exactly one of: a ticker, --tickers, or --portfolio")
        if self.end is not None and self.end < self.start:
            raise ValueError(f"end {self.end} precedes start {self.start}")
        if self.rolling is not None and (self.tickers or self.portfolio):
            raise ValueError("--rolling applies to a single ticker")
        return self

    @property
    def universe(self) -> list[str]:
        return [self.ticker] if self.ticker else list(self.tickers or [])


class FactorReport(Result):
    """Every factor result is a report: the disclaimer footer applies to all three shapes."""

    report: ClassVar[bool] = True


class FactorResult(FactorReport, RecordsResult):
    """One ticker: a row per term (alpha first), the model statistics in the header."""

    column_kinds: ClassVar[dict[str, str]] = {"term": "text"}
    ticker: str
    model: str
    frequency: str
    n_obs: int
    r2: float
    adj_r2: float
    hac_lags: int
    annualized_alpha: float
    alpha_p_hac: float
    alpha_statement: str

    def header_lines(self) -> list[str]:
        return [
            f"{self.ticker}: {self.model} on {self.frequency} excess returns (r - RF from the "
            f"factor file), {self.n_obs} observations",
            f"R² {self.r2:.4f}, adjusted R² {self.adj_r2:.4f}; HAC (Newey-West) standard errors "
            f"with {self.hac_lags} lag(s) reported beside OLS",
            self.alpha_statement,
            *super().header_lines(),
        ]


class FactorComparison(FactorReport, RecordsResult):
    """Several tickers: one row each with loadings, alpha, its HAC t-statistic and R²."""

    column_kinds: ClassVar[dict[str, str]] = {"ticker": "text"}
    model: str
    frequency: str
    hac_lags: dict[str, int]

    def header_lines(self) -> list[str]:
        return [
            f"{self.model} on {self.frequency} excess returns; rows in the order supplied; "
            "alpha_t is the HAC t-statistic",
            "alpha not marked * is not statistically distinguishable from zero at the 5% level",
            *super().header_lines(),
        ]


class RollingLoadings(FactorReport, FrameResult):
    ticker: str
    model: str
    window: int

    def header_lines(self) -> list[str]:
        return [
            f"{self.ticker}: {self.model} loadings over each trailing {self.window}-period window",
            *super().header_lines(),
        ]


def _term_rows(fit: fm.FactorRegression) -> list[dict[str, Any]]:
    rows = [{"term": "alpha", **fit.alpha.as_dict(), "annualized": fit.annualized_alpha}]
    for name, stats in fit.loadings.items():
        rows.append({"term": name, **stats.as_dict(), "annualized": None})
    return rows


@register(
    "analyze.factors",
    "Regress excess returns on CAPM or Fama-French factors; alpha with its t-statistic.",
    result=FactorReport,
)
def factors(p: FactorParams, ctx: Context) -> FactorReport:
    universe = load_universe(
        UniverseParams(
            tickers=p.universe or None,
            portfolio=p.portfolio,
            start=p.start,
            end=p.end,
            fill=p.fill,
            base=p.base,
        ),
        ctx,
    )
    if p.portfolio:
        p = p.model_copy(update={"tickers": list(universe.prices.columns)})
    end = p.end or ctx.today()
    factor_frame = _factors(ctx, p.model, p.frequency, p.start, end)
    returns = _returns_at(universe.prices, p.frequency)
    provenance = Provenance.from_attrs(
        universe.prices.attrs,
        start=str(returns.index.min().date()),
        end=str(returns.index.max().date()),
        notes=[
            f"factors: Ken French {fm.MODEL_SOURCE[p.model]} ({p.frequency}); "
            "RF from the same file",
            IN_SAMPLE_NOTE,
        ],
    )
    provenance.currency = universe.currency
    if p.rolling is not None:
        ticker = p.universe[0]
        frame = fm.rolling_loadings(
            returns[ticker], factor_frame, p.model, window=p.rolling, frequency=p.frequency
        )
        return RollingLoadings(
            frame=frame, ticker=ticker, model=p.model, window=p.rolling, provenance=provenance
        )
    fits = {
        ticker: fm.factor_regression(
            returns[ticker], factor_frame, p.model, frequency=p.frequency, hac_lags=p.hac_lags
        )
        for ticker in p.universe
    }
    if len(fits) == 1:
        ticker, fit = next(iter(fits.items()))
        provenance.start, provenance.end = str(fit.start.date()), str(fit.end.date())
        return FactorResult(
            rows=_term_rows(fit),
            columns=["term", *STAT_COLUMNS, "annualized"],
            ticker=ticker,
            model=p.model,
            frequency=p.frequency,
            n_obs=fit.n_obs,
            r2=fit.r2,
            adj_r2=fit.adj_r2,
            hac_lags=fit.hac_lags,
            annualized_alpha=fit.annualized_alpha,
            alpha_p_hac=fit.alpha.p_hac,
            alpha_statement=fit.alpha_statement,
            provenance=provenance,
        )
    loadings = list(fm.factor_columns(p.model))
    rows = []
    for ticker in p.universe:  # the order supplied, so output diffs across runs
        fit = fits[ticker]
        rows.append(
            {
                "ticker": ticker,
                **{name: fit.loadings[name].coefficient for name in loadings},
                "alpha_annualized": fit.annualized_alpha,
                "alpha_t": fit.alpha.t_hac,
                "alpha_p": fit.alpha.p_hac,
                "significant": "*" if fit.alpha_significant else "",
                "r2": fit.r2,
                "n_obs": fit.n_obs,
            }
        )
    return FactorComparison(
        rows=rows,
        columns=[
            "ticker",
            *loadings,
            "alpha_annualized",
            "alpha_t",
            "alpha_p",
            "significant",
            "r2",
            "n_obs",
        ],
        model=p.model,
        frequency=p.frequency,
        hac_lags={t: f.hac_lags for t, f in fits.items()},
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# analyze stock
# --------------------------------------------------------------------------- #


class StockParams(Params):
    ticker: Ticker = positional(description="Ticker symbol, e.g. NVDA.")
    start: date = Field(default=date(2015, 1, 1), description="First date, YYYY-MM-DD.")
    end: date | None = Field(default=None, description="Last date (default: today).")
    fill: FillPolicy = Field(description="Provider-gap policy: drop, ffill or raise. No default.")
    risk_free: float | None = Field(
        default=None, description="Annual decimal risk-free rate for the risk panel."
    )


class StockReport(RecordsResult):
    """Sections of metric/value rows: price, returns, risk, CAPM, fundamentals."""

    report: ClassVar[bool] = True
    column_kinds: ClassVar[dict[str, str]] = {"section": "text", "metric": "text"}
    ticker: str
    name: str | None
    fundamentals_note: str

    def header_lines(self) -> list[str]:
        title = f"{self.ticker}" + (f" — {self.name}" if self.name else "")
        return [title, self.fundamentals_note, *super().header_lines()]


def _rows(section: str, items: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"section": section, "metric": k, "value": v} for k, v in items.items()]


@register(
    "analyze.stock",
    "Price summary, risk panel, CAPM beta and fundamentals for one stock.",
    result=StockReport,
)
def stock(p: StockParams, ctx: Context) -> StockReport:
    universe = load_universe(
        UniverseParams(
            tickers=[p.ticker], start=p.start, end=p.end, fill=p.fill, risk_free=p.risk_free
        ),
        ctx,
    )
    prices = universe.prices[p.ticker]
    daily = universe.returns[p.ticker]
    panel = risk_metrics(daily, universe.risk_free, universe.frequency)
    rows = _rows(
        "price",
        {
            "first": float(prices.iloc[0]),
            "last": float(prices.iloc[-1]),
            "high": float(prices.max()),
            "low": float(prices.min()),
            "period_return": float(prices.iloc[-1] / prices.iloc[0] - 1.0),
            "currency": universe.currency,
        },
    )
    rows += _rows(
        "returns",
        {
            "annualized_return": annualized_return(daily, universe.frequency),
            "annualized_volatility": annualized_volatility(daily, universe.frequency),
            "n_obs": len(daily),
        },
    )
    rows += _rows("risk", {k: v for k, v in panel.as_dict().items() if k not in ("frequency",)})
    notes = [f"risk-free rate {universe.risk_free:.4%} ({universe.risk_free_source})"]
    end = p.end or ctx.today()
    try:
        factor_frame = _factors(ctx, "capm", "monthly", p.start, end)
        monthly = fm.to_monthly_returns(prices)
        fit = fm.factor_regression(pd.Series(monthly), factor_frame, "capm", frequency="monthly")
        rows += _rows(
            "capm",
            {
                "beta_mkt": fit.loadings["Mkt-RF"].coefficient,
                "beta_t_hac": fit.loadings["Mkt-RF"].t_hac,
                "alpha_annualized": fit.annualized_alpha,
                "alpha_p_hac": fit.alpha.p_hac,
                "r2": fit.r2,
                "n_months": fit.n_obs,
            },
        )
        notes.append(f"capm: {fit.alpha_statement}")
    except Exception as exc:  # the price and risk sections still render
        ctx.log.warning("capm.skipped", symbol=p.ticker, reason=f"{type(exc).__name__}: {exc}")
        notes.append(f"capm: not estimated ({exc})")
    fundamentals = ctx.price_provider().get_fundamentals(p.ticker)  # type: ignore[attr-defined]
    name: str | None = None
    if fundamentals is None:
        note = f"fundamentals: none reported for {p.ticker} (common for ETFs); section omitted"
    else:
        name = fundamentals.name
        rows += _rows(
            "fundamentals",
            {
                "market_cap": fundamentals.market_cap,
                "pe_ratio": fundamentals.pe_ratio,
                "price_to_book": fundamentals.price_to_book,
                "dividend_yield": fundamentals.dividend_yield,
                "sector": fundamentals.sector,
            },
        )
        note = FUNDAMENTALS_NOTE
    provenance = universe.provenance
    provenance.notes = [*notes, *provenance.notes]
    return StockReport(
        rows=rows,
        columns=["section", "metric", "value"],
        ticker=p.ticker,
        name=name,
        fundamentals_note=note,
        provenance=provenance,
    )
