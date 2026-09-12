"""Configuration resolution: flag → env → file → default; secrets masked; 0600.

Scenarios: Config file location; Setting a key; Secrets are never echoed;
Precedence.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from sobres.config import (
    config_path,
    default_db_url,
    display_value,
    has_secret_mode,
    mask_secret,
    read_config_file,
    resolve,
    user_config_dir,
    write_config_file,
)
from sobres.core.errors import ConfigurationError
from sobres.settings import FRED_API_KEY, LOG_LEVEL, get_setting


def test_precedence_chain(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config_file(path, {"log_level": "INFO", "fred_api_key": "fromfile"})
    env = {"SOBRES_LOG_LEVEL": "ERROR"}
    cfg = resolve({"log_level": "DEBUG"}, env, path=path)
    assert cfg.get("log_level") == "DEBUG" and cfg.source("log_level") == "flag"
    cfg = resolve({}, env, path=path)
    assert cfg.get("log_level") == "ERROR" and cfg.source("log_level") == "env"
    cfg = resolve({}, {}, path=path)
    assert cfg.get("log_level") == "INFO" and cfg.source("log_level") == "file"
    cfg = resolve({}, {}, path=tmp_path / "missing.toml")
    assert cfg.get("log_level") == "WARNING" and cfg.source("log_level") == "default"
    assert cfg.get("fred_api_key") is None


def test_env_alias_is_accepted_below_primary(tmp_path: Path) -> None:
    cfg = resolve({}, {"FRED_API_KEY": "alias"}, path=tmp_path / "c.toml")
    assert cfg.get(FRED_API_KEY.key) == "alias"
    cfg = resolve(
        {}, {"FRED_API_KEY": "alias", "SOBRES_FRED_API_KEY": "primary"}, path=tmp_path / "c.toml"
    )
    assert cfg.get(FRED_API_KEY.key) == "primary"


def test_secrets_masked() -> None:
    assert mask_secret("abcdef1234") == "****1234"
    assert mask_secret("") == "(unset)"
    assert display_value(FRED_API_KEY, "abcdef1234") == "****1234"
    assert display_value(LOG_LEVEL, "INFO") == "INFO"
    assert display_value(LOG_LEVEL, None) == "(unset)"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_config_file_written_at_0600(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    write_config_file(path, {"fred_api_key": "k", "slow_query_ms": 5, "container": True, "x": None})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert has_secret_mode(path)
    assert read_config_file(path) == {"fred_api_key": "k", "slow_query_ms": 5, "container": True}
    path.chmod(0o644)
    assert not has_secret_mode(path)


def test_config_file_location_defaults_to_user_config_dir() -> None:
    assert config_path({}) == user_config_dir() / "config.toml"
    assert config_path({"SOBRES_CONFIG_FILE": "/tmp/x/c.toml"}) == Path("/tmp/x/c.toml")
    assert user_config_dir().name == "sobres"


def test_default_db_url_is_sqlite_under_sobres_data_dir() -> None:
    url = default_db_url()
    assert url.startswith("sqlite:///")
    assert url.endswith("/sobres/sobres.db") or url.endswith("\\sobres\\sobres.db")


def test_invalid_toml_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ConfigurationError) as exc:
        read_config_file(path)
    assert "sobres init" in str(exc.value)


def test_unknown_key_in_file_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config_file(path, {"bogus": "x"})
    cfg = resolve({}, {}, path=path)
    assert isinstance(cfg.error, ConfigurationError) and "bogus" in str(cfg.error)


def test_type_coercion_and_choices() -> None:
    assert get_setting("slow_query_ms").coerce("12") == 12
    assert get_setting("implausible_move_threshold").coerce("0.3") == 0.3
    assert get_setting("container").coerce("yes") is True
    assert get_setting("container").coerce(False) is False
    with pytest.raises(ConfigurationError):
        get_setting("slow_query_ms").coerce("x")
    with pytest.raises(ConfigurationError):
        get_setting("implausible_move_threshold").coerce("x")
    with pytest.raises(ConfigurationError):
        get_setting("container").coerce("maybe")
    with pytest.raises(ConfigurationError):
        get_setting("log_level").coerce("LOUD")
    with pytest.raises(ConfigurationError):
        get_setting("nope")
