---
change: 0004-goal-planning
milestone: v1.2
depends_on: [0001-foundation-data-and-cli, 0002-portfolio-optimization]
status: proposed
planning_depth: proposal + spec delta (design and tasks written when 0003 lands)
---

# 0004 — Goal planning

## Outcome

```bash
qf plan retire --income 200000 --expenses 90000 --portfolio 400000 --return 0.07
qf plan house --price 950000 --down-pct 0.20 --by 2029-06-01 --monthly 3000
qf plan car --price 45000 --by 2027-01-01 --current 5000
qf plan goal --target 250000 --by 2032-01-01 --monthly 1500 --simulate 10000
```

Deterministic answers to "when / how much," and a Monte Carlo distribution behind
each so the answer comes with a probability rather than a false promise.

## Why

This is the slice closest to how JJ actually uses these numbers — the
`Areas/personal-finance-fire/` analyses are exactly these calculations, currently
done by hand per scenario. It also has the most existing code to reuse:
`espin086/fire-calculator`'s `core.py` (`savings_rate`, `fi_number`, `project`) is a
direct seed, and `espin086/CompountInterestAPI` already owns the compounding math.

It closes the loop with 0002: the optimizer says what to hold, the planner says
whether holding it gets you there.

## What changes

- **New capability `goal-planning`**: `core/goals.py` (generic funding solver plus
  retirement, house, car, education specializations) and `core/simulate.py`
  (Monte Carlo and historical-bootstrap engines).
- **New CLI group `qf plan`**: `retire`, `house`, `car`, `education`, `goal`.
- Port `fire-calculator`'s core functions, with its tests carried over as regression
  fixtures so the ported math is provably identical.

## Non-goals

- **No tax modeling.** Marginal rates, Roth conversion ladders, RMDs, and state tax
  are each their own project. Inputs are after-tax; the spec says so at the edge.
- No Social Security benefit estimation. Users supply an expected benefit.
- No mortgage amortization, PMI, or closing-cost modeling in v1.2 — `house` solves
  the down-payment savings path only.
- No account-type modeling (401k vs. Roth vs. taxable).
- No real-estate cash-flow analysis. That is `espin086/Real_Estate`'s job.

## Risks

| Risk | Mitigation |
|---|---|
| A single-point projection reads as a promise | Every `plan` command reports a success probability from simulation, not just the deterministic path; the deterministic answer is labeled as the 50th-percentile case |
| Sequence-of-returns risk is invisible in a CAGR model | Historical bootstrap mode resamples actual return sequences, so bad-early-years paths appear in the distribution |
| Real vs. nominal confusion — the most common error in retirement math | One explicit `--real` / `--nominal` flag with no ambiguous default; every output labels which it is; inflation sourced from FRED `CPIAUCSL` |
| The 4% rule applied as universal truth | The withdrawal rate is a parameter, defaulting to 4%, with the output stating the assumption and its origin (Trinity study, 30-year US history) |
