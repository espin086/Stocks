"""Price → returns, annualization, compounding. Pure functions over frames.

Simple returns are used everywhere they must aggregate across assets (a
portfolio return is the weighted sum of simple returns, not of log returns);
log returns are provided for the places that need additivity through time.

Sources: simple and log returns per Campbell, Lo & MacKinlay, *The
Econometrics of Financial Markets* (1997) §1.4; geometric annualization is
the compound annual growth rate ``(∏(1+r))^(N/n) - 1``.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year

NanPolicy = Literal["drop", "zero"]
NAN_POLICIES: tuple[str, ...] = ("drop", "zero")
Annualization = Literal["geometric", "arithmetic"]


def simple_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """``P_t / P_{t-1} - 1`` with the first row dropped."""
    out = prices / prices.shift(1) - 1.0
    out = out.iloc[1:]
    out.attrs = dict(prices.attrs)
    out.attrs["return_type"] = "simple"
    return out


def log_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """``ln(P_t / P_{t-1})`` with the first row dropped."""
    ratio = prices / prices.shift(1)
    logged: pd.DataFrame | pd.Series = cast(Any, np.log(ratio))
    out = logged.iloc[1:]
    out.attrs = dict(prices.attrs)
    out.attrs["return_type"] = "log"
    return out


def apply_nan_policy(
    returns: pd.DataFrame | pd.Series, policy: NanPolicy
) -> pd.DataFrame | pd.Series:
    """Resolve ``NaN`` returns explicitly: ``drop`` the row or treat as ``zero``.

    There is no default: the choice changes every downstream number, so the
    caller states it.
    """
    if policy not in NAN_POLICIES:
        raise ValueError(f"nan policy must be one of {NAN_POLICIES}, got {policy!r}")
    attrs = dict(returns.attrs)
    out = returns.dropna() if policy == "drop" else returns.fillna(0.0)
    out.attrs = attrs
    out.attrs["nan_policy"] = policy
    return out


def cumulative_wealth(
    returns: pd.DataFrame | pd.Series, initial: float = 1.0
) -> pd.DataFrame | pd.Series:
    """Growth of ``initial`` through the return series: ``initial · ∏(1 + r)``."""
    out = initial * (1.0 + returns).cumprod()
    out.attrs = dict(returns.attrs)
    return out


def annualized_return(
    returns: pd.Series, frequency: str, method: Annualization = "geometric"
) -> float:
    """Geometric ``(∏(1+r))^(N/n) - 1`` (default) or arithmetic ``mean(r)·N``.

    Geometric is the default because it is what an investor actually earns.
    """
    clean = returns.dropna()
    n = len(clean)
    if n == 0:
        raise ValueError("annualized_return needs at least one observation")
    periods = periods_per_year(frequency)
    if method == "geometric":
        growth = float(np.prod(1.0 + clean.to_numpy()))
        if growth <= 0:
            return -1.0
        return float(growth ** (periods / n) - 1.0)
    if method == "arithmetic":
        return float(clean.mean()) * float(periods)
    raise ValueError(f"method must be 'geometric' or 'arithmetic', got {method!r}")


def annualized_volatility(returns: pd.Series, frequency: str) -> float:
    """Sample standard deviation scaled by ``sqrt(periods per year)``."""
    clean = returns.dropna()
    if len(clean) < 2:
        raise ValueError("annualized_volatility needs at least two observations")
    return float(clean.std(ddof=1)) * float(np.sqrt(periods_per_year(frequency)))


def portfolio_returns(returns: pd.DataFrame, weights: pd.Series | dict[str, float]) -> pd.Series:
    """Period returns of a fixed-weight portfolio: ``Σ w_i r_i`` (simple returns)."""
    w = pd.Series(weights, dtype="float64").reindex(returns.columns)
    if w.isna().any():
        missing = list(w.index[w.isna()])
        raise ValueError(f"no weight for {missing}")
    out = returns.fillna(0.0) @ w
    out.name = "portfolio"
    out.attrs = dict(returns.attrs)
    return out
