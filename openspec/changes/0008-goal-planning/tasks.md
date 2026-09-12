# 0008 — Tasks

Each task names the test that proves it.

## Wave A — core

- [x] **A1. `core/goals.py`** — future value, the four inverses, `solve`, timing,
      Fisher, periodic rates, month arithmetic.
      → `tests/core/test_goals.py`
- [x] **A2. FIRE port** — `savings_rate`, `fi_number`, `project`, `coast_fi_balance`;
      parity with the fire-calculator golden fixture.
      → `tests/core/test_goals.py::test_parity_project` and siblings
- [x] **A3. Named goals** — house (price growth), car (resale), education (5% cost
      inflation).
      → `tests/core/test_goals.py`
- [x] **A4. `core/simulate.py`** — Monte Carlo and moving-block bootstrap, percentiles,
      success probability, seeds.
      → `tests/core/test_simulate.py`

## Wave B — CLI

- [x] **B1. `sobres plan retire|house|car|education|goal`** — real/nominal flags and
      labels, CPI inflation with fallback, simulation by default, seed printed,
      bootstrap with a stated window, the tax note and the disclaimer.
      → `tests/cli/test_plan.py`
- [x] **B2. Surfaces** — registry group, API routes, UI views.
      → `tests/api/test_parity.py`, `tests/invariants/test_every_command.py`
- [x] **B3. Docs** — README, CHANGELOG, design.

## Verification note

The CPI fixture is synthesized (see `tests/fixtures/README.md`), so the keyed
inflation path proves the plumbing and the CAGR arithmetic, not a real rate.
