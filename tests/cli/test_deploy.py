"""``sobres deploy`` and the container behaviours that run through the CLI.

Scenarios: The CLI is the entrypoint; One-off commands; Database lives on a
volume; A missing volume fails loudly; Data survives replacement; Host and
container share one database; Non-root; Configuration at runtime only; Doctor
in the container; `sobres open` in the container; Non-interactive init in the
container; Signals; Logs are the container's stream; Log level is configurable
at runtime; Tracing is configured, not built in; An unreachable collector never
breaks the container; The default stays SQLite on a volume; An external backend
needs no different image; A database URL is a secret; Compose generation;
Generated from resolved configuration; Secrets are referenced, never embedded;
Preflight; Exposure is called out; Environment template; Upgrades.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sobres import deploy as dep
from sobres.cli.context import Context
from sobres.config import resolve
from sobres.doctor import all_checks
from tests.conftest import SENTINEL_KEY

LEGACY_NAME = "".join(("quant", "folio"))  # 0011 C1: never in `sobres deploy` output


def _container_env(env: dict[str, str], data: Path) -> dict[str, str]:
    """What the image sets, pointed at a temp directory standing in for /data."""
    data.mkdir(parents=True, exist_ok=True)
    return {
        **env,
        "SOBRES_CONTAINER": "1",
        "SOBRES_DB_URL": f"sqlite:///{data.as_posix()}/sobres.db",
        "SOBRES_CONFIG_FILE": str(data / "config.toml"),
        "SOBRES_LOG_FORMAT": "json",
    }


# --------------------------------------------------------------- the entrypoint
def test_dockerfile_makes_the_cli_the_entrypoint_with_no_container_code_path() -> None:
    text = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["sobres"]' in text
    assert "CMD [" not in text.split("HEALTHCHECK")[0]  # no default subcommand: --help is help
    assert "USER sobres" in text and "useradd --uid" in text
    assert 'VOLUME ["/data"]' in text and "SOBRES_DB_URL=sqlite:////data/sobres.db" in text
    assert "EXPOSE 8787" in text
    assert "HEALTHCHECK" in text and '"deploy", "health"' in text
    assert "SOBRES_LOG_FORMAT=json" in text and "SOBRES_LOG_FILE" not in text
    assert "[data,econ,web,otel]" in text  # tracing installed, inert without OTEL_*


# ------------------------------------------------------------- data on a volume
def test_the_database_lives_on_the_volume_and_a_missing_mount_fails_loudly(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    data = tmp_path / "data"
    container = _container_env(env, data)
    result = cli("portfolio", "save", "core", "--tickers", "AAPL", "MSFT", env_extra=container)
    assert result.exit_code == 0, result.stderr
    assert (data / "sobres.db").exists()
    # The same file is what the host sees: reopening it (a "new container") finds the row.
    again = cli("portfolio", "list", "--format", "json", env_extra=container)
    assert "core" in again.stdout
    # A mount that cannot hold a database: its "directory" is a plain file (tests run as
    # root, so a permission bit alone would not stop the write).
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    unwritable = {**container, "SOBRES_DB_URL": f"sqlite:///{blocker.as_posix()}/sobres.db"}
    missing = cli("db", "info", env_extra=unwritable)
    assert missing.exit_code == 3
    assert "blocker is not writable" in missing.stderr
    assert "mount a volume at /data" in missing.stderr
    doctor = cli("doctor", "--offline", "--format", "json", env_extra=unwritable)
    checks = {c["name"]: c for c in json.loads(doctor.stdout)["checks"]}
    assert checks["data-volume"]["status"] == "fail"
    assert "docker run -v sobres:/data" in checks["data-volume"]["fix_hint"]


def test_sqlite_url_forms_resolve_to_the_right_file(tmp_path: Path) -> None:
    assert dep._sqlite_file("sqlite:////data/sobres.db") == Path("/data/sobres.db")
    assert dep._sqlite_file("sqlite:///rel.db") == (Path.cwd() / "rel.db").resolve()
    assert dep._sqlite_file("postgresql://u:p@h/db") is None


def test_external_backend_needs_no_volume(env: dict[str, str], tmp_path: Path) -> None:
    container = _container_env(env, tmp_path / "data")
    container["SOBRES_DB_URL"] = "postgresql://user:secret@db.internal/sobres"
    config = resolve(None, container, path=Path(container["SOBRES_CONFIG_FILE"]))
    status = dep.data_volume_status(config)
    assert status.status == "ok" and status.detail["volume_needed"] is False
    dep.require_data_volume(config)  # does not raise: the mount is unnecessary
    reports = dep.deployment_reports(config, host="0.0.0.0", port=8787, token_configured=True)
    database = next(r for r in reports if r.name == "database")
    assert "volume is unnecessary" in database.message
    assert "secret" not in json.dumps([r.__dict__ for r in reports])  # the URL is a secret
    compose = dep.compose_document(config)
    assert "secret" not in compose and "${SOBRES_DB_URL}" in compose
    assert "volumes:" not in compose and "no volume is needed" in compose


# ------------------------------------------------------------ runtime posture
def test_container_checks_are_declared_and_skip_outside_the_image(
    make_context: Callable[..., Context],
) -> None:
    names = {c.name for c in all_checks()}
    assert {"data-volume", "container-user"} <= names
    ctx = make_context()
    assert dep.data_volume_status(ctx.config).status == "skip"
    assert dep.container_user_status(ctx.config).status == "skip"


def test_non_root_is_checked_in_the_container(
    env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _container_env(env, tmp_path / "data")
    config = resolve(None, container, path=Path(container["SOBRES_CONFIG_FILE"]))
    monkeypatch.setattr(os, "getuid", lambda: 0)
    root = dep.container_user_status(config)
    assert root.status == "fail" and "uid 1000" in (root.fix_hint or "")
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    assert dep.container_user_status(config).status == "ok"


def test_configuration_comes_from_the_environment_with_cli_precedence(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    container = _container_env(env, tmp_path / "data")
    container["SOBRES_LOG_LEVEL"] = "DEBUG"
    shown = cli("config", "show", "--format", "json", env_extra=container)
    rows = {r["key"]: r for r in json.loads(shown.stdout)["rows"]}
    assert rows["log_level"]["value"] == "DEBUG" and rows["log_level"]["source"] == "env"
    # A --log-level flag still wins, exactly as it does in a shell: the container adds no layer.
    flagged = cli("--log-level", "ERROR", "config", "show", "--format", "json", env_extra=container)
    assert json.loads(flagged.stdout)["rows"]  # ran; DEBUG records did not reach stdout
    assert flagged.stdout.count("\n") <= shown.stdout.count("\n")


def test_logs_are_json_on_stderr_and_the_level_changes_at_runtime(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    container = _container_env(env, tmp_path / "data")
    quiet = cli("cache", "info", "--format", "json", env_extra=container)
    assert quiet.exit_code == 0 and "command.start" not in quiet.stderr
    loud = cli(
        "cache", "info", "--format", "json", env_extra={**container, "SOBRES_LOG_LEVEL": "INFO"}
    )
    line = next(ln for ln in loud.stderr.splitlines() if "command.start" in ln)
    assert json.loads(line)["event"] == "command.start"  # JSON, stderr, no TTY assumed
    json.loads(loud.stdout)  # stdout stays a single document
    assert not list((tmp_path / "data").glob("*.log"))


def test_tracing_is_inert_until_otel_variables_are_set(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    pytest.importorskip("opentelemetry.sdk")
    container = _container_env(env, tmp_path / "data")
    inert = cli("cache", "info", "--format", "json", env_extra=container)
    assert "tracing" not in inert.stderr
    unreachable = {
        **container,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9",
        "OTEL_TRACES_EXPORTER": "otlp",
    }
    result = cli("cache", "info", "--format", "json", env_extra=unreachable)
    assert result.exit_code == 0
    assert json.loads(result.stdout).keys() == json.loads(inert.stdout).keys()
    assert result.stderr.count("tracing.unavailable") <= 1  # warns once, never fails


# ------------------------------------------------------ open and init inside
def test_open_in_the_container_prints_the_host_url_and_never_launches(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.cli.commands import serve as serve_mod

    monkeypatch.setattr(serve_mod.webbrowser, "open", lambda url: pytest.fail("launched"))
    monkeypatch.setattr(serve_mod, "run_server", lambda *a, **k: pytest.fail("started a server"))
    container = _container_env(env, tmp_path / "data")
    result = cli("open", "doctor", env_extra=container)
    assert result.exit_code == 0
    assert "http://localhost:8787/doctor" in result.stderr and "container port" in result.stderr
    published = cli(
        "open", "--port", "9000", env_extra={**container, "SOBRES_PUBLISHED_PORT": "80"}
    )
    assert "http://localhost:80/" in published.stderr and "container port" not in published.stderr


def test_init_in_the_container_never_prompts_and_names_missing_required_values(
    cli: Callable[..., Any],
    env: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sobres import settings as st

    container = _container_env(env, tmp_path / "data")
    monkeypatch.setattr(Context, "build", _interactive_build(Context.build))
    result = cli("init", "--offline", env_extra={**container, "SOBRES_FRED_API_KEY": SENTINEL_KEY})
    assert result.exit_code == 0, result.stderr
    assert "?" not in result.stdout  # no prompt was rendered
    fred = st.get_setting("fred_api_key")
    monkeypatch.setattr(fred, "required", True)
    fresh = _container_env(env, tmp_path / "fresh")  # no config file yet, nothing in the env
    missing = cli("init", "--offline", env_extra={**fresh, "SOBRES_FRED_API_KEY": ""})
    assert missing.exit_code == 3 and "fred_api_key" in missing.stderr


def _interactive_build(original: Callable[..., Any]) -> Callable[..., Any]:
    """Pretend stdin is a TTY: the container must still not prompt."""

    def build(*args: Any, **kwargs: Any) -> Any:
        kwargs["interactive"] = True
        return original(*args, **kwargs)

    return staticmethod(build)  # type: ignore[return-value]


# -------------------------------------------------------------- generated files
def test_compose_is_generated_from_resolved_configuration_without_secrets(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    from sobres.__about__ import __version__

    result = cli(
        "deploy",
        "compose",
        env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY, "SOBRES_LOG_LEVEL": "INFO"},
    )
    assert result.exit_code == 0, result.stderr
    text = result.stdout
    assert f"image: aisolutionslab/sobres:{__version__}" in text
    assert "- sobres-data:/data" in text and '"8787:8787"' in text
    assert 'SOBRES_LOG_LEVEL: "INFO"' in text  # what the CLI resolves right now
    assert "SOBRES_FRED_API_KEY: ${SOBRES_FRED_API_KEY}" in text  # referenced by name
    assert SENTINEL_KEY not in text and "SOBRES_IMPLAUSIBLE_MOVE_THRESHOLD" not in text
    other_port = cli("deploy", "compose", "--port", "9000")
    assert '"9000:9000"' in other_port.stdout and '"--port", "9000"' in other_port.stdout
    assert LEGACY_NAME not in text.lower()


def test_env_template_lists_every_variable_and_no_secret_value(
    cli: Callable[..., Any],
) -> None:
    from sobres.settings import all_settings

    result = cli("deploy", "env", env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY})
    assert result.exit_code == 0
    for setting in all_settings():
        if setting.key != "container":
            assert f"{setting.env}=" in result.stdout, setting.env
            assert setting.description.strip().splitlines()[0][:30] in result.stdout
    assert "# default: WARNING" in result.stdout
    assert SENTINEL_KEY not in result.stdout and "SOBRES_FRED_API_KEY=\n" in result.stdout
    assert "****" + SENTINEL_KEY[-4:] in result.stdout  # recognisable, not usable


def test_preflight_reports_the_deployment_and_calls_out_exposure(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    exposed = cli("deploy", "check", "--offline", "--format", "json")
    assert exposed.exit_code == 1
    doc = json.loads(exposed.stdout)
    checks = {c["name"]: c for c in doc["checks"]}
    assert "python-version" in checks and "db-reachable" in checks  # doctor's checks first
    assert checks["image"]["message"].startswith("aisolutionslab/sobres:")
    assert checks["database"]["status"] == "ok" and "writable" in checks["database"]["message"]
    assert checks["bind"]["message"].startswith("0.0.0.0:8787")
    assert checks["token"]["status"] == "fail"  # an error, not a warning
    assert checks["credentials"]["status"] == "warn"
    rotated = cli("serve", "token", "rotate")
    assert rotated.exit_code == 0
    guarded = cli(
        "deploy",
        "check",
        "--offline",
        "--format",
        "json",
        env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY},
    )
    checks = {c["name"]: c for c in json.loads(guarded.stdout)["checks"]}
    assert checks["token"]["status"] == "ok" and guarded.exit_code == 0
    assert checks["credentials"]["message"] == "present: fred_api_key"  # by key only
    assert SENTINEL_KEY not in guarded.stdout
    loopback = cli("deploy", "check", "--offline", "--host", "127.0.0.1", "--format", "json")
    assert json.loads(loopback.stdout)["checks"]
    assert LEGACY_NAME not in loopback.stdout.lower()


def test_health_command_reports_readiness(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.cli.commands import deploy as deploy_mod

    class _Answer:
        def __init__(self, body: dict[str, Any]) -> None:
            self._body = body

        def json(self) -> dict[str, Any]:
            return self._body

    monkeypatch.setattr(
        deploy_mod.httpx,
        "get",
        lambda url, timeout: _Answer({"app": "sobres", "ready": True, "version": "9"}),
    )
    assert cli("deploy", "health").exit_code == 0
    monkeypatch.setattr(
        deploy_mod.httpx,
        "get",
        lambda url, timeout: _Answer(
            {"app": "sobres", "ready": False, "checks": {"db-schema": "fail"}}
        ),
    )
    result = cli("deploy", "health")
    assert result.exit_code == 1 and "db-schema" in result.stdout
    import httpx

    def _down(url: str, timeout: float) -> Any:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(deploy_mod.httpx, "get", _down)
    assert cli("deploy", "health", "--port", "1").exit_code == 1


def test_upgrade_path_migrates_on_first_open_after_a_backup(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path, fixture_dir: Path
) -> None:
    import shutil
    import sqlite3

    data = tmp_path / "data"
    container = _container_env(env, data)
    old = data / "sobres.db"
    con = sqlite3.connect(old)
    con.executescript((fixture_dir / "schema" / "v1.sql").read_text())
    con.commit()
    con.close()
    result = cli("db", "info", "--format", "json", env_extra=container)
    assert result.exit_code == 0, result.stderr
    rows = {r["item"]: r["value"] for r in json.loads(result.stdout)["rows"]}
    assert rows["schema_version"] >= 2
    assert list(data.glob("sobres.db.bak-*")), list(data.iterdir())  # backed up before migrating
    shutil.rmtree(data)


def test_signals_leave_no_job_running_forever(env: dict[str, str], tmp_path: Path) -> None:
    from sobres.api.jobs import JobRunner
    from sobres.config import resolve
    from sobres.data.storage.base import JobRecord, open_storage

    container = _container_env(env, tmp_path / "data")
    config = resolve(None, container, path=Path(container["SOBRES_CONFIG_FILE"]))
    storage = open_storage(config.db_url)
    try:
        orphan = storage.jobs.create(JobRecord(id="orphan1", command="optimize.risk", params={}))
        storage.jobs.update(orphan.id, state="running", progress=0.4)
        runner = JobRunner(storage, config, container)
        runner.start()
        recovered = storage.jobs.get("orphan1")
        assert recovered is not None and recovered.state == "failed"
        assert recovered.error is not None and "previous process" in recovered.error["message"]
        stuck = storage.jobs.create(JobRecord(id="stuck1", command="optimize.risk", params={}))
        storage.jobs.update(stuck.id, state="running")
        runner.stop(grace=0.1)
        after = storage.jobs.get("stuck1")
        assert (
            after is not None and after.state == "failed" and "shut down" in after.error["message"]
        )  # type: ignore[index]
    finally:
        storage.close()
