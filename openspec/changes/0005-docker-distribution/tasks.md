# 0005 — Tasks

Each task names the test that proves it.

## Wave A — the image

- [x] **A1. Multi-stage `Dockerfile`** — Node builds the SPA, Python builds the
      wheel (or the release passes its published wheel), a slim runtime carries
      neither toolchain; `ENTRYPOINT ["sobres"]`, non-root uid/gid 1000, `/data`
      volume, `EXPOSE 8787`, `HEALTHCHECK` on `sobres deploy health`.
      → `tests/architecture/test_deployment_files.py`,
      `tests/cli/test_deploy.py::test_dockerfile_makes_the_cli_the_entrypoint_with_no_container_code_path`
- [x] **A2. `.dockerignore`, `docker-compose.yml`** — nothing from a developer's
      machine reaches the build; the reference compose serves from a volume.
      → `tests/architecture/test_deployment_files.py::test_compose_reference_serves_on_8787_from_a_volume`

## Wave B — the container's behaviour through the CLI

- [x] **B1. Data on a volume** — `sqlite:////data/sobres.db` by default; a
      non-writable mount fails at startup with exit 3 naming the mount; doctor's
      `data-volume` and `container-user` checks.
      → `tests/cli/test_deploy.py::test_the_database_lives_on_the_volume_and_a_missing_mount_fails_loudly`
- [x] **B2. `sobres open` / `sobres init` in the container** — print the host URL,
      never launch; non-interactive by default, exit 3 naming a missing value.
      → `tests/cli/test_deploy.py`
- [x] **B3. Health is doctor** — `/api/v1/health` runs the fast offline checks and
      reports `ready`; `sobres deploy health` exits 1 when it is not.
      → `tests/api/test_api.py::test_health_and_docs`, `tests/cli/test_deploy.py::test_health_command_reports_readiness`
- [x] **B4. Signals** — a running job is cancelled at its checkpoint on shutdown and
      anything left is recorded as failed; orphans are recovered on start.
      → `tests/cli/test_deploy.py::test_signals_leave_no_job_running_forever`

## Wave C — `sobres deploy`

- [x] **C1. `compose`** — pinned image, `/data` mounted, port published, resolved
      non-default settings inline, secrets referenced by name.
      → `tests/cli/test_deploy.py::test_compose_is_generated_from_resolved_configuration_without_secrets`
- [x] **C2. `env`** — every variable, default and description; no secret values.
      → `tests/cli/test_deploy.py::test_env_template_lists_every_variable_and_no_secret_value`
- [x] **C3. `check`** — doctor's checks plus image, database, bind, token
      (exposure is an error) and credentials by key.
      → `tests/cli/test_deploy.py::test_preflight_reports_the_deployment_and_calls_out_exposure`

## Wave D — pipeline and docs

- [x] **D1. CI docker job** — builds the image, runs the documented quickstart
      (serve, health, UI, one-off command on the same volume, replacement),
      the missing-volume failure, the non-root check, the size budget.
      → `tests/architecture/test_deployment_files.py::test_ci_builds_the_image_and_runs_the_documented_quickstart`
- [x] **D2. Release docker job** — same gate as PyPI, exact wheel, version parity,
      never overwrite a tag, amd64+arm64, provenance and SBOM, trivy scan, Docker
      Hub login with repository secrets, disarmed until `DOCKER_RELEASE_ENABLED`.
      → `tests/architecture/test_deployment_files.py::test_release_publishes_the_image_on_the_same_gate`
- [x] **D3. `docs/DEPLOYING.md`**, README, CHANGELOG; 0011 C1 (the legacy name never
      appears in `sobres deploy` output).
      → `tests/cli/test_deploy.py`

## Verification note

The image is built and exercised in CI (`docker` job); the implementing
environment had no Docker daemon, so the Dockerfile's first real build is CI's. Multi-architecture push, the trivy scan and Docker Hub
publishing run only in the release workflow and need the secrets in
`docs/DEPLOYING.md`.
