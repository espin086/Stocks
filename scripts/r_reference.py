#!/usr/bin/env python3
"""Produce ``tests/fixtures/r_reference/`` for the legacy allocation LP.

The reference implementation is ``legacy_code/Financial Portfolio
Optimization.R`` (``linprog::solveLP``). Neither R nor the Google Sheet it
reads were reachable from the implementing environment, so this script solves
the *same* LP by exhaustive vertex enumeration — independent of the
``scipy.optimize.linprog`` path ``sobres.core.allocate`` uses — on a fixed
six-vehicle table, and records the optimum as the regression fixture. Re-run
the R script on the same table to replace it with R's own output.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "r_reference"

VEHICLES = [
    "first_mortgages",
    "second_mortgages",
    "personal_loans",
    "commercial_loans",
    "savings",
    "treasuries",
]
RETURNS_PCT = [9.0, 12.0, 15.0, 8.0, 3.0, 5.0]
RISK = [6.0, 8.0, 10.0, 4.0, 1.0, 2.0]


def constraint_matrix() -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Rows: budget (==), average risk (<=), commercial minimum (<=), mortgage ratio (<=)."""
    n = len(VEHICLES)
    budget = np.ones(n)
    risk = np.array(RISK) - 5.0
    commercial = np.full(n, 0.20)
    commercial[3] -= 1.0
    mortgages = np.array([-1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
    return (
        np.vstack([budget, risk, commercial, mortgages]),
        np.array([1.0, 0.0, 0.0, 0.0]),
        ["==", "<=", "<=", "<="],
    )


def enumerate_vertices() -> tuple[np.ndarray, float]:
    """Every basic feasible solution of {A_eq w = 1, A_ub w <= 0, 0 <= w <= 1}."""
    a, b, dirs = constraint_matrix()
    n = len(VEHICLES)
    # Candidate active sets: choose n tight constraints among the inequalities
    # (rows and bounds) plus the equality, solve, keep feasible ones.
    rows = [(a[i], b[i]) for i in range(len(dirs))]
    bound_rows = [(np.eye(n)[i], 0.0) for i in range(n)] + [(np.eye(n)[i], 1.0) for i in range(n)]
    candidates = rows[1:] + bound_rows
    best_w, best_value = None, -np.inf
    for active in itertools.combinations(range(len(candidates)), n - 1):
        system = np.vstack([rows[0][0], *[candidates[i][0] for i in active]])
        rhs = np.array([rows[0][1], *[candidates[i][1] for i in active]])
        if abs(np.linalg.det(system)) < 1e-12:
            continue
        w = np.linalg.solve(system, rhs)
        if (w < -1e-9).any() or (w > 1 + 1e-9).any():
            continue
        if (a[1:] @ w > 1e-9).any():
            continue
        value = float(np.array(RETURNS_PCT) / 100 @ w)
        if value > best_value + 1e-12:
            best_w, best_value = w, value
    assert best_w is not None
    return best_w, best_value


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    w, value = enumerate_vertices()
    payload = {
        "source": "legacy_code/Financial Portfolio Optimization.R (LP structure); "
        "values from exhaustive vertex enumeration, see scripts/r_reference.py",
        "vehicles": VEHICLES,
        "returns_pct": RETURNS_PCT,
        "risk": RISK,
        "constraints": {
            "budget": "sum(w) == 1",
            "average_risk": "(risk - 5) . w <= 0",
            "commercial_minimum": "0.20 . 1 - e_4 . w <= 0",
            "mortgage_ratio": "(-1, 2, 3, 0, 0, 0) . w <= 0",
        },
        "solution": {v: round(float(x), 10) for v, x in zip(VEHICLES, w, strict=True)},
        "objective": round(value, 10),
    }
    (OUT / "allocation.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["solution"], indent=2), payload["objective"])


if __name__ == "__main__":
    main()
