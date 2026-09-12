# sobres

[![CI](https://github.com/AI-Solutions-Lab-LLC/sobres/actions/workflows/ci.yml/badge.svg)](https://github.com/AI-Solutions-Lab-LLC/sobres/actions/workflows/ci.yml)
[![Release](https://github.com/AI-Solutions-Lab-LLC/sobres/actions/workflows/release.yml/badge.svg)](https://github.com/AI-Solutions-Lab-LLC/sobres/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/sobres.svg)](https://pypi.org/project/sobres/)
[![Python](https://img.shields.io/pypi/pyversions/sobres.svg)](https://pypi.org/project/sobres/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A one-stop **CLI for equity analysis** — market data, portfolio optimization, factor
models, econometrics, and real-world goal planning, in one tool.

> ⚠️ **For research and education only. Not investment advice.**

> 📍 **This repository was `espin086/Stocks`, now rebuilt as `sobres` under
> AI Solutions Lab.** The prior R linear-programming scripts and `yfinance`
> pullers have moved to
> [`legacy_code/`](legacy_code/) — nothing was deleted, and
> `legacy_code/Financial Portfolio Optimization.R` is the reference implementation
> that milestone 0002 ports and tests against. The original README is preserved at
> [`legacy_code/ORIGINAL-README.md`](legacy_code/ORIGINAL-README.md).

```bash
# Optimize a portfolio
sobres optimize markowitz --tickers AAPL MSFT NVDA JNJ XOM GLD \
    --start 2015-01-01 --fill ffill --objective max_sharpe --max-weight 0.35

# See the whole risk/return trade-off, not one point
sobres optimize frontier --tickers ... --fill ffill --points 50 --format csv > frontier.csv

# Find out whether that optimizer actually works out-of-sample
sobres optimize backtest --tickers ... --fill ffill --rebalance quarterly --lookback 36m

# Is there alpha, or is it just factor exposure?
sobres analyze factors NVDA --model ff5

# When can I retire?
sobres plan retire --income 200000 --expenses 90000 --portfolio 400000

# How much of my international return was the company, and how much was the dollar?
sobres fx attribution --tickers NESN.SW 7203.T ASML.AS --base USD

# That FIRE number buys a US lifestyle. What does it buy in Portugal?
sobres ppp adjust-goal --goal fire --to PRT
```

## Status

**v1.0.0.** The foundation (onboarding, the registry-generated CLI, the storage
port, keyless providers, the currency model, structured logging) and portfolio
optimization: Markowitz weights, the efficient frontier, a walk-forward backtest
and a risk panel. Persistence, the UI, the container and the remaining analytics
follow milestone by milestone below.

**Start here: [`openspec/project.md`](openspec/project.md)** for the architecture, then
the milestone plans in [`openspec/changes/`](openspec/changes/).

| # | Milestone | Ships | State |
|---|---|---|---|
| [0000](openspec/changes/0000-release-engineering/) | Release engineering | CI gate, version-gated PyPI publishing | ✅ Done |
| [0001](openspec/changes/0001-foundation-data-and-cli/) | Foundation | `init`/`doctor` onboarding, command registry, storage port, providers, currency, observability, `sobres data` | ✅ Done |
| [0002](openspec/changes/0002-portfolio-optimization/) | **Portfolio optimization (v1)** | Returns, risk, Markowitz, frontier, backtest | ✅ Done |
| [0003](openspec/changes/0003-local-persistence/) | Local persistence | Saved portfolios, goals, run history, `sobres db` | ✅ Done |
| [0004](openspec/changes/0004-web-ui/) | Web UI | FastAPI + React SPA derived from the registry, `sobres serve`, `sobres open` | ✅ Done |
| [0005](openspec/changes/0005-docker-distribution/) | Docker | One image on Docker Hub, `sobres deploy` | ✅ Done |
| [0006](openspec/changes/0006-landing-page/) | Landing page | Animated dark GitHub Pages site | ✅ Done |
| [0007](openspec/changes/0007-equity-factor-analysis/) | Factor analysis | CAPM, Fama-French 3/5 + momentum | 📋 Planned |
| [0008](openspec/changes/0008-goal-planning/) | Goal planning | Retirement/FIRE, house, car, education, Monte Carlo | 📋 Planned |
| [0009](openspec/changes/0009-econometrics-forecasting/) | Econometrics | ARIMA, GARCH, robust regression | 📋 Planned |
| [0010](openspec/changes/0010-currency-and-ppp/) | Exchange rates & PPP | FX attribution, hedging, PPP-adjusted goals | 📋 Planned |
| [0011](openspec/changes/0011-rebrand-sobres/) | Rebrand | One name everywhere: `sobres` | 🔧 In progress |

The whole tool also runs from one container — see [docs/DEPLOYING.md](docs/DEPLOYING.md):

```bash
docker run -p 8787:8787 -v sobres:/data aisolutionslab/sobres serve --host 0.0.0.0
sobres deploy compose > docker-compose.yml     # generated from your resolved configuration
sobres deploy check                            # doctor's checks plus mount, bind, token, credentials
```

## Install

```bash
pip install sobres          # (once the first release is published)
sobres init                             # guided setup: keys, storage — ends by running doctor
sobres doctor                           # every check tells you what's wrong and how to fix it
```

That's the whole onboarding path, and it stays three commands as the tool grows.
`sobres doctor --fix` applies the safe repairs; `sobres upgrade` detects how you
installed and runs the matching upgrade. `sobres open` starts the web UI and puts
it in your browser — `sobres open doctor` goes straight to a view.

Or for development:

```bash
git clone https://github.com/AI-Solutions-Lab-LLC/sobres.git
cd sobres
pip install -e ".[dev]"
pre-commit install                  # optional: run CI's checks before each commit
```

> **One name everywhere:** the distribution, the import package, and the console
> script are all `sobres` — `pip install sobres`, `import sobres`, `sobres --help`.

## Quickstart: the data layer

```bash
sobres data prices AAPL MSFT NVDA --start 2015-01-01          # Rich table on a TTY
sobres data prices AAPL --start 2020-01-01 --format csv > p.csv  # CSV when piped
sobres data factors --model ff5 --frequency monthly            # Fama-French + RF, decimal
sobres data fx EURUSD GBP/USD --start 2024-01-01               # ECB reference rates
sobres data macro DGS10 CPIAUCSL --start 2020-01-01            # needs a free FRED key
sobres cache info                                              # what is on disk, how old
sobres commands --format json                                  # the whole registry
```

Every data-emitting command takes `--format table|json|csv` (JSON is one
document at full precision; logs never touch stdout) and `--refresh` to bypass
the cache. A second identical call is served from the local SQLite file. Prices
default to the split- and dividend-adjusted close, state their currency, and
normalize pence- and cent-quoted listings to the major unit.

## Quickstart: optimization

```bash
sobres optimize markowitz --tickers AAPL MSFT JNJ XOM GLD --start 2015-01-01 --fill ffill
sobres optimize markowitz --tickers ... --fill ffill --objective min_variance --max-weight 0.35
sobres optimize frontier  --tickers ... --fill ffill --points 50 --format csv > frontier.csv
sobres optimize backtest  --tickers ... --fill ffill --rebalance quarterly --lookback 36m
sobres optimize risk      --tickers AAPL MSFT --weights 0.6 0.4 --start 2015-01-01 --fill ffill
```

`--fill` has no default on purpose: how provider gaps are handled changes every
number, so you say `drop`, `ffill` or `raise`. Ledoit-Wolf shrinkage is the
default covariance, transaction costs default to 10 bps, the risk-free rate comes
from FRED when a key is configured (and says `0.0 fallback` when not), and every
in-sample result is labelled as such. A multi-currency universe needs `--base`;
returns are converted before any moment is estimated. Read
[why your backtest looks too good](docs/why-your-backtest-looks-too-good.md)
before trusting the Sharpe ratio.

## Quickstart: saved state

```bash
sobres portfolio save core --tickers AAPL MSFT NVDA JNJ --weights 0.3 0.3 0.2 0.2
sobres optimize markowitz --portfolio core --start 2018-01-01 --fill ffill --save-run
sobres run list                          # newest first, with a one-line summary
sobres run show <id> --format json       # the complete stored record
sobres run diff <id-a> <id-b>            # two runs of the same command, side by side
sobres watchlist add tech NVDA AMD
sobres db info                           # path, schema version, size, rows per table
sobres db export --to ~/backups/sobres-$(date +%F).sqlite
```

One SQLite file holds the cache and everything you save; `sobres cache clear`
removes cached observations only and says what it preserved.

**No API key is required** for the core tool. Prices come from yfinance and factor
returns from the Ken French Data Library, both keyless. A free
[FRED key](https://fred.stlouisfed.org/docs/api/api_key.html) unlocks macro series
and the live risk-free rate — `sobres init` asks for it and offers to verify it, or:

```bash
sobres config set fred_api_key <YOUR_KEY>
```

## Quickstart: the web UI

```bash
pip install "sobres[web]"
sobres open                        # starts the server if needed, opens the browser
sobres open doctor                 # straight to a view: settings, doctor, runs, run <id>, ...
sobres serve                       # http://127.0.0.1:8787, no browser
sobres serve --host 0.0.0.0        # prints a token once; required off loopback
```

Every command in the registry is an HTTP route (`POST /api/v1/<group>/<name>`,
documented at `/api/docs`) and a form in the single-page app. The form shows the
equivalent `sobres` command line as you fill it in. Long computations
(`markowitz`, `frontier`, `backtest`) run as jobs with real progress and a cancel
button; results carry the same provenance header, in-sample label and disclaimer
the CLI prints. A parity test fails the build if a command lacks a route or a
view, and the same inputs give byte-identical JSON on both surfaces.

The server binds loopback by default. Binding any other address requires a
deployment token, generated once and stored hashed; `sobres serve token rotate`
replaces it. Cookies are `HttpOnly`, `SameSite=Strict` and the token is never
accepted on a query string.

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

## Landing page

<https://ai-solutions-lab-llc.github.io/sobres/> is built from `site/` and deployed
by GitHub Actions on every push to `main` that touches it. Every figure on it is
recorded by `python site/scripts/record_figures.py` from real `sobres` runs, the
version and install commands are generated at build time, and the build fails on
a bundle over 150 KB, a Lighthouse score under 95, a third-party request, or a
stale command name.

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
`src/sobres/__about__.py`, add a `CHANGELOG.md` section, merge to `main` —
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

sobres is a research and education tool. It is not investment advice, not a
recommendation to buy or sell any security, and carries no warranty of accuracy.
Data comes from third-party sources that may be delayed, revised, or wrong.
Backtested results are hypothetical and do not indicate future performance.
