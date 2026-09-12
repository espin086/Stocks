"""``EcbProvider`` against recorded payloads.

Scenarios: Provider protocol; Keyless default; Non-trading days; Calendar
mismatch is explicit; Rates are cached like any other observation.
"""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd
import pytest

from sobres.core.errors import ProviderError
from sobres.data.cache import ObservationCache
from sobres.data.currency import CurrencyPair, convert_series
from sobres.data.ecb_provider import EcbProvider, LiveEcbSource, parse_sdmx_csv
from sobres.data.fixtures import FixtureEcbSource
from sobres.data.storage.base import Storage
from tests.data.contracts import contract_test_fx_provider

PROVIDERS = {"ecb": lambda src: EcbProvider(source=src)}


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_fx_provider_contract(name: str, ecb_source: FixtureEcbSource) -> None:
    contract_test_fx_provider(PROVIDERS[name](ecb_source))


def test_keyless_default_quotes_per_euro(ecb_source: FixtureEcbSource) -> None:
    provider = EcbProvider(source=ecb_source)
    assert provider.base_currency == "EUR"
    frame = provider.get_rates(
        [CurrencyPair("EUR", "USD"), "GBPUSD", "eur/eur"], date(2020, 1, 1), date(2020, 1, 31)
    )
    assert list(frame.columns) == ["EURUSD", "GBPUSD", "EUREUR"]
    assert (frame["EUREUR"] == 1.0).all()
    usd = frame["EURUSD"].iloc[0]
    gbp = provider.get_rates(["EURGBP"], date(2020, 1, 1), date(2020, 1, 31))["EURGBP"].iloc[0]
    assert frame["GBPUSD"].iloc[0] == pytest.approx(usd / gbp)


def test_carry_forward_recorded_not_silent(ecb_source: FixtureEcbSource) -> None:
    provider = EcbProvider(source=ecb_source)
    table = provider.rates_table(["USD"], date(2019, 12, 20), date(2020, 1, 31))
    assert table.source == "ECB reference rates"
    # New Year's Day and a weekend: no ECB quote, so the prior quote is carried and recorded.
    prices = pd.Series(
        [1.0, 1.0, 1.0], index=pd.DatetimeIndex(["2020-01-03", "2020-01-04", "2020-01-06"])
    )
    out = convert_series(prices, "EUR", "USD", rates=table)
    assert out.attrs["carry_forward"] == ["2020-01-04"]
    assert out.iloc[1] == out.iloc[0]
    assert table.rate(CurrencyPair("EUR", "USD"), date(2020, 1, 1)) == pytest.approx(
        table.rate(CurrencyPair("EUR", "USD"), date(2019, 12, 31))
    )
    assert table.carry_forwards[-1]["date"] == "2020-01-01"


def test_rates_cached_through_the_port(storage: Storage, ecb_source: FixtureEcbSource) -> None:
    cache = ObservationCache(storage.observations)
    provider = EcbProvider(source=ecb_source, cache=cache)
    provider.get_rates(["EURUSD"], date(2020, 1, 1), date(2020, 1, 31))
    calls = len(ecb_source.calls)
    again = provider.get_rates(["EURUSD"], date(2020, 1, 5), date(2020, 1, 20))
    assert len(ecb_source.calls) == calls and again.attrs["cache"]["status"] == "hit"


def test_unknown_currency_and_empty_window(ecb_source: FixtureEcbSource) -> None:
    provider = EcbProvider(source=ecb_source)
    with pytest.raises(ProviderError, match="no reference rate"):
        provider.get_rates(["EURXXX"], date(2020, 1, 1), date(2020, 1, 31))
    with pytest.raises(ProviderError, match="no USD rates"):
        provider.get_rates(["EURUSD"], date(1990, 1, 1), date(1990, 1, 31))


def test_parse_sdmx_csv_rules() -> None:
    assert parse_sdmx_csv("USD", "").empty
    text = "KEY,TIME_PERIOD,OBS_VALUE\nk,2020-01-02,1.1\nk,2020-01-03,\n"
    series = parse_sdmx_csv("USD", text)
    assert list(series) == [1.1] and series.name == "EURUSD"
    with pytest.raises(ProviderError, match="TIME_PERIOD"):
        parse_sdmx_csv("USD", "a,b\n1,2\n")


class _Transport(httpx.BaseTransport):
    def __init__(self, status: int, text: str = "", exc: Exception | None = None) -> None:
        self.status, self.text, self.exc = status, text, exc

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, text=self.text, request=request)


def test_live_source_errors() -> None:
    ok = LiveEcbSource(httpx.Client(transport=_Transport(200, "KEY,TIME_PERIOD,OBS_VALUE\n")))
    assert ok.csv("USD", date(2020, 1, 1), date(2020, 1, 2)).startswith("KEY")
    with pytest.raises(ProviderError, match="no reference rate"):
        LiveEcbSource(httpx.Client(transport=_Transport(404))).csv(
            "XXX", date(2020, 1, 1), date(2020, 1, 2)
        )
    with pytest.raises(ProviderError, match="HTTP 503"):
        LiveEcbSource(httpx.Client(transport=_Transport(503))).csv(
            "USD", date(2020, 1, 1), date(2020, 1, 2)
        )
    with pytest.raises(ProviderError, match="ConnectError"):
        LiveEcbSource(httpx.Client(transport=_Transport(200, exc=httpx.ConnectError("x")))).csv(
            "USD", date(2020, 1, 1), date(2020, 1, 2)
        )
