# quantfolio

[![CI](https://github.com/espin086/Stocks/actions/workflows/ci.yml/badge.svg)](https://github.com/espin086/Stocks/actions/workflows/ci.yml)
[![Release](https://github.com/espin086/Stocks/actions/workflows/release.yml/badge.svg)](https://github.com/espin086/Stocks/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/quantfolio-cli.svg)](https://pypi.org/project/quantfolio-cli/)
[![Python](https://img.shields.io/pypi/pyversions/quantfolio-cli.svg)](https://pypi.org/project/quantfolio-cli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A one-stop **CLI for equity analysis** — market data, portfolio optimization, factor
models, econometrics, and real-world goal planning, in one tool.

> ⚠️ **For research and education only. Not investment advice.**

> 📍 **This repository is `espin086/Stocks`, being rebuilt as `quantfolio`.** The
> prior R linear-programming scripts and `yfinance` pullers have moved to
> [`legacy_code/`](legacy_code/) — nothing was deleted, and
> `legacy_code/Financial Portfolio Optimization.R` is the reference implementation
> that milestone 0002 ports and tests against. The original README is preserved at
> [`legacy_code/ORIGINAL-README.md`](legacy_code/ORIGINAL-README.md).

```bash
# Optimize a portfolio
qf optimize markowitz --tickers AAPL MSFT NVDA JNJ XOM GLD \
    --start 2015-01-01 --objective max-sharpe --max-weight 0.35

# See the whole risk/return trade-off, not one point
qf optimize frontier --tickers ... --points 50 --format csv > frontier.csv

# Find out whether that optimizer actually works out-of-sample
qf optimize backtest --tickers ... --rebalance quarterly --lookback 36m

# Is there alpha, or is it just factor exposure?
qf analyze factors NVDA --model ff5

# When can I retire?
qf plan retire --income 200000 --expenses 90000 --portfolio 400000

# How much of my international return was the company, and how much was the dollar?
qf fx attribution --tickers NESN.SW 7203.T ASML.AS --base USD

# That FIRE number buys a US lifestyle. What does it buy in Portugal?
qf ppp adjust-goal --goal fire --to PRT
```

## Status

🚧 **Pre-alpha — planning.** The repository currently contains the packaging
scaffold, the release pipeline, and the full spec-driven development plan. No
analytical code, UI, or container is implemented yet.

**Start here: [`openspec/project.md`](openspec/project.md)** for the architecture, then
the milestone plans in [`openspec/changes/`](openspec/changes/).

| # | Milestone | Ships | State |
|---|---|---|---|
| [0000](openspec/changes/0000-release-engineering/) | Release engineering | CI gate, version-gated PyPI publishing | ✅ Done |
| [0001](openspec/changes/0001-foundation-data-and-cli/) | Foundation | Command registry, storage port, providers, currency, observability, `qf data` | 📋 Planned |
| [0002](openspec/changes/0002-portfolio-optimization/) | **Portfolio optimization (v1)** | Returns, risk, Markowitz, frontier, backtest | 📋 Planned |
| [0003](openspec/changes/0003-local-persistence/) | Local persistence | Saved portfolios, goals, run history, `qf db` | 📋 Planned |
| [0004](openspec/changes/0004-web-ui/) | Web UI | FastAPI + React SPA derived from the registry, `qf serve` | 📋 Planned |
| [0005](openspec/changes/0005-docker-distribution/) | Docker | One image on Docker Hub, `qf deploy` | 📋 Planned |
| [0006](openspec/changes/0006-landing-page/) | Landing page | Animated dark GitHub Pages site | 📋 Planned |
| [0007](openspec/changes/0007-equity-factor-analysis/) | Factor analysis | CAPM, Fama-French 3/5 + momentum | 📋 Planned |
| [0008](openspec/changes/0008-goal-planning/) | Goal planning | Retirement/FIRE, house, car, education, Monte Carlo | 📋 Planned |
| [0009](openspec/changes/0009-econometrics-forecasting/) | Econometrics | ARIMA, GARCH, robust regression | 📋 Planned |
| [0010](openspec/changes/0010-currency-and-ppp/) | Exchange rates & PPP | FX attribution, hedging, PPP-adjusted goals | 📋 Planned |

Once 0005 lands, the whole tool runs from one container:

```bash
docker run -p 8787:8787 -v quantfolio:/data espin086/quantfolio serve --host 0.0.0.0
```

## Install

```bash
pip install quantfolio-cli          # (once the first release is published)
```

Or for development:

```bash
git clone https://github.com/espin086/Stocks.git
cd Stocks
pip install -e ".[dev]"
pre-commit install                  # optional: run CI's checks before each commit
```

> **On the name:** the distribution is `quantfolio-cli` because `quantfolio` on
> PyPI is held by an unrelated 2019 package. The import package and the CLI are
> both `quantfolio` — `import quantfolio`, `qf --help`.

**No API key is required** for the core tool. Prices come from yfinance and factor
returns from the Ken French Data Library, both keyless. A free
[FRED key](https://fred.stlouisfed.org/docs/api/api_key.html) unlocks macro series
and the live risk-free rate:

```bash
qf config set fred_api_key <YOUR_KEY>
```

## Data sources

| Source | Key | Used for |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | — | Prices, dividends, splits, fundamentals |
| [FRED](https://fred.stlouisfed.org/) | free | Risk-free rate, CPI, macro series |
| [Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) | — | Fama-French 3/5-factor + momentum returns |
| [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) | — | Daily exchange rates |
| [World Bank ICP](https://data.worldbank.org/indicator/PA.NUS.PPP) / [OECD](https://data.oecd.org/conversion/purchasing-power-parities-ppp.htm) | — | PPP conversion factors and price levels |

## Architecture

One rule, and everything follows from it:

```
              registry.py — every command declared once
                    │
adapters →  cli/ (Typer)  api/ (FastAPI)  frontend/ (React)   no business logic
math     →  core/         pure, I/O-free                      no network, no disk
I/O      →  data/         providers + SQLite                  no math
```

All math lives in `core/` as pure functions. The CLI, the HTTP API, and the web UI
are three renderings of one command registry — so "the UI has every CLI feature" is
a test that fails the build, not an intention. One SQLite file holds the cache,
saved portfolios, and run history, and is also the one thing Docker mounts. Full
detail: [`openspec/project.md`](openspec/project.md).

## Development

```bash
pytest -m "not network"   # full suite, offline
pytest -m network         # live provider contract tests (run deliberately)
ruff check . && ruff format --check .
mypy
```

Tests never hit the network by default. Provider payloads are recorded as fixtures;
math is tested against hand-computed and textbook values.

### CI

Every pull request runs lint, format, `mypy --strict`, and the test suite on
Python 3.11–3.13 (Linux) plus 3.12 on macOS and Windows, then builds the wheel
and sdist, installs the wheel into a clean environment and runs it, and audits
the dependency tree. CodeQL and Dependabot run alongside. One aggregated status
check, **All checks passed**, gates merges.

### Releases

Releasing is a version bump. Change `__version__` in
`src/quantfolio/__about__.py`, add a `CHANGELOG.md` section, merge to `main` —
the pipeline re-runs the full gate on that commit and publishes to PyPI via
Trusted Publishing (OIDC, no stored token) with PEP 740 attestations, then tags
and creates the GitHub release. Any push to `main` that doesn't change the
version publishes nothing.

See **[docs/RELEASING.md](docs/RELEASING.md)** for the one-time setup and the
failure playbook.

## Contributing

This project is spec-driven. Behavior changes start with an OpenSpec change under
`openspec/changes/` — proposal, spec delta, design, tasks — before implementation.
The spec delta is the contract; every scenario in it gets a test.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

quantfolio is a research and education tool. It is not investment advice, not a
recommendation to buy or sell any security, and carries no warranty of accuracy.
Data comes from third-party sources that may be delayed, revised, or wrong.
Backtested results are hypothetical and do not indicate future performance.
