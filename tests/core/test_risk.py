"""Every risk metric against a hand-computed 10-row fixture.

Scenarios: Metrics available; Sharpe ratio definition; Sortino uses downside
deviation; Max drawdown; Beta against a benchmark; Edge cases are enumerated.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import AlignmentError, InsufficientDataError
from sobres.core.risk import (
    beta,
    correlation_matrix,
    downside_deviation,
    excess_kurtosis,
    historical_cvar,
    historical_var,
    max_drawdown,
    risk_metrics,
    sharpe_ratio,
    skewness,
    sortino_ratio,
)

# Ten monthly returns. Hand computations below use these exact values.
R = [0.02, -0.01, 0.03, -0.04, 0.01, 0.05, -0.02, 0.00, 0.02, -0.03]
INDEX = pd.date_range("2020-01-31", periods=10, freq="ME")
SERIES = pd.Series(R, index=INDEX)
N = PERIODS_PER_YEAR["monthly"]


def test_annualized_return_and_volatility_match_hand_computation() -> None:
    growth = math.prod(1 + r for r in R)  # 1.0263... by hand: product of the ten factors
    expected_return = growth ** (N / 10) - 1
    mean = sum(R) / 10
    sample_var = sum((r - mean) ** 2 for r in R) / 9
    panel = risk_metrics(SERIES, 0.0, "monthly")
    assert panel.annualized_return == pytest.approx(expected_return)
    assert panel.volatility == pytest.approx(math.sqrt(sample_var) * math.sqrt(N))
    assert panel.n_obs == 10 and panel.frequency == "monthly"


def test_sharpe_is_excess_return_over_volatility() -> None:
    panel = risk_metrics(SERIES, 0.02, "monthly")
    assert panel.sharpe == pytest.approx((panel.annualized_return - 0.02) / panel.volatility)
    assert sharpe_ratio(0.1, 0.02, 0.2) == pytest.approx(0.4)
    assert math.isnan(sharpe_ratio(0.1, 0.0, 0.0))


def test_sortino_uses_downside_deviation_only() -> None:
    below = [min(r, 0.0) for r in R]  # -0.01, -0.04, -0.02, -0.03 and zeros
    dd = math.sqrt(sum(b**2 for b in below) / 10) * math.sqrt(N)
    assert downside_deviation(SERIES, "monthly") == pytest.approx(dd)
    panel = risk_metrics(SERIES, 0.0, "monthly")
    assert panel.sortino == pytest.approx(panel.annualized_return / dd)
    assert panel.sortino > panel.sharpe  # downside deviation < total volatility here
    assert math.isnan(sortino_ratio(pd.Series([0.01, 0.02]), "monthly", 0.0))


def test_max_drawdown_identifies_recovery_date() -> None:
    # Wealth path by hand: 1.02, 1.0098, 1.040094, 0.998490, 1.008475, 1.058899,
    # 1.037721, 1.037721, 1.058475, 1.026721. Peak 1.040094 (Mar), trough 0.998490
    # (Apr): the trough follows the peak directly, so the drawdown is April's -4%
    # exactly. Recovery: first wealth >= 1.040094 after the trough is June.
    dd = max_drawdown(SERIES)
    assert dd.max_drawdown == pytest.approx(-0.04)
    assert dd.peak == INDEX[2].date() and dd.trough == INDEX[3].date()
    assert dd.recovery == INDEX[5].date()
    never = max_drawdown(pd.Series([0.1, -0.5, 0.1], index=INDEX[:3]))
    assert never.recovery is None and never.max_drawdown == pytest.approx(-0.5)
    flat = max_drawdown(pd.Series([0.01, 0.01], index=INDEX[:2]))
    assert flat.max_drawdown == 0.0


def test_var_cvar_skew_kurtosis_hand_computed() -> None:
    sorted_r = sorted(R)
    # numpy's default linear quantile at 5% over 10 points: position 0.45 between the two smallest
    var95 = sorted_r[0] + 0.45 * (sorted_r[1] - sorted_r[0])
    assert historical_var(SERIES) == pytest.approx(var95)
    assert historical_cvar(SERIES) == pytest.approx(
        sorted_r[0]
    )  # only the worst month is at or below
    mean = sum(R) / 10
    m2 = sum((r - mean) ** 2 for r in R) / 10
    m3 = sum((r - mean) ** 3 for r in R) / 10
    m4 = sum((r - mean) ** 4 for r in R) / 10
    assert skewness(SERIES) == pytest.approx(m3 / m2**1.5)
    assert excess_kurtosis(SERIES) == pytest.approx(m4 / m2**2 - 3)
    constant = pd.Series([0.01, 0.01, 0.01])
    assert math.isnan(skewness(constant)) and math.isnan(excess_kurtosis(constant))


def test_calmar_is_return_over_drawdown_magnitude() -> None:
    panel = risk_metrics(SERIES, 0.0, "monthly")
    assert panel.calmar == pytest.approx(panel.annualized_return / abs(panel.max_drawdown))
    assert math.isnan(risk_metrics(pd.Series([0.01, 0.01], index=INDEX[:2]), 0.0, "monthly").calmar)


def test_beta_requires_30_overlapping_observations() -> None:
    rng = np.random.default_rng(1)
    market = pd.Series(rng.normal(0, 0.01, 40), index=pd.bdate_range("2020-01-01", periods=40))
    asset = 1.5 * market + pd.Series(rng.normal(0, 0.001, 40), index=market.index)
    assert beta(asset, market) == pytest.approx(
        1.5, abs=0.1
    )  # noise term: ±0.1 is the sampling error
    cov = np.cov(asset, market, ddof=1)[0, 1]
    assert beta(asset, market) == pytest.approx(cov / market.var(ddof=1))
    with pytest.raises(AlignmentError) as exc:
        beta(asset.iloc[:20], market)
    assert exc.value.exit_code == 5 and "30" in str(exc.value)


def test_panel_rejects_too_little_data_and_correlation_matrix_shape() -> None:
    with pytest.raises(InsufficientDataError):
        risk_metrics(pd.Series([0.01]), 0.0, "monthly")
    frame = pd.DataFrame({"A": R, "B": R[::-1]}, index=INDEX)
    corr = correlation_matrix(frame)
    assert corr.loc["A", "A"] == pytest.approx(1.0) and corr.shape == (2, 2)
    assert risk_metrics(SERIES, 0.0, "monthly").as_dict()["drawdown_peak"] == "2020-03-31"
