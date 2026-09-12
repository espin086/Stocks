"""Monte Carlo and block-bootstrap simulation of a funding path.

A plan's deterministic answer is one path — the median case under a constant
return. The simulation puts a distribution behind it: ``n`` paths of periodic
returns applied to the same balance and contribution schedule, and the fraction
that reach the target is the success probability.

    Monte Carlo:  r_t ~ Normal(mu_p, sigma_p) i.i.d. per period, where the periodic
                  moments come from annual ones: mu_p = (1+mu)^(1/k) - 1,
                  sigma_p = sigma / sqrt(k)   (k periods per year)
    Bootstrap:    r_t drawn as contiguous blocks of length ``block`` from a historical
                  return series (Künsch 1989, the moving-block bootstrap), which keeps
                  autocorrelation and therefore sequence-of-returns risk

Seeded ``numpy.random.default_rng``: the same seed reproduces every path bit for bit.
Pure functions; no I/O, no logging.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from sobres.core.conventions import periods_per_year
from sobres.core.errors import InsufficientDataError, UsageError

Method = Literal["montecarlo", "bootstrap"]
METHODS: tuple[str, ...] = ("montecarlo", "bootstrap")
PERCENTILES: tuple[int, ...] = (10, 25, 50, 75, 90)
DEFAULT_BLOCK = 12  # one year of monthly returns per block


@dataclass(frozen=True)
class Simulation:
    method: str
    n_paths: int
    periods: int
    seed: int
    target: float
    success_probability: float
    percentiles: dict[int, float]
    """Terminal balance at the 10th, 25th, 50th, 75th and 90th percentiles."""
    history_window: tuple[str, str] | None = None
    block: int | None = None


def periodic_moments(annual_mean: float, annual_vol: float, frequency: str) -> tuple[float, float]:
    k = periods_per_year(frequency)
    return (1.0 + annual_mean) ** (1.0 / k) - 1.0, annual_vol / np.sqrt(k)


def apply_returns(
    present: float, contribution: float, returns: np.ndarray, timing: str = "end"
) -> np.ndarray:
    """Terminal balances for a matrix of per-period returns (paths by periods)."""
    balances = np.full(returns.shape[0], float(present))
    for t in range(returns.shape[1]):
        if timing == "begin":
            balances = (balances + contribution) * (1.0 + returns[:, t])
        else:
            balances = balances * (1.0 + returns[:, t]) + contribution
    return balances


def montecarlo_returns(
    n_paths: int,
    periods: int,
    annual_mean: float,
    annual_vol: float,
    frequency: str,
    rng: np.random.Generator,
) -> np.ndarray:
    mu, sigma = periodic_moments(annual_mean, annual_vol, frequency)
    draws = rng.normal(mu, sigma, size=(n_paths, periods))
    return np.asarray(np.maximum(draws, -0.999))  # a period cannot lose more than everything


def bootstrap_returns(
    n_paths: int, periods: int, history: pd.Series, block: int, rng: np.random.Generator
) -> np.ndarray:
    values = history.dropna().to_numpy(dtype="float64")
    if len(values) < max(block, 2):
        raise InsufficientDataError(
            f"{len(values)} historical returns; at least {max(block, 2)} are needed to bootstrap",
            hint="widen --history-start or shorten --block",
        )
    starts = rng.integers(0, len(values) - block + 1, size=(n_paths, int(np.ceil(periods / block))))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_paths, -1)[:, :periods]
    return np.asarray(values[idx], dtype="float64")


def simulate(
    *,
    present: float,
    contribution: float,
    periods: int,
    target: float,
    frequency: str = "monthly",
    method: Method | str = "montecarlo",
    annual_mean: float = 0.0,
    annual_vol: float = 0.0,
    history: pd.Series | None = None,
    block: int = DEFAULT_BLOCK,
    n_paths: int = 10_000,
    seed: int | None = None,
    timing: str = "end",
) -> Simulation:
    """Run ``n_paths`` funding paths and summarize where they end."""
    if method not in METHODS:
        raise UsageError(f"method must be one of {', '.join(METHODS)}, got {method!r}")
    if n_paths <= 0:
        raise UsageError("the number of simulated paths must be positive")
    if periods <= 0:
        raise UsageError("the horizon must be at least one period")
    seed_used = int(np.random.SeedSequence().generate_state(1)[0]) if seed is None else int(seed)
    rng = np.random.default_rng(seed_used)
    window: tuple[str, str] | None = None
    if method == "bootstrap":
        if history is None:
            raise UsageError("--method bootstrap needs a historical return series (--history)")
        returns = bootstrap_returns(n_paths, periods, history, block, rng)
        clean = history.dropna()
        window = (
            str(pd.Timestamp(clean.index.min()).date()),
            str(pd.Timestamp(clean.index.max()).date()),
        )
    else:
        returns = montecarlo_returns(n_paths, periods, annual_mean, annual_vol, frequency, rng)
    terminal = apply_returns(present, contribution, returns, timing)
    pct = {p: float(np.percentile(terminal, p)) for p in PERCENTILES}
    return Simulation(
        method=method,
        n_paths=n_paths,
        periods=periods,
        seed=seed_used,
        target=target,
        success_probability=float(np.mean(terminal >= target)),
        percentiles=pct,
        history_window=window,
        block=block if method == "bootstrap" else None,
    )
