"""``sobres config`` group.

Scenarios: Setting a key; Secrets are never echoed; Config file location.
"""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_set_persists_at_0600(cli: Callable[..., Any], env: dict[str, str]) -> None:
    result = cli("config", "set", "fred_api_key", "ABC123XYZ")
    assert (
        result.exit_code == 0 and "****3XYZ" in result.stdout and "ABC123XYZ" not in result.stdout
    )
    path = Path(env["SOBRES_CONFIG_FILE"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'fred_api_key = "ABC123XYZ"' in path.read_text(encoding="utf-8")
    assert cli("config", "path").stdout.strip().endswith("config.toml")


def test_show_masks_api_keys(cli: Callable[..., Any]) -> None:
    cli("config", "set", "fred_api_key", "ABC123XYZ")
    result = cli("config", "show", "--format", "json")
    rows = {r["key"]: r for r in json.loads(result.stdout)["rows"]}
    assert rows["fred_api_key"]["value"] == "****3XYZ"
    assert rows["fred_api_key"]["source"] == "file"
    assert rows["db_url"]["value"].startswith("****")  # a DB URL may carry credentials
    assert rows["log_level"]["value"] == "WARNING" and rows["log_level"]["source"] == "default"
    assert "ABC123XYZ" not in result.stdout
    table = cli("config", "show")
    assert "ABC123XYZ" not in table.stdout and "****3XYZ" in table.stdout


def test_set_validates_key_and_value(cli: Callable[..., Any]) -> None:
    assert cli("config", "set", "nope", "1").exit_code == 3
    bad = cli("config", "set", "log_level", "LOUD")
    assert bad.exit_code == 3 and "DEBUG, INFO" in bad.stderr


def test_unset_removes_key(cli: Callable[..., Any], env: dict[str, str]) -> None:
    cli("config", "set", "log_level", "INFO")
    assert "removed" in cli("config", "unset", "log_level").stdout
    assert "log_level" not in Path(env["SOBRES_CONFIG_FILE"]).read_text(encoding="utf-8")
    assert "was not set" in cli("config", "unset", "log_level").stdout
