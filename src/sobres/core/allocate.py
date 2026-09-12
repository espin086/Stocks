"""The budget-allocation LP ported from ``legacy_code/Financial Portfolio Optimization.R``.

The original splits a budget across six vehicles to maximize average return
per dollar subject to: the fractions sum to one; a weighted-average risk
ceiling; a minimum share in one category; and a cross-category ratio. It is
kept as a general LP over named vehicles so the R script's outputs serve as
regression fixtures (``tests/fixtures/r_reference/``).

Solver: ``scipy.optimize.linprog`` (HiGHS). Pure; no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog

from sobres.core.errors import OptimizationError, UsageError


@dataclass(frozen=True)
class LinearConstraint:
    """``coefficients · w <= rhs`` (or ``==`` when ``equality``)."""

    name: str
    coefficients: Sequence[float]
    rhs: float
    equality: bool = False


@dataclass(frozen=True)
class Allocation:
    weights: dict[str, float]
    expected_return: float
    binding: tuple[str, ...] = field(default_factory=tuple)


def linear_allocation(
    vehicles: Sequence[str],
    returns: Sequence[float],
    constraints: Sequence[LinearConstraint],
    *,
    lower: float = 0.0,
    upper: float = 1.0,
) -> Allocation:
    """Maximize ``returns · w`` subject to ``Σw = 1``, bounds and the constraints."""
    n = len(vehicles)
    if len(returns) != n:
        raise UsageError(f"{len(returns)} returns for {n} vehicles")
    a_eq = [np.ones(n)]
    b_eq = [1.0]
    a_ub: list[np.ndarray] = []
    b_ub: list[float] = []
    for c in constraints:
        if len(c.coefficients) != n:
            raise UsageError(
                f"constraint {c.name!r} has {len(c.coefficients)} coefficients for {n} vehicles"
            )
        if c.equality:
            a_eq.append(np.asarray(c.coefficients, dtype="float64"))
            b_eq.append(float(c.rhs))
        else:
            a_ub.append(np.asarray(c.coefficients, dtype="float64"))
            b_ub.append(float(c.rhs))
    result = linprog(
        -np.asarray(returns, dtype="float64"),
        A_ub=np.array(a_ub) if a_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=np.array(a_eq),
        b_eq=np.array(b_eq),
        bounds=[(lower, upper)] * n,
        method="highs",
    )
    if not result.success:
        raise OptimizationError(f"allocation LP failed: {result.message}")
    w = np.asarray(result.x, dtype="float64")
    binding = tuple(
        c.name
        for c in constraints
        if not c.equality and abs(float(np.dot(c.coefficients, w)) - c.rhs) < 1e-9
    )
    return Allocation(
        weights={v: float(x) for v, x in zip(vehicles, w, strict=True)},
        expected_return=float(np.dot(returns, w)),
        binding=binding,
    )


def legacy_constraints(
    risks: Sequence[float], *, max_average_risk: float = 5.0, min_commercial: float = 0.20
) -> list[LinearConstraint]:
    """The four constraints of the original script, in its vehicle order.

    Vehicle order: first mortgages, second mortgages, personal loans, commercial
    loans, and two more (the sheet's rows 5 and 6). The mortgage constraint keeps
    the script's coefficients ``(-1, 2, 3, 0, 0, 0)`` exactly, code over comment.
    """
    n = len(risks)
    if n != 6:
        raise UsageError("the legacy allocation expects exactly six vehicles")
    risk_row = [r - max_average_risk for r in risks]
    commercial = [min_commercial] * n
    commercial[3] -= 1.0
    return [
        LinearConstraint("average-risk", risk_row, 0.0),
        LinearConstraint("commercial-minimum", commercial, 0.0),
        LinearConstraint("mortgage-ratio", [-1.0, 2.0, 3.0, 0.0, 0.0, 0.0], 0.0),
    ]
