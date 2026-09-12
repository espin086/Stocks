"""Deployment: the container's checks and the files the CLI generates for it.

0005's rule is that there is no container-only code path — the image's
entrypoint is ``sobres`` — so what this module adds is *knowledge about the
deployment*: the mount the data lives on, the user the container runs as, the
bind address and whether a token guards it. ``sobres deploy check`` runs
doctor's checks plus these; the container ``HEALTHCHECK`` calls the same health
endpoint the API serves, which runs the same checks.

The generated ``docker-compose.yml`` and ``.env`` reflect the configuration the
CLI resolves right now, so a working local setup produces a matching deployment.
Secrets are referenced by variable name and never embedded: the output is a file
people commit.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sobres.__about__ import __version__
from sobres.api.auth import is_loopback
from sobres.config import Config, mask_secret
from sobres.core.errors import ConfigurationError
from sobres.data.storage.base import url_scheme
from sobres.doctor import Check, CheckReport, CheckResult, declare_check
from sobres.settings import CONTAINER, DB_URL, Setting, all_settings

IMAGE = "aisolutionslab/sobres"
DATA_DIR = Path("/data")
CONTAINER_PORT = 8787
CONTAINER_UID = 1000
CONTAINER_GID = 1000
MOUNT_HINT = f"mount a volume at {DATA_DIR}: docker run -v sobres:{DATA_DIR} ..."


def in_container(config: Config) -> bool:
    return bool(config.get(CONTAINER.key))


def _sqlite_file(db_url: str) -> Path | None:
    if url_scheme(db_url) != "sqlite":
        return None
    raw = db_url.split("://", 1)[1]
    if raw.startswith("//"):  # sqlite:////abs/path.db — an absolute path
        return Path(raw[1:])
    if raw.startswith("/"):  # sqlite:///rel/path.db — relative to the working directory
        return Path(raw[1:]).resolve()
    return Path(raw).resolve() if raw else None


def data_volume_status(config: Config) -> CheckResult:
    """Is the database's directory writable? Outside a container this is a skip."""
    if not in_container(config):
        return CheckResult("skip", "not running in the container image")
    path = _sqlite_file(config.db_url)
    if path is None:
        return CheckResult(
            "ok",
            f"external backend {url_scheme(config.db_url)}: {DATA_DIR} is not needed",
            detail={"volume_needed": False},
        )
    directory = path.parent
    while not directory.exists() and directory != directory.parent:
        directory = directory.parent  # the adapter creates missing directories on open
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        return CheckResult(
            "fail",
            f"{directory} is not writable: the database cannot be persisted there",
            MOUNT_HINT,
            detail={"path": str(path), "volume_needed": True},
        )
    return CheckResult(
        "ok",
        f"database {path} on a writable mount",
        detail={"path": str(path), "volume_needed": True},
    )


def require_data_volume(config: Config) -> None:
    """Fail loudly at startup rather than persist into the container layer."""
    result = data_volume_status(config)
    if result.status == "fail":
        raise ConfigurationError(result.message, hint=result.fix_hint)


def container_user_status(config: Config) -> CheckResult:
    if not in_container(config):
        return CheckResult("skip", "not running in the container image")
    uid = os.getuid()
    if uid == 0:
        return CheckResult(
            "fail",
            "running as root: files written to the volume will be root-owned",
            f"drop --user; the image runs as uid {CONTAINER_UID} (gid {CONTAINER_GID})",
        )
    return CheckResult("ok", f"running as uid {uid}", detail={"uid": uid})


declare_check(Check("data-volume", "deployment", lambda ctx: data_volume_status(ctx.config)))
declare_check(Check("container-user", "deployment", lambda ctx: container_user_status(ctx.config)))


# --------------------------------------------------------------------------- #
# sobres deploy check
# --------------------------------------------------------------------------- #


def _report(name: str, result: CheckResult) -> CheckReport:
    return CheckReport(
        name,
        "deployment",
        result.status,
        result.message,
        result.fix_hint,
        None,
        dict(result.detail),
    )


def deployment_reports(
    config: Config, *, host: str, port: int, token_configured: bool
) -> list[CheckReport]:
    """The deployment-specific lines: image, bind, exposure, credentials by key."""
    reports = [
        _report("image", CheckResult("ok", f"{IMAGE}:{__version__}", detail={"image": IMAGE})),
    ]
    path = _sqlite_file(config.db_url)
    if path is None:
        reports.append(
            _report(
                "database",
                CheckResult(
                    "ok",
                    f"external backend {url_scheme(config.db_url)}; "
                    "the /data volume is unnecessary",
                    detail={"volume_needed": False},
                ),
            )
        )
    else:
        writable = path.parent.is_dir() and os.access(path.parent, os.W_OK)
        reports.append(
            _report(
                "database",
                CheckResult(
                    "ok" if writable else "fail",
                    f"sqlite {path} ({'writable' if writable else 'not writable'})",
                    None if writable else MOUNT_HINT,
                    detail={"path": str(path), "volume_needed": True},
                ),
            )
        )
    loopback = is_loopback(host)
    reports.append(
        _report(
            "bind",
            CheckResult(
                "ok",
                f"{host}:{port} ({'loopback' if loopback else 'reachable from the network'})",
                detail={"host": host, "port": port},
            ),
        )
    )
    if loopback:
        token = CheckResult("ok", "token not required on loopback")
    elif token_configured:
        token = CheckResult("ok", "token required and configured (stored hashed)")
    else:
        token = CheckResult(
            "fail",
            f"{host} is reachable from the network and no deployment token is configured",
            "run once: sobres serve token rotate  (or start `sobres serve --host` once)",
        )
    reports.append(_report("token", token))
    present = [
        s.key for s in all_settings() if s.secret and s.key != DB_URL.key and config.get(s.key)
    ]
    reports.append(
        _report(
            "credentials",
            CheckResult(
                "ok" if present else "warn",
                "present: " + ", ".join(present) if present else "no API keys configured",
                None if present else "keyless providers still work; see sobres config show",
                detail={"present": present},
            ),
        )
    )
    return reports


# --------------------------------------------------------------------------- #
# Generated files
# --------------------------------------------------------------------------- #


def _yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def compose_document(config: Config, *, port: int = CONTAINER_PORT, host: str = "0.0.0.0") -> str:
    """A compose file for the running version: /data mounted, the port published.

    Secrets are referenced as ``${VAR}``; non-secret settings the user has set
    are written inline so the deployment matches the local setup.
    """
    env_lines: list[str] = []
    for setting in all_settings():
        if setting.key in (CONTAINER.key, DB_URL.key) or setting.standard:
            continue
        value = config.get(setting.key)
        if setting.secret:
            if value:
                env_lines.append(f"      {setting.env}: ${{{setting.env}}}")
            continue
        if value is None or config.source(setting.key) == "default":
            continue
        if setting.key in ("config_file", "fixture_dir"):
            continue  # paths on this machine mean nothing inside the container
        env_lines.append(f"      {setting.env}: {_yaml_str(str(value))}")
    external = _sqlite_file(config.db_url) is None
    if external:
        env_lines.append(f"      {DB_URL.env}: ${{{DB_URL.env}}}")
    lines = [
        f"# Generated by `sobres deploy compose` for sobres {__version__}.",
        "# Secrets are referenced from the environment (see `sobres deploy env`), never embedded.",
        "services:",
        "  sobres:",
        f"    image: {IMAGE}:{__version__}",
        f'    command: ["serve", "--host", "{host}", "--port", "{port}"]',
        "    ports:",
        f'      - "{port}:{port}"',
    ]
    if not external:
        lines += ["    volumes:", "      - sobres-data:/data"]
    if env_lines:
        lines += ["    environment:", *env_lines]
    lines += [
        "    restart: unless-stopped",
        "    healthcheck:",
        f'      test: ["CMD", "sobres", "deploy", "health", "--port", "{port}"]',
        "      interval: 30s",
        "      timeout: 5s",
        "      retries: 3",
    ]
    if not external:
        lines += ["volumes:", "  sobres-data:"]
    else:
        lines.append(f"# {DB_URL.env} names an external backend: no volume is needed.")
    return "\n".join(lines) + "\n"


def env_template(config: Config, settings: Iterable[Setting] | None = None) -> str:
    """Every recognized variable with its default and description; secrets left blank."""
    out = [
        f"# sobres {__version__} environment template (`sobres deploy env`).",
        "# Copy to .env beside docker-compose.yml; secrets are never written here.",
        "",
    ]
    for setting in settings or all_settings():
        if setting.key == CONTAINER.key:
            continue
        out.append(f"# {setting.description.strip()}")
        default = "" if setting.default in (None, False) else str(setting.default)
        out.append(f"# default: {default or '(unset)'}")
        if setting.secret:
            configured = config.get(setting.key)
            if configured:
                out.append(f"# currently configured ({mask_secret(configured)}); value not written")
            out.append(f"{setting.env}=")
        elif setting.standard:
            out.append(
                f"{setting.env}="
            )  # OTEL_*: the collector is the deployment's, not this machine's
        else:
            value = config.get(setting.key)
            out.append(f"{setting.env}={'' if value is None else value}")
        out.append("")
    return "\n".join(out)


def host_url(port: int, environ: Mapping[str, str]) -> tuple[str, str | None]:
    """The URL a person on the host reaches the UI at, and a note when it is a guess."""
    published = environ.get("SOBRES_PUBLISHED_PORT", "").strip()
    if published.isdigit():
        return f"http://localhost:{published}", None
    return (
        f"http://localhost:{port}",
        f"{port} is the container port; use the host port you published with -p <host>:{port}",
    )


def as_dicts(reports: Iterable[CheckReport]) -> list[dict[str, Any]]:
    return [r.__dict__ for r in reports]
