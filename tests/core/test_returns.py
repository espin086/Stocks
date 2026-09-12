"""Return computation against hand-computed values.

Scenarios: Simple returns; Log returns; Annualization; Geometric vs arithmetic;
Missing observations.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from sobres.core.returns import (
    annualized_return,
    annualized_volatility,
    apply_nan_policy,
    cumulative_wealth,
    log_returns,
    portfolio_returns,
    simple_returns,
)

# Prices 100 → 110 → 99 → 108.9: simple returns +10%, -10%, +10% by hand.
PRICES = pd.Series([100.0, 110.0, 99.0, 108.9], index=pd.bdate_range("2020-01-01", periods=4))


def test_simple_returns_hand_computed() -> None:
    r = simple_returns(PRICES)
    assert list(r.round(12)) == [0.1, -0.1, 0.1]
    assert len(r) == 3 and r.attrs["return_type"] == "simple"


def test_log_returns_hand_computed() -> None:
    r = log_returns(PRICES)
    assert r.iloc[0] == pytest.approx(math.log(1.1))
    assert r.iloc[1] == pytest.approx(math.log(0.9))
    frame = log_returns(pd.DataFrame({"A": PRICES}))
    assert frame.shape == (3, 1)


def test_geometric_matches_hand_computed() -> None:
    # Twelve monthly returns of exactly +1% compound to 1.01^12 - 1 per year.
    r = pd.Series([0.01] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))
    assert annualized_return(r, "monthly") == pytest.approx(1.01**12 - 1)
    assert annualized_return(r, "monthly", "arithmetic") == pytest.approx(0.12)
    # Six months of the same series annualize to the same geometric rate.
    assert annualized_return(r.iloc[:6], "monthly") == pytest.approx(1.01**12 - 1)
    with pytest.raises(ValueError):
        annualized_return(r, "monthly", "harmonic")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        annualized_return(pd.Series(dtype=float), "monthly")
    assert annualized_return(pd.Series([-1.0, 0.5]), "annual") == -1.0


def test_annualization_uses_convention_table() -> None:
    daily = pd.Series([0.01, -0.01, 0.02, 0.0], index=pd.bdate_range("2020-01-01", periods=4))
    assert annualized_return(daily, "daily", "arithmetic") == pytest.approx(daily.mean() * 252)
    assert annualized_volatility(daily, "daily") == pytest.approx(daily.std(ddof=1) * np.sqrt(252))
    assert annualized_volatility(daily, "weekly") == pytest.approx(daily.std(ddof=1) * np.sqrt(52))
    with pytest.raises(ValueError):
        annualized_volatility(pd.Series([0.1]), "daily")


def test_nan_policy_has_no_default() -> None:
    import inspect

    assert (
        inspect.signature(apply_nan_policy).parameters["policy"].default is inspect.Parameter.empty
    )
    r = pd.Series([0.1, np.nan, 0.2])
    assert list(apply_nan_policy(r, "drop")) == [0.1, 0.2]
    assert list(apply_nan_policy(r, "zero")) == [0.1, 0.0, 0.2]
    assert apply_nan_policy(r, "zero").attrs["nan_policy"] == "zero"
    with pytest.raises(ValueError):
        apply_nan_policy(r, "ffill")  # type: ignore[arg-type]


def test_cumulative_wealth_and_portfolio_returns() -> None:
    r = simple_returns(PRICES)
    wealth = cumulative_wealth(r, initial=100.0)
    assert wealth.iloc[-1] == pytest.approx(108.9)
    frame = pd.DataFrame({"A": [0.1, 0.0], "B": [0.0, -0.1]})
    port = portfolio_returns(frame, {"A": 0.5, "B": 0.5})
    assert list(port) == pytest.approx([0.05, -0.05])
    with pytest.raises(ValueError):
        portfolio_returns(frame, {"A": 1.0})
