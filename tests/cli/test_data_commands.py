"""``sobres data`` — one test per subcommand x three formats.

Scenarios: Prices; Macro; Factors; Forced refresh; Survivorship is stated, not
hidden; Results state their currency; Conversion is an assumption worth logging.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from tests.conftest import SENTINEL_KEY

CASES = {
    "prices": ["data", "prices", "AAPL", "MSFT", "--start", "2020-01-01", "--end", "2020-03-31"],
    "macro": ["data", "macro", "DGS10", "CPIAUCSL", "--start", "2020-01-01", "--end", "2020-06-30"],
    "factors": [
        "data",
        "factors",
        "--model",
        "ff5",
        "--frequency",
        "monthly",
        "--start",
        "2020-01-01",
        "--end",
        "2020-12-31",
    ],
    "fx": ["data", "fx", "EURUSD", "USD/JPY", "--start", "2020-01-01", "--end", "2020-01-31"],
}
COLUMNS = {
    "prices": ["AAPL", "MSFT"],
    "macro": ["DGS10", "CPIAUCSL"],
    "factors": ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"],
    "fx": ["EURUSD", "USDJPY"],
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("fmt", ["table", "json", "csv"])
def test_data_subcommand_in_every_format(cli: Callable[..., Any], name: str, fmt: str) -> None:
    result = cli(*CASES[name], "--format", fmt, env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY})
    assert result.exit_code == 0, result.stderr
    if fmt == "json":
        doc = json.loads(result.stdout)
        assert doc["columns"] == COLUMNS[name]
        assert doc["rows"] and "index" in doc["rows"][0]
    elif fmt == "csv":
        assert result.stdout.splitlines()[0] == "date," + ",".join(COLUMNS[name])
    else:
        for column in COLUMNS[name]:
            assert column in result.stdout
        assert "source:" in result.stdout


def test_prices_state_currency_and_return_kind(cli: Callable[..., Any]) -> None:
    result = cli(*CASES["prices"], "--format", "table")
    assert "currency: USD" in result.stdout and "total return" in result.stdout
    result = cli(
        "data",
        "prices",
        "AAPL",
        "VOD.L",
        "--start",
        "2020-01-01",
        "--end",
        "2020-01-31",
        "--format",
        "json",
    )
    assert json.loads(result.stdout)["provenance"]["currency"] == {"AAPL": "USD", "VOD.L": "GBP"}


def test_prices_uses_cache_then_refresh(cli: Callable[..., Any]) -> None:
    first = json.loads(cli(*CASES["prices"], "--format", "json").stdout)
    second = json.loads(cli(*CASES["prices"], "--format", "json").stdout)
    assert first["provenance"]["cache"] == "miss" and second["provenance"]["cache"] == "hit"
    assert first["rows"] == second["rows"]
    third = json.loads(cli(*CASES["prices"], "--format", "json", "--refresh").stdout)
    assert third["provenance"]["cache"] == "refresh" and third["rows"] == first["rows"]


def test_macro_without_key_exits_3(cli: Callable[..., Any]) -> None:
    result = cli(*CASES["macro"], env_extra={"SOBRES_FIXTURE_DIR": ""})
    assert result.exit_code == 3
    assert "SOBRES_FRED_API_KEY is not set" in result.stderr
    assert "sobres config set fred_api_key <KEY>" in result.stderr


def test_unknown_ticker_exits_4_naming_it(cli: Callable[..., Any]) -> None:
    result = cli("data", "prices", "AAPL", "ZZZZ", "--start", "2020-01-01")
    assert result.exit_code == 4 and "ZZZZ" in result.stderr


def test_fx_rejects_malformed_pair(cli: Callable[..., Any]) -> None:
    result = cli("data", "fx", "EURUS", "--start", "2020-01-01")
    assert result.exit_code == 2 and "pairs" in result.stderr


def test_factors_notes_decimal_convention(cli: Callable[..., Any]) -> None:
    result = cli(*CASES["factors"], "--format", "table")
    assert "decimal returns" in result.stdout


def test_fx_empty_window_is_a_usage_error(cli: Callable[..., Any]) -> None:
    result = cli("data", "fx", "EURUSD", "--start", "1990-01-01", "--end", "1990-01-10")
    assert result.exit_code in (2, 4)
