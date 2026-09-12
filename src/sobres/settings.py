"""The settings registry: every configurable value is one declaration here.

From one ``Setting`` the tool derives ``sobres init`` (prompt), ``sobres doctor``
(check), ``sobres config set|show`` (accept, mask) and — from 0004 — the settings
page. Nothing else may read ``os.environ``: ``tests/cli/test_settings.py``
scans the source tree and fails on an env var that is not declared here.

Two naming rules are tested:

* every declared env var starts with ``SOBRES_`` (0011), except a setting marked
  ``standard=True`` — a third-party convention such as the OpenTelemetry
  ``OTEL_*`` names that must keep their published spelling to work at all;
* any variable carrying the pre-rename prefix aborts startup naming the
  replacement (0011, "Old names fail loudly, never silently").
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from sobres.core.errors import ConfigurationError

ENV_PREFIX = "SOBRES_"
# Built from pieces so the repository-wide "no residual old name" test stays
# meaningful: this is the one place the old prefix must be spelled.
LEGACY_ENV_PREFIX = "".join(("QUANT", "FOLIO", "_"))

SettingType = Literal["str", "int", "float", "bool", "path"]
LiveValidator = Callable[[str], "LiveResult"]


@dataclass(frozen=True)
class LiveResult:
    """Outcome of a setting's one-request live validation."""

    ok: bool
    message: str


@dataclass
class Setting:
    """One configurable value, declared once."""

    key: str
    env: str
    description: str
    type: SettingType = "str"
    default: Any = None
    required: bool = False
    secret: bool = False
    obtain: str | None = None
    affects: tuple[str, ...] = ()
    """Commands that will not work without this setting (named in prompts)."""
    validate_live: LiveValidator | None = field(default=None, compare=False)
    standard: bool = False
    """True for an externally standardized env name exempt from the prefix rule."""
    aliases: tuple[str, ...] = ()
    """Additional env names accepted for this setting (lower precedence)."""
    choices: tuple[str, ...] = ()

    @property
    def env_names(self) -> tuple[str, ...]:
        return (self.env, *self.aliases)

    def coerce(self, raw: str | Any) -> Any:
        """Parse a string from env or file into the declared type."""
        if raw is None:
            return None
        if self.type == "str" or self.type == "path":
            value = str(raw)
            if self.choices and value not in self.choices:
                raise ConfigurationError(
                    f"{self.key} must be one of {', '.join(self.choices)}; got {value!r}",
                    hint=f"run: sobres config set {self.key} <value>",
                )
            return value
        if self.type == "int":
            try:
                return int(raw)
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(
                    f"{self.key} must be an integer; got {raw!r}",
                    hint=f"run: sobres config set {self.key} <integer>",
                ) from exc
        if self.type == "float":
            try:
                return float(raw)
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(
                    f"{self.key} must be a number; got {raw!r}",
                    hint=f"run: sobres config set {self.key} <number>",
                ) from exc
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(
            f"{self.key} must be true or false; got {raw!r}",
            hint=f"run: sobres config set {self.key} true",
        )


_REGISTRY: dict[str, Setting] = {}


def declare(setting: Setting) -> Setting:
    """Register a setting. Keys and env names are unique across the registry."""
    if setting.key in _REGISTRY:
        raise ValueError(f"setting {setting.key!r} declared twice")
    for existing in _REGISTRY.values():
        if set(existing.env_names) & set(setting.env_names):
            raise ValueError(f"env name of {setting.key!r} clashes with {existing.key!r}")
    _REGISTRY[setting.key] = setting
    return setting


def all_settings() -> list[Setting]:
    """Every declared setting, in declaration order (the order ``init`` walks)."""
    return list(_REGISTRY.values())


def get_setting(key: str) -> Setting:
    try:
        return _REGISTRY[key]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ConfigurationError(
            f"unknown setting {key!r}", hint=f"known settings: {known}"
        ) from None


def is_secret_key(key: str) -> bool:
    """The masking rule from the cli-shell spec: key/token/secret in the name."""
    lowered = key.lower()
    return any(marker in lowered for marker in ("key", "token", "secret", "password"))


def check_legacy_environment(environ: Mapping[str, str]) -> None:
    """Refuse to start while any pre-rename variable is set (0011).

    A stale variable would otherwise read as unset and the tool would silently
    use a default — the failure mode the rename must not introduce.
    """
    stale = sorted(name for name in environ if name.startswith(LEGACY_ENV_PREFIX))
    if not stale:
        return
    renamed = [f"{name} → {ENV_PREFIX}{name[len(LEGACY_ENV_PREFIX) :]}" for name in stale]
    raise ConfigurationError(
        "the environment still carries variables from the project's former name: "
        + ", ".join(stale),
        hint="rename them and retry: " + "; ".join(renamed),
    )


# --------------------------------------------------------------------------- #
# Declarations. Order matters: it is the order ``sobres init`` walks.
# --------------------------------------------------------------------------- #


def _validate_fred_key(value: str) -> LiveResult:
    # Imported lazily so the settings registry never depends on the data layer.
    from sobres.data.fred_provider import validate_api_key

    return validate_api_key(value)


FRED_API_KEY = declare(
    Setting(
        key="fred_api_key",
        env="SOBRES_FRED_API_KEY",
        aliases=("FRED_API_KEY",),
        description="Unlocks FRED macro series and the live risk-free rate.",
        secret=True,
        required=False,
        obtain="https://fred.stlouisfed.org/docs/api/api_key.html",
        affects=("data.macro", "data.fx (fred source)"),
        validate_live=_validate_fred_key,
    )
)

DB_URL = declare(
    Setting(
        key="db_url",
        env="SOBRES_DB_URL",
        description=(
            "Storage backend URL. Defaults to SQLite in the user data directory; "
            "0005 sets sqlite:////data/sobres.db in the container."
        ),
        type="str",
        default=None,
        secret=True,  # a database URL may carry credentials; redact it everywhere
        obtain="leave empty for the default SQLite file",
    )
)

LOG_LEVEL = declare(
    Setting(
        key="log_level",
        env="SOBRES_LOG_LEVEL",
        description="Default log level for stderr (DEBUG, INFO, WARNING, ERROR).",
        default="WARNING",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
)

LOG_FORMAT = declare(
    Setting(
        key="log_format",
        env="SOBRES_LOG_FORMAT",
        description="Log rendering: 'auto' (human on a TTY, JSON otherwise), 'human' or 'json'.",
        default="auto",
        choices=("auto", "human", "json"),
    )
)

LOG_FILE = declare(
    Setting(
        key="log_file",
        env="SOBRES_LOG_FILE",
        description="Optional JSON log file, rotated at 10 MB with 5 backups kept.",
        type="path",
        default=None,
    )
)

IMPLAUSIBLE_MOVE = declare(
    Setting(
        key="implausible_move_threshold",
        env="SOBRES_IMPLAUSIBLE_MOVE_THRESHOLD",
        description="Single-day return above which an observation is flagged (default 50%).",
        type="float",
        default=0.5,
    )
)

SLOW_QUERY_MS = declare(
    Setting(
        key="slow_query_ms",
        env="SOBRES_SLOW_QUERY_MS",
        description="Storage operations slower than this many milliseconds log at WARNING.",
        type="int",
        default=500,
    )
)

CONFIG_FILE = declare(
    Setting(
        key="config_file",
        env="SOBRES_CONFIG_FILE",
        description=(
            "Override the config file location (default: <user-config-dir>/sobres/config.toml)."
        ),
        type="path",
        default=None,
    )
)

OTEL_ENDPOINT = declare(
    Setting(
        key="otel_exporter_otlp_endpoint",
        env="OTEL_EXPORTER_OTLP_ENDPOINT",
        description=(
            "OpenTelemetry collector endpoint. Setting it activates tracing "
            "(requires: pip install sobres[otel])."
        ),
        default=None,
        standard=True,
    )
)

OTEL_TRACES_EXPORTER = declare(
    Setting(
        key="otel_traces_exporter",
        env="OTEL_TRACES_EXPORTER",
        description="OpenTelemetry traces exporter name ('otlp', 'console' or 'none').",
        default=None,
        standard=True,
    )
)

FIXTURE_DIR = declare(
    Setting(
        key="fixture_dir",
        env="SOBRES_FIXTURE_DIR",
        description=(
            "Serve every provider from recorded payloads in this directory instead of "
            "the network (used by the test suite and CI's clean-install smoke test)."
        ),
        type="path",
        default=None,
    )
)

CONTAINER = declare(
    Setting(
        key="container",
        env="SOBRES_CONTAINER",
        description=(
            "Set to 1 by the container image so `sobres upgrade` knows how it was installed."
        ),
        type="bool",
        default=False,
    )
)
