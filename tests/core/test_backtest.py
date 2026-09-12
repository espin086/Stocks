"""The walk-forward engine.

Scenarios: No lookahead; Rebalancing frequencies; Transaction costs; Weight
drift between rebalances; Benchmark comparison; Insufficient lookback; Long
computations report progress without logging; Survivorship is stated, not hidden.
"""

from __future__ import annotations

import itertools
from datetime import date

import numpy as np
import pandas as pd
import pytest

from sobres.core.backtest import (
    DEFAULT_COST_BPS,
    REBALANCES,
    rebalance_dates,
    turnover,
    walk_forward,
)
from sobres.core.errors import InsufficientDataError, UsageError

INDEX = pd.bdate_range("2020-01-01", periods=300)


def _returns(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(0.0005, 0.01, (300, 3)), index=INDEX, columns=list("ABC"))


def momentum(window: pd.DataFrame) -> pd.Series:
    """Weights proportional to trailing mean return, floored at zero — deterministic."""
    m = window.mean().clip(lower=0.0) + 1e-9
    return m / m.sum()


def test_no_lookahead_under_future_perturbation() -> None:
    returns = _returns()
    result = walk_forward(returns, momentum, frequency="daily", rebalance="monthly", lookback=60)
    for t in result.weights_history.index[1:4]:
        perturbed = returns.copy()
        perturbed.loc[t:] *= 50.0  # every observation at or after t, massively changed
        again = walk_forward(
            perturbed, momentum, frequency="daily", rebalance="monthly", lookback=60
        )
        np.testing.assert_array_equal(
            result.weights_history.loc[t].to_numpy(), again.weights_history.loc[t].to_numpy()
        )


def test_rebalancing_frequencies() -> None:
    assert REBALANCES == ("monthly", "quarterly", "annual", "never")
    first = INDEX[60]
    monthly = rebalance_dates(INDEX, "monthly", first)
    assert monthly[0] == first
    assert all(d.month != n.month for d, n in itertools.pairwise(monthly))
    quarterly = rebalance_dates(INDEX, "quarterly", first)
    assert len(quarterly) < len(monthly)
    assert len(rebalance_dates(INDEX, "annual", first)) == 2  # 2020 start and 2021
    assert rebalance_dates(INDEX, "never", first) == [first]
    assert rebalance_dates(INDEX, "monthly", INDEX[-1] + pd.Timedelta(days=10)) == []
    with pytest.raises(UsageError):
        rebalance_dates(INDEX, "weekly", first)  # type: ignore[arg-type]


def test_turnover_formula() -> None:
    assert turnover(np.array([0.6, 0.4]), np.array([0.5, 0.5])) == pytest.approx(0.1)
    assert turnover(np.array([1.0, 0.0]), np.array([0.0, 0.0])) == pytest.approx(0.5)


def test_default_cost_is_10bps() -> None:
    import inspect

    assert DEFAULT_COST_BPS == 10.0
    assert inspect.signature(walk_forward).parameters["cost_bps"].default == 10.0
    returns = _returns()
    costly = walk_forward(returns, momentum, frequency="daily", rebalance="monthly", lookback=60)
    free = walk_forward(
        returns, momentum, frequency="daily", rebalance="monthly", lookback=60, cost_bps=0
    )
    assert free.total_cost == 0 and costly.total_cost > 0
    assert costly.total_cost == pytest.approx(costly.total_turnover * 10 / 10_000)
    assert free.equity_curve.iloc[-1] > costly.equity_curve.iloc[-1]


def test_weights_drift_between_rebalances() -> None:
    # Two assets, no rebalance after the first: A doubles on day 1, B is flat, so
    # A's drifted weight becomes 2/3 and the portfolio return on day 2 is
    # 2/3 · 0 + 1/3 · 0.5 = 1/6, not the constant-weight 0.25.
    idx = pd.bdate_range("2020-01-01", periods=5)
    returns = pd.DataFrame(
        {"A": [0.0, 0.0, 1.0, 0.0, 0.0], "B": [0.0, 0.0, 0.0, 0.5, 0.0]}, index=idx
    )
    equal = lambda w: pd.Series({"A": 0.5, "B": 0.5})  # noqa: E731
    result = walk_forward(
        returns, equal, frequency="daily", rebalance="never", lookback=2, cost_bps=0
    )
    curve = result.equity_curve
    assert curve.iloc[0] == pytest.approx(1.5)  # day 3: A doubled at weight 0.5
    assert curve.iloc[1] == pytest.approx(1.5 * (1 + 1 / 6))  # day 4: drifted weights
    assert result.n_rebalances == 1 and result.total_turnover == pytest.approx(0.5)


def test_benchmark_uses_same_window() -> None:
    returns = _returns()
    result = walk_forward(returns, momentum, frequency="daily", rebalance="quarterly", lookback=60)
    assert result.equity_curve.index.equals(result.benchmark_curve.index)
    assert result.oos_start == result.equity_curve.index[0].date()
    assert result.oos_end == INDEX[-1].date()
    assert result.benchmark.n_obs == result.strategy.n_obs
    equal = lambda w: pd.Series(1 / 3, index=list("ABC"))  # noqa: E731
    same = walk_forward(returns, equal, frequency="daily", rebalance="quarterly", lookback=60)
    pd.testing.assert_series_equal(same.equity_curve, same.benchmark_curve, check_names=False)


def test_start_shifts_to_first_viable_date_and_reports() -> None:
    returns = _returns()
    result = walk_forward(
        returns,
        momentum,
        frequency="daily",
        rebalance="monthly",
        lookback=60,
        start=date(2020, 1, 2),
    )
    assert result.shifted_start and result.requested_start == date(2020, 1, 2)
    assert result.oos_start == INDEX[60].date()
    later = walk_forward(
        returns,
        momentum,
        frequency="daily",
        rebalance="monthly",
        lookback=60,
        start=date(2020, 9, 1),
    )
    assert not later.shifted_start and later.oos_start >= date(2020, 9, 1)
    with pytest.raises(InsufficientDataError):
        walk_forward(returns.iloc[:50], momentum, frequency="daily", lookback=60)
    with pytest.raises(InsufficientDataError):
        walk_forward(returns, momentum, frequency="daily", lookback=60, start=date(2030, 1, 1))
    with pytest.raises(UsageError):
        walk_forward(returns, momentum, frequency="daily", lookback=1)


def test_progress_callback_is_optional_and_counts_rebalances() -> None:
    returns = _returns()
    seen: list[tuple[int, int]] = []
    result = walk_forward(
        returns,
        momentum,
        frequency="daily",
        rebalance="monthly",
        lookback=60,
        progress=lambda d, t: seen.append((d, t)),
    )
    assert seen[-1] == (result.n_rebalances, result.n_rebalances)
    assert [d for d, _ in seen] == list(range(1, result.n_rebalances + 1))
    silent = walk_forward(returns, momentum, frequency="daily", rebalance="monthly", lookback=60)
    pd.testing.assert_series_equal(silent.equity_curve, result.equity_curve)


def test_strategy_weights_must_sum_to_one() -> None:
    bad = lambda w: pd.Series({"A": 0.5, "B": 0.2, "C": 0.1})  # noqa: E731
    with pytest.raises(UsageError, match="sum to"):
        walk_forward(_returns(), bad, frequency="daily", lookback=60)
