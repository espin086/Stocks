# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases are cut by bumping `src/quantfolio/__about__.py` and adding a section
here — the release pipeline refuses to publish a version this file does not
describe. See [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

### Added
- Nothing yet. Work is tracked in `openspec/changes/`.

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

[Unreleased]: https://github.com/espin086/Stocks/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/espin086/Stocks/releases/tag/v0.0.1
