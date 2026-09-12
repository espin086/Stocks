# 0002 — Tasks

Depends on 0001. Estimates are focused hours.

## Wave A — return and risk primitives (parallel-safe)

- [ ] **A1. Conventions** (0.5h)
      `core/conventions.py`: `PERIODS_PER_YEAR`, frequency inference from an index.
      → `tests/core/test_conventions.py::test_frequency_inference`
- [ ] **A2. Returns** (2h)
      `core/returns.py`: simple, log, cumulative wealth, annualized (geometric +
      arithmetic), explicit NaN policy.
      → `tests/core/test_returns.py::test_geometric_matches_hand_computed`,
        `::test_annualization_uses_convention_table`,
        `::test_nan_policy_has_no_default`
- [ ] **A3. Risk panel** (3h)
      `core/risk.py`: vol, Sharpe, Sortino, Calmar, max drawdown (+peak/trough/
      recovery dates), VaR/CVaR, skew, kurtosis, beta, correlation matrix.
      → `tests/core/test_risk.py` — every metric against a hand-computed 10-row
        fixture; `::test_max_drawdown_identifies_recovery_date`;
        `::test_beta_requires_30_overlapping_observations`

## Wave B — estimation (A2 first)

- [ ] **B1. Expected returns** (2h)
      `core/moments.py`: `mean_historical`, `ewma`, `capm`.
      → `tests/core/test_moments.py::test_capm_uses_benchmark_and_risk_free`
- [ ] **B2. Covariance** (3h)
      `sample`, `ledoit_wolf`, `ewma`, `semicovariance`; shrinkage intensity in
      `attrs`; `n_obs <= n_assets` → `InsufficientDataError`.
      → `::test_ledoit_wolf_is_default`,
        `::test_singular_case_raises_with_both_counts`
- [ ] **B3. PSD conditioning** (2h)
      Symmetrize, eigenvalue clip, trace-preserving rescale, stderr warning.
      → `tests/core/test_psd.py::test_repairs_non_psd_and_warns`,
        `::test_repaired_matrix_is_psd`,
        `::test_already_psd_matrix_is_unchanged`

## Wave C — optimizer (B first) — critical path

- [ ] **C1. Constraint model** (1.5h)
      `Constraints` dataclass: bounds, `max_weight`, `allow_short`, groups.
      Infeasibility detected before the solver runs (`max_weight * n < 1`).
      → `tests/core/test_constraints.py::test_infeasible_max_weight_raises_usage`
- [ ] **C2. `min_variance` + `equal_weight`** (2h)
      SLSQP scaffold, weight-sum equality, box bounds.
      → `::test_min_variance_matches_analytic_two_asset`
- [ ] **C3. `max_sharpe`** (3h)
      Multi-start (equal-weight, min-variance, seeded random); best feasible wins.
      → `::test_max_sharpe_matches_closed_form_tangency`,
        `::test_deterministic_across_runs`
- [ ] **C4. `target_return` / `target_risk`** (2h)
      → `::test_target_return_above_attainable_raises_with_max`
- [ ] **C5. `risk_parity`** (2h)
      → `::test_risk_contributions_equal_within_tolerance`
- [ ] **C6. Solver failure + concentration warning** (1h)
      → `::test_nonconvergence_raises_optimization_error`,
        `::test_concentration_warning_above_50pct`
- [ ] **C7. Efficient frontier** (2.5h)
      N points from min-variance return to max attainable; flag min-var and
      max-Sharpe points.
      → `::test_volatility_non_decreasing_in_return`,
        `::test_named_points_flagged`

## Wave D — backtest (C first)

- [ ] **D1. Walk-forward engine** (4h)
      Rebalance schedule; the slicing discipline from `design.md`; weight drift
      between rebalances.
      → `tests/core/test_backtest.py::test_no_lookahead_under_future_perturbation`
        ← *the most important test in this change*
      → `::test_weights_drift_between_rebalances`
- [ ] **D2. Transaction costs** (1.5h)
      `turnover = 0.5 * Σ|w_new - w_drifted|`; 10 bps default.
      → `::test_turnover_formula`, `::test_default_cost_is_10bps`
- [ ] **D3. Benchmark + result assembly** (2h)
      Equal-weight benchmark over the identical window; `BacktestResult`.
      → `::test_benchmark_uses_same_window`
- [ ] **D4. Short-lookback handling** (1h)
      → `::test_start_shifts_to_first_viable_date_and_reports`

## Wave E — CLI (C, D first)

- [ ] **E1. `qf optimize markowitz`** (2h) — estimator provenance in the header.
      → `tests/cli/test_optimize.py::test_header_names_estimators`
- [ ] **E2. `qf optimize frontier`** (1.5h)
      → `::test_csv_columns_are_ret_vol_sharpe_then_tickers`
- [ ] **E3. `qf optimize backtest`** (2h) — side-by-side panels, OOS window, costs.
      → `::test_output_states_oos_window_and_costs`
- [ ] **E4. `qf optimize risk`** (1h) — fixed weights, full panel.
      → `::test_weights_must_match_ticker_count_and_sum_to_one`

## Wave F — validation and release

- [ ] **F1. R reference fixtures** (2h)
      Run `legacy_code/Financial Portfolio Optimization.R` on a fixed universe; check
      outputs into `tests/fixtures/r_reference/`.
      → `tests/test_r_parity.py::test_weights_match_within_1e-4`
- [ ] **F2. Textbook validation** (2h)
      A published two- and three-asset example with known answers, end to end.
      → `tests/test_textbook_cases.py`
- [ ] **F3. Docs: "Why your backtest looks too good"** (2h)
      Plain-language page on estimation error, in-sample vs. walk-forward, and how
      to read the gap. Linked from `qf optimize backtest` output.
- [ ] **F4. README + `v1.0.0`** (2h) — worked example with real output; tag; PyPI.

**Total: ~48h.** Critical path: B2 → B3 → C2 → C3 → C7 → D1 → E3.

## Definition of done

- [ ] All four `qf optimize` subcommands work end to end on live data
- [ ] The no-lookahead test passes (D1)
- [ ] Weights match the R reference within `1e-4` (F1)
- [ ] Max-Sharpe matches the closed-form tangency portfolio within `1e-6` (C3)
- [ ] `mypy --strict` clean; `pytest -m "not network"` green offline
- [ ] Every scenario in the spec delta has a test referencing it
- [ ] `v1.0.0` tagged and published
