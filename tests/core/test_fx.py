"""Currency decomposition, risk and hedging against hand-computed identities.

Scenarios: Decomposition; The cross term is reported, not hidden; Multi-period
attribution compounds; Risk decomposition; Correlation is not assumed away;
Net currency exposure; Construction; Missing rate data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.fx import (
    HEDGE_NOTE,
    aggregate,
    compound_decomposition,
    currency_risk,
    decompose_return,
    hedge_cost,
    hedged_returns,
)

IDX = pd.bdate_range("2024-01-01", periods=4)


def test_decomposition_reconciles_exactly_with_the_cross_term_shown() -> None:
    local = pd.Series([0.10, -0.05, 0.02, 0.00], index=IDX)
    fx = pd.Series([0.02, 0.03, -0.01, 0.05], index=IDX)
    frame = decompose_return(local, fx)
    assert list(frame.columns) == ["local", "fx", "cross", "total"]
    # Period 1 by hand: 1.10 × 1.02 − 1 = 0.122 = 0.10 + 0.02 + 0.002
    assert frame["total"].iloc[0] == pytest.approx(0.122)
    assert frame["cross"].iloc[0] == pytest.approx(0.002)
    np.testing.assert_allclose(frame["total"], frame["local"] + frame["fx"] + frame["cross"])
    with pytest.raises(InsufficientDataError):
        decompose_return(local, fx.shift(10, freq="D"))


def test_multi_period_attribution_compounds_geometrically() -> None:
    local = pd.Series([0.10, -0.05], index=IDX[:2])
    fx = pd.Series([0.02, 0.03], index=IDX[:2])
    d = compound_decomposition(decompose_return(local, fx))
    assert d.local == pytest.approx(1.10 * 0.95 - 1)
    assert d.fx == pytest.approx(1.02 * 1.03 - 1)
    assert d.total == pytest.approx(1.10 * 1.02 * 0.95 * 1.03 - 1)
    assert d.cross == pytest.approx(d.total - d.local - d.fx) and d.reconciles
    port = aggregate({"A": d, "B": d}, {"A": 0.5, "B": 0.5})
    assert port.total == pytest.approx(d.total) and port.reconciles
    with pytest.raises(UsageError):
        aggregate({"A": d}, {"A": 0.0})


def test_currency_risk_reports_correlation_and_exposure_not_additivity() -> None:
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=500)
    a = pd.Series(rng.normal(0, 0.01, 500), index=idx)
    b = pd.Series(rng.normal(0, 0.01, 500), index=idx)
    # B's currency moves against B's local return: a natural hedge lowers total risk.
    fx_b = -0.8 * b + rng.normal(0, 0.003, 500)
    local = pd.DataFrame({"A": a, "B": b})
    fx = pd.DataFrame({"A": 0.0, "B": fx_b}, index=idx)
    risk = currency_risk(local, fx, {"A": 0.5, "B": 0.5}, {"A": "USD", "B": "GBP"}, "USD", "daily")
    assert risk.currency_contribution < 0  # negative correlation reduced risk
    assert risk.correlations["B"] < -0.9 and np.isnan(risk.correlations["A"])
    assert risk.exposures == {"USD": 0.5, "GBP": 0.5}
    assert risk.total_volatility == pytest.approx(
        risk.local_volatility + risk.currency_contribution
    )
    amplified = currency_risk(
        local,
        pd.DataFrame({"A": 0.0, "B": 0.8 * b}, index=idx),
        {"A": 0.5, "B": 0.5},
        {"A": "USD", "B": "GBP"},
        "USD",
        "daily",
    )
    assert amplified.currency_contribution > 0 and amplified.correlations["B"] > 0.9
    with pytest.raises(UsageError):
        currency_risk(local, fx, {"A": 0.7, "B": 0.5}, {}, "USD", "daily")


def test_hedged_construction_adds_the_forward_premium_per_period() -> None:
    idx = pd.bdate_range("2024-01-01", periods=5)
    local = pd.Series(0.001, index=idx, name="X")
    base_rate = pd.Series([0.05], index=pd.DatetimeIndex(["2023-12-01"]))  # 5% annual
    foreign_rate = pd.Series([0.02], index=pd.DatetimeIndex(["2023-12-01"]))  # 2% annual
    hedged = hedged_returns(local, base_rate, foreign_rate, "daily")
    premium = (0.05 - 0.02) / PERIODS_PER_YEAR["daily"]
    np.testing.assert_allclose(hedged.to_numpy(), 0.001 + premium)
    assert hedged.name == "X_hedged" and hedged.attrs["hedge"].startswith("covered interest parity")
    assert "not an achievable realized return" in HEDGE_NOTE
    unhedged = pd.Series(0.001, index=idx)
    assert hedge_cost(hedged, unhedged) == pytest.approx((1 + 0.001 + premium) ** 5 - (1.001) ** 5)


def test_missing_rate_data_is_loud() -> None:
    idx = pd.bdate_range("2024-01-01", periods=5)
    local = pd.Series(0.001, index=idx)
    with pytest.raises(InsufficientDataError):
        hedged_returns(local, pd.Series(dtype="float64"), pd.Series([0.02], index=idx[:1]), "daily")
