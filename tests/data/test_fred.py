"""``FredProvider`` against recorded payloads.

Scenarios: Key present; Key absent; Risk-free rate helper; Provider outage;
Recorded payloads; Macro.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from sobres.core.errors import ConfigurationError, ProviderError, UnknownTickerError
from sobres.data.fixtures import FixtureFredSource
from sobres.data.fred_provider import (
    FredProvider,
    LiveFredSource,
    get_risk_free_rate,
    missing_key_error,
    parse_observations,
    validate_api_key,
)
from tests.data.contracts import contract_test_macro_provider

PROVIDERS = {"fred": lambda src: FredProvider("key", source=src)}


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_macro_provider_contract(name: str, fred_source: FixtureFredSource) -> None:
    contract_test_macro_provider(PROVIDERS[name](fred_source))


def test_missing_key_exits_3_with_guidance() -> None:
    with pytest.raises(ConfigurationError) as exc:
        FredProvider(None)
    err = exc.value
    assert err.exit_code == 3
    text = str(err)
    assert "SOBRES_FRED_API_KEY is not set" in text
    assert "https://fred.stlouisfed.org/docs/api/api_key.html" in text
    assert "sobres config set fred_api_key <KEY>" in text
    assert str(missing_key_error()) == text
    FredProvider(
        "", source=FixtureFredSource(__import__("pathlib").Path("."))
    )  # a source needs no key


def test_key_present_returns_float64_column(fred_source: FixtureFredSource) -> None:
    frame = FredProvider("key", source=fred_source).get_series(
        ["DGS10"], date(2020, 1, 1), date(2020, 1, 31)
    )
    assert str(frame.dtypes["DGS10"]) == "float64"
    assert frame["DGS10"].isna().sum() == 1  # New Year's Day is "." in the payload


def test_risk_free_converted_to_decimal(fred_source: FixtureFredSource) -> None:
    provider = FredProvider("key", source=fred_source)
    rf = get_risk_free_rate(provider, date(2020, 1, 1), date(2020, 3, 31), tenor="3m")
    raw = provider.get_series(["DTB3"], date(2020, 1, 1), date(2020, 3, 31))["DTB3"]
    assert (rf.dropna() == raw.dropna() / 100).all()
    assert rf.dropna().max() < 0.2  # decimal, not percent
    assert rf.name == "rf_3m" and rf.attrs["source"] == "FRED DTB3"
    with pytest.raises(ValueError):
        get_risk_free_rate(provider, date(2020, 1, 1), tenor="2y")


def test_unknown_series_raises(fred_source: FixtureFredSource) -> None:
    with pytest.raises(UnknownTickerError):
        FredProvider("key", source=fred_source).get_series(
            ["NOPE"], date(2020, 1, 1), date(2020, 1, 2)
        )


def test_parse_observations_rules() -> None:
    series = parse_observations(
        "X", [{"date": "2020-01-01", "value": "."}, {"date": "2020-01-02", "value": "1.5"}]
    )
    assert series.isna().iloc[0] and series.iloc[1] == 1.5
    with pytest.raises(ProviderError, match="non-numeric"):
        parse_observations("X", [{"date": "2020-01-01", "value": "abc"}])
    with pytest.raises(ProviderError, match="date"):
        parse_observations("X", [{"value": "1"}])


class _Transport(httpx.BaseTransport):
    def __init__(self, status: int, body: Any, *, raise_exc: Exception | None = None) -> None:
        self.status, self.body, self.raise_exc = status, body, raise_exc
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc is not None:
            raise self.raise_exc
        content = json.dumps(self.body) if isinstance(self.body, dict) else self.body
        return httpx.Response(self.status, content=content, request=request)


def _client(transport: _Transport) -> httpx.Client:
    return httpx.Client(transport=transport)


def test_live_source_parses_and_reports() -> None:
    body = {"observations": [{"date": "2020-01-02", "value": "1.0"}]}
    t = _Transport(200, body)
    rows = LiveFredSource("KEY", _client(t)).observations(
        "DGS10", date(2020, 1, 1), date(2020, 1, 31)
    )
    assert rows == body["observations"]
    assert "api_key=KEY" in str(t.requests[0].url)
    assert (
        LiveFredSource("KEY", _client(_Transport(200, {"observations": []}))).observations(
            "X", date(2020, 1, 1), date(2020, 1, 2)
        )
        == []
    )


@pytest.mark.parametrize(
    ("status", "body", "exc_type"),
    [
        (400, "Bad Request. The series does not exist.", UnknownTickerError),
        (400, "Bad Request. api_key invalid", ConfigurationError),
        (403, "forbidden", ConfigurationError),
        (500, "server error", ProviderError),
        (200, {"nope": 1}, ProviderError),
    ],
)
def test_live_source_error_translation(status: int, body: Any, exc_type: type[Exception]) -> None:
    with pytest.raises(exc_type):
        LiveFredSource("KEY", _client(_Transport(status, body))).observations(
            "X", date(2020, 1, 1), date(2020, 1, 2)
        )


def test_live_source_network_failure_is_provider_error() -> None:
    t = _Transport(200, {}, raise_exc=httpx.ConnectError("down"))
    with pytest.raises(ProviderError, match="ConnectError"):
        LiveFredSource("KEY", _client(t)).observations("X", date(2020, 1, 1), date(2020, 1, 2))


def test_validate_api_key_never_raises() -> None:
    assert validate_api_key("k", _client(_Transport(200, {"seriess": []}))).ok
    assert not validate_api_key("k", _client(_Transport(400, "bad"))).ok
    result = validate_api_key("k", _client(_Transport(200, {}, raise_exc=httpx.ConnectError("x"))))
    assert not result.ok and "ConnectError" in result.message
