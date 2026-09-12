# 0011 — tasks

## A. Package identity

- [ ] **A1. Rename the source tree** `src/quantfolio/` → `src/sobres/` with
      `git mv` so history follows. → test: `pytest` collects and passes unchanged.
- [ ] **A2. `pyproject.toml`** — `name = "sobres"`, `[project.scripts] sobres =
      "sobres.cli.main:app"`, drop the second entry point, update `packages`,
      `tool.hatch.version.path`, coverage source, and mypy/ruff path settings.
      → test: `tests/test_packaging.py` asserts the installed distribution is
      `sobres` and exactly one console script exists.
- [ ] **A3. Import rewrite** — every `from quantfolio` / `import quantfolio`.
      → test: a grep test asserts the string `quantfolio` appears nowhere under
      `src/`, `tests/`, or `docs/`.

## B. Runtime names

- [ ] **B1. Settings prefix** `QUANTFOLIO_*` → `SOBRES_*` in the settings
      registry. → test: every declared setting's env var starts with `SOBRES_`.
- [ ] **B2. Legacy env guard** — startup fails with a named replacement when any
      `QUANTFOLIO_*` variable is set. → test: a fixture sets `QUANTFOLIO_DB_URL`
      and asserts the error names `SOBRES_DB_URL`.
- [ ] **B3. Paths** — `platformdirs` app name, default DB filename `sobres.db`.
      → test: the default DB URL resolves under a `sobres` data dir.
- [ ] **B4. Legacy data check** — a doctor check that finds an old `quantfolio`
      config or data directory and prints the `mv` to run, without moving it.
      → test: the check reports actionable when a fake legacy dir exists.

## C. Published surfaces

- [ ] **C1. Docker** — image name `aisolutionslab/sobres`, volume examples, and
      the health check calling `sobres doctor`. → test: `sobres deploy check`
      output contains no `quantfolio`.
- [ ] **C2. Landing page** — base URL, install snippet, and every command example.
      → test: the site build fails on the string `qf `.
- [ ] **C3. Docs and README** — install line, quickstart, every command example,
      `docs/RELEASING.md`. → test: the repository-wide grep test from A3 covers
      markdown too.
- [ ] **C4. CI** — workflow names, artifact names, cache keys, and the PyPI
      environment. → test: a dry-run release to TestPyPI uploads `sobres`.

## D. Reserve the name

- [ ] **D1. Publish `0.0.0`** to PyPI as `sobres` to hold the name, per 0000's
      armed-release gate. → test: `check_release.py` reports the name as held by
      this project.

## Definition of done

- [ ] `rg -i quantfolio` and `rg -w qf` return nothing outside `CHANGELOG.md`
- [ ] `pip install -e .` then `sobres doctor` passes on a clean environment
- [ ] Every test that passed before the rename passes after it, with identical
      fixture values
- [ ] `openspec validate` is clean
