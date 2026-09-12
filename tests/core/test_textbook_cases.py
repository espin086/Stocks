"""Published two- and three-asset examples, end to end.

Scenarios: Sources of truth; Tolerances are explicit and justified.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from sobres.core.optimize import Constraints, efficient_frontier, optimize


def test_bodie_kane_marcus_two_asset_minimum_variance() -> None:
    """Bodie, Kane & Marcus, *Investments*, ch. 7 example: debt (E=8%, σ=12%),
    equity (E=13%, σ=20%), ρ=0.3. The minimum-variance weight on debt is
    (σ_E² - Cov) / (σ_D² + σ_E² - 2Cov) = (0.04 - 0.0072)/(0.0144 + 0.04 - 0.0144) = 0.82."""
    cov = 0.3 * 0.12 * 0.20
    mu = pd.Series({"D": 0.08, "E": 0.13})
    sigma = pd.DataFrame([[0.0144, cov], [cov, 0.04]], index=["D", "E"], columns=["D", "E"])
    p = optimize(mu, sigma, "min_variance")
    assert p.weights["D"] == pytest.approx(0.82, abs=1e-6)
    assert p.expected_return == pytest.approx(0.82 * 0.08 + 0.18 * 0.13, abs=1e-6)


def test_bodie_kane_marcus_tangency_portfolio() -> None:
    """Same example with r_f = 5%: the tangency weight on debt is
    [E(R_D)σ_E² - E(R_E)Cov] / [E(R_D)σ_E² + E(R_E)σ_D² - (E(R_D)+E(R_E))Cov] with excess
    returns E(R_D)=3%, E(R_E)=8%:
    (0.03·0.04 - 0.08·0.0072)/(0.03·0.04 + 0.08·0.0144 - 0.11·0.0072) = 0.40."""
    cov = 0.3 * 0.12 * 0.20
    mu = pd.Series({"D": 0.08, "E": 0.13})
    sigma = pd.DataFrame([[0.0144, cov], [cov, 0.04]], index=["D", "E"], columns=["D", "E"])
    w_d = (0.03 * 0.04 - 0.08 * cov) / (0.03 * 0.04 + 0.08 * 0.0144 - 0.11 * cov)
    assert w_d == pytest.approx(0.40, abs=1e-3)  # the textbook rounds to two decimals
    p = optimize(mu, sigma, "max_sharpe", risk_free=0.05)
    assert p.weights["D"] == pytest.approx(w_d, abs=1e-6)


def test_three_asset_frontier_brackets_the_textbook_points() -> None:
    mu = pd.Series({"D": 0.08, "E": 0.13, "T": 0.05})
    cov = 0.3 * 0.12 * 0.20
    sigma = pd.DataFrame(
        [[0.0144, cov, 0.0], [cov, 0.04, 0.0], [0.0, 0.0, 1e-6]],
        index=list("DET"),
        columns=list("DET"),
    )
    frontier = efficient_frontier(mu, sigma, n_points=20, constraints=Constraints(), risk_free=0.05)
    rets = np.array([p.expected_return for p in frontier.points])
    assert rets.min() == pytest.approx(
        0.05, abs=1e-3
    )  # the near-riskless asset anchors the low end
    assert rets.max() == pytest.approx(0.13, abs=1e-6)
    vols = [p.volatility for p in frontier.points]
    assert all(b >= a - 1e-8 for a, b in itertools.pairwise(vols))
