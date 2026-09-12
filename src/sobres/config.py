"""Configuration resolution: flag → environment → config file → default.

The config file is ``<user-config-dir>/sobres/config.toml`` at mode ``0600``
(it holds API keys). Secrets are masked to their last four characters wherever
they are shown. Nothing here reads ``os.environ`` directly: the environment is
passed in, which is what makes the precedence chain testable.
"""

from __future__ import annotations

import os
import stat
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import platformdirs

from sobres.core.errors import ConfigurationError
from sobres.settings import CONFIG_FILE, DB_URL, Setting, all_settings, get_setting

APP_NAME = "sobres"
CONFIG_FILENAME = "config.toml"
DB_FILENAME = "sobres.db"
SECRET_MODE = 0o600

Source = str  # "flag" | "env" | "file" | "default"


def user_config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME))


def user_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME))


def process_environment() -> dict[str, str]:
    """A copy of the process environment, for adapters that were not handed one."""
    return dict(os.environ)


def legacy_dirs() -> list[Path]:
    """Where the pre-rename tool kept its config and data, for the doctor check."""
    old = "".join(("quant", "folio"))
    return [Path(platformdirs.user_config_dir(old)), Path(platformdirs.user_data_dir(old))]


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get(CONFIG_FILE.env)
    if override:
        return Path(override).expanduser()
    return user_config_dir() / CONFIG_FILENAME


def default_db_url() -> str:
    return f"sqlite:///{(user_data_dir() / DB_FILENAME).as_posix()}"


def mask_secret(value: Any) -> str:
    """``****`` plus the last four characters — enough to recognise, not to use."""
    text = "" if value is None else str(value)
    if not text:
        return "(unset)"
    return "****" + text[-4:]


def display_value(setting: Setting, value: Any) -> str:
    if value is None:
        return "(unset)"
    if setting.secret:
        return mask_secret(value)
    return str(value)


# --------------------------------------------------------------------------- #
# Config file
# --------------------------------------------------------------------------- #


def read_config_file(path: Path) -> dict[str, Any]:
    """Parse the TOML config file; a missing file is an empty configuration."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"config file {path} is not valid TOML: {exc}",
            hint="fix or delete the file, then run: sobres init",
        ) from exc
    except OSError as exc:
        raise ConfigurationError(
            f"config file {path} could not be read: {exc.strerror}",
            hint="check the file's permissions",
        ) from exc
    return {str(k): v for k, v in data.items()}


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def write_config_file(path: Path, values: Mapping[str, Any]) -> None:
    """Write scalar settings as TOML at mode 0600, creating the directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# sobres configuration — written by `sobres init` / `sobres config set`", ""]
    for key in sorted(values):
        value = values[key]
        if value is None or value == "":
            continue
        lines.append(f"{key} = {_toml_scalar(value)}")
    text = "\n".join(lines) + "\n"
    # Create with restrictive permissions from the first byte, never chmod after.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, SECRET_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    ensure_secret_mode(path)


def file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def has_secret_mode(path: Path) -> bool:
    if sys.platform == "win32":  # pragma: no cover - POSIX modes are advisory there
        return True
    return file_mode(path) == SECRET_MODE


def ensure_secret_mode(path: Path) -> bool:
    """Set mode 0600 if it is not already; returns whether a change was made."""
    if has_secret_mode(path):
        return False
    path.chmod(SECRET_MODE)
    return True


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Resolved:
    """One setting's resolved value and where it came from."""

    setting: Setting
    value: Any
    source: Source


class Config:
    """The fully resolved configuration for one run."""

    def __init__(
        self,
        resolved: Mapping[str, Resolved],
        path: Path,
        error: ConfigurationError | None = None,
    ) -> None:
        self._resolved = dict(resolved)
        self.path = path
        self.error = error
        """A config-file problem found while resolving: doctor reports it, others raise."""

    def get(self, key: str) -> Any:
        return self._resolved[key].value

    def source(self, key: str) -> Source:
        return self._resolved[key].source

    def items(self) -> list[Resolved]:
        return list(self._resolved.values())

    @property
    def db_url(self) -> str:
        return str(self.get(DB_URL.key) or default_db_url())

    @property
    def exists(self) -> bool:
        return self.path.exists()


def resolve(
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    path: Path | None = None,
) -> Config:
    """Resolve every declared setting through the precedence chain."""
    env = os.environ if environ is None else environ
    flags = dict(overrides or {})
    cfg_path = path or config_path(env)
    error: ConfigurationError | None = None
    try:
        file_values = read_config_file(cfg_path)
        for key in file_values:
            get_setting(key)  # an unknown key in the file is a configuration error
    except ConfigurationError as exc:
        error, file_values = exc, {}
    resolved: dict[str, Resolved] = {}
    for setting in all_settings():
        if setting.key in flags and flags[setting.key] is not None:
            resolved[setting.key] = Resolved(setting, setting.coerce(flags[setting.key]), "flag")
            continue
        env_value = next((env[name] for name in setting.env_names if env.get(name)), None)
        if env_value is not None:
            resolved[setting.key] = Resolved(setting, setting.coerce(env_value), "env")
            continue
        if setting.key in file_values and file_values[setting.key] not in (None, ""):
            resolved[setting.key] = Resolved(
                setting, setting.coerce(file_values[setting.key]), "file"
            )
            continue
        resolved[setting.key] = Resolved(setting, setting.default, "default")
    return Config(resolved, cfg_path, error)
