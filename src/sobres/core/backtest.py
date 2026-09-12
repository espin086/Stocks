"""Walk-forward evaluation with weight drift and transaction costs.

Lookahead prevention is structural: ``walk_forward`` slices
``returns.loc[:t].iloc[:-1]`` (strictly before the rebalance date) trimmed to
the lookback and passes **only that slice** to the strategy, which therefore
has no reference with which to reach forward. The test perturbs every
observation at or after ``t`` and asserts the weights at ``t`` are identical.

Turnover at a rebalance is ``0.5 · Σ|w_new - w_drifted|``; the cost deducted
is ``cost_bps / 10 000 · turnover`` of portfolio value. Between rebalances
weights drift with realized returns. The default cost is 10 bps, not 0: a
costless backtest flatters every high-turnover strategy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.risk import RiskPanel, risk_metrics

Rebalance = Literal["monthly", "quarterly", "annual", "never"]
REBALANCES: tuple[str, ...] = ("monthly", "quarterly", "annual", "never")
DEFAULT_COST_BPS = 10.0

Strategy = Callable[[pd.DataFrame], pd.Series]
"""Given returns strictly before the rebalance date, return weights indexed by asset."""

Progress = Callable[[int, int], None]
"""``progress(done, total)`` after each rebalance; optional and I/O-free here."""


@dataclass(frozen=True)
class BacktestResult:
    strategy: RiskPanel
    benchmark: RiskPanel
    equity_curve: pd.Series
    benchmark_curve: pd.Series
    weights_history: pd.DataFrame
    total_turnover: float
    total_cost: float
    oos_start: date
    oos_end: date
    n_rebalances: int
    requested_start: date | None
    shifted_start: bool
    rebalance: str
    lookback: int
    cost_bps: float


def rebalance_dates(
    index: pd.DatetimeIndex, rebalance: Rebalance, first: pd.Timestamp
) -> list[pd.Timestamp]:
    """First trading day of each period on or after ``first``; just ``first`` for ``never``."""
    if rebalance not in REBALANCES:
        raise UsageError(f"rebalance must be one of {', '.join(REBALANCES)}, got {rebalance!r}")
    eligible = index[index >= first]
    if len(eligible) == 0:
        return []
    if rebalance == "never":
        return [eligible[0]]
    period = {"monthly": "M", "quarterly": "Q", "annual": "Y"}[rebalance]
    periods = eligible.to_period(period)
    starts = [eligible[0]]
    for prev, cur, stamp in zip(periods[:-1], periods[1:], eligible[1:], strict=True):
        if cur != prev:
            starts.append(stamp)
    return starts


def turnover(new: np.ndarray, drifted: np.ndarray) -> float:
    """``0.5 · Σ|w_new - w_drifted|``: one-way traded fraction of the portfolio."""
    return 0.5 * float(np.abs(new - drifted).sum())


def _drift(weights: np.ndarray, period_returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Weights after one period of realized returns, and the portfolio return."""
    grown = weights * (1.0 + period_returns)
    total = float(grown.sum())
    portfolio_return = total - 1.0
    if total <= 0:
        return np.zeros_like(weights), portfolio_return
    return grown / total, portfolio_return


def _run(
    returns: pd.DataFrame,
    strategy: Strategy,
    schedule: list[pd.Timestamp],
    cost_rate: float,
    lookback: int,
    progress: Progress | None,
) -> tuple[pd.Series, pd.DataFrame, float, float]:
    assets = list(returns.columns)
    n = len(assets)
    values = returns.to_numpy(dtype="float64")
    index = pd.DatetimeIndex(returns.index)
    start_pos = int(np.searchsorted(index.to_numpy(), schedule[0].to_datetime64()))
    weights = np.zeros(n)
    value = 1.0
    curve: list[float] = []
    history: list[tuple[pd.Timestamp, np.ndarray]] = []
    total_turnover = 0.0
    total_cost = 0.0
    rebalance_set = set(schedule)
    done = 0
    for pos in range(start_pos, len(index)):
        stamp = index[pos]
        if stamp in rebalance_set:
            # Strictly before t, trimmed to the lookback: the only data the strategy sees.
            window = returns.iloc[max(0, pos - lookback) : pos]
            target = strategy(window.copy()).reindex(assets).fillna(0.0).to_numpy(dtype="float64")
            if abs(target.sum() - 1.0) > 1e-6:
                raise UsageError(
                    f"strategy weights on {stamp.date()} sum to {target.sum():.6f}, not 1"
                )
            traded = turnover(target, weights)
            cost = cost_rate * traded
            value *= 1.0 - cost
            total_turnover += traded
            total_cost += cost
            weights = target
            history.append((stamp, weights.copy()))
            done += 1
            if progress is not None:
                progress(done, len(schedule))
        weights, period_return = _drift(weights, np.nan_to_num(values[pos]))
        value *= 1.0 + period_return
        curve.append(value)
    equity = pd.Series(curve, index=index[start_pos:], name="equity")
    weights_history = pd.DataFrame(
        [w for _, w in history], index=pd.DatetimeIndex([s for s, _ in history]), columns=assets
    )
    return equity, weights_history, total_turnover, total_cost


def _curve_returns(curve: pd.Series) -> pd.Series:
    """Period returns of an equity curve that starts from a value of 1.0."""
    first = pd.Series([float(curve.iloc[0]) - 1.0], index=[curve.index[0]])
    return pd.concat([first, curve.pct_change().dropna()])


def walk_forward(
    returns: pd.DataFrame,
    strategy: Strategy,
    *,
    frequency: str,
    rebalance: Rebalance = "quarterly",
    lookback: int = 756,
    cost_bps: float = DEFAULT_COST_BPS,
    start: date | None = None,
    risk_free: float = 0.0,
    progress: Progress | None = None,
) -> BacktestResult:
    """Re-solve at each rebalance on prior data only; compare with equal weight.

    ``lookback`` is in observations of ``returns``' own frequency. If the
    requested ``start`` has fewer than ``lookback`` observations before it,
    the backtest starts at the first date that does and reports the shift.
    """
    if lookback < 2:
        raise UsageError("lookback must be at least 2 observations")
    index = pd.DatetimeIndex(returns.index)
    if len(index) <= lookback + 1:
        raise InsufficientDataError(
            f"{len(index)} observations cannot support a {lookback}-observation lookback "
            "plus an out-of-sample window",
            hint="widen --start/--end or shorten --lookback",
        )
    first_viable = index[lookback]
    requested = pd.Timestamp(start) if start is not None else first_viable
    shifted = requested < first_viable
    first = max(requested, first_viable)
    schedule = rebalance_dates(index, rebalance, first)
    if not schedule:
        raise InsufficientDataError(
            "no observations after the first viable rebalance date",
            hint="widen --end or shorten --lookback",
        )
    cost_rate = cost_bps / 10_000.0
    equity, weights_history, total_turnover, total_cost = _run(
        returns, strategy, schedule, cost_rate, lookback, progress
    )
    n = len(returns.columns)

    def equal_weight(_window: pd.DataFrame) -> pd.Series:
        return pd.Series(np.full(n, 1.0 / n), index=returns.columns)

    bench_equity, _, _, _ = _run(returns, equal_weight, schedule, cost_rate, lookback, None)
    strategy_returns = equity.pct_change().dropna()
    strategy_returns = pd.concat(
        [pd.Series([equity.iloc[0] - 1.0], index=[equity.index[0]]), strategy_returns]
    )
    bench_returns = pd.concat(
        [
            pd.Series([bench_equity.iloc[0] - 1.0], index=[bench_equity.index[0]]),
            bench_equity.pct_change().dropna(),
        ]
    )
    return BacktestResult(
        strategy=risk_metrics(strategy_returns, risk_free, frequency),
        benchmark=risk_metrics(bench_returns, risk_free, frequency),
        equity_curve=equity,
        benchmark_curve=bench_equity.rename("benchmark"),
        weights_history=weights_history,
        total_turnover=total_turnover,
        total_cost=total_cost,
        oos_start=equity.index[0].date(),
        oos_end=equity.index[-1].date(),
        n_rebalances=len(schedule),
        requested_start=start,
        shifted_start=bool(shifted),
        rebalance=rebalance,
        lookback=lookback,
        cost_bps=cost_bps,
    )
