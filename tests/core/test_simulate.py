"""Monte Carlo and block bootstrap: known answers, reproducibility, preserved blocks.

Scenarios: Simulation is run by default; Reported distribution; Bootstrap mode;
Reproducibility; The deterministic path is labeled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.goals import future_value, periodic_rate
from sobres.core.simulate import (
    PERCENTILES,
    apply_returns,
    bootstrap_returns,
    periodic_moments,
    simulate,
)


def test_zero_volatility_reproduces_the_deterministic_path() -> None:
    rate = periodic_rate(0.06, 12)
    result = simulate(
        present=1_000, contribution=100, periods=24, target=0, annual_mean=0.06, n_paths=50, seed=1
    )
    expected = future_value(1_000, 100, rate, 24)
    for p in PERCENTILES:
        assert result.percentiles[p] == pytest.approx(expected, rel=1e-12)
    assert result.success_probability == 1.0 and result.method == "montecarlo"
    assert set(result.percentiles) == {10, 25, 50, 75, 90}


def test_periodic_moments_and_timing() -> None:
    mu, sigma = periodic_moments(0.12, 0.24, "monthly")
    assert mu == pytest.approx(1.12 ** (1 / 12) - 1) and sigma == pytest.approx(0.24 / np.sqrt(12))
    returns = np.array([[0.1, 0.1]])
    assert apply_returns(100, 10, returns)[0] == pytest.approx((100 * 1.1 + 10) * 1.1 + 10)
    assert apply_returns(100, 10, returns, "begin")[0] == pytest.approx(
        ((100 + 10) * 1.1 + 10) * 1.1
    )


def test_seed_reproduces_every_path_and_is_reported_when_auto_generated() -> None:
    a = simulate(
        present=0,
        contribution=100,
        periods=120,
        target=20_000,
        annual_mean=0.07,
        annual_vol=0.15,
        n_paths=500,
        seed=42,
    )
    b = simulate(
        present=0,
        contribution=100,
        periods=120,
        target=20_000,
        annual_mean=0.07,
        annual_vol=0.15,
        n_paths=500,
        seed=42,
    )
    assert a == b and a.seed == 42
    auto = simulate(
        present=0,
        contribution=100,
        periods=12,
        target=1,
        annual_mean=0.07,
        annual_vol=0.15,
        n_paths=10,
    )
    again = simulate(
        present=0,
        contribution=100,
        periods=12,
        target=1,
        annual_mean=0.07,
        annual_vol=0.15,
        n_paths=10,
        seed=auto.seed,
    )
    assert again.percentiles == auto.percentiles  # the printed seed reproduces the auto-seeded run
    assert (
        0.0 < a.success_probability < 1.0
        and a.percentiles[10] < a.percentiles[50] < a.percentiles[90]
    )


def test_bootstrap_preserves_contiguous_blocks_and_states_the_window() -> None:
    history = pd.Series(
        np.arange(1, 25) / 100.0, index=pd.date_range("2020-01-31", periods=24, freq="ME")
    )
    draws = bootstrap_returns(4, 9, history, 3, np.random.default_rng(0))
    assert draws.shape == (4, 9)
    for row in draws:
        for k in range(0, 9, 3):  # every block is three consecutive historical returns
            assert row[k + 1] == pytest.approx(row[k] + 0.01) and row[k + 2] == pytest.approx(
                row[k] + 0.02
            )
    result = simulate(
        present=100,
        contribution=0,
        periods=6,
        target=100,
        method="bootstrap",
        history=history,
        block=3,
        n_paths=20,
        seed=1,
    )
    assert result.history_window == ("2020-01-31", "2021-12-31") and result.block == 3
    with pytest.raises(UsageError, match="bootstrap needs"):
        simulate(present=1, contribution=0, periods=6, target=1, method="bootstrap", n_paths=5)
    with pytest.raises(InsufficientDataError):
        bootstrap_returns(2, 4, history.iloc[:2], 3, np.random.default_rng(0))


def test_input_validation() -> None:
    with pytest.raises(UsageError):
        simulate(present=1, contribution=0, periods=6, target=1, method="quantum", n_paths=5)
    with pytest.raises(UsageError):
        simulate(present=1, contribution=0, periods=0, target=1, n_paths=5)
    with pytest.raises(UsageError):
        simulate(present=1, contribution=0, periods=1, target=1, n_paths=0)
