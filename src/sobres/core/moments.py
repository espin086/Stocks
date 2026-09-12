"""Expected-return and covariance estimators, and the PSD conditioning every solve needs.

Estimators are pluggable by name so the optimizer's inputs can change without
touching the solver. Shrinkage (Ledoit & Wolf, 2004, "A well-conditioned
estimator for large-dimensional covariance matrices", *J. Multivariate
Analysis* 88) is the **default** covariance because unconstrained
mean-variance on a sample covariance is an error maximizer.

All outputs are annualized with ``PERIODS_PER_YEAR[frequency]``; the returned
frames carry ``attrs`` describing the estimator and any repair applied, so an
adapter can log the assumption and a report can print it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year
from sobres.core.errors import InsufficientDataError, UsageError

ReturnMethod = Literal["mean_historical", "ewma", "capm"]
CovMethod = Literal["sample", "ledoit_wolf", "ewma", "semicovariance", "garch"]
RETURN_METHODS: tuple[str, ...] = ("mean_historical", "ewma", "capm")
COV_METHODS: tuple[str, ...] = ("sample", "ledoit_wolf", "ewma", "semicovariance", "garch")
DEFAULT_COV: CovMethod = "ledoit_wolf"
EWMA_SPAN = 60
PSD_TOLERANCE = 1e-10


@dataclass(frozen=True)
class PsdRepair:
    """What nearest-PSD projection did to a covariance matrix."""

    min_eigenvalue: float
    clipped: int


def _require_enough(returns: pd.DataFrame) -> None:
    n_obs, n_assets = returns.shape
    if n_obs <= n_assets:
        raise InsufficientDataError(
            f"{n_obs} observations for {n_assets} assets: the sample covariance matrix is "
            "singular (needs more observations than assets)",
            hint="widen --start/--end or drop assets",
        )


def expected_returns(
    returns: pd.DataFrame,
    frequency: str,
    method: ReturnMethod = "mean_historical",
    *,
    benchmark: pd.Series | None = None,
    risk_free: float = 0.0,
    span: int = EWMA_SPAN,
) -> pd.Series:
    """Annualized expected return per asset.

    ``mean_historical``: arithmetic mean times periods per year.
    ``ewma``: exponentially weighted mean (``span`` periods) times periods per year.
    ``capm``: ``r_f + beta_i (E[r_m] - r_f)`` with ``beta_i = cov(r_i, r_m)/var(r_m)``
    over the aligned overlap; needs ``benchmark`` (Sharpe, 1964).
    """
    periods = periods_per_year(frequency)
    clean = returns.dropna(how="all")
    if method == "mean_historical":
        out = clean.mean() * periods
    elif method == "ewma":
        out = clean.ewm(span=span).mean().iloc[-1] * periods
    elif method == "capm":
        if benchmark is None:
            raise UsageError("the capm estimator needs a benchmark return series")
        both = pd.concat([clean, benchmark.rename("__m__")], axis=1, join="inner").dropna()
        market = both["__m__"]
        var_m = float(market.var(ddof=1))
        premium = float(market.mean()) * periods - risk_free
        betas = both.drop(columns="__m__").apply(
            lambda c: float(np.cov(c, market, ddof=1)[0, 1]) / var_m
        )
        out = risk_free + betas * premium
    else:
        raise ValueError(f"method must be one of {RETURN_METHODS}, got {method!r}")
    out = out.astype("float64")
    out.name = "expected_return"
    out.attrs = {"estimator": method, "frequency": frequency, "n_obs": len(clean)}
    return out


def _sample(x: np.ndarray) -> np.ndarray:
    return np.cov(x, rowvar=False, ddof=1)


def ledoit_wolf_shrinkage(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrink the sample covariance toward ``mu·I`` with the Ledoit-Wolf intensity.

    Follows Ledoit & Wolf (2004), eqs. 14 and 15, on demeaned observations
    ``x`` (n by p): ``S = XᵀX/n``, ``mu = tr(S)/p``, ``delta² = ||S - mu I||²``,
    ``beta² = (1/n²) Σ_k ||x_k x_kᵀ - S||²`` (scaled Frobenius norms, divided by
    ``p``), intensity ``beta²/delta²`` clipped to ``[0, 1]``.
    """
    n, p = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / n
    mu = float(np.trace(s)) / p
    delta = float(np.sum((s - mu * np.eye(p)) ** 2)) / p
    x2 = x**2
    beta_sum = float(np.sum(x2.T @ x2)) / n - float(np.sum(s**2))
    beta = beta_sum / (n * p)
    beta = min(beta, delta)
    shrinkage = 0.0 if delta == 0 else beta / delta
    shrunk = (1.0 - shrinkage) * s + shrinkage * mu * np.eye(p)
    return shrunk, float(shrinkage)


def _ewma_cov(x: np.ndarray, span: int) -> np.ndarray:
    lam = 1.0 - 2.0 / (span + 1.0)
    n = x.shape[0]
    weights = lam ** np.arange(n - 1, -1, -1)
    weights /= weights.sum()
    centred = x - np.average(x, axis=0, weights=weights)
    return np.asarray((centred * weights[:, None]).T @ centred, dtype="float64")


def _semicov(x: np.ndarray, target: float) -> np.ndarray:
    shortfall = np.minimum(x - target, 0.0)
    return np.asarray(shortfall.T @ shortfall / x.shape[0], dtype="float64")


def covariance(
    returns: pd.DataFrame,
    frequency: str,
    method: CovMethod = DEFAULT_COV,
    *,
    span: int = EWMA_SPAN,
    target: float = 0.0,
) -> pd.DataFrame:
    """Annualized covariance by ``method``; Ledoit-Wolf shrinkage by default.

    Raises ``InsufficientDataError`` when observations do not exceed assets.
    The result is symmetrized and PSD-repaired by ``condition_covariance``;
    ``attrs`` record ``estimator``, ``shrinkage`` (for Ledoit-Wolf) and any
    ``psd_repair``.
    """
    clean = returns.dropna()
    _require_enough(clean)
    x = clean.to_numpy(dtype="float64")
    periods = periods_per_year(frequency)
    shrinkage: float | None = None
    if method == "sample":
        raw = _sample(x)
    elif method == "ledoit_wolf":
        raw, shrinkage = ledoit_wolf_shrinkage(x)
    elif method == "ewma":
        raw = _ewma_cov(x, span)
    elif method == "semicovariance":
        raw = _semicov(x, target)
    elif method == "garch":
        # 0009: GARCH(1,1) conditional variances with constant correlation, already annualized.
        from sobres.core.timeseries import garch_covariance

        raw = garch_covariance(clean, frequency) / periods
    else:
        raise ValueError(f"method must be one of {COV_METHODS}, got {method!r}")
    sigma = pd.DataFrame(raw * periods, index=clean.columns, columns=clean.columns)
    sigma, repair = condition_covariance(sigma)
    sigma.attrs = {
        "estimator": method,
        "frequency": frequency,
        "n_obs": len(clean),
        "shrinkage": shrinkage,
        "psd_repair": None if repair is None else repair.__dict__,
    }
    return sigma


def condition_covariance(sigma: pd.DataFrame) -> tuple[pd.DataFrame, PsdRepair | None]:
    """Symmetrize, then nearest-PSD by eigenvalue clipping with trace preserved.

    ``(Σ + Σᵀ)/2`` removes float asymmetry; if the smallest eigenvalue is below
    ``-1e-10`` every negative eigenvalue is clipped to ``1e-10`` and the matrix
    rescaled to keep its trace (Higham-style projection). The repair is
    returned so the caller can log it at WARNING — this module never logs.
    """
    values = sigma.to_numpy(dtype="float64")
    sym = (values + values.T) / 2.0
    eigenvalues, vectors = np.linalg.eigh(sym)
    min_eig = float(eigenvalues.min())
    if min_eig >= -PSD_TOLERANCE:
        return pd.DataFrame(sym, index=sigma.index, columns=sigma.columns), None
    clipped = int((eigenvalues < PSD_TOLERANCE).sum())
    fixed = np.clip(eigenvalues, PSD_TOLERANCE, None)
    repaired = vectors @ np.diag(fixed) @ vectors.T
    trace_before = float(np.trace(sym))
    trace_after = float(np.trace(repaired))
    if trace_before > 0 and trace_after > 0:
        repaired *= trace_before / trace_after
    repaired = (repaired + repaired.T) / 2.0
    out = pd.DataFrame(repaired, index=sigma.index, columns=sigma.columns)
    return out, PsdRepair(min_eigenvalue=min_eig, clipped=clipped)


def is_psd(sigma: pd.DataFrame, tolerance: float = PSD_TOLERANCE) -> bool:
    values = sigma.to_numpy(dtype="float64")
    return bool(np.allclose(values, values.T, atol=tolerance)) and bool(
        np.linalg.eigvalsh((values + values.T) / 2).min() >= -tolerance
    )
