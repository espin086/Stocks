"""The legacy allocation LP port against its reference fixture.

Scenarios: Sources of truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sobres.core.allocate import LinearConstraint, legacy_constraints, linear_allocation
from sobres.core.errors import OptimizationError, UsageError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "r_reference" / "allocation.json"


def test_weights_match_within_1e_4() -> None:
    ref = json.loads(FIXTURE.read_text())
    vehicles = ref["vehicles"]
    returns = [r / 100 for r in ref["returns_pct"]]
    result = linear_allocation(vehicles, returns, legacy_constraints(ref["risk"]))
    for vehicle in vehicles:
        # abs=1e-4: the tolerance the 0002 tasks set for matching the R reference
        assert result.weights[vehicle] == pytest.approx(
            ref["solution"][vehicle], abs=1e-4
        )  # 1e-4 per the 0002 task list
    assert result.expected_return == pytest.approx(ref["objective"], abs=1e-4)  # same 1e-4
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert "commercial-minimum" in result.binding or "average-risk" in result.binding


def test_constraints_are_the_scripts_four() -> None:
    cons = legacy_constraints([6, 8, 10, 4, 1, 2])
    assert [c.name for c in cons] == ["average-risk", "commercial-minimum", "mortgage-ratio"]
    assert list(cons[2].coefficients) == [-1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
    with pytest.raises(UsageError):
        legacy_constraints([1, 2, 3])


def test_lp_validation_and_infeasibility() -> None:
    with pytest.raises(UsageError):
        linear_allocation(["a", "b"], [0.1], [])
    with pytest.raises(UsageError):
        linear_allocation(["a", "b"], [0.1, 0.2], [LinearConstraint("bad", [1.0], 0.0)])
    with pytest.raises(OptimizationError):
        linear_allocation(["a", "b"], [0.1, 0.2], [LinearConstraint("impossible", [1.0, 1.0], 0.5)])
    eq = linear_allocation(
        ["a", "b"], [0.1, 0.2], [LinearConstraint("half", [1.0, 0.0], 0.5, equality=True)]
    )
    assert eq.weights == pytest.approx({"a": 0.5, "b": 0.5})
