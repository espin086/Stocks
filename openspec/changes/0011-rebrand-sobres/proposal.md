---
change: 0011-rebrand-sobres
milestone: out-of-band
depends_on: [0000-release-engineering]
status: proposed
---

# 0011 — Rebrand to sobres

## Outcome

One name, everywhere:

```bash
pip install sobres
sobres init
sobres doctor
sobres data prices AAPL MSFT --start 2015-01-01
```

```python
from sobres.core.optimize import max_sharpe
```

The repository is `AI-Solutions-Lab-LLC/sobres`. The distribution, the import
package, the console script, the environment prefix, the container image and the
landing-page URL all read `sobres`, and nothing in the repository still says
`quantfolio` or `qf`.

## Why

The project moved. It was `espin086/Stocks`, packaged as `quantfolio` with a `qf`
console script; it now lives in the `AI-Solutions-Lab-LLC` organization under the
name `sobres`. Carrying two names is the expensive part: a user reads `sobres` on
GitHub, installs `quantfolio-cli`, and types `qf`. Every one of those is a place
to get it wrong, and every published artifact that ships under the old name is one
more thing to deprecate later.

The `quantfolio` name was never usable on PyPI anyway — it is held by an unrelated
2019 package, which is why `quantfolio-cli` existed as a fallback. `sobres` was
unclaimed as of 2026-09-12, so the rename removes the fallback rather than
replacing one workaround with another.

Doing this before the first PyPI upload costs one mechanical pass. Doing it after
costs a deprecation shim, a release note, and a name nobody can reclaim.

## What changes

| Surface | From | To |
|---|---|---|
| PyPI distribution | `quantfolio-cli` | `sobres` |
| Import package | `src/quantfolio/` | `src/sobres/` |
| Console script | `quantfolio`, `qf` | `sobres` |
| Env var prefix | `QUANTFOLIO_` | `SOBRES_` |
| Default DB path | `<user-data-dir>/quantfolio.db` | `<user-data-dir>/sobres.db` |
| Container image | `espin086/quantfolio` | `aisolutionslab/sobres` |
| Landing page | `espin086.github.io/Stocks` | `ai-solutions-lab-llc.github.io/sobres` |
| Config / cache dir | `platformdirs("quantfolio")` | `platformdirs("sobres")` |

The OpenSpec documents were rewritten to the new names on 2026-09-12. This change
is what brings the code up to them, so until it lands the specs and the source
disagree by design.

## Non-goals

- **No compatibility shim.** No `quantfolio` alias package, no `qf` alias script,
  no env-var fallback. Nothing has been published under the old name, so there is
  no installed base to keep working, and a shim would be permanent by accident.
- **No behavior change.** Not one number the tool prints moves. If a test fixture
  changes value, the rename broke something.
- **No PEP 541 request** for the `quantfolio` name. It is abandoned, not contested.
- **No re-tagging of history.** Old commits keep their paths; `git log --follow`
  is the answer for archaeology.

## Risks

| Risk | Mitigation |
|---|---|
| A user's existing local database and config sit under the old `quantfolio` paths | `sobres doctor` detects a legacy directory and reports the exact `mv` to run; it does not move data silently |
| The `sobres` name is claimed on PyPI before the first upload | Reserve it by publishing `0.0.0` as soon as this change merges, per 0000's release gate |
| A stale `QUANTFOLIO_*` env var in someone's shell reads as unset and the tool silently uses a default | The settings registry refuses to start when any `QUANTFOLIO_*` variable is present, naming the `SOBRES_*` replacement |
| The Docker Hub namespace is wrong | `aisolutionslab` is an assumption. Confirm the organization's actual Docker Hub account before 0005 publishes an image |

## Open questions

- Docker Hub namespace for the AI Solutions Lab organization — `aisolutionslab` is
  a placeholder used consistently across these documents.
- Whether the GitHub Pages site publishes from the repository or from an
  organization-level pages repo, which decides the final URL path.
