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
              ├──────────────────────────────────────────────┤
  math     →  │  core/  pure, I/O-free, deterministic        │  no network, no disk
              ├──────────────────────────────────────────────┤
  I/O      →  │  data/  providers + SQLite → pandas objects  │  no math
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
├── data/
│   ├── base.py             # PriceProvider / FactorProvider / MacroProvider protocols
│   ├── db.py               # SQLite connection, pragmas, migrations
│   ├── cache.py            # observation cache w/ per-dataset TTL
│   ├── store/              # 0003: portfolios, watchlists, goals, runs, jobs
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
| `qf portfolio save core --tickers ...` | Save a named portfolio |
| `qf run list` / `qf run show <id>` | Browse saved analysis runs |
| `qf db info` / `qf db export --to ...` | Inspect and back up the database |
| `qf serve --host 0.0.0.0` | Run the web UI and API |
| `qf deploy compose` / `qf deploy check` | Generate and verify a deployment |

## Data sources (v1)

| Source | Key needed | Used for |
|---|---|---|
| **yfinance** | no | Prices, dividends, splits, fundamentals |
| **FRED** | free API key (`FRED_API_KEY`) | Risk-free rate, CPI, macro series |
| **Ken French Data Library** | no | Fama-French 3/5-factor + momentum returns |

`pip install quantfolio-cli` must produce a working tool with **no keys
configured**. Anything requiring a key degrades with a clear, actionable error —
never a stack trace.

## Storage

**One SQLite file is the entire local state** — cached observations, saved
portfolios, goals, run history, and jobs. Not a cache directory plus a database
plus a config of saved things.

That single decision pays three times: sub-range cache reuse (asking for 2015–2024
after caching 2015–2025 costs nothing), one thing for Docker to mount as a volume,
and one file to copy to back up or move machines. Location is `QUANTFOLIO_DB`,
defaulting to the platform data dir locally and `/data/quantfolio.db` in the
container.

API keys are the exception: they stay in the config file at mode `0600` and never
enter the database.

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
| 0001 | `foundation-data-and-cli` | Provider layer, SQLite cache, config, CLI shell, `qf data *` |
| 0002 | `portfolio-optimization` | **v1.0.0** — returns/risk, MVO, frontier, backtest |
| 0003 | `local-persistence` | Schema + migrations, saved portfolios/goals/runs, `qf db` |
| 0004 | `web-ui` | Command registry, FastAPI, React SPA, jobs + SSE, `qf serve` |
| 0005 | `docker-distribution` | One image on Docker Hub, CLI entrypoint, `qf deploy` |
| 0006 | `landing-page` | Animated dark GitHub Pages site |
| 0007 | `equity-factor-analysis` | Single-stock analysis, CAPM, Fama-French 3/5 + momentum |
| 0008 | `goal-planning` | Retirement/FIRE, house, car, education, Monte Carlo |
| 0009 | `econometrics-forecasting` | ARIMA/GARCH forecasting, stationarity, macro overlays |

0001 → 0002 is the v1.0.0 release. 0003 → 0006 turn it into a deployable product
with a UI. 0007–0009 then add analytics to a UI that already exists, rather than
retrofitting one at the end. Each change depends only on what came before it.

## Non-negotiables

1. **Not investment advice.** Every report-style output carries a disclaimer footer.
2. **No key, no problem.** The tool works out of the box on free sources.
3. **Reproducible.** Same inputs + same cached data + same seed → identical output.
4. **Cite the math.** Each core function's docstring names the formula and a source.
5. **The UI never diverges from the CLI.** Both are generated from one registry,
   and a parity test fails the build if they drift.
