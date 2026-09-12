"""Constrained mean-variance optimization and the efficient frontier.

Markowitz (1952) mean-variance: choose weights ``w`` with ``Σw = 1`` and box
bounds to minimize ``wᵀΣw`` (min variance), maximize ``(wᵀμ - r_f)/sqrt(wᵀΣw)``
(max Sharpe, the tangency portfolio of Tobin 1958), hit a target return or
risk, equalize risk contributions (Maillard, Roncalli & Teïletche 2010), or
hold equal weights.

Solver: SLSQP via ``scipy.optimize.minimize``. Max-Sharpe runs from several
starting points (equal weight, min variance, seeded random) and the best
feasible solution wins, so a local optimum cannot pass as the answer.
Determinism is preserved by a fixed seed. Nothing here logs; findings such as
a concentration warning are returned on the result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from sobres.core.errors import InsufficientDataError, OptimizationError, UsageError

Objective = Literal[
    "min_variance", "max_sharpe", "target_return", "target_risk", "risk_parity", "equal_weight"
]
OBJECTIVES: tuple[str, ...] = (
    "min_variance",
    "max_sharpe",
    "target_return",
    "target_risk",
    "risk_parity",
    "equal_weight",
)
WEIGHT_TOLERANCE = 1e-8
CONCENTRATION_THRESHOLD = 0.50
RANDOM_STARTS = 8


@dataclass(frozen=True)
class Constraints:
    """Bounds on every weight. Long-only ``[0, 1]`` unless ``allow_short``."""

    max_weight: float | None = None
    allow_short: bool = False
    min_weight: float | None = None

    def bounds(self, n: int) -> list[tuple[float, float]]:
        lower = -1.0 if self.allow_short else 0.0
        if self.min_weight is not None:
            lower = max(lower, self.min_weight)
        upper = 1.0 if self.max_weight is None else min(1.0, self.max_weight)
        if upper * n < 1.0 - WEIGHT_TOLERANCE:
            raise UsageError(
                f"max_weight {upper} times {n} assets is below 1.0: the constraint is infeasible",
                hint=f"raise --max-weight to at least {1.0 / n:.4f} or add assets",
            )
        if lower > upper:
            raise UsageError(f"min_weight {lower} exceeds max_weight {upper}")
        return [(lower, upper)] * n


@dataclass(frozen=True)
class Estimators:
    expected_return: str
    covariance: str
    shrinkage: float | None = None
    psd_repair: dict[str, float] | None = None


@dataclass(frozen=True)
class Portfolio:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe: float
    objective: str
    estimators: Estimators
    risk_free: float
    warnings: tuple[str, ...] = ()
    solver_status: str = "optimal"
    risk_contributions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FrontierPoint:
    expected_return: float
    volatility: float
    sharpe: float
    weights: dict[str, float]
    is_min_variance: bool = False
    is_max_sharpe: bool = False


@dataclass(frozen=True)
class Frontier:
    points: tuple[FrontierPoint, ...]
    estimators: Estimators
    risk_free: float


def _stats(
    w: np.ndarray, mu: np.ndarray, sigma: np.ndarray, rf: float
) -> tuple[float, float, float]:
    ret = float(w @ mu)
    var = float(w @ sigma @ w)
    vol = float(np.sqrt(max(var, 0.0)))
    sharpe = (ret - rf) / vol if vol > 0 else float("nan")
    return ret, vol, sharpe


def _solve(
    fun: Callable[[np.ndarray], float],
    x0: np.ndarray,
    bounds: list[tuple[float, float]],
    constraints: list[dict[str, object]],
) -> tuple[np.ndarray, bool, str]:
    result = minimize(
        fun,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    w = np.asarray(result.x, dtype="float64")
    feasible = bool(result.success) and abs(w.sum() - 1.0) < 1e-6
    return w, feasible, str(result.message)


def _clean(w: np.ndarray, bounds: list[tuple[float, float]]) -> np.ndarray:
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w = np.clip(w, lo, hi)
    w[np.abs(w) < 1e-12] = 0.0
    return w / w.sum() if abs(w.sum()) > 1e-12 else w


def max_attainable_return(mu: np.ndarray, bounds: list[tuple[float, float]]) -> float:
    """Greedy: fill the highest-return assets to their upper bounds (box + sum = 1)."""
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w = lo.copy()
    remaining = 1.0 - w.sum()
    for i in np.argsort(-mu):
        room = hi[i] - w[i]
        take = min(room, remaining)
        w[i] += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return float(w @ mu)


def optimize(
    mu: pd.Series,
    sigma: pd.DataFrame,
    objective: Objective = "max_sharpe",
    constraints: Constraints | None = None,
    *,
    risk_free: float = 0.0,
    target: float | None = None,
    seed: int = 0,
    estimators: Estimators | None = None,
    explicit_max_weight: bool = False,
) -> Portfolio:
    """Solve one objective on annualized ``mu`` and ``sigma``; return a valid portfolio.

    Weights sum to one within ``1e-8`` and satisfy every bound within ``1e-8``.
    ``OptimizationError`` is raised if the solver does not converge; no weight
    vector is returned then. A concentration warning is attached when a weight
    exceeds 50% and no explicit ``max_weight`` was given.
    """
    if objective not in OBJECTIVES:
        raise UsageError(f"objective must be one of {', '.join(OBJECTIVES)}, got {objective!r}")
    cons = constraints or Constraints()
    assets = list(mu.index)
    sigma = sigma.loc[assets, assets]
    m = mu.to_numpy(dtype="float64")
    s = sigma.to_numpy(dtype="float64")
    n = len(assets)
    bounds = cons.bounds(n)
    sum_to_one = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    equal = np.full(n, 1.0 / n)
    est = estimators or Estimators(
        expected_return=str(mu.attrs.get("estimator", "given")),
        covariance=str(sigma.attrs.get("estimator", "given")),
        shrinkage=sigma.attrs.get("shrinkage"),
        psd_repair=sigma.attrs.get("psd_repair"),
    )
    status = "optimal"

    def variance(w: np.ndarray) -> float:
        return float(w @ s @ w)

    if objective == "equal_weight":
        w = equal
    elif objective == "min_variance":
        w, ok, msg = _solve(variance, equal, bounds, sum_to_one)
        if not ok:
            raise OptimizationError(f"min_variance did not converge: {msg}")
    elif objective == "max_sharpe":
        w = _max_sharpe(m, s, risk_free, bounds, sum_to_one, seed)
    elif objective == "target_return":
        if target is None:
            raise UsageError("target_return needs --target")
        attainable = max_attainable_return(m, bounds)
        if target > attainable + 1e-9:
            raise InsufficientDataError(
                f"target return {target:.4%} exceeds the attainable maximum {attainable:.4%}",
                hint=f"choose --target at or below {attainable:.4f}",
            )
        cons_list = [*sum_to_one, {"type": "eq", "fun": lambda w: float(w @ m - target)}]
        w, ok, msg = _solve(variance, equal, bounds, cons_list)
        if not ok:
            raise OptimizationError(f"target_return did not converge: {msg}")
    elif objective == "target_risk":
        if target is None:
            raise UsageError("target_risk needs --target")
        w_min, ok, msg = _solve(variance, equal, bounds, sum_to_one)
        if not ok:
            raise OptimizationError(f"target_risk did not converge: {msg}")
        min_vol = float(np.sqrt(variance(w_min)))
        if target < min_vol - 1e-9:
            raise InsufficientDataError(
                f"target risk {target:.4%} is below the minimum attainable "
                f"volatility {min_vol:.4%}",
                hint=f"choose --target at or above {min_vol:.4f}",
            )
        cons_list = [
            *sum_to_one,
            {"type": "ineq", "fun": lambda w: float(target**2 - w @ s @ w)},
        ]
        w, ok, msg = _solve(lambda w: -float(w @ m), w_min, bounds, cons_list)
        if not ok:
            raise OptimizationError(f"target_risk did not converge: {msg}")
    else:  # risk_parity
        w = _risk_parity(s, bounds, sum_to_one, equal)
    w = _clean(w, bounds)
    ret, vol, sharpe = _stats(w, m, s, risk_free)
    contributions = (w * (s @ w)) / (w @ s @ w) if vol > 0 else np.zeros(n)
    warnings: list[str] = []
    if (
        not explicit_max_weight
        and objective not in ("equal_weight",)
        and w.max() > CONCENTRATION_THRESHOLD
    ):
        top = assets[int(np.argmax(w))]
        warnings.append(
            f"{top} takes {w.max():.1%} of the portfolio: unconstrained mean-variance "
            "solutions concentrate; consider --max-weight"
        )
    return Portfolio(
        weights={a: float(x) for a, x in zip(assets, w, strict=True)},
        expected_return=ret,
        volatility=vol,
        sharpe=sharpe,
        objective=objective,
        estimators=est,
        risk_free=risk_free,
        warnings=tuple(warnings),
        solver_status=status,
        risk_contributions={a: float(c) for a, c in zip(assets, contributions, strict=True)},
    )


def _max_sharpe(
    m: np.ndarray,
    s: np.ndarray,
    rf: float,
    bounds: list[tuple[float, float]],
    sum_to_one: list[dict[str, object]],
    seed: int,
) -> np.ndarray:
    n = len(m)

    def neg_sharpe(w: np.ndarray) -> float:
        var = float(w @ s @ w)
        if var <= 0:
            return 1e6
        return -float((w @ m - rf) / np.sqrt(var))

    starts = [np.full(n, 1.0 / n)]
    w_min, ok, _ = _solve(lambda w: float(w @ s @ w), starts[0], bounds, sum_to_one)
    if ok:
        starts.append(w_min)
    rng = np.random.default_rng(seed)
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    for _ in range(RANDOM_STARTS):
        raw = rng.dirichlet(np.ones(n))
        starts.append(
            np.clip(lo + raw * (hi - lo), lo, hi)
            / max(np.sum(np.clip(lo + raw * (hi - lo), lo, hi)), 1e-12)
        )
    best: np.ndarray | None = None
    best_value = np.inf
    messages: list[str] = []
    for x0 in starts:
        w, ok, msg = _solve(neg_sharpe, x0, bounds, sum_to_one)
        if not ok:
            messages.append(msg)
            continue
        value = neg_sharpe(w)
        if value < best_value - 1e-12:
            best, best_value = w, value
    if best is None:
        raise OptimizationError(
            "max_sharpe did not converge from any starting point: "
            + "; ".join(sorted(set(messages)))
        )
    return best


def _risk_parity(
    s: np.ndarray,
    bounds: list[tuple[float, float]],
    sum_to_one: list[dict[str, object]],
    x0: np.ndarray,
) -> np.ndarray:
    n = s.shape[0]

    def objective(w: np.ndarray) -> float:
        total = float(w @ s @ w)
        if total <= 0:
            return 1e6
        rc = w * (s @ w) / total
        return float(np.sum((rc - 1.0 / n) ** 2)) * 1e4

    w, ok, msg = _solve(objective, x0, bounds, sum_to_one)
    if not ok:
        raise OptimizationError(f"risk_parity did not converge: {msg}")
    return w


def efficient_frontier(
    mu: pd.Series,
    sigma: pd.DataFrame,
    n_points: int = 50,
    constraints: Constraints | None = None,
    *,
    risk_free: float = 0.0,
    seed: int = 0,
) -> Frontier:
    """``n_points`` portfolios from the min-variance return to the max attainable.

    The minimum-variance and maximum-Sharpe portfolios are flagged. Sorted by
    expected return, volatility is non-decreasing on the efficient portion —
    the invariant that catches a broken solver.
    """
    if n_points < 2:
        raise UsageError("the frontier needs at least two points")
    cons = constraints or Constraints()
    min_var = optimize(
        mu, sigma, "min_variance", cons, risk_free=risk_free, explicit_max_weight=True
    )
    max_sharpe = optimize(
        mu, sigma, "max_sharpe", cons, risk_free=risk_free, seed=seed, explicit_max_weight=True
    )
    bounds = cons.bounds(len(mu))
    top = max_attainable_return(mu.to_numpy(dtype="float64"), bounds)
    targets = np.linspace(min_var.expected_return, top, n_points)
    points: list[FrontierPoint] = []
    for i, target in enumerate(targets):
        if i == 0:
            p = min_var
        else:
            p = optimize(
                mu,
                sigma,
                "target_return",
                cons,
                risk_free=risk_free,
                target=float(target),
                explicit_max_weight=True,
            )
        points.append(
            FrontierPoint(
                expected_return=p.expected_return,
                volatility=p.volatility,
                sharpe=p.sharpe,
                weights=p.weights,
                is_min_variance=(i == 0),
            )
        )
    points.append(
        FrontierPoint(
            expected_return=max_sharpe.expected_return,
            volatility=max_sharpe.volatility,
            sharpe=max_sharpe.sharpe,
            weights=max_sharpe.weights,
            is_max_sharpe=True,
        )
    )
    points.sort(key=lambda p: (p.expected_return, p.volatility))
    return Frontier(points=tuple(points), estimators=min_var.estimators, risk_free=risk_free)
