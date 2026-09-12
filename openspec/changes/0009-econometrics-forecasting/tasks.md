# 0009 — Tasks

Each task names the test that proves it.

## Wave A — core

- [x] **A1. `core/timeseries.py`** — ADF/KPSS with disagreement stated, ACF/PACF with
      bounds, differencing to stationarity (refuse past d=2), ARIMA grid selection
      with candidates, forecasts with 80%/95% intervals, Ljung-Box.
      → `tests/core/test_timeseries.py`
- [x] **A2. Volatility** — GARCH(1,1), EGARCH, EWMA via `arch` with simulated bands,
      annualized by the conventions table, seed reported.
      → `tests/core/test_timeseries.py::test_garch_fit_recovers_persistence_and_offers_egarch_and_ewma`
- [x] **A3. GARCH covariance in the estimator registry** — `covariance(..., method="garch")`.
      → `tests/core/test_timeseries.py::test_feeds_the_optimizer_through_the_estimator_registry`
- [x] **A4. `core/regression.py`** — OLS with hac/hc0–hc3/none, VIF (>10 flagged), R²,
      adjusted R², F, Durbin-Watson, Breusch-Pagan.
      → `tests/core/test_regression.py`
- [x] **A5. Dependency gating** — exit 3 with the install hint, no traceback.
      → `tests/core/test_timeseries.py::test_missing_extra_is_an_exit_3_with_the_install_hint`,
      `tests/cli/test_econ.py::test_missing_extra_exits_3_with_the_install_hint`

## Wave B — CLI

- [x] **B1. `sobres econ diagnose|forecast|volatility|regress`** — symbol resolution,
      transforms stated, every header line the spec asks for.
      → `tests/cli/test_econ.py`
- [x] **B2. Surfaces** — registry group, API routes, UI views; `arch` in the econ extra and
      in doctor's extras table.
      → `tests/api/test_parity.py`, `tests/invariants/test_every_command.py`
- [x] **B3. Docs** — README, CHANGELOG, design.

## Verification note

FRED and Yahoo fixtures are synthesized random walks, so the offline suite
proves the statistics on constructed series with known properties and the
plumbing on the fixtures; no claim is made about any real series.
