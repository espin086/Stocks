# Roadmap

Each milestone is an OpenSpec change under `openspec/changes/`. The proposal and
spec delta for all five are written; `design.md` and `tasks.md` are written in full
for 0001 and 0002, and are deliberately deferred for 0003–0005 until the change
before them lands — planning that far ahead in implementation detail goes stale
before it is used.

| # | Milestone | Depends on | Est. | Planning depth |
|---|---|---|---|---|
| 0000 | Release engineering: CI gate + PyPI pipeline | — | done | proposal + spec + tasks |
| 0001 | Foundation: storage port, data layer, currency, observability, CLI shell | 0000 | ~51h | proposal + 5 specs + design + tasks |
| 0002 | **Portfolio optimization → v1.0.0** | 0001 | ~48h | proposal + spec + design + tasks |
| 0003 | Local persistence (SQLite) → v1.1 | 0002 | ~25h est. | proposal + spec |
| 0004 | Web UI (FastAPI + React) → v1.2 | 0003 | ~70h est. | proposal + specs |
| 0005 | Docker distribution → v1.2 | 0004 | ~25h est. | proposal + spec |
| 0006 | Landing page (GitHub Pages) → v1.2 | 0005 | ~30h est. | proposal + spec |
| 0007 | Equity & factor analysis → v1.3 | 0002 | ~35h est. | proposal + spec |
| 0008 | Goal planning → v1.4 | 0002 | ~30h est. | proposal + spec |
| 0009 | Econometrics & forecasting → v1.5 | 0007 | ~40h est. | proposal + spec |
| 0010 | Exchange rates & PPP → v1.6 | 0002, 0008 | ~35h est. | proposal + 2 specs |

**v1.0.0 = 0001 + 0002 (~99h).** **v1.2, the deployable product = 0003–0006
(~150h more).**

## Sequencing rationale

**0001 first** because every later milestone consumes prices, factors, or macro
series. Building them per-feature guarantees four copies of the same date-alignment
bug.

**0002 as v1** because portfolio optimization is the highest-value slice and the one
that forces the hardest shared foundations — returns, covariance estimation,
constrained optimization, risk metrics. 0003 and 0004 both reuse that machinery. Any
other starting point would build a thinner base.

**0003–0006 before the remaining analytics** because a tool nobody can run is not
worth adding features to. Persistence, a UI, a container, and a page that explains
it turn v1.0.0 from a working optimizer into something demoable and deployable.
0007–0009 then add analytics to a UI that already exists — which is cheap, because
the command registry generates the UI — rather than retrofitting a UI onto five
milestones of accumulated commands, which is not.

**0003 before 0004** because the UI needs saved state to show and a job table to
report progress from. Building it on ad-hoc files would mean two storage stories to
reconcile later.

**0005 before 0006** because a landing page for something nobody can install yet is
a liability. The page's install commands are generated from the repository, so they
cannot advertise what does not exist.

**0007 before 0008** because the Ken French data lands in 0001 and the regression
machinery feeds back into 0002 as a candidate expected-return estimator, compounding
sooner.

**0009 before 0010** because GARCH-based covariance is an *improvement* to the
optimizer, and improving an optimizer that is not yet trusted is premature.

**0010 last** because it is the only milestone that makes every earlier one
international, and adding breadth before the domestic case is trustworthy is the
wrong order. Its foundation is not deferred, though: the currency *model* lands in
0001, since returns computed without a currency concept have to be recomputed when
one arrives — which by 0002 is every risk and optimization function.

## Explicitly out of scope for the whole tool

- Multi-user accounts, per-user data isolation, or a shared hosted service
- Kubernetes manifests, Helm charts, or multi-replica deployment (one SQLite file
  means one writer)
- A second storage backend as part of the planned milestones. The port, registry
  and conformance suite exist from 0001 so PostgreSQL or DuckDB is a new adapter
  file and a fixture-list entry, but none is built on speculation
- A metrics pipeline; logs and traces only
- Exchange-rate forecasting, currency trading, carry strategies, or FX timing.
  Rates are near a random walk at these horizons and PPP has no short-run
  predictive power; a `qf fx forecast` would be the most misleading thing here
- Derivatives pricing. Hedged returns come from interest-rate differentials under
  covered interest parity, not from a forward or options model
- Tax, residency, visa, or healthcare modeling for relocation
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
- A PostgreSQL or DuckDB storage adapter, if a deployment ever needs one
- Portfolio import from a broker CSV export
- Scheduled refresh of saved portfolios, as a first-class feature rather than a
  cron job calling the CLI
