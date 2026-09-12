"""Expected-return and covariance estimators against hand computations.

Scenarios: Available estimators; Covariance estimators; Shrinkage is the
default; Insufficient observations; Every covariance matrix is usable;
Conversion precedes estimation.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.moments import (
    COV_METHODS,
    RETURN_METHODS,
    covariance,
    expected_returns,
    is_psd,
    ledoit_wolf_shrinkage,
)

INDEX = pd.bdate_range("2020-01-01", periods=6)
RET = pd.DataFrame(
    {"A": [0.01, -0.02, 0.03, 0.00, 0.02, -0.01], "B": [0.00, 0.01, -0.01, 0.02, -0.02, 0.03]},
    index=INDEX,
)


def test_available_estimators() -> None:
    assert RETURN_METHODS == ("mean_historical", "ewma", "capm")
    assert COV_METHODS == ("sample", "ledoit_wolf", "ewma", "semicovariance", "garch")
    for method in RETURN_METHODS:
        if method == "capm":
            continue
        assert list(expected_returns(RET, "daily", method).index) == ["A", "B"]  # type: ignore[arg-type]
    for method in COV_METHODS:
        if method == "garch":
            continue  # needs 30+ observations and the econ extra: tests/core/test_timeseries.py
        sigma = covariance(RET, "daily", method)  # type: ignore[arg-type]
        assert sigma.shape == (2, 2) and sigma.attrs["estimator"] == method
    with pytest.raises(ValueError):
        expected_returns(RET, "daily", "magic")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        covariance(RET, "daily", "magic")  # type: ignore[arg-type]


def test_mean_historical_is_annualized_mean() -> None:
    mu = expected_returns(RET, "daily")
    assert mu["A"] == pytest.approx(sum(RET["A"]) / 6 * 252)
    assert mu.attrs["estimator"] == "mean_historical"
    ewma = expected_returns(RET, "daily", "ewma", span=3)
    assert ewma["A"] != mu["A"]


def test_capm_uses_benchmark_and_risk_free() -> None:
    market = pd.Series([0.01, -0.01, 0.02, 0.0, 0.01, -0.02], index=INDEX)
    mu = expected_returns(RET, "daily", "capm", benchmark=market, risk_free=0.02)
    beta_a = np.cov(RET["A"], market, ddof=1)[0, 1] / market.var(ddof=1)
    premium = market.mean() * 252 - 0.02
    assert mu["A"] == pytest.approx(0.02 + beta_a * premium)
    with pytest.raises(UsageError):
        expected_returns(RET, "daily", "capm")


def test_ledoit_wolf_is_default() -> None:
    assert inspect.signature(covariance).parameters["method"].default == "ledoit_wolf"
    sigma = covariance(RET, "daily")
    assert sigma.attrs["estimator"] == "ledoit_wolf"
    assert 0.0 <= sigma.attrs["shrinkage"] <= 1.0
    sample = covariance(RET, "daily", "sample")
    assert sample.attrs["shrinkage"] is None
    assert sample.loc["A", "A"] == pytest.approx(RET["A"].var(ddof=1) * 252)


def test_ledoit_wolf_matches_paper_formula_computed_by_hand() -> None:
    """Ledoit & Wolf (2004) intensity recomputed with explicit loops."""
    x = RET.to_numpy()
    n, p = x.shape
    xc = x - x.mean(axis=0)
    s = np.zeros((p, p))
    for k in range(n):
        s += np.outer(xc[k], xc[k]) / n
    mu = np.trace(s) / p
    delta = np.sum((s - mu * np.eye(p)) ** 2) / p
    beta_terms = 0.0
    for k in range(n):
        beta_terms += np.sum((np.outer(xc[k], xc[k]) - s) ** 2) / p
    beta = min(beta_terms / n**2, delta)
    intensity = beta / delta
    expected = (1 - intensity) * s + intensity * mu * np.eye(p)
    shrunk, got = ledoit_wolf_shrinkage(x)
    assert got == pytest.approx(intensity)
    np.testing.assert_allclose(shrunk, expected, rtol=1e-12)


def test_singular_case_raises_with_both_counts() -> None:
    with pytest.raises(InsufficientDataError) as exc:
        covariance(RET.iloc[:2], "daily")
    assert "2 observations for 2 assets" in str(exc.value) and "singular" in str(exc.value)
    assert exc.value.exit_code == 5


def test_every_covariance_is_symmetric_and_psd() -> None:
    for method in COV_METHODS:
        if method == "garch":
            continue  # proved on a long simulated series in tests/core/test_timeseries.py
        sigma = covariance(RET, "daily", method)  # type: ignore[arg-type]
        values = sigma.to_numpy()
        assert np.allclose(values, values.T, atol=1e-10)
        assert is_psd(sigma)
    semi = covariance(RET, "daily", "semicovariance")
    shortfall = np.minimum(RET.to_numpy(), 0.0)
    np.testing.assert_allclose(semi.to_numpy(), shortfall.T @ shortfall / 6 * 252, rtol=1e-12)
