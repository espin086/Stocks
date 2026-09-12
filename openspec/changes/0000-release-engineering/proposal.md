---
change: 0000-release-engineering
milestone: infrastructure (precedes 0001)
depends_on: []
status: proposed
---

# 0000 — Release engineering

## Outcome

Merging a version bump to `main` publishes the package to PyPI, with no manual
upload step and no credential living in this repository:

```
bump src/sobres/__about__.py  +  add a CHANGELOG.md section  →  merge  →  live on PyPI
```

Every other push to `main` publishes nothing and says so.

## Why

Spec-driven development only works if shipping is boring. If releasing is a
manual ritual, the gap between "0002 is done" and "someone can `pip install` it"
becomes the place where work stalls.

This change is numbered 0000 because it lands before any feature work: the gates
it installs are what every later change is measured against, and a quality bar
added after the code is written never catches what it would have prevented.

## What changes

- **New capability `release-pipeline`.**
- `.github/workflows/ci.yml` — reusable (`workflow_call`) gate: lint, format,
  `mypy --strict`, pytest across 3.11–3.13 on Linux plus 3.12 on macOS and
  Windows, artifact verification, and a dependency audit, behind one aggregator
  status check.
- `.github/workflows/release.yml` — version-gated publish on push to `main`,
  which *calls* `ci.yml` rather than restating it.
- `.github/scripts/check_release.py` — the release decision, runnable locally.
- `.github/workflows/codeql.yml`, `.github/dependabot.yml`,
  `.pre-commit-config.yaml`, `CHANGELOG.md`, `docs/RELEASING.md`.
- `tests/test_packaging.py` — release invariants enforced by `pytest`.
- Distribution named `sobres`; the import package is `sobres` and the console
  script is `sobres`.
- Publishing authenticates with the organization-level secrets `PYPI_PROD` and
  `PYPI_TEST`, which every `AI-Solutions-Lab-LLC` repository shares.

## Non-goals

- No release branches, no backport policy, no long-term support lines. One
  moving `main`.
- No signed git tags. PEP 740 attestations bind artifacts to the workflow that
  built them, which is the property that actually matters to an installer.
- No automated version bumping from commit messages. Deciding that a change is a
  minor rather than a patch is a judgement call, and conventional-commit parsers
  get it wrong quietly.
- No docs site publishing. Not until there are docs worth hosting.
- No conda-forge or OS packaging.

## Risks

| Risk | Mitigation |
|---|---|
| Merging the pipeline fires a publish before PyPI is configured, producing a red run on `main` | Publishing is disarmed until the repository variable `RELEASE_ENABLED` is `true`; `decide` reports "not armed" and exits clean |
| A network blip makes the index look empty, and a published version is re-published | `check_release.py` fails closed on any non-404 error rather than treating an unreachable index as "nothing published" |
| The organization PyPI token leaks and every repository in the organization is exposed | The token is org-scoped by design, so the blast radius is the organization. It is never echoed, the `pypi` environment can require human approval, and rotation is one place. Trusted Publishing would remove the token entirely and is the upgrade path once the org is ready for it |
| A bad version reaches PyPI, where it can never be replaced | `verify` re-runs the whole CI gate on the release commit; the wheel is installed in a clean environment and executed before upload; the `pypi` environment can require a human approval |
| The release gate drifts from the PR gate as CI grows | `release.yml` calls `ci.yml` via `workflow_call`; there is one definition of "green" |
| A required check is silently skipped and reads as passing | The `all-green` aggregator treats `skipped` and `cancelled` as failures, and it is the only required status check |
| The distribution name is unavailable on PyPI at release time | `sobres` was unclaimed as of 2026-09-12 (PyPI returns 404). `check_release.py` fails closed if the name is claimed by anyone else before the first upload, and the name is reserved by publishing `0.0.0` early |
