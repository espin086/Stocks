"""Time-series diagnostics and forecasting: stationarity, ARIMA, GARCH.

Honest uncertainty is the point. A forecast here is never a point: it carries
80% and 95% prediction intervals; an ARIMA order chosen automatically comes with
the criterion and the runners-up; a non-stationary input is differenced to
stationarity with the order reported, or refused. Everything is a pure function
over a series; ``statsmodels`` and ``arch`` are imported lazily so the base
install imports this module and only a call fails, with the install hint.

Math and sources:

    ADF   Dickey & Fuller (1979), Said & Dickey (1984): H0 unit root
    KPSS  Kwiatkowski, Phillips, Schmidt & Shin (1992): H0 stationarity
    ARIMA Box & Jenkins (1970); order by AIC/BIC over a small grid
    Ljung-Box  Ljung & Box (1978) on residuals: H0 no autocorrelation
    GARCH(1,1) Bollerslev (1986); EGARCH Nelson (1991); EWMA RiskMetrics (1996, λ=0.94)
    CCC covariance  Bollerslev (1990): Σ = D R D with GARCH variances on the diagonal
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year
from sobres.core.errors import ConfigurationError, InsufficientDataError, UsageError

ECON_HINT = "This command needs the econ extra. Install it with: pip install 'sobres[econ]'"
SIGNIFICANCE = 0.05
MAX_D = 2
DEFAULT_LAGS = 20
MIN_OBS = 30
Criterion = Literal["aic", "bic"]
VolModel = Literal["garch", "egarch", "ewma"]
VOL_MODELS: tuple[str, ...] = ("garch", "egarch", "ewma")
EWMA_LAMBDA = 0.94


def require_econ() -> None:
    """Raise the documented exit-3 error when the econ extra is absent."""
    try:
        import arch  # noqa: F401
        import statsmodels  # noqa: F401
    except ImportError as exc:
        raise ConfigurationError(ECON_HINT) from exc


def _clean(series: pd.Series) -> pd.Series:
    clean = pd.Series(series).dropna().astype("float64")
    if len(clean) < MIN_OBS:
        raise InsufficientDataError(
            f"{len(clean)} observations; at least {MIN_OBS} are needed",
            hint="widen --start/--end",
        )
    if float(clean.std(ddof=0)) == 0.0:
        raise InsufficientDataError(
            "the series is constant over the window; there is nothing to test or forecast",
            hint="widen --start/--end or choose another series",
        )
    return clean


# --------------------------------------------------------------------------- #
# Stationarity and correlation structure
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StationarityTest:
    name: str
    statistic: float
    pvalue: float
    null: str
    conclusion: Literal["stationary", "non-stationary"]
    lags: int


@dataclass(frozen=True)
class Diagnostics:
    n_obs: int
    adf: StationarityTest
    kpss: StationarityTest
    agree: bool
    verdict: str
    acf: list[float]
    pacf: list[float]
    bound: float
    """The ±1.96/√n significance bound for a single autocorrelation."""

    @property
    def stationary(self) -> bool:
        return self.adf.conclusion == "stationary" and self.kpss.conclusion == "stationary"


def _adf(series: pd.Series) -> StationarityTest:
    import warnings

    from statsmodels.tsa.stattools import adfuller

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)  # the 0.16 result-object transition
        stat, p, lags, *_ = adfuller(series.to_numpy(), autolag="AIC")
    return StationarityTest(
        "ADF",
        float(stat),
        float(p),
        "unit root (non-stationary)",
        "stationary" if p < SIGNIFICANCE else "non-stationary",
        int(lags),
    )


def _kpss(series: pd.Series) -> StationarityTest:
    import warnings

    from statsmodels.tools.sm_exceptions import InterpolationWarning
    from statsmodels.tsa.stattools import kpss

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InterpolationWarning)
        warnings.simplefilter("ignore", FutureWarning)  # the 0.16 result-object transition
        stat, p, lags, _ = kpss(series.to_numpy(), regression="c", nlags="auto")
    return StationarityTest(
        "KPSS",
        float(stat),
        float(p),
        "stationary",
        "non-stationary" if p < SIGNIFICANCE else "stationary",
        int(lags),
    )


def stationarity(series: pd.Series) -> tuple[StationarityTest, StationarityTest]:
    require_econ()
    clean = _clean(series)
    return _adf(clean), _kpss(clean)


def diagnose(series: pd.Series, lags: int = DEFAULT_LAGS) -> Diagnostics:
    """ADF and KPSS with their disagreement stated, plus ACF/PACF through ``lags``."""
    require_econ()
    from statsmodels.tsa.stattools import acf, pacf

    clean = _clean(series)
    adf, kp = _adf(clean), _kpss(clean)
    agree = adf.conclusion == kp.conclusion
    if agree:
        verdict = f"both tests conclude {adf.conclusion}"
    elif adf.conclusion == "stationary":
        verdict = (
            "the tests disagree: ADF rejects a unit root but KPSS rejects stationarity — "
            "consistent with a trend-stationary or near-integrated series; do not resolve by fiat"
        )
    else:
        verdict = (
            "the tests disagree: KPSS does not reject stationarity but ADF cannot reject a "
            "unit root — the sample may be too short to tell; do not resolve by fiat"
        )
    max_lag = min(lags, len(clean) // 2 - 1)
    return Diagnostics(
        n_obs=len(clean),
        adf=adf,
        kpss=kp,
        agree=agree,
        verdict=verdict,
        acf=[float(v) for v in acf(clean.to_numpy(), nlags=max_lag, fft=True)[1:]],
        pacf=[float(v) for v in pacf(clean.to_numpy(), nlags=max_lag)[1:]],
        bound=float(1.96 / np.sqrt(len(clean))),
    )


def difference_to_stationary(series: pd.Series, max_d: int = MAX_D) -> tuple[pd.Series, int]:
    """Difference until ADF rejects a unit root, at most ``max_d`` times, else refuse."""
    require_econ()
    current = _clean(series)
    for d in range(max_d + 1):
        if _adf(current).conclusion == "stationary":
            return current, d
        current = current.diff().dropna()
    raise InsufficientDataError(
        f"the series is not stationary after differencing {max_d} times (ADF cannot reject a "
        "unit root)",
        hint="transform the series (log, returns) or specify --order with a larger d deliberately",
    )


# --------------------------------------------------------------------------- #
# ARIMA
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Candidate:
    order: tuple[int, int, int]
    aic: float
    bic: float


@dataclass(frozen=True)
class Forecast:
    model: str
    order: tuple[int, int, int]
    criterion: str
    candidates: list[Candidate]
    """The chosen order first, then the next two best under ``criterion``."""
    horizon: int
    n_obs: int
    d_reported: int
    point: pd.Series = field(repr=False)
    lower80: pd.Series = field(repr=False)
    upper80: pd.Series = field(repr=False)
    lower95: pd.Series = field(repr=False)
    upper95: pd.Series = field(repr=False)
    ljung_box_statistic: float
    ljung_box_pvalue: float
    ljung_box_lags: int
    aic: float
    bic: float

    @property
    def residuals_adequate(self) -> bool:
        return self.ljung_box_pvalue >= SIGNIFICANCE

    @property
    def ljung_box_statement(self) -> str:
        if self.residuals_adequate:
            return (
                f"Ljung-Box on residuals: Q = {self.ljung_box_statistic:.2f}, "
                f"p = {self.ljung_box_pvalue:.3f} over {self.ljung_box_lags} lags; "
                "no evidence of remaining autocorrelation"
            )
        return (
            f"Ljung-Box on residuals: Q = {self.ljung_box_statistic:.2f}, "
            f"p = {self.ljung_box_pvalue:.3f} over {self.ljung_box_lags} lags; residuals are "
            "autocorrelated — the model is inadequate and its intervals are too narrow"
        )

    def frame(self) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "forecast": self.point,
                "lower80": self.lower80,
                "upper80": self.upper80,
                "lower95": self.lower95,
                "upper95": self.upper95,
            }
        )
        out.index.name = "date"
        return out


def _fit_arima(series: pd.Series, order: tuple[int, int, int]) -> Any:
    import warnings

    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    from statsmodels.tsa.arima.model import ARIMA

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        warnings.simplefilter("ignore", UserWarning)
        return ARIMA(series.to_numpy(), order=order).fit()


def select_order(
    series: pd.Series, d: int, *, criterion: Criterion = "aic", max_p: int = 3, max_q: int = 3
) -> list[Candidate]:
    """Every (p, d, q) on the grid, sorted by ``criterion``; the first is the choice."""
    candidates: list[Candidate] = []
    for p in range(max_p + 1):
        for q in range(max_q + 1):
            if p == 0 and q == 0 and d == 0:
                continue
            try:
                fit = _fit_arima(series, (p, d, q))
            except Exception:  # a non-invertible corner of the grid is not an error
                continue
            candidates.append(Candidate((p, d, q), float(fit.aic), float(fit.bic)))
    if not candidates:
        raise InsufficientDataError(
            "no ARIMA order on the grid could be fitted", hint="widen the window"
        )
    key = (lambda c: c.aic) if criterion == "aic" else (lambda c: c.bic)
    return sorted(candidates, key=key)


def _next_index(index: pd.Index, horizon: int) -> pd.Index:
    if isinstance(index, pd.DatetimeIndex) and len(index) > 2:
        freq = pd.infer_freq(index) or pd.tseries.frequencies.to_offset(
            pd.Timedelta(
                days=int(np.median(np.diff(index.values)).astype("timedelta64[D]").astype(int)) or 1
            )
        )
        try:
            return pd.date_range(index[-1], periods=horizon + 1, freq=freq)[1:]
        except Exception:
            pass
    return pd.RangeIndex(1, horizon + 1)


def arima_forecast(
    series: pd.Series,
    horizon: int,
    *,
    order: tuple[int, int, int] | None = None,
    criterion: Criterion = "aic",
    max_p: int = 3,
    max_q: int = 3,
    ljung_box_lags: int = 10,
) -> Forecast:
    """Fit ARIMA — the given order, or the best on a grid — and forecast with intervals.

    With ``order`` unspecified (or its ``d`` None), the series is differenced to
    stationarity and the ``d`` used is reported; if ``d = 2`` is not enough the
    fit refuses. Intervals are the model's own 80% and 95% prediction intervals.
    """
    require_econ()
    from statsmodels.stats.diagnostic import acorr_ljungbox

    if horizon <= 0:
        raise UsageError("--horizon must be at least 1")
    clean = _clean(series)
    if order is None:
        _, d = difference_to_stationary(clean)
        candidates = select_order(clean, d, criterion=criterion, max_p=max_p, max_q=max_q)
        chosen = candidates[0].order
    else:
        chosen = order
        d = order[1]
        fit0 = _fit_arima(clean, chosen)
        candidates = [Candidate(chosen, float(fit0.aic), float(fit0.bic))]
    fit = _fit_arima(clean, chosen)
    result = fit.get_forecast(steps=horizon)
    mean = np.asarray(result.predicted_mean, dtype="float64")
    ci80 = np.asarray(result.conf_int(alpha=0.20), dtype="float64")
    ci95 = np.asarray(result.conf_int(alpha=0.05), dtype="float64")
    index = _next_index(clean.index, horizon)
    lb_lags = min(ljung_box_lags, max(1, len(clean) // 5))
    lb = acorr_ljungbox(np.asarray(fit.resid, dtype="float64"), lags=[lb_lags], return_df=True)
    return Forecast(
        model="arima",
        order=chosen,
        criterion=criterion,
        candidates=candidates[:3],
        horizon=horizon,
        n_obs=len(clean),
        d_reported=d,
        point=pd.Series(mean, index=index, name="forecast"),
        lower80=pd.Series(ci80[:, 0], index=index),
        upper80=pd.Series(ci80[:, 1], index=index),
        lower95=pd.Series(ci95[:, 0], index=index),
        upper95=pd.Series(ci95[:, 1], index=index),
        ljung_box_statistic=float(lb["lb_stat"].iloc[0]),
        ljung_box_pvalue=float(lb["lb_pvalue"].iloc[0]),
        ljung_box_lags=lb_lags,
        aic=float(fit.aic),
        bic=float(fit.bic),
    )


# --------------------------------------------------------------------------- #
# Volatility
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class VolatilityForecast:
    model: str
    horizon: int
    n_obs: int
    frequency: str
    seed: int
    simulations: int
    params: dict[str, float]
    point: pd.Series = field(repr=False)
    """Annualized conditional volatility per step ahead."""
    lower80: pd.Series = field(repr=False)
    upper80: pd.Series = field(repr=False)
    lower95: pd.Series = field(repr=False)
    upper95: pd.Series = field(repr=False)
    last_observed: float
    """Annualized conditional volatility at the last observation."""

    def frame(self) -> pd.DataFrame:
        out = pd.DataFrame(
            {
                "volatility": self.point,
                "lower80": self.lower80,
                "upper80": self.upper80,
                "lower95": self.lower95,
                "upper95": self.upper95,
            }
        )
        out.index.name = "step"
        return out


def _arch_model(returns_pct: np.ndarray, model: str) -> Any:
    from arch.univariate import EGARCH, GARCH, ConstantMean, EWMAVariance, Normal

    am = ConstantMean(returns_pct)
    if model == "garch":
        am.volatility = GARCH(p=1, q=1)
    elif model == "egarch":
        am.volatility = EGARCH(p=1, o=1, q=1)
    elif model == "ewma":
        am.volatility = EWMAVariance(EWMA_LAMBDA)
    else:
        raise UsageError(f"model must be one of {', '.join(VOL_MODELS)}, got {model!r}")
    am.distribution = Normal()
    return am


def volatility_forecast(
    returns: pd.Series,
    horizon: int,
    *,
    model: VolModel | str = "garch",
    frequency: str = "daily",
    seed: int | None = None,
    simulations: int = 1000,
) -> VolatilityForecast:
    """Conditional volatility ``horizon`` steps ahead, annualized, with simulated intervals.

    Returns enter in percent (the ``arch`` convention for numerical stability) and
    leave as annualized decimal volatility: ``sqrt(variance) / 100 * sqrt(periods)``.
    Intervals are the 10/90 and 2.5/97.5 percentiles of the variance across
    simulated paths from the fitted model.
    """
    require_econ()
    if horizon <= 0:
        raise UsageError("--horizon must be at least 1")
    clean = _clean(returns)
    seed_used = int(np.random.SeedSequence().generate_state(1)[0]) if seed is None else int(seed)
    am = _arch_model(clean.to_numpy() * 100.0, model)
    fit = am.fit(disp="off")
    # The shocks come from our own seeded generator: arch's random_state argument does not
    # make its simulation reproducible, a shock callable does.
    generator = np.random.default_rng(seed_used)

    def shocks(size: int | tuple[int, ...]) -> np.ndarray:
        return generator.standard_normal(size)

    forecast = fit.forecast(
        horizon=horizon, method="simulation", simulations=simulations, rng=shocks
    )
    paths = np.asarray(forecast.simulations.variances[-1], dtype="float64")  # paths by horizon
    scale = np.sqrt(periods_per_year(frequency)) / 100.0
    vol_paths = np.sqrt(paths) * scale
    index = pd.RangeIndex(1, horizon + 1, name="step")
    point = pd.Series(
        np.sqrt(np.asarray(forecast.variance.iloc[-1], dtype="float64")) * scale, index=index
    )

    def q(p: float) -> pd.Series:
        return pd.Series(np.percentile(vol_paths, p, axis=0), index=index)

    return VolatilityForecast(
        model=model,
        horizon=horizon,
        n_obs=len(clean),
        frequency=frequency,
        seed=seed_used,
        simulations=simulations,
        params={k: float(v) for k, v in fit.params.items()},
        point=point,
        lower80=q(10),
        upper80=q(90),
        lower95=q(2.5),
        upper95=q(97.5),
        last_observed=float(fit.conditional_volatility[-1]) * scale,
    )


def garch_covariance(returns: pd.DataFrame, frequency: str) -> np.ndarray:
    """One-step-ahead GARCH(1,1) variances on the diagonal, sample correlation off it.

    Bollerslev's constant-conditional-correlation construction, ``Σ = D R D``,
    annualized. The caller (``moments.covariance``) applies the PSD conditioning
    every estimator gets.
    """
    require_econ()
    clean = returns.dropna()
    if len(clean) < MIN_OBS:
        raise InsufficientDataError(
            f"{len(clean)} observations; GARCH needs at least {MIN_OBS}", hint="widen --start/--end"
        )
    variances = []
    for column in clean.columns:
        fit = _arch_model(clean[column].to_numpy(dtype="float64") * 100.0, "garch").fit(disp="off")
        one_step = float(fit.forecast(horizon=1).variance.iloc[-1, 0]) / 100.0**2
        variances.append(one_step)
    d = np.diag(np.sqrt(np.asarray(variances)))
    corr = np.corrcoef(clean.to_numpy(dtype="float64"), rowvar=False)
    corr = np.atleast_2d(corr)
    sigma = d @ corr @ d
    return np.asarray(sigma * periods_per_year(frequency), dtype="float64")
