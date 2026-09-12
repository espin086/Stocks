# 0010 — Tasks

Each task names the test that proves it.

## Wave A — core

- [x] **A1. `core/fx.py`** — decomposition, compounding, aggregation, currency risk,
      hedged returns and hedge cost.
      → `tests/core/test_fx.py`
- [x] **A2. `core/ppp.py`** — absolute vs relative PPP, real rate, valuation gaps in
      words, goal restatement, vintage staleness, ISO3 table, framing constants.
      → `tests/core/test_ppp.py`

## Wave B — data

- [x] **B1. `PppProvider`** — World Bank (default, keyless) and OECD parsers on recorded
      shapes, vintage through the cache, missing coverage named; BIS REER provider.
      → `tests/data/test_ppp_provider.py`
- [x] **B2. Settings and checks** — `SOBRES_PPP_PROVIDER`, `SOBRES_PPP_STALE_YEARS`;
      worldbank, oecd and bis in the provider registry (doctor reachability checks).
      → `tests/cli/test_doctor.py::test_every_setting_and_provider_has_a_check`
- [x] **B3. Fixtures** — synthesized World Bank JSON, OECD and BIS SDMX-CSV, two more FRED
      series; `synthesize_fixtures.py` and `record_fixtures.py` updated.

## Wave C — CLI

- [x] **C1. `sobres fx rates|convert|attribution|hedge`** — carry-forward stated, cross term
      shown, risk decomposition with correlations and exposure, hedge caveat, missing leg loud.
      → `tests/cli/test_fx.py`
- [x] **C2. `--hedged` on the optimizer** — hedged series, labelled with the assumption;
      `--base` required for mixed currencies (0001, re-asserted).
      → `tests/cli/test_fx.py::test_base_currency_is_explicit_and_hedged_optimization_is_labelled`
- [x] **C3. `sobres ppp compare|relative|reer|adjust-goal`** — framing on every output,
      direction in words, vintage and staleness, OECD alternative, saved goals restated.
      → `tests/cli/test_ppp.py`
- [x] **C4. `sobres plan … --save-goal`** — stores the target for `ppp adjust-goal`.
      → `tests/cli/test_ppp.py::test_adjust_goal_reads_a_goal_saved_by_plan`
- [x] **C5. Docs** — README, CHANGELOG, design.

## Verification note

World Bank, OECD, BIS, ECB and FRED fixtures are synthesized in the publishers'
documented payload shapes (this environment has no route to them), so the
suite proves the parsers, the arithmetic and the framing, not any real
valuation gap. `scripts/record_fixtures.py --only documents` records live.
