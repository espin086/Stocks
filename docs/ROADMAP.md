# Roadmap

Each milestone is an OpenSpec change under `openspec/changes/`. The proposal and
spec delta for all five are written; `design.md` and `tasks.md` are written in full
for 0001 and 0002, and are deliberately deferred for 0003–0005 until the change
before them lands — planning that far ahead in implementation detail goes stale
before it is used.

| # | Milestone | Depends on | Est. | Planning depth |
|---|---|---|---|---|
| 0000 | Release engineering: CI gate + PyPI pipeline | — | done | proposal + spec + tasks |
| 0001 | Foundation: data layer + CLI shell | — | ~27h | proposal + specs + design + tasks |
| 0002 | **Portfolio optimization → v1.0.0** | 0001 | ~48h | proposal + spec + design + tasks |
| 0003 | Equity & factor analysis → v1.1 | 0001, 0002 | ~35h est. | proposal + spec |
| 0004 | Goal planning → v1.2 | 0001, 0002 | ~30h est. | proposal + spec |
| 0005 | Econometrics & forecasting → v1.3 | 0001–0003 | ~40h est. | proposal + spec |

**v1.0.0 = 0001 + 0002 (~75h).**

## Sequencing rationale

**0001 first** because every later milestone consumes prices, factors, or macro
series. Building them per-feature guarantees four copies of the same date-alignment
bug.

**0002 as v1** because portfolio optimization is the highest-value slice and the one
that forces the hardest shared foundations — returns, covariance estimation,
constrained optimization, risk metrics. 0003 and 0004 both reuse that machinery. Any
other starting point would build a thinner base.

**0003 before 0004** because the Ken French data lands in 0001 and the regression
machinery feeds back into 0002 as a candidate expected-return estimator, compounding
sooner.

**0005 last** because GARCH-based covariance is an *improvement* to the optimizer,
and improving an optimizer that is not yet trusted is premature.

## Explicitly out of scope for the whole tool

- Live trading, broker connections, order generation
- Tax modeling (marginal rates, Roth ladders, RMDs, wash sales, lot tracking)
- Intraday or tick data
- Machine-learning price prediction
- Causal inference (that work lives in `espin086/Econometrics`)
- Real-estate cash-flow analysis (that lives in `espin086/Real_Estate`)

## Post-v1.3 candidates

Not planned, not promised — recorded so the architecture keeps room for them:

- Black-Litterman with a workable view-specification UX
- CVaR and robust optimization objectives (the `cvxpy` extra exists for this)
- Factor-tilted portfolio construction (0003 exposures → 0002 optimizer)
- A paid provider adapter (Polygon / Tiingo / FMP) behind the existing protocols
- A FastAPI surface over the same `core/` (the layering already permits it)
- Portfolio import from a broker CSV export
