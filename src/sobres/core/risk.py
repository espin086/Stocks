"""The risk panel: volatility, Sharpe, Sortino, drawdown, VaR/CVaR, beta.

Every metric names its formula. Sources: Sharpe (1994) for the Sharpe ratio;
Sortino & van der Meer (1991) for downside deviation; Jorion, *Value at Risk*
(2006) for historical VaR and expected shortfall; the Calmar ratio is annual
return over the maximum drawdown magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year
from sobres.core.errors import AlignmentError, InsufficientDataError
from sobres.core.returns import annualized_return, annualized_volatility, cumulative_wealth

MIN_BETA_OVERLAP = 30


@dataclass(frozen=True)
class Drawdown:
    max_drawdown: float
    peak: date
    trough: date
    recovery: date | None


@dataclass(frozen=True)
class RiskPanel:
    annualized_return: float
    volatility: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    drawdown_peak: date
    drawdown_trough: date
    drawdown_recovery: date | None
    var_95: float
    cvar_95: float
    skew: float
    kurtosis: float
    n_obs: int
    frequency: str
    risk_free: float

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in self.__dict__.items():
            out[key] = value.isoformat() if isinstance(value, date) else value
        return out


def sharpe_ratio(ann_return: float, ann_risk_free: float, ann_vol: float) -> float:
    """``(R_p - R_f) / sigma_p`` on annualized inputs (Sharpe, 1994)."""
    if ann_vol == 0:
        return float("nan")
    return (ann_return - ann_risk_free) / ann_vol


def downside_deviation(returns: pd.Series, frequency: str, target: float = 0.0) -> float:
    """Annualized ``sqrt(mean(min(r - target, 0)^2))`` (Sortino & van der Meer)."""
    clean = returns.dropna().to_numpy()
    shortfall = np.minimum(clean - target, 0.0)
    return float(np.sqrt(np.mean(shortfall**2))) * float(np.sqrt(periods_per_year(frequency)))


def sortino_ratio(
    returns: pd.Series, frequency: str, ann_risk_free: float, target: float = 0.0
) -> float:
    """``(R_p - R_f) / downside deviation``, denominator below ``target`` only."""
    dd = downside_deviation(returns, frequency, target)
    if dd == 0:
        return float("nan")
    return (annualized_return(returns, frequency) - ann_risk_free) / dd


def max_drawdown(returns: pd.Series) -> Drawdown:
    """Most negative ``V_t / max(V_0..t) - 1`` over cumulative wealth, with dates.

    Recovery is the first date after the trough where wealth regains the peak,
    or ``None`` if it never does within the series.
    """
    clean = returns.dropna()
    index = pd.DatetimeIndex(clean.index)
    wealth = np.asarray(cumulative_wealth(clean).to_numpy(), dtype="float64")
    running_peak = np.maximum.accumulate(wealth)
    drawdowns = wealth / running_peak - 1.0
    trough_pos = int(np.argmin(drawdowns))
    peak_value = float(running_peak[trough_pos])
    peak_pos = int(np.argmax(wealth[: trough_pos + 1] >= peak_value))
    after = np.where(wealth[trough_pos + 1 :] >= peak_value)[0]
    recovery = None if len(after) == 0 else index[trough_pos + 1 + int(after[0])]
    return Drawdown(
        max_drawdown=float(drawdowns[trough_pos]),
        peak=index[peak_pos].date(),
        trough=index[trough_pos].date(),
        recovery=None if recovery is None else recovery.date(),
    )


def historical_var(returns: pd.Series, level: float = 0.95) -> float:
    """Historical VaR: the ``(1 - level)`` empirical quantile of period returns.

    A loss is negative, so VaR(95) is the 5th percentile return.
    """
    return float(np.quantile(returns.dropna().to_numpy(), 1.0 - level))


def historical_cvar(returns: pd.Series, level: float = 0.95) -> float:
    """Expected shortfall: mean of returns at or below the VaR quantile."""
    clean = returns.dropna().to_numpy()
    threshold = np.quantile(clean, 1.0 - level)
    tail = clean[clean <= threshold]
    return float(tail.mean())


def skewness(returns: pd.Series) -> float:
    """Sample skewness, ``m_3 / m_2^{3/2}`` on population moments (Fisher-Pearson)."""
    clean = returns.dropna().to_numpy()
    centred = clean - clean.mean()
    m2 = np.mean(centred**2)
    if m2 == 0:
        return float("nan")
    return float(np.mean(centred**3) / m2**1.5)


def excess_kurtosis(returns: pd.Series) -> float:
    """``m_4 / m_2^2 - 3`` on population moments (zero for a normal)."""
    clean = returns.dropna().to_numpy()
    centred = clean - clean.mean()
    m2 = np.mean(centred**2)
    if m2 == 0:
        return float("nan")
    return float(np.mean(centred**4) / m2**2 - 3.0)


def beta(asset: pd.Series, benchmark: pd.Series) -> float:
    """``cov(a, b) / var(b)`` over the aligned overlap; needs 30 observations."""
    both = pd.concat([asset.rename("a"), benchmark.rename("b")], axis=1, join="inner").dropna()
    if len(both) < MIN_BETA_OVERLAP:
        raise AlignmentError(
            f"beta needs at least {MIN_BETA_OVERLAP} overlapping observations, found {len(both)}",
            hint="widen the window or align the frequencies",
        )
    a = both["a"].to_numpy()
    b = both["b"].to_numpy()
    var_b = np.var(b, ddof=1)
    return float(np.cov(a, b, ddof=1)[0, 1] / var_b)


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()


def risk_metrics(
    returns: pd.Series, risk_free: float, frequency: str, *, min_obs: int = 2
) -> RiskPanel:
    """The full panel for one return series. ``risk_free`` is a decimal annual rate."""
    clean = returns.dropna()
    if len(clean) < max(min_obs, 2):
        raise InsufficientDataError(
            f"{len(clean)} observations, need at least {max(min_obs, 2)} for a risk panel",
            hint="widen --start/--end",
        )
    ann = annualized_return(clean, frequency)
    vol = annualized_volatility(clean, frequency)
    dd = max_drawdown(clean)
    calmar = ann / abs(dd.max_drawdown) if dd.max_drawdown < 0 else float("nan")
    return RiskPanel(
        annualized_return=ann,
        volatility=vol,
        sharpe=sharpe_ratio(ann, risk_free, vol),
        sortino=sortino_ratio(clean, frequency, risk_free),
        calmar=calmar,
        max_drawdown=dd.max_drawdown,
        drawdown_peak=dd.peak,
        drawdown_trough=dd.trough,
        drawdown_recovery=dd.recovery,
        var_95=historical_var(clean),
        cvar_95=historical_cvar(clean),
        skew=skewness(clean),
        kurtosis=excess_kurtosis(clean),
        n_obs=len(clean),
        frequency=frequency,
        risk_free=risk_free,
    )
