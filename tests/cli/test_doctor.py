"""``sobres doctor`` — every line actionable.

Scenarios: Checks are declared, like commands and settings; What is checked in
0001; Every line is actionable; Output; Exit code; Offline; Safe automatic
repair; Secrets never appear; One implementation of health; A legacy data
directory; Installer is detected, not assumed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from sobres import doctor as doc
from sobres.cli.context import Context
from sobres.data.providers import PROVIDERS
from sobres.doctor import Check, CheckResult, all_checks, declare_check, run_checks
from sobres.settings import all_settings
from tests.conftest import SENTINEL_KEY

REQUIRED_CHECKS = {
    "python-version",
    "sobres-version",
    "newer-release",
    "installer",
    "config-file",
    "db-url",
    "db-reachable",
    "db-schema",
    "cache",
    "disk-space",
    "extras",
    "legacy-directories",
}


def test_every_setting_and_provider_has_a_check() -> None:
    names = {c.name for c in all_checks()}
    assert names >= REQUIRED_CHECKS
    for setting in all_settings():
        assert f"setting:{setting.key}" in names
    for spec in PROVIDERS:
        assert f"provider:{spec.name}" in names
    assert not any(c.touches_secret for c in all_checks())


def test_failure_lines_always_carry_a_next_step(cli: Callable[..., Any]) -> None:
    with pytest.raises(ValueError):
        CheckResult("fail", "broken")
    result = cli(
        "doctor", "--offline", "--format", "json", env_extra={"SOBRES_DB_URL": "postgresql://x/y"}
    )
    checks = json.loads(result.stdout)["checks"]
    for c in checks:
        if c["status"] == "fail":
            assert c["fix_hint"], c["name"]
    assert result.exit_code == 1


def test_offline_skips_rather_than_fails(cli: Callable[..., Any]) -> None:
    result = cli("doctor", "--offline", "--format", "json")
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    for spec in PROVIDERS:
        assert checks[f"provider:{spec.name}"]["status"] == "skip"
    assert checks["newer-release"]["status"] == "skip"
    assert result.exit_code == 0


def test_warnings_do_not_change_exit_code_without_strict(cli: Callable[..., Any]) -> None:
    plain = cli("doctor", "--offline", "--format", "json")
    doc_ = json.loads(plain.stdout)
    assert doc_["summary"]["warn"] >= 1 and plain.exit_code == 0  # no config file yet → warn
    strict = cli("doctor", "--offline", "--strict")
    assert strict.exit_code == 1


def test_tty_rendering_groups_by_category(cli: Callable[..., Any]) -> None:
    result = cli("doctor", "--offline", "--format", "table")
    out = result.stdout
    assert "runtime" in out and "storage" in out and "providers" in out
    assert "✔ python-version" in out and "- provider:yfinance" in out
    assert "→ run: sobres init" in out
    assert " ok, " in out and " skipped" in out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_fix_repairs_permissions_and_migrations_but_never_secrets(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    cli("config", "set", "fred_api_key", SENTINEL_KEY)
    path = Path(env["SOBRES_CONFIG_FILE"])
    path.chmod(0o644)
    before = path.read_text(encoding="utf-8")
    broken = cli("doctor", "--offline", "--format", "json")
    checks = {c["name"]: c for c in json.loads(broken.stdout)["checks"]}
    assert (
        checks["config-file"]["status"] == "fail"
        and "chmod 600" in checks["config-file"]["fix_hint"]
    )
    fixed = cli("doctor", "--offline", "--fix", "--format", "json")
    checks = {c["name"]: c for c in json.loads(fixed.stdout)["checks"]}
    assert (
        checks["config-file"]["status"] == "ok"
        and checks["config-file"]["fixed"] == "set mode 0600"
    )
    assert path.read_text(encoding="utf-8") == before  # the secret itself was never touched
    assert SENTINEL_KEY not in fixed.stdout and SENTINEL_KEY not in fixed.stderr
    assert checks["setting:fred_api_key"]["message"] == "fred_api_key: present (from file)"


def test_fix_applies_pending_migrations(
    cli: Callable[..., Any], make_context: Callable[..., Context]
) -> None:
    from sobres.data.storage.base import OpenOptions

    ctx = make_context(open_options=OpenOptions(migrate=False))
    reports = {r.name: r for r in run_checks(ctx, offline=True, only=["db-schema"])}
    assert reports["db-schema"].status == "fail" and "pending" in reports["db-schema"].message
    reports = {r.name: r for r in run_checks(ctx, offline=True, fix=True, only=["db-schema"])}
    assert reports["db-schema"].status == "ok" and reports["db-schema"].fixed.startswith("applied")


def test_secrets_never_appear_in_any_format(cli: Callable[..., Any]) -> None:
    for fmt in ("table", "json", "csv"):
        result = cli(
            "doctor", "--offline", "--format", fmt, env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY}
        )
        assert SENTINEL_KEY not in result.stdout and SENTINEL_KEY not in result.stderr
        assert SENTINEL_KEY[-4:] not in result.stdout


def test_legacy_directory_reports_the_move_without_moving(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy = tmp_path / "old-config"
    legacy.mkdir()
    (legacy / "config.toml").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(doc, "legacy_dirs", lambda: [legacy, tmp_path / "absent"])
    [report] = run_checks(make_context(), offline=True, only=["legacy-directories"])
    assert report.status == "warn"
    assert f"mv {legacy}" in (report.fix_hint or "")
    assert (legacy / "config.toml").exists()  # nothing moved, copied or deleted


def test_installer_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    assert doc.detect_installer({"SOBRES_CONTAINER": "1"}) == "container"
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/pipx/venvs/sobres")
    assert doc.detect_installer({}) == "pipx"
    monkeypatch.setattr(sys, "prefix", "/home/u/.local/share/uv/tools/sobres")
    assert doc.detect_installer({}) == "uv"
    monkeypatch.setattr(sys, "prefix", "/usr")
    assert doc.detect_installer({}) == "pip"
    assert doc.detect_installer({"UV_TOOL_DIR": "/x"}) == "uv"
    assert set(doc.UPGRADE_COMMANDS) == {"pip", "pipx", "uv", "container"}


class _Transport(httpx.BaseTransport):
    def __init__(self, status: int, body: Any = "", exc: Exception | None = None) -> None:
        self.status, self.body, self.exc = status, body, exc

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.exc:
            raise self.exc
        content = json.dumps(self.body) if isinstance(self.body, dict) else self.body
        return httpx.Response(self.status, content=content, request=request)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    client = httpx.Client(transport=transport)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kw: client.get(url, **{k: v for k, v in kw.items() if k != "timeout"}),
    )


def test_network_checks_use_five_second_cap_and_report(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert doc.NETWORK_TIMEOUT_S <= 5
    for check in all_checks():
        if check.network:
            assert check.name.startswith(("provider:", "newer-release", "setting-live:"))
    _patch_httpx(monkeypatch, _Transport(200, {"info": {"version": "99.0.0"}}))
    reports = {
        r.name: r for r in run_checks(make_context(), only=["newer-release", "provider:yfinance"])
    }
    assert reports["newer-release"].status == "warn" and "sobres upgrade" in (
        reports["newer-release"].fix_hint or ""
    )
    assert reports["provider:yfinance"].status == "ok"
    _patch_httpx(monkeypatch, _Transport(200, {"info": {"version": "0.0.1"}}))
    assert run_checks(make_context(), only=["newer-release"])[0].status == "ok"
    _patch_httpx(monkeypatch, _Transport(503, "down"))
    reports = {
        r.name: r for r in run_checks(make_context(), only=["newer-release", "provider:ecb"])
    }
    assert reports["newer-release"].status == "skip" and reports["provider:ecb"].status == "warn"
    _patch_httpx(monkeypatch, _Transport(200, exc=httpx.ConnectError("x")))
    reports = {
        r.name: r for r in run_checks(make_context(), only=["newer-release", "provider:ecb"])
    }
    assert (
        reports["newer-release"].status == "skip"
        and "unreachable" in reports["provider:ecb"].message
    )
    _patch_httpx(monkeypatch, _Transport(200, "not json"))
    assert doc.latest_release() is None


def test_provider_check_skips_when_its_key_is_absent(make_context: Callable[..., Context]) -> None:
    [report] = run_checks(make_context(), only=["provider:fred"])
    assert report.status == "skip" and "fred_api_key" in report.message


def test_live_setting_check_paths(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.settings import LiveResult, get_setting

    [skipped] = run_checks(make_context(), only=["setting-live:fred_api_key"])
    assert skipped.status == "skip"
    fred = get_setting("fred_api_key")
    monkeypatch.setattr(fred, "validate_live", lambda v: LiveResult(False, "rejected"))
    ctx = make_context(environ={"SOBRES_FRED_API_KEY": "bad"})
    [failed] = run_checks(ctx, only=["setting-live:fred_api_key"])
    assert failed.status == "fail" and "sobres config set fred_api_key" in (failed.fix_hint or "")
    monkeypatch.setattr(fred, "validate_live", lambda v: LiveResult(True, "accepted"))
    [ok] = run_checks(ctx, only=["setting-live:fred_api_key"])
    assert ok.status == "ok"


def test_check_exceptions_never_take_doctor_down(make_context: Callable[..., Context]) -> None:
    def explode(ctx: Any) -> CheckResult:
        raise RuntimeError("boom")

    def refuse(ctx: Any) -> CheckResult:
        from sobres.core.errors import ConfigurationError

        raise ConfigurationError("nope", hint="do this")

    declare_check(Check("test-explode", "test", explode))
    declare_check(Check("test-refuse", "test", refuse))
    try:
        reports = {
            r.name: r for r in run_checks(make_context(), only=["test-explode", "test-refuse"])
        }
        assert (
            reports["test-explode"].status == "fail"
            and "RuntimeError" in reports["test-explode"].message
        )
        assert reports["test-refuse"].fix_hint == "do this"
        with pytest.raises(ValueError, match="declared twice"):
            declare_check(Check("test-explode", "test", explode))
    finally:
        doc._CHECKS[:] = [c for c in doc._CHECKS if not c.name.startswith("test-")]


def test_disk_space_and_extras_and_python(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import sys

    ctx = make_context()
    assert run_checks(ctx, only=["disk-space"])[0].status == "ok"
    monkeypatch.setattr(
        shutil, "disk_usage", lambda p: type("U", (), {"free": 1, "total": 1, "used": 0})()
    )
    assert run_checks(ctx, only=["disk-space"])[0].status == "warn"

    def raising(p: Any) -> Any:
        raise OSError("nope")

    monkeypatch.setattr(shutil, "disk_usage", raising)
    assert run_checks(ctx, only=["disk-space"])[0].status == "skip"
    monkeypatch.setattr(doc, "EXTRAS", {"data": ("definitely_not_installed_module",)})
    assert run_checks(ctx, only=["extras"])[0].status == "warn"
    monkeypatch.setattr(doc, "EXTRAS", {"data": ("json",), "web": ("nope_module",)})
    assert "available: web" in run_checks(ctx, only=["extras"])[0].message
    monkeypatch.setattr(doc, "EXTRAS", {"data": ("json",)})
    assert run_checks(ctx, only=["extras"])[0].status == "ok"
    monkeypatch.setattr(sys, "version_info", (3, 9, 0))
    assert run_checks(ctx, only=["python-version"])[0].status == "fail"


def test_config_file_check_paths(make_context: Callable[..., Context], env: dict[str, str]) -> None:
    path = Path(env["SOBRES_CONFIG_FILE"])
    ctx = make_context()
    assert run_checks(ctx, only=["config-file"])[0].status == "warn"
    [report] = run_checks(ctx, only=["config-file"], fix=True)
    assert report.fixed is None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("bad = [\n", encoding="utf-8")
    path.chmod(0o600)
    assert run_checks(make_context(), only=["config-file"])[0].status == "fail"


def test_db_reachable_reports_corruption(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = make_context()
    monkeypatch.setattr(type(ctx.storage), "integrity_check", lambda self: False)
    [report] = run_checks(ctx, only=["db-reachable"])
    assert report.status == "fail" and "sobres db repair" in (report.fix_hint or "")


def test_cache_check_reports_age(cli: Callable[..., Any]) -> None:
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    result = cli("doctor", "--offline", "--format", "json")
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert (
        "observations" in checks["cache"]["message"]
        and "oldest fetch" in checks["cache"]["message"]
    )
    assert checks["installer"]["detail"]["installer"] in {"pip", "pipx", "uv", "container"}
