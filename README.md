# quantfolio

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
```

## Status

🚧 **Pre-alpha — planning.** The repository currently contains the packaging
scaffold and the full spec-driven development plan. No analytical code is
implemented yet.

**Start here: [`openspec/project.md`](openspec/project.md)** for the architecture, then
the milestone plans in [`openspec/changes/`](openspec/changes/).

| # | Milestone | Ships | State |
|---|---|---|---|
| [0001](openspec/changes/0001-foundation-data-and-cli/) | Foundation | Provider layer, cache, CLI shell, `qf data` | 📋 Planned |
| [0002](openspec/changes/0002-portfolio-optimization/) | **Portfolio optimization (v1)** | Returns, risk, Markowitz, frontier, backtest | 📋 Planned |
| [0003](openspec/changes/0003-equity-factor-analysis/) | Factor analysis | CAPM, Fama-French 3/5 + momentum | 📋 Planned |
| [0004](openspec/changes/0004-goal-planning/) | Goal planning | Retirement/FIRE, house, car, education, Monte Carlo | 📋 Planned |
| [0005](openspec/changes/0005-econometrics-forecasting/) | Econometrics | ARIMA, GARCH, robust regression | 📋 Planned |

## Install

```bash
git clone https://github.com/espin086/Stocks.git
cd Stocks
pip install -e ".[dev]"     # development
```

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

## Architecture

One rule, and everything follows from it:

```
adapters →  cli/ (Typer)    api/ (future)      no business logic
math     →  core/           pure, I/O-free     no network, no disk
I/O      →  data/           providers + cache  no math
```

All math lives in `core/` as pure functions. The CLI is argv → data → core → render.
This is what makes the math testable without a network and the tool portable to a
web API later without moving a line of logic. Full detail:
[`openspec/project.md`](openspec/project.md).

## Development

```bash
pytest -m "not network"   # full suite, offline
pytest -m network         # live provider contract tests (run deliberately)
ruff check . && ruff format --check .
mypy
```

Tests never hit the network by default. Provider payloads are recorded as fixtures;
math is tested against hand-computed and textbook values.

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
