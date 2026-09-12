"""The optimizer against closed forms.

Scenarios: Supported objectives; Weights are a valid portfolio; Long-only by
default; Position limits; Target return infeasible; Max-Sharpe correctness;
Solver failure is never silent; Concentration warning; Determinism; Frontier
generation; Monotonicity; Named points identified; Algebraic properties.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sobres.core.errors import InsufficientDataError, OptimizationError, UsageError
from sobres.core.optimize import (
    OBJECTIVES,
    Constraints,
    efficient_frontier,
    max_attainable_return,
    optimize,
)

# Two assets: mu = (0.10, 0.15), vol = (0.20, 0.30), correlation 0.2.
MU2 = pd.Series({"A": 0.10, "B": 0.15})
SIG2 = pd.DataFrame(
    [[0.04, 0.2 * 0.2 * 0.3], [0.2 * 0.2 * 0.3, 0.09]], index=["A", "B"], columns=["A", "B"]
)
MU3 = pd.Series({"A": 0.08, "B": 0.12, "C": 0.10})
SIG3 = pd.DataFrame(
    [[0.04, 0.006, 0.002], [0.006, 0.09, 0.012], [0.002, 0.012, 0.0225]],
    index=list("ABC"),
    columns=list("ABC"),
)


def test_supported_objectives() -> None:
    assert OBJECTIVES == (
        "min_variance",
        "max_sharpe",
        "target_return",
        "target_risk",
        "risk_parity",
        "equal_weight",
    )
    with pytest.raises(UsageError):
        optimize(MU2, SIG2, "max_drawdown")  # type: ignore[arg-type]


def test_min_variance_matches_analytic_two_asset() -> None:
    # w_A = (σ_B² - σ_AB) / (σ_A² + σ_B² - 2σ_AB)  (Markowitz two-asset minimum variance)
    s_ab = 0.2 * 0.2 * 0.3
    w_a = (0.09 - s_ab) / (0.04 + 0.09 - 2 * s_ab)
    p = optimize(MU2, SIG2, "min_variance")
    assert p.weights["A"] == pytest.approx(w_a, abs=1e-6)  # SLSQP tolerance: ftol 1e-12 on variance
    assert p.weights["B"] == pytest.approx(1 - w_a, abs=1e-6)
    assert sum(p.weights.values()) == pytest.approx(1.0, abs=1e-8)
    assert p.objective == "min_variance" and p.solver_status == "optimal"


def test_max_sharpe_matches_closed_form_tangency() -> None:
    # Tangency weights ∝ Σ⁻¹(μ - r_f), normalized (Tobin 1958); long-only holds here.
    rf = 0.02
    excess = MU3.to_numpy() - rf
    raw = np.linalg.solve(SIG3.to_numpy(), excess)
    w = raw / raw.sum()
    assert (w > 0).all()
    p = optimize(MU3, SIG3, "max_sharpe", risk_free=rf)
    for asset, expected in zip(list("ABC"), w, strict=True):
        assert p.weights[asset] == pytest.approx(expected, abs=1e-6)
    expected_ret = float(w @ MU3.to_numpy())
    expected_vol = float(np.sqrt(w @ SIG3.to_numpy() @ w))
    assert p.expected_return == pytest.approx(expected_ret, abs=1e-6)
    assert p.volatility == pytest.approx(expected_vol, abs=1e-6)
    assert p.sharpe == pytest.approx((expected_ret - rf) / expected_vol, abs=1e-6)


def test_deterministic_across_runs() -> None:
    a = optimize(MU3, SIG3, "max_sharpe", seed=7)
    b = optimize(MU3, SIG3, "max_sharpe", seed=7)
    assert a.weights == b.weights  # bit-for-bit


def test_weights_are_a_valid_portfolio_under_every_objective() -> None:
    cons = Constraints(max_weight=0.6)
    for objective in OBJECTIVES:
        target = {"target_return": 0.10, "target_risk": 0.22}.get(objective)
        p = optimize(MU3, SIG3, objective, cons, target=target)  # type: ignore[arg-type]
        assert sum(p.weights.values()) == pytest.approx(1.0, abs=1e-8)
        for w in p.weights.values():
            assert -1e-8 <= w <= 0.6 + 1e-8


def test_long_only_by_default_and_short_relaxes() -> None:
    assert Constraints().bounds(3) == [(0.0, 1.0)] * 3
    assert Constraints(allow_short=True).bounds(2) == [(-1.0, 1.0)] * 2
    assert Constraints(max_weight=0.5, min_weight=0.1).bounds(2) == [(0.1, 0.5)] * 2
    # A and B correlated 0.9 with very different volatility, C independent: the
    # unconstrained minimum-variance portfolio w = Σ⁻¹1 / (1ᵀΣ⁻¹1) shorts B
    # (closed form, Merton 1972) and every weight lies inside [-1, 1].
    sigma = pd.DataFrame(
        [[0.01, 0.045, 0.0], [0.045, 0.25, 0.0], [0.0, 0.0, 0.01]],
        index=list("ABC"),
        columns=list("ABC"),
    )
    inv_ones = np.linalg.solve(sigma.to_numpy(), np.ones(3))
    closed_form = inv_ones / inv_ones.sum()
    assert closed_form[1] < 0
    short = optimize(MU3, sigma, "min_variance", Constraints(allow_short=True))
    for asset, expected in zip(list("ABC"), closed_form, strict=True):
        assert short.weights[asset] == pytest.approx(expected, abs=1e-6)
    long_only = optimize(MU3, sigma, "min_variance")
    assert long_only.weights["B"] == pytest.approx(0.0, abs=1e-8)


def test_infeasible_max_weight_raises_usage() -> None:
    with pytest.raises(UsageError) as exc:
        Constraints(max_weight=0.3).bounds(3)
    assert exc.value.exit_code == 2 and "infeasible" in str(exc.value)
    with pytest.raises(UsageError):
        Constraints(max_weight=0.2, min_weight=0.5).bounds(2)
    p = optimize(MU3, SIG3, "max_sharpe", Constraints(max_weight=0.35), explicit_max_weight=True)
    assert max(p.weights.values()) <= 0.35 + 1e-8


def test_target_return_above_attainable_raises_with_max() -> None:
    assert max_attainable_return(MU3.to_numpy(), Constraints().bounds(3)) == pytest.approx(0.12)
    assert max_attainable_return(
        MU3.to_numpy(), Constraints(max_weight=0.5).bounds(3)
    ) == pytest.approx(0.11)
    with pytest.raises(InsufficientDataError) as exc:
        optimize(MU3, SIG3, "target_return", target=0.13)
    assert "12.0000%" in str(exc.value)
    with pytest.raises(UsageError):
        optimize(MU3, SIG3, "target_return")
    p = optimize(MU3, SIG3, "target_return", target=0.10)
    assert p.expected_return == pytest.approx(0.10, abs=1e-7)


def test_target_risk_paths() -> None:
    min_var = optimize(MU3, SIG3, "min_variance")
    with pytest.raises(InsufficientDataError):
        optimize(MU3, SIG3, "target_risk", target=min_var.volatility * 0.5)
    with pytest.raises(UsageError):
        optimize(MU3, SIG3, "target_risk")
    p = optimize(MU3, SIG3, "target_risk", target=0.20)
    assert p.volatility <= 0.20 + 1e-6 and p.expected_return >= min_var.expected_return - 1e-9


def test_risk_contributions_equal_within_tolerance() -> None:
    p = optimize(MU3, SIG3, "risk_parity")
    contributions = np.array(list(p.risk_contributions.values()))
    np.testing.assert_allclose(contributions, 1 / 3, atol=1e-4)  # SLSQP on a scaled objective


def test_equal_weight_needs_no_solver() -> None:
    p = optimize(MU3, SIG3, "equal_weight")
    assert p.weights == {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    assert p.warnings == ()


def test_nonconvergence_raises_optimization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from sobres.core import optimize as mod

    class _Result:
        success = False
        x = np.array([0.5, 0.5])
        message = "Iteration limit reached"

    monkeypatch.setattr(mod, "minimize", lambda *a, **k: _Result())
    for objective in ("min_variance", "max_sharpe", "risk_parity", "target_risk"):
        with pytest.raises(OptimizationError, match="Iteration limit"):
            optimize(MU2, SIG2, objective, target=0.25)  # type: ignore[arg-type]
    with pytest.raises(OptimizationError):
        optimize(MU2, SIG2, "target_return", target=0.12)


def test_concentration_warning_above_50pct() -> None:
    lopsided = pd.Series({"A": 0.30, "B": 0.02})
    p = optimize(lopsided, SIG2, "max_sharpe")
    assert p.weights["A"] > 0.5
    assert any("--max-weight" in w for w in p.warnings)
    silenced = optimize(
        lopsided, SIG2, "max_sharpe", Constraints(max_weight=0.9), explicit_max_weight=True
    )
    assert silenced.warnings == ()


def test_frontier_generation_and_named_points() -> None:
    frontier = efficient_frontier(MU3, SIG3, n_points=10)
    assert len(frontier.points) == 11  # 10 targets plus the max-Sharpe point
    assert sum(p.is_min_variance for p in frontier.points) == 1
    assert sum(p.is_max_sharpe for p in frontier.points) == 1
    first = frontier.points[0]
    assert first.is_min_variance and first.expected_return == pytest.approx(
        optimize(MU3, SIG3, "min_variance").expected_return, abs=1e-8
    )
    assert frontier.points[-1].expected_return == pytest.approx(0.12, abs=1e-7)
    for point in frontier.points:
        assert sum(point.weights.values()) == pytest.approx(1.0, abs=1e-8)
        assert point.sharpe == pytest.approx(point.expected_return / point.volatility, abs=1e-9)
    with pytest.raises(UsageError):
        efficient_frontier(MU3, SIG3, n_points=1)


def test_volatility_non_decreasing_in_return() -> None:
    frontier = efficient_frontier(MU3, SIG3, n_points=25)
    vols = [p.volatility for p in frontier.points]
    for earlier, later in itertools.pairwise(vols):
        assert later >= earlier - 1e-8


@settings(max_examples=25, deadline=None)
@given(
    rets=st.lists(st.floats(min_value=0.01, max_value=0.3), min_size=3, max_size=3),
    vols=st.lists(st.floats(min_value=0.05, max_value=0.5), min_size=3, max_size=3),
)
def test_weights_sum_to_one_over_generated_inputs(rets: list[float], vols: list[float]) -> None:
    mu = pd.Series(rets, index=list("ABC"))
    sigma = pd.DataFrame(np.diag(np.square(vols)), index=list("ABC"), columns=list("ABC"))
    for objective in ("min_variance", "max_sharpe", "risk_parity"):
        p = optimize(mu, sigma, objective)  # type: ignore[arg-type]
        assert sum(p.weights.values()) == pytest.approx(1.0, abs=1e-8)
        assert all(-1e-8 <= w <= 1 + 1e-8 for w in p.weights.values())
