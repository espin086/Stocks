"""Currency analytics: what the asset did, what the currency did, and what a hedge would cost.

    Decomposition (Solnik & McLeavey, *Global Investments*, ch. 2):
        (1 + r_total) = (1 + r_local)(1 + r_fx)
        r_total = r_local + r_fx + r_local · r_fx           — the cross term is its own component
    Compounded over a window, each component is the product of its (1 + r) minus one, and the
    compounded cross term is whatever makes the identity hold exactly:
        cross = (1 + R_total) - (1 + R_local) - (1 + R_fx) + 1
    Hedged return under covered interest parity (Solnik & McLeavey ch. 11):
        r_hedged ≈ r_local + (i_base - i_foreign) · Δt      — the forward premium earned by
        rolling a forward each period; excludes transaction costs, bid-ask and basis
    Currency risk: total volatility in base currency versus the volatility of the same
    weights on local returns (currencies held fixed); the difference is the currency's
    contribution, which can be negative when the correlation between local and FX returns
    is negative — so that correlation is reported, never assumed away.

Pure functions over series and frames; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.returns import annualized_volatility

HEDGE_NOTE = (
    "hedged figures are an interest-rate-differential approximation of a rolling hedge under "
    "covered interest parity, excluding transaction costs, bid-ask spread and basis; "
    "they are not an achievable realized return"
)


@dataclass(frozen=True)
class Decomposition:
    local: float
    fx: float
    cross: float
    total: float

    @property
    def reconciles(self) -> bool:
        return abs(self.total - (self.local + self.fx + self.cross)) < 1e-12


def decompose_return(local_returns: pd.Series, fx_returns: pd.Series) -> pd.DataFrame:
    """Per period: local, fx, cross and total, reconciling exactly.

    ``fx_returns`` are the period returns of the rate quoted as *base per one unit of
    local currency*, so a strengthening local currency is a positive fx return for a
    base-currency investor.
    """
    both = pd.concat([local_returns.rename("local"), fx_returns.rename("fx")], axis=1, join="inner")
    both = both.dropna()
    if both.empty:
        raise InsufficientDataError("no overlapping dates between the asset and the rate")
    out = both.copy()
    out["cross"] = out["local"] * out["fx"]
    out["total"] = (1.0 + out["local"]) * (1.0 + out["fx"]) - 1.0
    out.index.name = "date"
    return out


def compound_decomposition(per_period: pd.DataFrame) -> Decomposition:
    """Geometric compounding of each component; the cross term closes the identity."""
    local = float(np.prod(1.0 + per_period["local"].to_numpy()) - 1.0)
    fx = float(np.prod(1.0 + per_period["fx"].to_numpy()) - 1.0)
    total = float(np.prod(1.0 + per_period["total"].to_numpy()) - 1.0)
    cross = total - local - fx
    return Decomposition(local, fx, cross, total)


def aggregate(components: dict[str, Decomposition], weights: dict[str, float]) -> Decomposition:
    """Weight-average each component; the cross term keeps the identity exact."""
    total_w = sum(weights.values())
    if total_w <= 0:
        raise UsageError("weights must sum to a positive number")
    local = sum(components[k].local * w for k, w in weights.items()) / total_w
    fx = sum(components[k].fx * w for k, w in weights.items()) / total_w
    total = sum(components[k].total * w for k, w in weights.items()) / total_w
    return Decomposition(local, fx, total - local - fx, total)


@dataclass(frozen=True)
class CurrencyRisk:
    total_volatility: float
    """Annualized, base currency."""
    local_volatility: float
    """Annualized, the same weights on local returns — currencies held fixed."""
    currency_contribution: float
    """``total - local``; negative when currencies diversified the assets."""
    correlations: dict[str, float]
    """Per asset: correlation of its local return with its currency's return (NaN if in base)."""
    exposures: dict[str, float]
    """Share of portfolio value by currency."""


def currency_risk(
    local: pd.DataFrame,
    fx: pd.DataFrame,
    weights: dict[str, float],
    currencies: dict[str, str],
    base: str,
    frequency: str,
) -> CurrencyRisk:
    """Volatility with and without currency moves, plus the correlations that explain the gap.

    ``fx`` has one column per asset holding that asset's currency return against the base
    (zero for assets already in the base currency).
    """
    cols = list(weights)
    w = np.array([weights[c] for c in cols], dtype="float64")
    if abs(w.sum() - 1.0) > 1e-9:
        raise UsageError(f"weights sum to {w.sum():.6f}, not 1.0")
    frame = pd.concat([local[cols], fx[cols].add_suffix("__fx")], axis=1, join="inner").dropna()
    if len(frame) < 3:
        raise InsufficientDataError("fewer than three overlapping observations")
    local_ret = frame[cols]
    total_ret = (1.0 + local_ret.to_numpy()) * (
        1.0 + frame[[f"{c}__fx" for c in cols]].to_numpy()
    ) - 1.0
    port_total = pd.Series(total_ret @ w, index=frame.index)
    port_local = pd.Series(local_ret.to_numpy() @ w, index=frame.index)
    total_vol = annualized_volatility(port_total, frequency)
    local_vol = annualized_volatility(port_local, frequency)
    correlations: dict[str, float] = {}
    for c in cols:
        if currencies.get(c, base) == base:
            correlations[c] = float("nan")
        else:
            correlations[c] = float(np.corrcoef(frame[c], frame[f"{c}__fx"])[0, 1])
    exposures: dict[str, float] = {}
    for c in cols:
        ccy = currencies.get(c, base)
        exposures[ccy] = exposures.get(ccy, 0.0) + float(weights[c])
    _ = periods_per_year(frequency)
    return CurrencyRisk(total_vol, local_vol, total_vol - local_vol, correlations, exposures)


def hedged_returns(
    local: pd.Series, base_rate: pd.Series, foreign_rate: pd.Series, frequency: str
) -> pd.Series:
    """``r_local + (i_base - i_foreign)/periods`` per period, rates as decimal annual levels.

    Rates are aligned to the return dates with the last known level carried forward.
    Raises ``InsufficientDataError`` when either rate series has no overlap.
    """
    periods = periods_per_year(frequency)
    idx = pd.DatetimeIndex(local.dropna().index)
    b = base_rate.dropna().reindex(base_rate.dropna().index.union(idx)).ffill().reindex(idx)
    f = foreign_rate.dropna().reindex(foreign_rate.dropna().index.union(idx)).ffill().reindex(idx)
    if b.isna().all() or f.isna().all():
        raise InsufficientDataError("no short-term rate observations overlap the return window")
    premium = (b - f) / periods
    out = pd.Series((local.reindex(idx) + premium).dropna())
    out.name = f"{local.name}_hedged" if local.name else "hedged"
    out.attrs = {"hedge": "covered interest parity approximation", "periods_per_year": periods}
    return out


def hedge_cost(hedged: pd.Series, unhedged: pd.Series) -> float:
    """Cumulative hedged minus cumulative unhedged return over the common window."""
    both = pd.concat([hedged.rename("h"), unhedged.rename("u")], axis=1, join="inner").dropna()
    h = float(np.prod(1.0 + both["h"].to_numpy()) - 1.0)
    u = float(np.prod(1.0 + both["u"].to_numpy()) - 1.0)
    return h - u
