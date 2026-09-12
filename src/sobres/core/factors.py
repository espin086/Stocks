"""Factor-model regressions: CAPM, Fama-French three and five factors, plus momentum.

The question these answer: is an asset's excess return explained by known risk
factors, or is there alpha — and is that alpha distinguishable from zero? So
every coefficient comes with its standard error, t-statistic and p-value, and
alpha comes twice: under classical OLS standard errors and under Newey-West
(HAC) standard errors that survive autocorrelated, heteroskedastic residuals.

Math (Fama & French 1993, 2015; Carhart 1997 for momentum; Newey & West 1987):

    r_i,t - RF_t = alpha + sum_k beta_k F_k,t + e_t              (OLS by least squares)
    Var_OLS(b)   = s^2 (X'X)^-1,  s^2 = e'e / (n - k)
    Var_HAC(b)   = (X'X)^-1 [ S_0 + sum_{l=1}^{L} w_l (S_l + S_l') ] (X'X)^-1,
                   S_l = sum_t x_t e_t e_{t-l} x_{t-l}',  w_l = 1 - l/(L+1)   (Bartlett kernel)
    L            = floor(4 (n/100)^(2/9))                          (Newey & West 1994 rule)
    t = b / se,  p = 2 (1 - T_{n-k}(|t|)),  annualized alpha = (1 + alpha)^periods - 1

Pure functions over frames; no I/O, no logging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

from sobres.core.conventions import PERIODS_PER_YEAR, periods_per_year
from sobres.core.errors import InsufficientDataError, UsageError

Model = Literal["capm", "ff3", "ff5", "ff5+mom"]
MODELS: tuple[str, ...] = ("capm", "ff3", "ff5", "ff5+mom")
MODEL_FACTORS: dict[str, tuple[str, ...]] = {
    "capm": ("Mkt-RF",),
    "ff3": ("Mkt-RF", "SMB", "HML"),
    "ff5": ("Mkt-RF", "SMB", "HML", "RMW", "CMA"),
    "ff5+mom": ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM"),
}
# The factor file each model's columns come from (the data layer fetches by this).
MODEL_SOURCE: dict[str, str] = {"capm": "ff3", "ff3": "ff3", "ff5": "ff5", "ff5+mom": "ff5+mom"}
RISK_FREE_COLUMN = "RF"
SIGNIFICANCE = 0.05
# Three years of monthly observations, or one year of daily ones.
MIN_OBS: dict[str, int] = {
    "monthly": 3 * PERIODS_PER_YEAR["monthly"],
    "daily": PERIODS_PER_YEAR["daily"],
}
ALPHA_NOT_DISTINGUISHABLE = "alpha is not statistically distinguishable from zero at the 5% level"


@dataclass(frozen=True)
class CoefficientStats:
    """One regression term under classical and HAC standard errors."""

    coefficient: float
    se: float
    t: float
    p: float
    se_hac: float
    t_hac: float
    p_hac: float

    def as_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class FactorRegression:
    model: str
    frequency: str
    n_obs: int
    start: pd.Timestamp
    end: pd.Timestamp
    alpha: CoefficientStats
    annualized_alpha: float
    loadings: dict[str, CoefficientStats]
    r2: float
    adj_r2: float
    hac_lags: int
    residuals: pd.Series = field(repr=False, compare=False)

    @property
    def alpha_significant(self) -> bool:
        """Under the HAC standard error — the conservative one."""
        return self.alpha.p_hac <= SIGNIFICANCE

    @property
    def alpha_statement(self) -> str:
        if self.alpha_significant:
            return (
                f"alpha {self.annualized_alpha:.4%} annualized is distinguishable from zero at "
                f"the 5% level (HAC t = {self.alpha.t_hac:.2f}, p = {self.alpha.p_hac:.3f})"
            )
        return (
            f"{ALPHA_NOT_DISTINGUISHABLE} (HAC t = {self.alpha.t_hac:.2f}, "
            f"p = {self.alpha.p_hac:.3f}); the point estimate {self.annualized_alpha:.4%} "
            "annualized should not be read on its own"
        )


def newey_west_lags(n_obs: int) -> int:
    """Newey & West (1994) automatic bandwidth: floor(4 (n/100)^(2/9))."""
    return int(np.floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0)))


def factor_columns(model: str) -> tuple[str, ...]:
    if model not in MODEL_FACTORS:
        raise UsageError(f"model must be one of {', '.join(MODELS)}, got {model!r}")
    return MODEL_FACTORS[model]


def excess_returns(returns: pd.Series, factors: pd.DataFrame) -> pd.Series:
    """``r - RF`` on the inner join of the two indexes; RF comes from the factor file."""
    if RISK_FREE_COLUMN not in factors.columns:
        raise UsageError(f"the factor frame has no {RISK_FREE_COLUMN} column")
    both = pd.concat([returns.rename("__r__"), factors[RISK_FREE_COLUMN]], axis=1, join="inner")
    both = both.dropna()
    out = both["__r__"] - both[RISK_FREE_COLUMN]
    out.name = returns.name
    return out


def _design(excess: pd.Series, factors: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.concat([excess.rename("__y__"), factors[list(columns)]], axis=1, join="inner")
    return frame.dropna()


def _ols_with_hac(
    y: np.ndarray, x: np.ndarray, lags: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Coefficients, OLS se, HAC se, residuals, R², adjusted R²."""
    n, k = x.shape
    xtx_inv = np.linalg.inv(x.T @ x)
    beta = xtx_inv @ x.T @ y
    resid = y - x @ beta
    dof = n - k
    s2 = float(resid @ resid) / dof
    se_ols = np.sqrt(np.diag(s2 * xtx_inv))
    scores = x * resid[:, None]  # x_t e_t, one row per observation
    s = scores.T @ scores
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        gamma = scores[lag:].T @ scores[:-lag]
        s += w * (gamma + gamma.T)
    cov_hac = xtx_inv @ s @ xtx_inv
    se_hac = np.sqrt(np.diag(cov_hac))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else float("nan")
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof if tss > 0 else float("nan")
    return beta, se_ols, se_hac, resid, r2, adj_r2


def _stats(coef: float, se: float, se_hac: float, dof: int) -> CoefficientStats:
    t = coef / se if se > 0 else float("inf")
    t_hac = coef / se_hac if se_hac > 0 else float("inf")
    p = float(2.0 * stats.t.sf(abs(t), dof)) if np.isfinite(t) else 0.0
    p_hac = float(2.0 * stats.t.sf(abs(t_hac), dof)) if np.isfinite(t_hac) else 0.0
    return CoefficientStats(float(coef), float(se), float(t), p, float(se_hac), float(t_hac), p_hac)


def factor_regression(
    returns: pd.Series,
    factors: pd.DataFrame,
    model: Model | str = "ff3",
    *,
    frequency: str = "monthly",
    hac_lags: int | None = None,
    min_obs: int | None = None,
) -> FactorRegression:
    """Regress ``returns - RF`` on the model's factors with OLS and HAC inference.

    ``returns`` are simple periodic returns at ``frequency``; ``factors`` is the
    Ken French frame at the same frequency (decimal returns, ``RF`` included).
    Raises ``InsufficientDataError`` below ``MIN_OBS[frequency]`` observations.
    """
    columns = factor_columns(model)
    missing = [c for c in columns if c not in factors.columns]
    if missing:
        raise UsageError(f"factor frame lacks {', '.join(missing)} needed by {model}")
    excess = excess_returns(returns, factors)
    frame = _design(excess, factors, columns)
    required = MIN_OBS.get(frequency, MIN_OBS["monthly"]) if min_obs is None else min_obs
    if len(frame) < required:
        raise InsufficientDataError(
            f"{len(frame)} {frequency} observations available, {required} required for a "
            f"{model} regression",
            hint="widen --start/--end, or use --frequency daily for a short history",
        )
    y = frame["__y__"].to_numpy(dtype="float64")
    x = np.column_stack([np.ones(len(frame)), frame[list(columns)].to_numpy(dtype="float64")])
    lags = newey_west_lags(len(frame)) if hac_lags is None else int(hac_lags)
    beta, se, se_hac, resid, r2, adj_r2 = _ols_with_hac(y, x, lags)
    dof = len(frame) - x.shape[1]
    alpha = _stats(beta[0], se[0], se_hac[0], dof)
    loadings = {
        name: _stats(beta[i + 1], se[i + 1], se_hac[i + 1], dof) for i, name in enumerate(columns)
    }
    periods = periods_per_year(frequency)
    return FactorRegression(
        model=model,
        frequency=frequency,
        n_obs=len(frame),
        start=pd.Timestamp(frame.index.min()),
        end=pd.Timestamp(frame.index.max()),
        alpha=alpha,
        annualized_alpha=float((1.0 + alpha.coefficient) ** periods - 1.0),
        loadings=loadings,
        r2=r2,
        adj_r2=adj_r2,
        hac_lags=lags,
        residuals=pd.Series(resid, index=frame.index, name="residual"),
    )


def rolling_loadings(
    returns: pd.Series,
    factors: pd.DataFrame,
    model: Model | str = "ff3",
    *,
    window: int,
    frequency: str = "monthly",
) -> pd.DataFrame:
    """Factor loadings (and alpha) re-estimated over each trailing ``window`` of periods.

    One row per window end; exposure instability is visible rather than averaged
    away. Raises ``InsufficientDataError`` when fewer than ``window`` observations exist.
    """
    columns = factor_columns(model)
    excess = excess_returns(returns, factors)
    frame = _design(excess, factors, columns)
    if window < len(columns) + 2:
        raise UsageError(f"--rolling must be at least {len(columns) + 2} for {model}")
    if len(frame) < window:
        raise InsufficientDataError(
            f"{len(frame)} {frequency} observations available, {window} required for one window",
            hint="shorten --rolling or widen --start/--end",
        )
    rows: list[dict[str, float]] = []
    index: list[pd.Timestamp] = []
    for end in range(window, len(frame) + 1):
        piece = frame.iloc[end - window : end]
        y = piece["__y__"].to_numpy(dtype="float64")
        x = np.column_stack([np.ones(window), piece[list(columns)].to_numpy(dtype="float64")])
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        loadings = {c: float(beta[i + 1]) for i, c in enumerate(columns)}
        rows.append({"alpha": float(beta[0]), **loadings})
        index.append(pd.Timestamp(piece.index[-1]))
    out = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="date"))
    out.attrs = {"model": model, "window": window, "frequency": frequency}
    return out


def capm_beta(returns: pd.Series, factors: pd.DataFrame, *, frequency: str = "monthly") -> float:
    """The market loading from a CAPM regression on excess returns."""
    fit = factor_regression(returns, factors, "capm", frequency=frequency)
    return fit.loadings["Mkt-RF"].coefficient


def to_monthly_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Month-end prices → simple monthly returns, aligned with how the factors are published."""
    monthly = prices.resample("ME").last()
    out = monthly.pct_change().dropna(how="all")
    return out
