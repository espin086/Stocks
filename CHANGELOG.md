# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut by bumping `src/sobres/__about__.py` and adding a section
here — the release pipeline refuses to publish a version this file does not
describe. See [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

### Added
- **Local persistence (change 0003).** Schema version 2 with saved portfolios,
  watchlists, goals, run history and job records behind the storage port;
  `sobres portfolio`, `sobres watchlist`, `sobres run` and `sobres db` groups;
  `--portfolio <name>` wherever `--tickers` is accepted and `--save-run` on
  the analytical commands; `sobres db export` (SQLite backup API) and
  `sobres db repair` (recovery into a new file, original untouched);
  migrations tested against recorded prior-version fixtures.

## [1.0.0] - 2026-09-12

The first release: the foundation plus portfolio optimization. From here the
CLI's command surface, its `--format json` shapes and the `sobres.core` public
functions are the compatibility surface.

### Added
- **Portfolio optimization (change 0002).** `sobres optimize markowitz`
  (min variance, max Sharpe, target return, target risk, risk parity, equal
  weight; Ledoit-Wolf shrinkage by default; a concentration warning), `sobres
  optimize frontier`, `sobres optimize backtest` (walk-forward with weight
  drift, 10 bps default costs and an equal-weight benchmark on the same
  schedule) and `sobres optimize risk`. Returns, annualization, the risk panel
  (Sharpe, Sortino, Calmar, drawdown with dates, VaR/CVaR, skew, kurtosis,
  beta), expected-return and covariance estimators with PSD conditioning, and
  the budget-allocation LP ported from the legacy R script.
- `docs/why-your-backtest-looks-too-good.md`.
- **Foundation (change 0001).** The command registry and the Typer CLI
  generated from it; the settings registry behind `sobres init`, `sobres doctor`
  and `sobres config`; `sobres upgrade`; the storage port with its SQLite adapter,
  forward-only migrations and a shared conformance suite; the observation cache
  with per-dataset TTL and sub-range reuse; keyless yfinance, ECB and Ken French
  providers plus FRED behind a free key; the currency model (`CurrencyPair`,
  `convert`, sub-unit normalization, exact return conversion); structured
  logging to stderr with redaction and opt-in OpenTelemetry tracing; and the
  `sobres data`, `sobres cache`, `sobres config` and `sobres commands` groups.
- Test scaffolding: architecture and invariant suites, recorded-fixture
  provider tests, a scenario-coverage test, and `scripts/record_fixtures.py`.

### Changed
- **Renamed the project to `sobres`** (change 0011). The PyPI distribution,
  the import package, and the console script are all `sobres`; the `qf` and
  `quantfolio` names are gone with no compatibility shim, since nothing was
  ever published under them. The repository now lives at
  `AI-Solutions-Lab-LLC/sobres`.

## [0.0.1] - 2026-09-12

### Added
- Project scaffold: packaging (`hatchling`), the `qf` / `quantfolio` console
  scripts, and a Typer root application with `--version`.
- Spec-driven development plan for five milestones under `openspec/`.
- CI: lint, format, `mypy --strict`, and pytest across Python 3.11–3.13 on
  Linux plus 3.12 on macOS and Windows, wheel and sdist verification, and a
  dependency audit.
- Release pipeline: version-gated publishing to PyPI from `main` via Trusted
  Publishing, with PEP 740 attestations and an automatic GitHub release.

### Notes
- No analytical code yet. The spec deltas in `openspec/changes/` are the
  contract that later releases implement.
- Distributed as `quantfolio-cli` because the `quantfolio` name on PyPI is held
  by an unrelated package. The import package and CLI are both `quantfolio`.

[Unreleased]: https://github.com/AI-Solutions-Lab-LLC/sobres/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AI-Solutions-Lab-LLC/sobres/compare/v0.0.1...v1.0.0
[0.0.1]: https://github.com/espin086/Stocks/releases/tag/v0.0.1
