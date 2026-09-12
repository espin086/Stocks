# 0011 — tasks

## A. Package identity

- [x] **A1. Rename the source tree** `src/quantfolio/` → `src/sobres/` with
      `git mv` so history follows. → test: `pytest` collects and passes unchanged.
- [x] **A2. `pyproject.toml`** — `name = "sobres"`, `[project.scripts] sobres =
      "sobres.cli.main:app"`, drop the second entry point, update `packages`,
      `tool.hatch.version.path`, coverage source, and mypy/ruff path settings.
      → test: `tests/test_packaging.py` asserts the installed distribution is
      `sobres` and exactly one console script exists.
- [x] **A3. Import rewrite** — every `from quantfolio` / `import quantfolio`.
      → test: a grep test asserts the string `quantfolio` appears nowhere under
      `src/`, `tests/`, or `docs/`.

## B. Runtime names

- [x] **B1. Settings prefix** *(lands with 0001, which introduces the registry)* `QUANTFOLIO_*` → `SOBRES_*` in the settings
      registry. → test: every declared setting's env var starts with `SOBRES_`.
- [x] **B2. Legacy env guard** *(lands with 0001)* — startup fails with a named replacement when any
      `QUANTFOLIO_*` variable is set. → test: a fixture sets `QUANTFOLIO_DB_URL`
      and asserts the error names `SOBRES_DB_URL`.
- [x] **B3. Paths** *(lands with 0001)* — `platformdirs` app name, default DB filename `sobres.db`.
      → test: the default DB URL resolves under a `sobres` data dir.
- [x] **B4. Legacy data check** *(lands with 0001's doctor)* — a doctor check that finds an old `quantfolio`
      config or data directory and prints the `mv` to run, without moving it.
      → test: the check reports actionable when a fake legacy dir exists.

## C. Published surfaces

- [ ] **C1. Docker** *(lands with 0005)* — image name `aisolutionslab/sobres`, volume examples, and
      the health check calling `sobres doctor`. → test: `sobres deploy check`
      output contains no `quantfolio`.
- [ ] **C2. Landing page** *(lands with 0006)* — base URL, install snippet, and every command example.
      → test: the site build fails on the string `qf `.
- [x] **C3. Docs and README** — install line, quickstart, every command example,
      `docs/RELEASING.md`. → test: the repository-wide grep test from A3 covers
      markdown too.
- [x] **C4. CI** — workflow names, artifact names, cache keys, and the PyPI
      environment. → test: a dry-run release to TestPyPI uploads `sobres`.

## D. Reserve the name

- [ ] **D1. Publish `0.0.0`** to PyPI as `sobres` to hold the name, per 0000's
      armed-release gate. → test: `check_release.py` reports the name as held by
      this project.

## Definition of done

- [x] `rg -i quantfolio` and `rg -w qf` return nothing outside `CHANGELOG.md`
      (and the 0011 change documents themselves) — `tests/test_rebrand.py`
- [x] `pip install -e .` then `sobres doctor` passes on a clean environment
- [x] Every test that passed before the rename passes after it, with identical
      fixture values
- [ ] `openspec validate` is clean
