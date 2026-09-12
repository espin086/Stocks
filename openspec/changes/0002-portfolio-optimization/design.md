# 0002 — Design

## Pipeline

```
tickers ──► data.get_prices ──► core.returns ──┬─► core.moments.expected_returns ─┐
                                               └─► core.moments.covariance ───────┤
                                                                                  ▼
                                                                         core.optimize
                                                                                  │
                                        ┌─────────────────────────────────────────┤
                                        ▼                                         ▼
                               core.backtest (walk-forward)              efficient_frontier
                                        │                                         │
                                        └──────────────► cli/render ◄─────────────┘
```

Every arrow crosses a pure function boundary. `core` receives frames and returns
frozen dataclasses; it never learns where the data came from.

## Why the backtest is not optional

Unconstrained mean-variance optimization on historical means is a well-documented
trap: it is an error-maximizer. Estimation noise in expected returns gets amplified
into extreme weights, and the resulting in-sample Sharpe is close to meaningless.

Three design responses, all in v1:

1. **Shrinkage by default.** Ledoit-Wolf is the default covariance estimator, not an
   option a user has to discover. Sample covariance remains available and explicit.
2. **The frontier, not the point.** `qf optimize frontier` shows the whole trade-off
   curve. A single "optimal" portfolio invites false precision; a curve does not.
3. **Walk-forward truth.** `qf optimize backtest` re-solves at each rebalance using
   only prior data. The gap between the in-sample Sharpe and the walk-forward Sharpe
   is the most useful number this tool produces, and it ships in v1.

Transaction costs default to 10 bps rather than 0 for the same reason: the default
should not flatter the result.

## Solver

**Default: `scipy.optimize.minimize(method="SLSQP")`.** It handles every v1
objective (equality constraint on the weight sum, box bounds, one nonlinear
objective), and it is already a base dependency via `scipy`.

- `min_variance` — quadratic, well-conditioned; SLSQP is comfortable.
- `max_sharpe` — solved on the transformed problem (minimize negative Sharpe) with
  multiple starting points (equal-weight, min-variance, random) to guard against a
  local optimum; the best feasible solution wins. Determinism is preserved by a
  fixed seed for the random starts.
- `target_return` / `target_risk` — add one equality constraint.
- `risk_parity` — minimize the sum of squared deviations of risk contributions
  `w_i * (Σw)_i / (wᵀΣw)` from `1/n`.
- `equal_weight` — no solver.

`cvxpy` stays an **opt-in extra** (`pip install quantfolio[opt]`). It is the right
tool for convex objectives that SLSQP handles badly (CVaR, cardinality, robust
formulations) — all post-v1. Making it a base dependency would drag a solver stack
into an install that does not need it.

## Covariance conditioning

Before any solve:

1. Symmetrize: `Σ = (Σ + Σᵀ) / 2` (removes float asymmetry).
2. Eigen-decompose; if `λ_min < -1e-10`, clip negatives to `1e-10` and rescale to
   preserve the trace — the standard nearest-PSD repair — and warn to stderr with
   `λ_min`.
3. If `n_obs <= n_assets`, raise `InsufficientDataError` rather than repair. A sample
   covariance matrix from fewer observations than assets is rank-deficient by
   construction; shrinkage can hide it, and hiding it is how a user gets confident
   nonsense.

## Lookahead prevention

The single most damaging bug class in a backtest, so it is structural, not careful:

`core/backtest.py` never sees the full return frame. `walk_forward()` slices with
`returns.loc[:t].iloc[:-1]` at the top of each rebalance and passes **only that
slice** into the optimizer callable. The optimizer has no way to reach forward
because it has no reference to reach with.

The test that proves it perturbs all data at and after `t` by a large factor and
asserts the weights at `t` are bit-identical.

## Result types

Frozen dataclasses, not dicts — they serialize cleanly to JSON and typecheck.

```python
@dataclass(frozen=True)
class Portfolio:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe: float
    estimators: Estimators      # provenance: which mu/sigma methods produced this

@dataclass(frozen=True)
class RiskPanel:
    annualized_return: float; volatility: float
    sharpe: float; sortino: float; calmar: float
    max_drawdown: float; drawdown_peak: date; drawdown_trough: date
    drawdown_recovery: date | None
    var_95: float; cvar_95: float; skew: float; kurtosis: float

@dataclass(frozen=True)
class BacktestResult:
    strategy: RiskPanel; benchmark: RiskPanel
    equity_curve: pd.Series; weights_history: pd.DataFrame
    total_turnover: float; total_cost: float
    oos_start: date; oos_end: date
```

`Portfolio.estimators` is what lets the CLI print "Ledoit-Wolf shrinkage, geometric
mean historical returns" in the header. A number whose provenance is not on screen
invites misreading.

## Conventions, settled once

`core/conventions.py`:

```python
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52, "monthly": 12,
                    "quarterly": 4, "annual": 1}
```

No literal `252` appears anywhere else in the codebase — a grep for it in a review
is a finding. Simple returns are used everywhere except where log returns are
explicitly required (they are not additive across assets, so portfolio aggregation
uses simple returns; this is noted in the docstring of every function that touches
the distinction).

## Porting from `legacy_code/`

`legacy_code/Financial Portfolio Optimization.R` — this repository's own prior
R implementation — is the reference. The plan:

1. Run the R script on a fixed ticker set and date range; capture weights and
   frontier points.
2. Check those outputs into `tests/fixtures/r_reference/`.
3. Assert the Python port matches within `1e-4`.

This turns prior work into a regression test rather than a rewrite that might
quietly differ.

## Alternatives considered

| Choice | Rejected alternative | Why |
|---|---|---|
| Hand-rolled on `scipy` | `PyPortfolioOpt` | It is a good library, but it is the product here. The exercise is owning the math; a thin wrapper over someone else's optimizer is a different (smaller) tool |
| SLSQP default, `cvxpy` extra | `cvxpy` base | Solver stack weight in an install that does not need it |
| Ledoit-Wolf default | Sample covariance default | The default should be the one that does not blow up; sample covariance is a deliberate choice, not an accident |
| 10 bps default cost | 0 bps default | A zero-cost default systematically flatters high-turnover strategies |
| Geometric annualization default | Arithmetic | It is what an investor actually earns |
