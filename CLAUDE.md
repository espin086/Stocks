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
registry.py  One declaration per command (0004). CLI, API and UI derive from it.
cli/    Typer adapters — argv → data → core → render.    NO business logic.
api/    FastAPI adapters (0004).                          NO business logic.
core/   Pure, I/O-free math over frames and dataclasses.  NO network, NO disk.
data/   Providers + SQLite → pandas objects.              NO math.
```

If you find yourself computing something in `cli/` or `api/`, it belongs in
`core/`. If you find yourself calling a provider or opening a connection from
`core/`, pass the frame in instead.

From 0004 on, never add a command to only one surface. Declare it in
`registry.py`; the CLI, the HTTP route, and the UI form come from that. A parity
test fails the build if a registered command lacks a route or a view.

## Storage

One SQLite file is the whole local state — cached observations, saved portfolios,
goals, runs, jobs. Path from `QUANTFOLIO_DB`, `/data/quantfolio.db` in Docker.

- Never add a second store (a cache directory, a JSON sidecar, a pickle). The
  single-file property is what makes the container one volume and a backup one copy.
- Migrations are forward-only and never edited after release; a correction is a new
  migration.
- `qf cache clear` removes cached observations only. It must never touch
  user-authored rows.
- API keys live in the config file at `0600`, never in the database.

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
