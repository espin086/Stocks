"""The doctor check registry: every diagnostic is a declared ``Check``.

A check has a name, a category, a ``run`` returning ok / warn / fail / skip
with a message, and an optional idempotent ``fix``. Every failing line carries
its next step — a diagnostic without a fix is a complaint. Network checks are
capped at five seconds and skipped under ``--offline``. No fix ever creates,
changes or deletes a secret.

0005's ``sobres deploy check`` and the container health check run these same
checks rather than their own, so there is one definition of "this install works".
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from sobres.__about__ import __version__
from sobres.config import (
    config_path,
    ensure_secret_mode,
    has_secret_mode,
    legacy_dirs,
    user_config_dir,
)
from sobres.core.errors import SobresError
from sobres.data.providers import PROVIDERS
from sobres.data.storage.base import url_scheme
from sobres.settings import Setting, all_settings, get_setting

Status = Literal["ok", "warn", "fail", "skip"]
NETWORK_TIMEOUT_S = 5.0
PYPI_URL = "https://pypi.org/pypi/sobres/json"
MIN_PYTHON = (3, 11)
MIN_FREE_BYTES = 200 * 1024 * 1024
EXTRAS: dict[str, tuple[str, ...]] = {
    "data": ("yfinance",),
    "econ": ("statsmodels",),
    "opt": ("cvxpy",),
    "otel": ("opentelemetry.sdk",),
    "web": ("fastapi", "uvicorn"),
}


@dataclass(frozen=True)
class CheckResult:
    status: Status
    message: str
    fix_hint: str | None = None
    """The exact command or action that fixes it. Required when status is fail."""
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == "fail" and not self.fix_hint:
            raise ValueError(f"a failing check must carry a next step: {self.message!r}")


@dataclass(frozen=True)
class Check:
    name: str
    category: str
    run: Callable[[Any], CheckResult]
    fix: Callable[[Any], str | None] | None = None
    """Idempotent repair returning what it did, or None when not applicable."""
    network: bool = False
    touches_secret: bool = False  # always False: fixes never write secrets


@dataclass(frozen=True)
class CheckReport:
    name: str
    category: str
    status: Status
    message: str
    fix_hint: str | None
    fixed: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


_CHECKS: list[Check] = []


def declare_check(check: Check) -> Check:
    if any(c.name == check.name for c in _CHECKS):
        raise ValueError(f"check {check.name!r} declared twice")
    _CHECKS.append(check)
    return check


def all_checks() -> list[Check]:
    return list(_CHECKS)


def run_checks(
    ctx: Any,
    *,
    offline: bool = False,
    fix: bool = False,
    only: Sequence[str] | None = None,
) -> list[CheckReport]:
    reports: list[CheckReport] = []
    for check in _CHECKS:
        if only is not None and check.name not in only:
            continue
        if check.network and offline:
            reports.append(
                CheckReport(check.name, check.category, "skip", "skipped (offline)", None)
            )
            continue
        fixed: str | None = None
        try:
            result = check.run(ctx)
            if fix and result.status in ("warn", "fail") and check.fix is not None:
                fixed = check.fix(ctx)
                if fixed is not None:
                    result = check.run(ctx)
        except SobresError as exc:
            result = CheckResult("fail", exc.message, exc.hint or "see the message above")
        except Exception as exc:
            result = CheckResult(
                "fail", f"{type(exc).__name__}: {exc}", "rerun with --debug and report the error"
            )
        reports.append(
            CheckReport(
                check.name,
                check.category,
                result.status,
                result.message,
                result.fix_hint,
                fixed,
                dict(result.detail),
            )
        )
    return reports


def exit_code(reports: Sequence[CheckReport], *, strict: bool = False) -> int:
    if any(r.status == "fail" for r in reports):
        return 1
    if strict and any(r.status == "warn" for r in reports):
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Network helper
# --------------------------------------------------------------------------- #


def _probe(url: str, timeout: float = NETWORK_TIMEOUT_S) -> tuple[bool, str]:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        return False, f"unreachable ({type(exc).__name__})"
    if response.status_code >= 500:
        return False, f"HTTP {response.status_code}"
    return True, f"HTTP {response.status_code}"


# --------------------------------------------------------------------------- #
# 0001 checks
# --------------------------------------------------------------------------- #


def _python_version(ctx: Any) -> CheckResult:
    version = sys.version_info[:3]
    text = ".".join(str(v) for v in version)
    if version[:2] < MIN_PYTHON:
        return CheckResult(
            "fail",
            f"Python {text} is below the minimum {'.'.join(map(str, MIN_PYTHON))}",
            "install Python 3.11 or newer and reinstall sobres",
        )
    return CheckResult("ok", f"Python {text}")


declare_check(Check("python-version", "runtime", _python_version))


def _installed_version(ctx: Any) -> CheckResult:
    return CheckResult("ok", f"sobres {__version__}")


declare_check(Check("sobres-version", "runtime", _installed_version))


def latest_release(timeout: float = NETWORK_TIMEOUT_S) -> str | None:
    """The newest version on PyPI, or None when unknown. Never raises."""
    try:
        response = httpx.get(PYPI_URL, timeout=timeout)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return str(response.json()["info"]["version"])
    except (KeyError, ValueError, TypeError):
        return None


def _newer_release(ctx: Any) -> CheckResult:
    latest = latest_release()
    if latest is None:
        return CheckResult("skip", "could not query PyPI for a newer release")
    if _version_tuple(latest) > _version_tuple(__version__):
        return CheckResult(
            "warn", f"sobres {latest} is available (installed {__version__})", "run: sobres upgrade"
        )
    return CheckResult("ok", f"up to date (latest on PyPI: {latest})")


def _version_tuple(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


declare_check(Check("newer-release", "runtime", _newer_release, network=True))


def detect_installer(environ: dict[str, str] | None = None) -> str:
    """pip, pipx, uv or container — detected, not assumed."""
    env = environ if environ is not None else {}
    if (
        env.get("SOBRES_CONTAINER", "").strip().lower() in ("1", "true", "yes")
        or Path("/.dockerenv").exists()
    ):
        return "container"
    prefix = str(sys.prefix).lower()
    if "pipx" in prefix:
        return "pipx"
    if "/uv/" in prefix or "uv/tools" in prefix or env.get("UV_TOOL_DIR"):
        return "uv"
    return "pip"


UPGRADE_COMMANDS: dict[str, str] = {
    "pip": f"{sys.executable} -m pip install --upgrade sobres",
    "pipx": "pipx upgrade sobres",
    "uv": "uv tool upgrade sobres",
    "container": "docker pull aisolutionslab/sobres:latest",
}


def _installer(ctx: Any) -> CheckResult:
    name = detect_installer(dict(ctx.environ))
    return CheckResult("ok", f"installed with {name}", detail={"installer": name})


declare_check(Check("installer", "runtime", _installer))


def _config_file(ctx: Any) -> CheckResult:
    path = ctx.config.path
    if not path.exists():
        return CheckResult(
            "warn",
            f"no config file at {path}",
            "run: sobres init  (the tool works without one on keyless providers)",
        )
    if ctx.config.error is not None:
        exc = ctx.config.error
        return CheckResult("fail", exc.message, exc.hint or "run: sobres init")
    if not has_secret_mode(path):
        return CheckResult(
            "fail", f"{path} is not mode 0600", f"run: chmod 600 {path}  (or: sobres doctor --fix)"
        )
    return CheckResult("ok", f"config file {path} (mode 0600)")


def _fix_config_file(ctx: Any) -> str | None:
    path = ctx.config.path
    if not path.exists():
        user_config_dir().mkdir(parents=True, exist_ok=True)
        return None  # creating the file itself would mean writing settings; not ours to do
    return "set mode 0600" if ensure_secret_mode(path) else None


declare_check(Check("config-file", "configuration", _config_file, fix=_fix_config_file))


def _setting_check(setting: Setting) -> Callable[[Any], CheckResult]:
    def run(ctx: Any) -> CheckResult:
        value = ctx.config.get(setting.key)
        source = ctx.config.source(setting.key)
        if value in (None, "") and setting.required:
            return CheckResult(
                "fail",
                f"{setting.key} is required and not set",
                f"run: sobres config set {setting.key} <value>"
                + (f"  (obtain: {setting.obtain})" if setting.obtain else ""),
            )
        if value in (None, ""):
            affected = f"; without it: {', '.join(setting.affects)}" if setting.affects else ""
            return CheckResult(
                "ok" if not setting.affects else "warn",
                f"{setting.key} not set{affected}",
                f"run: sobres config set {setting.key} <value>" if setting.affects else None,
            )
        shown = "present" if setting.secret else str(value)
        return CheckResult("ok", f"{setting.key}: {shown} (from {source})")

    return run


for _setting in all_settings():
    declare_check(Check(f"setting:{_setting.key}", "settings", _setting_check(_setting)))


def _setting_live_check(setting: Setting) -> Callable[[Any], CheckResult]:
    def run(ctx: Any) -> CheckResult:
        value = ctx.config.get(setting.key)
        if value in (None, ""):
            return CheckResult("skip", f"{setting.key} not set; nothing to verify")
        assert setting.validate_live is not None
        outcome = setting.validate_live(str(value))
        if outcome.ok:
            return CheckResult("ok", f"{setting.key}: {outcome.message}")
        return CheckResult(
            "fail",
            f"{setting.key}: {outcome.message}",
            f"run: sobres config set {setting.key} <KEY>  (obtain: {setting.obtain})",
        )

    return run


for _setting in all_settings():
    if _setting.validate_live is not None:
        declare_check(
            Check(
                f"setting-live:{_setting.key}",
                "settings",
                _setting_live_check(_setting),
                network=True,
            )
        )


def _db_url(ctx: Any) -> CheckResult:
    url = ctx.config.db_url
    scheme = url_scheme(url)
    from sobres.data.storage.base import registered_backends

    if scheme not in registered_backends():
        return CheckResult(
            "fail",
            f"no backend for scheme {scheme!r}",
            f"set SOBRES_DB_URL to one of: {', '.join(registered_backends())}",
        )
    return CheckResult("ok", f"backend {scheme}", detail={"url_scheme": scheme})


declare_check(Check("db-url", "storage", _db_url))


def _db_reachable(ctx: Any) -> CheckResult:
    storage = ctx.storage
    if not storage.integrity_check():
        return CheckResult(
            "fail",
            f"database {storage.location} failed its integrity check",
            "run: sobres db repair",
        )
    probe_key = "__doctor_probe__"
    storage.kv.set(probe_key, datetime.now(UTC).isoformat())
    storage.kv.delete(probe_key)
    return CheckResult("ok", f"database {storage.location} readable and writable")


declare_check(Check("db-reachable", "storage", _db_reachable))


def _db_schema(ctx: Any) -> CheckResult:
    storage = ctx.storage
    pending = storage.pending_migrations()
    if pending:
        return CheckResult(
            "fail",
            f"{len(pending)} pending migration(s): {', '.join(pending)}",
            "run: sobres doctor --fix  (or any command; migrations apply on open)",
        )
    return CheckResult("ok", f"schema version {storage.schema_version()} matches the code")


def _fix_db_schema(ctx: Any) -> str | None:
    applied = ctx.storage.migrate()
    return f"applied {', '.join(applied)}" if applied else None


declare_check(Check("db-schema", "storage", _db_schema, fix=_fix_db_schema))


def _cache(ctx: Any) -> CheckResult:
    stats = ctx.storage.observations.cache_stats()
    if stats.entries == 0:
        return CheckResult("ok", "cache is empty")
    age = ""
    if stats.oldest_fetch is not None:
        days = (datetime.now(UTC) - stats.oldest_fetch).days
        age = f", oldest fetch {days}d ago"
    return CheckResult(
        "ok",
        f"{stats.entries:,} observations in {stats.series} series, "
        f"{stats.size_bytes / 1e6:.1f} MB on disk{age}",
    )


declare_check(Check("cache", "storage", _cache))


def _disk_space(ctx: Any) -> CheckResult:
    storage = ctx.storage
    location = Path(storage.location) if storage.location != ":memory:" else Path.cwd()
    probe = location if location.exists() else location.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return CheckResult("skip", "could not determine free disk space")
    free_mb = usage.free / 1e6
    if usage.free < MIN_FREE_BYTES:
        return CheckResult(
            "warn", f"only {free_mb:.0f} MB free at {probe}", "free disk space or move the database"
        )
    return CheckResult("ok", f"{free_mb / 1000:.1f} GB free at {probe}")


declare_check(Check("disk-space", "storage", _disk_space))


def _provider_check(spec: Any) -> Callable[[Any], CheckResult]:
    def run(ctx: Any) -> CheckResult:
        if spec.requires_setting:
            value = ctx.config.get(spec.requires_setting)
            if value in (None, ""):
                return CheckResult(
                    "skip", f"{spec.name}: {spec.requires_setting} not set; reachability not probed"
                )
        ok, text = _probe(spec.reachability_url)
        if not ok:
            return CheckResult(
                "warn", f"{spec.name} {text}", "check your network or proxy; retry later"
            )
        return CheckResult("ok", f"{spec.name} reachable ({text})")

    return run


for _spec in PROVIDERS:
    declare_check(
        Check(f"provider:{_spec.name}", "providers", _provider_check(_spec), network=True)
    )


def _extras(ctx: Any) -> CheckResult:
    installed = [
        name
        for name, modules in EXTRAS.items()
        if all(importlib.util.find_spec(m) is not None for m in modules)
    ]
    missing = [name for name in EXTRAS if name not in installed]
    text = f"installed extras: {', '.join(installed) or 'none'}"
    if "data" not in installed:
        return CheckResult(
            "warn",
            text + " — 'data' is missing so prices cannot be fetched",
            "run: pip install 'sobres[data]'",
        )
    if missing:
        return CheckResult("ok", text + f" (available: {', '.join(missing)})")
    return CheckResult("ok", text)


declare_check(Check("extras", "runtime", _extras))


def _legacy_dirs(ctx: Any) -> CheckResult:
    found = [p for p in legacy_dirs() if p.exists()]
    if not found:
        return CheckResult("ok", "no legacy config or data directories")
    moves = "; ".join(
        f"mv {p} {user_config_dir() if 'config' in str(p) else user_config_dir().parent / 'sobres'}"
        for p in found
    )
    return CheckResult(
        "warn",
        f"legacy directory found: {', '.join(str(p) for p in found)}",
        f"move it yourself if you want the old data: {moves}",
    )


declare_check(Check("legacy-directories", "configuration", _legacy_dirs))


def check_for(name: str) -> Check:
    for check in _CHECKS:
        if check.name == name:
            return check
    raise KeyError(name)


def config_path_for(ctx: Any) -> Path:
    return config_path(ctx.environ)


def setting_for(key: str) -> Setting:
    return get_setting(key)


# The deployment checks (0005) live beside the deployment knowledge; importing
# them here is what registers them, so `sobres doctor` in the container reports
# the data mount and the user it runs as.
from sobres import deploy as _deploy  # noqa: E402

__all__ = ["Check", "CheckReport", "CheckResult", "all_checks", "declare_check", "run_checks"]
_ = _deploy
