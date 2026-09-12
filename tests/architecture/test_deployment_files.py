"""The image, compose file and pipeline are code; these rules keep them honest.

Scenarios: No container-only code path; Serving; Minimal runtime; Health; No
secrets in the image; Same gate as PyPI; Version parity is asserted; Tagging;
Architectures; Provenance; Registry; Credentials; Build and push; Size budget;
Vulnerability scan; Quickstart is real.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = (REPO / "Dockerfile").read_text()
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text()
RELEASE = (REPO / ".github" / "workflows" / "release.yml").read_text()
COMPOSE = (REPO / "docker-compose.yml").read_text()


def _stage(name: str) -> str:
    match = re.search(rf"FROM [^\n]* AS {name}\n(.*?)(?=\nFROM |\Z)", DOCKERFILE, re.S)
    assert match, name
    return match.group(1)


def test_runtime_stage_is_minimal_and_installs_only_the_wheel() -> None:
    runtime = _stage("runtime")
    assert "node" not in runtime.lower() and "npm" not in runtime.lower()
    assert "apt-get install" not in runtime and "build-essential" not in runtime
    assert "COPY --from=wheel-source /wheels/" in runtime
    assert not re.search(r"COPY (src|frontend)/", runtime)  # nothing but the built artifact
    assert "prebuilt" in DOCKERFILE and "COPY dist/*.whl /wheels/" in DOCKERFILE
    assert "ARG WHEEL_SOURCE=wheel" in DOCKERFILE


def test_no_secret_reaches_the_image() -> None:
    for pattern in ("API_KEY=", "TOKEN=", "PASSWORD=", "COPY config"):
        assert pattern not in DOCKERFILE, pattern
    ignore = (REPO / ".dockerignore").read_text()
    for entry in (".env", ".git", "tests", "frontend/node_modules"):
        assert entry in ignore.splitlines(), entry
    assert "scanners: vuln,secret" in RELEASE  # asserted by a scan, not by review


def test_health_is_doctor_not_a_second_notion() -> None:
    assert re.search(r'HEALTHCHECK[^\n]*\\\n\s*CMD \["sobres", "deploy", "health"', DOCKERFILE)
    assert '"CMD", "sobres", "deploy", "health"' in COMPOSE
    app = (REPO / "src" / "sobres" / "api" / "app.py").read_text()
    assert "run_checks(state.context(), offline=True, only=READINESS_CHECKS)" in app


def test_compose_reference_serves_on_8787_from_a_volume() -> None:
    assert 'command: ["serve", "--host", "0.0.0.0", "--port", "8787"]' in COMPOSE
    assert "- sobres-data:/data" in COMPOSE and '"8787:8787"' in COMPOSE
    assert "${SOBRES_FRED_API_KEY" in COMPOSE  # referenced, never a value


def test_ci_builds_the_image_and_runs_the_documented_quickstart() -> None:
    assert "docker/build-push-action@v6" in CI and "load: true" in CI
    assert "serve --host 0.0.0.0" in CI and "/api/v1/health" in CI
    assert "-v sobres-ci:/data" in CI and "docker stop -t 10" in CI  # data survives replacement
    assert "portfolio save core" in CI and "grep -q '\"core\"'" in CI
    assert "500 * 1024 * 1024" in CI  # the size budget fails the build
    assert "--entrypoint id sobres:ci -u" in CI  # non-root
    assert "needs: [lint, typecheck, test, frontend, build, docker, security]" in CI


def test_release_publishes_the_image_on_the_same_gate() -> None:
    docker_job = RELEASE.split("  docker:\n", 1)[1].split("  github-release:", 1)[0]
    assert "needs: [decide, build, publish]" in docker_job
    assert "needs.decide.outputs.publish == 'true'" in docker_job
    assert "vars.DOCKER_RELEASE_ENABLED == 'true'" in docker_job  # disarmed by default
    assert "name: release-dist" in docker_job and "WHEEL_SOURCE=prebuilt" in docker_job
    assert 'test "$reported" = "$VERSION"' in docker_job  # version parity before any push
    assert "docker manifest inspect" in docker_job  # never overwrite an exact tag
    assert "${IMAGE}:${VERSION},${IMAGE}:${minor},${IMAGE}:latest" in docker_job
    assert "platforms: linux/amd64,linux/arm64" in docker_job
    assert "provenance: mode=max" in docker_job and "sbom: true" in docker_job
    assert "not an OIDC-signed identity" in docker_job
    assert "IMAGE: aisolutionslab/sobres" in docker_job
    assert "docker/login-action@v3" in docker_job
    assert "${{ secrets.DOCKERHUB_USERNAME }}" in docker_job
    assert "${{ secrets.DOCKERHUB_TOKEN }}" in docker_job
    assert "DOCKERHUB" not in RELEASE.split("  docker:\n", 1)[0]  # read by the push job alone
    for action in (
        "docker/setup-qemu-action",
        "docker/setup-buildx-action",
        "docker/build-push-action",
    ):
        assert action in docker_job, action
    assert (
        docker_job.count("docker/build-push-action") == 2
    )  # one native check, one multi-arch push
    assert "aquasecurity/trivy-action" in docker_job and "ignore-unfixed: true" in docker_job
    assert 'exit-code: "1"' in docker_job and (REPO / ".trivyignore").exists()
    assert "500 * 1024 * 1024" in docker_job
