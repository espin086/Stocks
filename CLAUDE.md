# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Read first

`openspec/project.md` — architecture, package layout, command surface, and the
milestone plan. Then the relevant change under `openspec/changes/`.

## This project is spec-driven

Behavior changes start with an OpenSpec change, not with code:

```
openspec/changes/<NNNN>-<slug>/
├── proposal.md    # outcome, why, what changes, non-goals, risks
├── design.md      # how, and what was rejected
├── tasks.md       # ~2h chunks, each naming the test that proves it
└── specs/<capability>/spec.md   # ADDED/MODIFIED/REMOVED Requirements + Scenarios
```

**The spec delta is the contract.** Every `#### Scenario:` gets a test. When
implementing, work the change's `tasks.md` in wave order and check boxes as you go.

Do not implement a behavior that has no scenario. Add the scenario first.

## The one architectural rule

```
registry.py  One declaration per command (0001). CLI, API (0004) and UI derive from it.
cli/    Typer adapters — argv → data → core → render.    NO business logic.
api/    FastAPI adapters (0004).                          NO business logic.
        ^ logs and spans are emitted at this layer
core/   Pure, I/O-free math over frames and dataclasses.  NO network, NO disk,
                                                          NO logging, NO tracing.
data/   Providers + storage port → pandas objects.        NO math.
        storage/adapters/ is the only place a DB driver is imported.
```

Anything swappable sits behind a `Protocol` in our own namespace — data
providers, the storage backend, the solver — and its library types never appear
in a signature outside its adapter. Where more than one implementation is
plausible, a shared conformance suite defines the contract.

If you find yourself computing something in `cli/` or `api/`, it belongs in
`core/`. If you find yourself calling a provider or opening a connection from
`core/`, pass the frame in instead.

**Never write a Typer command by hand.** Every command is a registry
declaration — a pydantic parameter model, a typed result, a handler — and the
CLI is generated from it. From 0004 the HTTP route and the UI form come from
the same declaration, and a parity test fails the build if one is missing.
Cross-field rules (weights match tickers, `--portfolio` excludes `--tickers`)
are model validators, never handler code.

**Tests are organized by what they prove** — `tests/core/` (known answers),
`tests/data/` (recorded fixtures, conformance), `tests/cli/`,
`tests/architecture/` (import and literal rules), `tests/invariants/` (every
registered command), `tests/network/` (marked). A math test never asserts
against a value the function itself produced. Architecture rules in this file
are enforced by `tests/architecture/`, not by review.

**Missing data has no default.** Callers choose `drop`, `ffill`, or `raise`.
Only provider gaps are fillable; market closures, pre-listing, and delisting
are not. Alignment records what it dropped. Survivorship bias is stated in
output, never silently accepted or claimed to be corrected.

## Storage is a port, not a database

Persistence goes through repository protocols in `data/storage/base.py`. The
SQLite adapter is one implementation; `QUANTFOLIO_DB_URL` selects it.

- **Never import a database driver outside `data/storage/adapters/`** — not
  `sqlite3`, not `sqlalchemy`. A test enforces this.
- **Phrase ports in domain terms** (observations, date ranges, portfolios), never
  as SQL execution. A SQL-shaped port makes switching a rewrite.
- Stay inside the SQLite / PostgreSQL / DuckDB intersection: portable column
  types, application-generated ids, explicit UTC timestamps, JSON as text. No
  backend-specific SQL in shared code — if something cannot be expressed
  portably, it becomes a named adapter method every adapter implements.
- **Add every new repository to the shared conformance suite.** That suite is
  what makes a second backend a new file rather than a project.
- SQLAlchemy Core sits below the protocols as the dialect layer. Not the ORM, and
  never visible to a call site.
- Migrations are forward-only and never edited after release; a correction is a
  new migration. One migration set, applied by the adapter, no branching on
  backend.
- One SQLite file holding everything is a property of the *default backend*, not
  of the system. Don't add a second store (a cache directory, a JSON sidecar, a
  pickle) — that would break it for no gain.
- `qf cache clear` removes cached observations only. It must never touch
  user-authored rows.
- API keys and database URLs are secrets: config file at `0600`, never in the
  database, always redacted in output.

## Logging and tracing

structlog always on (default WARNING); OpenTelemetry behind the `otel` extra,
no-op unless `OTEL_*` is set.

- **Logs go to stderr. Always.** stdout carries results only — `--format json`
  must stay a single parseable document at any log level.
- **Never import logging or tracing inside `core/`.** Instrumentation lives in
  the adapters, which observe the calls they make. A test enforces this.
- For a computation long enough to need intermediate visibility, add an
  **optional progress callback** to the core function and let the caller decide
  whether it becomes a log line, a span event, or a job update. With no callback,
  nothing changes.
- **Redact at the formatter, not at call sites.** Keys matching key/token/secret/
  password/authorization, and credentials inside URLs.
- An assumption that changes a number — fallback risk-free rate, repaired
  covariance matrix, shifted backtest start — logs at **WARNING**, not INFO.
  These are the lines that explain a surprising result.
- Observability may never change behavior: stdout is byte-identical across log
  levels and with tracing on or off, and that is a test.
- An unreachable exporter warns once and never fails a command.

## Currency

Treated like timezone: carried on every monetary series, converted once,
explicitly, never mixed silently.

- **Never multiply or divide by a rate at a call site.** Call
  `convert(amount, from_ccy, to_ccy, on=date)`. Direction lives in
  `CurrencyPair(base, quote)` — units of *quote* per one unit of *base*.
- **Converting returns is `(1 + r_local) * (1 + r_fx) - 1`**, never
  `r_local + r_fx`. The dropped cross term is the standard bug.
- Normalize sub-unit quotations (GBp, ZAc, ILA) in the data layer. This error is
  silent and off by 100×.
- Mixed currencies with no target raise `UsageError`. Never guess, never default
  to USD, never infer from an exchange suffix.
- Convert returns **before** estimating moments. Covariance does not transform
  by converting the statistic afterwards.
- A single-currency run must fetch no rates and match a no-conversion build.
- **Never forecast an exchange rate.** PPP is a valuation gap, not a signal, a
  target, or a convergence path — and every PPP output says so.

## Conventions

- **Python 3.11+**, `mypy --strict` clean, `ruff` for lint and format.
- **Typer + Rich.** Every data-emitting command supports `--format table|json|csv`.
- **Never a bare `252`.** Annualization constants come from
  `core/conventions.py::PERIODS_PER_YEAR`. A literal periods-per-year in a diff is a
  review finding.
- **No network in tests by default.** Provider payloads are recorded fixtures under
  `tests/fixtures/`. Live tests carry `@pytest.mark.network` and are excluded from CI.
- **Math is tested against known answers** — hand-computed fixtures, textbook
  examples, closed-form solutions — never against whatever the code happened to
  output.
- **Errors carry exit codes.** `1` internal, `2` usage, `3` config/credential,
  `4` provider, `5` insufficient data. Never surface a traceback for an anticipated
  failure; `--debug` is the escape hatch.
- **Docstrings cite the math.** Name the formula and a source.

## Non-negotiables

1. **Not investment advice.** Report-style table output carries the disclaimer
   footer. It is omitted from `json`/`csv` so it cannot corrupt parsing.
2. **Works with no API key.** yfinance and Ken French are keyless. A missing key
   produces an actionable exit-3 message, never a traceback.
3. **Reproducible.** Same inputs + same cache + same seed → identical output. Print
   the seed even when auto-generated.
4. **Honest by default.** Shrinkage on, transaction costs on, prediction intervals
   mandatory, alpha reported with its t-statistic. Defaults must not flatter results.
   This carries into the UI (0004) and the landing page (0006): in-sample results
   are labelled as such, and the page may not claim an unshipped capability.

## Reuse before rebuilding

Prior work in JJ's repos that these milestones draw on — check it before writing
new code (see the table in `openspec/project.md` for what to lift from each):
`fire-calculator`, `CompountInterestAPI`, `NewsWaveMetrics`, `jjutils`, `Econometrics`.

This repository's own `legacy_code/` is the first place to look: it holds the R
linear-programming portfolio optimizer and the `yfinance` puller that `quantfolio`
supersedes. `legacy_code/Financial Portfolio Optimization.R` is the reference
implementation for `core/optimize.py` and the source of its regression fixtures.

## Releasing

Releases are **version-gated pushes to `main`** — bump `__version__` in
`src/quantfolio/__about__.py`, add a `CHANGELOG.md` section for it, merge. The
pipeline re-runs the full CI gate on that commit and publishes to PyPI. A push
to `main` that does not change the version publishes nothing.

- The release workflow **calls** `ci.yml` rather than restating its steps. When
  adding a check, add it to `ci.yml` and the release inherits it.
- Never add a PyPI token to this repo. Publishing is OIDC Trusted Publishing.
- Never make `pip-audit` soft-fail. An unfixable advisory gets a named
  `--ignore-vuln` with a written reason — see `docs/RELEASING.md`.
- The distribution is `quantfolio-cli`; the import package and CLI stay
  `quantfolio` / `qf`. `tests/test_packaging.py` pins this.

## Commands

```bash
pip install -e ".[dev]"
pre-commit install                         # same checks CI runs
pytest -m "not network"                    # full suite, offline
pytest tests/core/test_optimize.py -k sharpe
ruff check . && ruff format --check . && mypy
python .github/scripts/check_release.py    # what would the next merge publish?
```
