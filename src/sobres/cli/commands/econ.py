"""``sobres econ`` — stationarity diagnostics, ARIMA and GARCH forecasts, robust regression.

Adapters only. A symbol is a FRED series when it carries a ``fred:`` prefix or
looks like one (a digit or more than five characters: ``DGS10``, ``CPIAUCSL``),
and a price ticker otherwise (``SPY``, ``AAPL``); ``ticker:`` overrides. Prices
become simple returns for volatility and regression and stay levels for
forecasting and diagnosis; macro levels are differenced for regression, and the
output says which transform was applied. ``statsmodels``/``arch`` are the econ
extra: without it every command exits 3 with the install hint, never a traceback.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar, Literal

import pandas as pd
from pydantic import Field, field_validator

from sobres.cli.context import Context
from sobres.core import regression as rg
from sobres.core import timeseries as ts
from sobres.core.conventions import infer_frequency
from sobres.core.errors import UsageError
from sobres.core.returns import simple_returns
from sobres.registry import Params, positional, register
from sobres.results import FrameResult, Provenance, RecordsResult, Result

Source = Literal["auto", "fred", "ticker"]


class EconReport(Result):
    report: ClassVar[bool] = True


# --------------------------------------------------------------------------- #
# Symbol resolution
# --------------------------------------------------------------------------- #


def classify(symbol: str, source: Source = "auto") -> tuple[str, str]:
    """``("fred", "DGS10")`` or ``("ticker", "SPY")`` from a symbol and an optional override."""
    text = symbol.strip()
    lower = text.lower()
    if lower.startswith("fred:"):
        return "fred", text[5:].upper()
    if lower.startswith("ticker:"):
        return "ticker", text[7:].upper()
    if source != "auto":
        return source, text.upper()
    looks_like_fred = any(ch.isdigit() for ch in text) or (len(text) > 5 and "." not in text)
    return ("fred" if looks_like_fred else "ticker"), text.upper()


def load_series(
    symbol: str, ctx: Context, start: date, end: date, *, source: Source = "auto"
) -> tuple[pd.Series, str, Provenance]:
    """One level series (prices or a macro series) with its kind and provenance."""
    kind, name = classify(symbol, source)
    if kind == "fred":
        frame = ctx.macro_provider().get_series([name], start, end)
    else:
        frame = ctx.price_provider().get_prices([name], start, end)
    series = pd.Series(frame[name]).dropna()
    series.name = name
    provenance = Provenance.from_attrs(
        frame.attrs,
        start=str(series.index.min().date()) if len(series) else None,
        end=str(series.index.max().date()) if len(series) else None,
    )
    return series, kind, provenance


# --------------------------------------------------------------------------- #
# Shared parameters
# --------------------------------------------------------------------------- #


class WindowParams(Params):
    start: date = Field(default=date(2010, 1, 1), description="First date, YYYY-MM-DD.")
    end: date | None = Field(default=None, description="Last date (default: today).")
    source: Source = Field(
        default="auto",
        description="How to read bare symbols: auto (digits or >5 chars = FRED), fred, ticker.",
    )


# --------------------------------------------------------------------------- #
# econ diagnose
# --------------------------------------------------------------------------- #


class DiagnoseParams(WindowParams):
    series: str = positional(description="A FRED series (DGS10) or a ticker (SPY, or ticker:X).")
    lags: int = Field(default=ts.DEFAULT_LAGS, ge=1, le=100, description="ACF/PACF lags.")


class DiagnosisResult(EconReport, RecordsResult):
    """One row per lag (ACF, PACF, the bound); the tests in the header."""

    column_kinds: ClassVar[dict[str, str]] = {"lag": "int"}
    series: str
    n_obs: int
    adf: dict[str, Any]
    kpss: dict[str, Any]
    agree: bool
    verdict: str
    bound: float

    def header_lines(self) -> list[str]:
        a, k = self.adf, self.kpss
        return [
            f"{self.series}: {self.n_obs} observations",
            f"ADF (H0 unit root): statistic {a['statistic']:.3f}, p = {a['pvalue']:.3f}, "
            f"{a['lags']} lags -> {a['conclusion']}",
            f"KPSS (H0 stationary): statistic {k['statistic']:.3f}, p = {k['pvalue']:.3f}, "
            f"{k['lags']} lags -> {k['conclusion']}",
            self.verdict,
            f"ACF/PACF significance bound ±{self.bound:.4f} (1.96/√n)",
            *super().header_lines(),
        ]


@register(
    "econ.diagnose",
    "Stationarity tests (ADF, KPSS) and ACF/PACF through lag 20 for one series.",
    result=DiagnosisResult,
)
def diagnose(p: DiagnoseParams, ctx: Context) -> DiagnosisResult:
    series, _kind, provenance = load_series(
        p.series, ctx, p.start, p.end or ctx.today(), source=p.source
    )
    d = ts.diagnose(series, lags=p.lags)
    rows = [
        {
            "lag": i + 1,
            "acf": a,
            "pacf": pc,
            "acf_significant": abs(a) > d.bound,
            "pacf_significant": abs(pc) > d.bound,
        }
        for i, (a, pc) in enumerate(zip(d.acf, d.pacf, strict=True))
    ]
    return DiagnosisResult(
        rows=rows,
        columns=["lag", "acf", "pacf", "acf_significant", "pacf_significant"],
        series=str(series.name),
        n_obs=d.n_obs,
        adf=d.adf.__dict__,
        kpss=d.kpss.__dict__,
        agree=d.agree,
        verdict=d.verdict,
        bound=d.bound,
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# econ forecast
# --------------------------------------------------------------------------- #


class ForecastParams(WindowParams):
    series: str = positional(description="A FRED series (CPIAUCSL) or a ticker (levels).")
    horizon: int = Field(default=12, ge=1, le=120, description="Steps ahead.")
    model: Literal["arima"] = Field(default="arima", description="Forecasting model.")
    order: str | None = Field(
        default=None, description="Fixed p,d,q (e.g. 1,1,0); default: --auto over a grid."
    )
    auto: bool = Field(default=True, description="Select the order by information criterion.")
    criterion: ts.Criterion = Field(default="aic", description="Criterion for --auto.")
    max_p: int = Field(default=3, ge=0, le=5, description="Largest AR order on the grid.")
    max_q: int = Field(default=3, ge=0, le=5, description="Largest MA order on the grid.")

    @field_validator("order")
    @classmethod
    def _order_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split(",")
        if len(parts) != 3 or not all(part.strip().isdigit() for part in parts):
            raise ValueError("--order must be three integers: p,d,q")
        return value

    @property
    def order_tuple(self) -> tuple[int, int, int] | None:
        if self.order is None:
            return None
        p, d, q = (int(x) for x in self.order.split(","))
        return p, d, q


class ForecastResult(EconReport, FrameResult):
    """Point forecast with 80% and 95% intervals in every row; never a point alone."""

    series: str
    model: str
    order: list[int]
    criterion: str
    candidates: list[dict[str, Any]]
    d_reported: int
    n_obs: int
    aic: float
    bic: float
    ljung_box: dict[str, float]
    residuals_adequate: bool
    ljung_box_statement: str

    def header_lines(self) -> list[str]:
        p, d, q = self.order
        lines = [
            f"{self.series}: ARIMA({p},{d},{q}) on {self.n_obs} observations; differenced d={d} "
            f"to stationarity"
            if self.d_reported == d
            else f"{self.series}: ARIMA({p},{d},{q})",
            f"selected by {self.criterion}: "
            + "; ".join(
                f"({c['order'][0]},{c['order'][1]},{c['order'][2]}) "
                f"{self.criterion}={c[self.criterion]:.2f}"
                for c in self.candidates
            ),
            self.ljung_box_statement,
            "intervals: 80% and 95% prediction intervals from the fitted model; "
            "the point forecast is not a prediction on its own",
        ]
        return [*lines, *super().header_lines()]


@register(
    "econ.forecast",
    "ARIMA forecast with 80% and 95% prediction intervals; order selection made visible.",
    result=ForecastResult,
)
def forecast(p: ForecastParams, ctx: Context) -> ForecastResult:
    series, _kind, provenance = load_series(
        p.series, ctx, p.start, p.end or ctx.today(), source=p.source
    )
    fit = ts.arima_forecast(
        series,
        p.horizon,
        order=p.order_tuple,
        criterion=p.criterion,
        max_p=p.max_p,
        max_q=p.max_q,
    )
    if fit.d_reported:
        ctx.log.warning("arima.differenced", series=str(series.name), d=fit.d_reported)
    return ForecastResult(
        frame=fit.frame(),
        series=str(series.name),
        model=fit.model,
        order=list(fit.order),
        criterion=fit.criterion,
        candidates=[{"order": list(c.order), "aic": c.aic, "bic": c.bic} for c in fit.candidates],
        d_reported=fit.d_reported,
        n_obs=fit.n_obs,
        aic=fit.aic,
        bic=fit.bic,
        ljung_box={
            "statistic": fit.ljung_box_statistic,
            "pvalue": fit.ljung_box_pvalue,
            "lags": fit.ljung_box_lags,
        },
        residuals_adequate=fit.residuals_adequate,
        ljung_box_statement=fit.ljung_box_statement,
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# econ volatility
# --------------------------------------------------------------------------- #


class VolatilityParams(WindowParams):
    ticker: str = positional(description="A ticker whose returns are modelled.")
    horizon: int = Field(default=30, ge=1, le=250, description="Steps ahead.")
    model: ts.VolModel = Field(default="garch", description="garch, egarch or ewma.")
    simulations: int = Field(default=1000, ge=100, description="Paths for the intervals.")
    seed: int | None = Field(default=None, description="Seed; printed even when auto-generated.")


class VolatilityResult(EconReport, FrameResult):
    index_label: ClassVar[str | None] = "step"
    ticker: str
    model: str
    frequency: str
    n_obs: int
    seed: int
    simulations: int
    params: dict[str, float]
    last_observed: float

    def header_lines(self) -> list[str]:
        params = ", ".join(f"{k}={v:.4g}" for k, v in self.params.items())
        return [
            f"{self.ticker}: {self.model.upper()} on {self.n_obs} {self.frequency} returns; "
            "volatility is annualized (sqrt of periods per year from the conventions table)",
            f"parameters: {params}",
            f"last observed conditional volatility {self.last_observed:.4%} annualized",
            f"intervals: 80% and 95% bands from {self.simulations} simulated paths, "
            f"seed {self.seed}",
            *super().header_lines(),
        ]


@register(
    "econ.volatility",
    "GARCH, EGARCH or EWMA conditional volatility forecast, annualized, with intervals.",
    result=VolatilityResult,
)
def volatility(p: VolatilityParams, ctx: Context) -> VolatilityResult:
    series, _kind, provenance = load_series(
        p.ticker, ctx, p.start, p.end or ctx.today(), source="ticker"
    )
    returns = pd.Series(simple_returns(series)).dropna()
    frequency = infer_frequency(pd.DatetimeIndex(returns.index))
    fit = ts.volatility_forecast(
        returns,
        p.horizon,
        model=p.model,
        frequency=frequency,
        seed=p.seed,
        simulations=p.simulations,
    )
    return VolatilityResult(
        frame=fit.frame(),
        ticker=str(series.name),
        model=fit.model,
        frequency=fit.frequency,
        n_obs=fit.n_obs,
        seed=fit.seed,
        simulations=fit.simulations,
        params=fit.params,
        last_observed=fit.last_observed,
        provenance=provenance,
    )


# --------------------------------------------------------------------------- #
# econ regress
# --------------------------------------------------------------------------- #


class RegressParams(WindowParams):
    y: str = Field(description="Dependent series: a ticker (returns) or fred:SERIES (differences).")
    x: list[str] = Field(min_length=1, description="Regressors, same conventions.")
    robust: rg.Robust = Field(default="hac", description="Covariance: hac, hc0-hc3 or none.")
    hac_lags: int | None = Field(
        default=None, ge=0, description="Newey-West lags for --robust hac."
    )


class RegressionResult(EconReport, RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"term": "text", "transform": "text"}
    y: str
    robust: str
    hac_lags: int | None
    n_obs: int
    r2: float
    adj_r2: float
    f_statistic: float
    f_pvalue: float
    durbin_watson: float
    breusch_pagan: dict[str, float]
    vif: dict[str, float]
    vif_flags: list[str]
    transforms: dict[str, str]

    def header_lines(self) -> list[str]:
        cov = (
            f"HAC (Newey-West, {self.hac_lags} lags)"
            if self.robust == "hac"
            else self.robust.upper()
        )
        if self.robust == "none":
            cov = "classical OLS (no robust correction)"
        lines = [
            f"{self.y} on {', '.join(k for k in self.transforms if k != self.y)}: "
            f"{self.n_obs} observations; standard errors: {cov}",
            "transforms: " + ", ".join(f"{k} = {v}" for k, v in self.transforms.items()),
            f"R² {self.r2:.4f}, adjusted R² {self.adj_r2:.4f}; F = {self.f_statistic:.2f} "
            f"(p = {self.f_pvalue:.3g}); Durbin-Watson {self.durbin_watson:.3f}",
            f"Breusch-Pagan {self.breusch_pagan['statistic']:.2f} "
            f"(p = {self.breusch_pagan['pvalue']:.3f}): "
            + (
                "heteroskedastic residuals; prefer a robust covariance"
                if self.breusch_pagan["pvalue"] < 0.05
                else "no evidence of heteroskedasticity"
            ),
        ]
        if len(self.vif) > 1:
            vif = ", ".join(f"{k} {v:.2f}" for k, v in self.vif.items())
            lines.append(
                f"VIF: {vif}"
                + (
                    f"; above 10 (multicollinear): {', '.join(self.vif_flags)}"
                    if self.vif_flags
                    else ""
                )
            )
        return [*lines, *super().header_lines()]


def _regressor(
    symbol: str, ctx: Context, start: date, end: date, source: Source
) -> tuple[pd.Series, str]:
    series, kind, _ = load_series(symbol, ctx, start, end, source=source)
    if kind == "ticker":
        out = pd.Series(simple_returns(series)).dropna()
        return out, "simple returns"
    out = series.diff().dropna()
    return out, "first differences"


@register(
    "econ.regress",
    "OLS with robust standard errors, VIF and residual diagnostics.",
    result=RegressionResult,
)
def regress(p: RegressParams, ctx: Context) -> RegressionResult:
    end = p.end or ctx.today()
    y, y_transform = _regressor(p.y, ctx, p.start, end, p.source)
    columns: dict[str, pd.Series] = {}
    transforms = {str(y.name): y_transform}
    for symbol in p.x:
        series, transform = _regressor(symbol, ctx, p.start, end, p.source)
        name = str(series.name)
        if name in columns or name == y.name:
            raise UsageError(f"{name} appears twice")
        columns[name] = series
        transforms[name] = transform
    x = pd.DataFrame(columns)
    fit = rg.regress(y, x, robust=p.robust, hac_lags=p.hac_lags)
    rows = [{"term": name, **term.as_dict()} for name, term in fit.terms.items()]
    return RegressionResult(
        rows=rows,
        columns=["term", "coefficient", "se", "t", "p"],
        y=str(y.name),
        robust=fit.robust,
        hac_lags=fit.hac_lags,
        n_obs=fit.n_obs,
        r2=fit.r2,
        adj_r2=fit.adj_r2,
        f_statistic=fit.f_statistic,
        f_pvalue=fit.f_pvalue,
        durbin_watson=fit.durbin_watson,
        breusch_pagan={
            "statistic": fit.breusch_pagan_statistic,
            "pvalue": fit.breusch_pagan_pvalue,
        },
        vif=fit.vif,
        vif_flags=fit.vif_flags,
        transforms=transforms,
        provenance=Provenance(notes=["returns and differences are aligned on their common dates"]),
    )
