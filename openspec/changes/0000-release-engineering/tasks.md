# 0000 — Tasks

All complete. Recorded so the change archives with its own checklist.

## Wave A — CI gate

- [x] **A1. Reusable CI workflow** — lint, format, `mypy --strict`, test matrix
      (3.11/3.12/3.13 on Linux, 3.12 on macOS and Windows), `workflow_call`.
- [x] **A2. Artifact verification** — build sdist + wheel, `twine check
      --strict`, install the wheel in a clean venv and run both console scripts,
      prove the sdist builds a wheel.
- [x] **A3. Dependency audit** — `pip-audit --strict` as a gating job.
- [x] **A4. Aggregator status check** — `all-green`, treating skipped and
      cancelled as failures.
      → verified: the naive `grep` form matches structural JSON lines and always
        fails; replaced with `contains(needs.*.result, ...)`.

## Wave B — release

- [x] **B1. Release decision** — `.github/scripts/check_release.py`; fails closed
      on an unreachable index; runnable locally.
      → verified against live PyPI in all three modes (disarmed, armed, testpypi)
- [x] **B2. Release workflow** — calls `ci.yml`, builds, asserts the built
      version, publishes via Trusted Publishing with attestations, tags and
      creates the GitHub release.
- [x] **B3. Arming switch** — `RELEASE_ENABLED`, so merging the pipeline cannot
      fire a publish before PyPI is configured.
- [x] **B4. TestPyPI rehearsal** — `workflow_dispatch` with a target input.

## Wave C — hygiene

- [x] **C1. CodeQL** — push, PR, and weekly schedule.
- [x] **C2. Dependabot** — grouped weekly actions and dev-dependency updates.
- [x] **C3. pre-commit** — ruff, ruff-format, mypy, and file hygiene.
- [x] **C4. `CHANGELOG.md`** — Keep a Changelog format, gated by the pipeline.
- [x] **C5. Packaging tests** — `tests/test_packaging.py`: version format,
      installed metadata parity, changelog section, both entry points.
- [x] **C6. `docs/RELEASING.md`** — the one-time setup and the failure playbook.
- [x] **C7. Distribution name** is `sobres`, unclaimed on PyPI as of 2026-09-12.
      An earlier `quantfolio` / `quantfolio-cli` naming is superseded by change 0011.

## Definition of done

- [x] `ruff`, `ruff format`, `mypy --strict`, `pytest` all pass locally
- [x] Coverage at 100%, CI gate set at 90%
- [x] `check_release.py` verified against the live index in every mode
- [x] Every workflow parses as valid YAML
- [ ] **Owner action:** `pypi` / `testpypi` environments created and wired to the
      organization secrets `PYPI_PROD` and `PYPI_TEST`, `RELEASE_ENABLED` set,
      `main` protected (see `docs/RELEASING.md`)
- [ ] **B5. Token-auth upload** — `release.yml` passes `secrets.PYPI_PROD` /
      `secrets.PYPI_TEST` as the upload password and drops the `id-token: write`
      permission and the attestation step. → test: a TestPyPI rehearsal uploads
      successfully and the run log contains no token fragment.
