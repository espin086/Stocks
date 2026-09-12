# quantfolio — project context

## What this is

A one-stop **CLI for equity analysis**: pull market and macro data, optimize a
portfolio, analyze an individual stock with factor models, run econometric
forecasts, and plan real-world money goals (retirement, house, car, college).

The CLI is the first surface. The library underneath it is designed so a web API
or notebook can sit on top later without moving any logic.

## The one architectural rule

```
              ┌──────────────────────────────────────────────┐
              │            registry.py  (0004)               │  one declaration
              │   every command: params, types, defaults      │  per capability
              └───────┬──────────────────┬───────────────────┘
                      │                  │
              ┌───────▼──────────────────▼───────────────────┐
  adapters →  │  cli/ (Typer)   api/ (FastAPI)   frontend/   │  no business logic
              │      ↑ logs and spans are emitted here        │
              ├──────────────────────────────────────────────┤
  math     →  │  core/  pure, I/O-free, deterministic        │  no network, no disk,
              │         optional progress callback            │  no logging
              ├──────────────────────────────────────────────┤
  I/O      →  │  data/  providers ─┐                          │  no math
              │         storage/base.py  ← port               │
              │         storage/adapters/  ← only place a     │
              │              database driver is imported      │
              └──────────────────────────────────────────────┘
```

- `core/**` — pure functions and frozen dataclasses. Given the same inputs, always
  the same outputs. No `requests`, no `open()`, no `datetime.now()` reaching in
  unannounced (clock is injected).
- `data/**` — every byte that crosses the network. Returns plain `pandas` objects
  with a documented shape. Caches to disk. Knows nothing about optimization.
- `cli/**`, `api/**`, `frontend/**` — parse, call `core`, format. Three renderings
  of one set of capabilities, all generated from `registry.py` (0004) so a
  parameter added in one place appears in all three. A parity test fails the build
  if any registered command lacks an API route or a UI view.

This rule is what makes the tool testable: the math is tested against fixtures with
no network, and the providers are tested against recorded payloads. It is also what
makes the UI cheap — it is a third adapter, not a second implementation.

## Package layout (target)

```
src/quantfolio/
├── __about__.py
├── config.py               # settings: cache dir, API keys from env, defaults
├── core/
│   ├── returns.py          # price → returns, annualization, compounding
│   ├── risk.py             # vol, downside dev, VaR/CVaR, max drawdown, beta
│   ├── moments.py          # expected returns + covariance estimators
│   ├── optimize.py         # Markowitz MVO, efficient frontier, risk parity
│   ├── factors.py          # CAPM, Fama-French 3/5, momentum regressions
│   ├── timeseries.py       # ARIMA/GARCH wrappers, stationarity tests
│   ├── goals.py            # retirement / house / car / education solvers
│   ├── simulate.py         # Monte Carlo + bootstrap engines
│   └── backtest.py         # walk-forward rebalancing evaluation
├── registry.py             # 0004: every command declared once
├── observability/          # logging + tracing setup, redaction
├── data/
│   ├── base.py             # PriceProvider / FactorProvider / MacroProvider protocols
│   ├── cache.py            # observation cache w/ per-dataset TTL, over the port
│   ├── storage/
│   │   ├── base.py         # repository protocols + backend registry
│   │   ├── migrations/     # one backend-neutral migration set
│   │   └── adapters/       # the ONLY place a DB driver is imported
│   │       └── sqlite.py
│   ├── yfinance_provider.py
│   ├── fred_provider.py
│   └── ken_french.py
├── cli/
│   ├── main.py             # root Typer app
│   ├── render.py           # table | json | csv renderers
│   └── commands/
│       ├── data.py, analyze.py, optimize.py, plan.py, econ.py
│       ├── portfolio.py, run.py, db.py      # 0003
│       └── serve.py, deploy.py              # 0004, 0005
└── api/                    # 0004: FastAPI adapter + job runner + SSE

frontend/                   # 0004: React SPA (built assets ship in the wheel)
site/                       # 0006: animated landing page → GitHub Pages
```

## Command surface (target)

| Command | Does |
|---|---|
| `qf data prices AAPL MSFT --start 2015-01-01` | Fetch + cache price history |
| `qf data macro DGS10 CPIAUCSL` | Fetch FRED series |
| `qf analyze stock NVDA` | Fundamentals, risk, CAPM beta |
| `qf analyze factors NVDA --model ff5` | Fama-French regression, alpha + t-stats |
| `qf optimize markowitz --tickers ... --objective max-sharpe` | Optimal weights |
| `qf optimize frontier --tickers ... --points 50` | Efficient frontier |
| `qf optimize backtest --weights ... --rebalance quarterly` | Walk-forward test |
| `qf plan retire --income ... --expenses ...` | FIRE number + date |
| `qf plan house --price ... --down-pct ...` | Savings path to a down payment |
| `qf plan goal --target ... --by 2032-01-01` | Generic funding solver |
| `qf econ forecast CPIAUCSL --model arima` | Time-series forecast |
| `qf fx rates EURUSD` / `qf fx convert 1000 --from USD --to EUR` | Exchange rates and conversion |
| `qf fx attribution --tickers ... --base USD` | Split return into asset vs currency |
| `qf fx hedge --tickers ... --compare unhedged` | What hedging would have cost |
| `qf ppp compare --base USD --vs EUR MXN` | Market rate vs purchasing-power rate |
| `qf ppp adjust-goal --goal fire --to PRT` | Restate a goal at another price level |
| `qf portfolio save core --tickers ...` | Save a named portfolio |
| `qf run list` / `qf run show <id>` | Browse saved analysis runs |
| `qf db info` / `qf db export --to ...` | Inspect and back up the database |
| `qf serve --host 0.0.0.0` | Run the web UI and API |
| `qf deploy compose` / `qf deploy check` | Generate and verify a deployment |

## Data sources

| Source | Key needed | Used for | From |
|---|---|---|---|
| **yfinance** | no | Prices, dividends, splits, fundamentals | 0001 |
| **ECB reference rates** | no | Daily exchange rates | 0001 |
| **FRED** | free API key (`FRED_API_KEY`) | Risk-free rate, CPI, macro series | 0001 |
| **Ken French Data Library** | no | Fama-French 3/5-factor + momentum returns | 0001 |
| **World Bank ICP / OECD** | no | PPP conversion factors, comparative price levels | 0010 |
| **BIS** | no | Published real effective exchange rates | 0010 |

`pip install quantfolio-cli` must produce a working tool with **no keys
configured**. Anything requiring a key degrades with a clear, actionable error —
never a stack trace.

## Storage: a port, with SQLite behind it

Persistence is reachable only through repository protocols in
`data/storage/base.py`, phrased in domain terms — observations, date ranges,
portfolios — never as SQL execution. A port phrased as SQL is a SQL port, and
swapping it would still be a rewrite.

`QUANTFOLIO_DB_URL` selects the adapter, defaulting to
`sqlite:///<user-data-dir>/quantfolio.db`. **No database driver is imported
outside `data/storage/adapters/`**, and a test enforces it.

SQLAlchemy Core (the expression language, not the ORM) sits *below* the
protocols as the dialect layer, with Alembic for migrations. Call sites never see
a `Session`, a `Table`, or a `Row`, so even that choice stays reversible.

The schema stays inside the capability intersection of **SQLite, PostgreSQL, and
DuckDB**: portable column types, application-generated identifiers, explicit UTC
timestamps, JSON stored as text, and no backend-specific SQL in shared code.

**Only the SQLite adapter is implemented.** The port, the registry, and a shared
**conformance suite** ship with it. The suite is the part that makes a second
backend cheap — it states the contract in executable form while there is exactly
one implementation, and adding a backend means a new adapter file plus one
fixture-list entry.

With SQLite, one file is the entire local state — cache, portfolios, goals, runs,
jobs. That is a property of the default backend, not of the system: it is what
lets Docker mount one volume and a backup be one copy.

API keys are the exception: they stay in the config file at mode `0600` and never
enter the database.

## Currency

Handled like timezone: every monetary series declares its currency, conversion is
one explicit operation, and mixing is refused rather than guessed.

Direction is carried by `CurrencyPair(base, quote)` — units of *quote* per one
unit of *base* — and **no call site ever multiplies or divides by a rate**; they
call `convert()`. That removes the inversion bug by removing the opportunity.

Return conversion uses the exact identity `(1+r_local)(1+r_fx)-1`, never the
additive approximation. Sub-unit quotations (GBp, ZAc, ILA) are normalized in the
data layer, with a test against a real pence-quoted listing.

The model lands in 0001 because returns computed without a currency concept must
be recomputed when one arrives — which by 0002 means every risk and optimization
function. The analytics are 0010. A single-currency run fetches no rates and is
identical to a build without any of this.

## Observability

Structured logging always (default WARNING); OpenTelemetry tracing behind the
`otel` extra, no-op unless `OTEL_*` is configured.

Three rules that everything else follows from:

1. **Logs go to stderr, always.** `--format json` must stay a single parseable
   document on stdout at any log level.
2. **`core/` imports no logging or tracing.** Instrumentation lives in the
   adapters, which observe the calls they make. Long computations take an
   optional progress callback; the caller decides whether that becomes a log
   line, a span event, or a job progress update.
3. **Redaction happens at the formatter**, not at call sites — a test runs every
   command with a sentinel credential at DEBUG and asserts it appears nowhere.

Observability may never change a result: stdout is byte-identical across log
levels and with tracing on or off, and that is a test. An unreachable exporter
warns once and never fails a command.

## Prior art in JJ's repos (reuse, don't rebuild)

| Source repo | What to lift |
|---|---|
| `espin086/fire-calculator` | The core/adapter architecture itself, plus `savings_rate`, `fi_number`, `project` → seeds `core/goals.py` |
| `espin086/CompountInterestAPI` | Compounding math, already packaged and tested |
| `legacy_code/` (this repo) | `StockMarketData.py` price pulls; `Financial Portfolio Optimization.R` is the reference implementation to port to `core/optimize.py` |
| `espin086/NewsWaveMetrics` | `fetch_yfinance.py` and `extract_economic_data.py` — working yfinance + FRED extraction patterns |
| `espin086/jjutils` | `base_regression.py` — regression scaffolding for `core/factors.py` |
| `espin086/Econometrics` | statsmodels usage patterns for `core/timeseries.py` |

## Milestones

Each is one OpenSpec change under `openspec/changes/`.

| # | Change | Ships |
|---|---|---|
| 0000 | `release-engineering` | CI gate, version-gated PyPI publishing |
| 0001 | `foundation-data-and-cli` | Provider layer, storage port + SQLite adapter, cache, logging + tracing, CLI shell, `qf data *` |
| 0002 | `portfolio-optimization` | **v1.0.0** — returns/risk, MVO, frontier, backtest |
| 0003 | `local-persistence` | Schema + migrations, saved portfolios/goals/runs, `qf db` |
| 0004 | `web-ui` | Command registry, FastAPI, React SPA, jobs + SSE, `qf serve` |
| 0005 | `docker-distribution` | One image on Docker Hub, CLI entrypoint, `qf deploy` |
| 0006 | `landing-page` | Animated dark GitHub Pages site |
| 0007 | `equity-factor-analysis` | Single-stock analysis, CAPM, Fama-French 3/5 + momentum |
| 0008 | `goal-planning` | Retirement/FIRE, house, car, education, Monte Carlo |
| 0009 | `econometrics-forecasting` | ARIMA/GARCH forecasting, stationarity, macro overlays |
| 0010 | `currency-and-ppp` | FX attribution and hedging, PPP comparison, PPP-adjusted goals |

0001 → 0002 is the v1.0.0 release. 0003 → 0006 turn it into a deployable product
with a UI. 0007–0009 then add analytics to a UI that already exists, rather than
retrofitting one at the end. 0010 makes the whole tool international, last because
it is the change that touches every earlier one. Each change depends only on what
came before it.

## Non-negotiables

1. **Not investment advice.** Every report-style output carries a disclaimer footer.
2. **No key, no problem.** The tool works out of the box on free sources.
3. **Reproducible.** Same inputs + same cached data + same seed → identical output.
4. **Cite the math.** Each core function's docstring names the formula and a source.
5. **The UI never diverges from the CLI.** Both are generated from one registry,
   and a parity test fails the build if they drift.
6. **Swappable things sit behind ports.** Data providers, the storage backend,
   and the solver are protocols in this codebase's namespace; their library types
   never appear in signatures outside their adapter.
7. **Observability never changes behavior.** No secret in a log or a span, no
   log on stdout, no instrumentation inside `core/`.
8. **No forecasting of exchange rates, ever.** PPP is reported as a valuation
   gap, never as a signal, a target, or a convergence path.
