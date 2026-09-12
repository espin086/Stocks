"""``sobres cache`` group.

Scenarios: Inspect; Clear; Cache and user data are never conflated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def test_info_reports_size_entries_and_age(cli: Callable[..., Any]) -> None:
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    result = cli("cache", "info", "--format", "json")
    rows = {r["metric"]: r["value"] for r in json.loads(result.stdout)["rows"]}
    assert rows["entries"] > 0 and rows["series"] == 1 and rows["size_bytes"] > 0
    assert rows["oldest_entry_age_days"] is not None
    table = cli("cache", "info", "--format", "table")
    assert "entries" in table.stdout


def test_clear_requires_confirmation(cli: Callable[..., Any]) -> None:
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    declined = cli("cache", "clear", input="n\n")
    assert declined.exit_code == 2 and "cancelled" in declined.stderr
    assert json.loads(cli("cache", "info", "--format", "json").stdout)["rows"][2]["value"] > 0
    accepted = cli("cache", "clear", "--yes")
    assert accepted.exit_code == 0 and "removed" in accepted.stdout
    assert "untouched" in accepted.stdout
    rows = {
        r["metric"]: r["value"]
        for r in json.loads(cli("cache", "info", "--format", "json").stdout)["rows"]
    }
    assert rows["entries"] == 0


def test_clear_scoped_to_provider(cli: Callable[..., Any]) -> None:
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    cli("data", "fx", "EURUSD", "--start", "2020-01-01", "--end", "2020-01-31")
    result = cli("cache", "clear", "--yes", "--provider", "ecb")
    assert "provider ecb" in result.stdout
    rows = {
        r["metric"]: r["value"]
        for r in json.loads(cli("cache", "info", "--format", "json").stdout)["rows"]
    }
    assert rows["series"] == 1
