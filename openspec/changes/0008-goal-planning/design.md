# 0008 — Design

## One identity, four inverses

Every goal is the future value of a balance plus a level contribution at a
periodic rate. `core/goals.py::solve` inverts it for whichever of target,
periods, contribution or rate is missing: target and contribution in closed
form, periods by the log formula, rate by bisection (the identity is monotone in
the rate). `--timing begin` (annuity-due) multiplies the contribution stream by
`1 + r`. The named goals — house, car, education, retirement — only decide what
the target and the horizon are.

## Real by default, Fisher, never subtraction

`--real` is the default: the `--return` you give is nominal and is deflated by
inflation with `(1 + n)/(1 + i) − 1`, and every amount is labelled
`(today's dollars)`. `--nominal` skips the conversion and labels `(nominal)`.
Inflation is the trailing 10-year CPI CAGR from FRED `CPIAUCSL` when a key is
configured; otherwise 2.5% with a stderr note. The rate and its source are in
every output's header.

## Simulation behind every answer

`core/simulate.py` runs `--simulate` paths (10,000 by default; `0` disables)
of monthly returns applied to the same balance and contribution schedule, and
reports the success probability and the 10/25/50/75/90th percentile terminal
balances. Monte Carlo draws i.i.d. normal periodic returns from the annual
mean and `--vol` (15% by default, stated); `--method bootstrap` resamples
contiguous blocks (12 months by default) of an actual monthly return history
built from `--history <tickers>`, which preserves autocorrelation and therefore
sequence-of-returns risk, and the history window is stated. The seed is printed
even when auto-generated. The deterministic figures are labelled the median
case, not the answer.

## FIRE parity

`savings_rate`, `fi_number` and `project` are ported verbatim from
`espin086/fire-calculator` (MIT, same author) and asserted against its
`testdata/golden.json`, copied to `tests/fixtures/fire_calculator/`, at the
golden file's own tolerance. Coast FI discounts the FI number at the return
over the years to the target age.

## Not modeled, and said so

Taxes: every input is after-tax and every output says so. Social Security,
mortgages, account types: out of scope per the proposal.

## Rejected

| Choice | Rejected | Why |
|---|---|---|
| Bisection for the rate | Newton | Monotone identity; bisection cannot diverge and needs no derivative |
| Trailing 10-year CPI | Latest year-over-year CPI | One year is noise; the target is decades away |
| Normal periodic returns | Lognormal | Simpler to state; clipped at −99.9% per period; the bootstrap is the realistic mode |
| `--history` tickers for the bootstrap | A built-in index series | No keyless point-in-time index history exists; the user names what they hold |
