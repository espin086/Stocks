"""``KenFrenchProvider`` against recorded payloads.

Scenarios: Supported models; Decimal convention; Unexpected file layout;
Factors; Recorded payloads.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import httpx
import pytest

from sobres.core.errors import ProviderError
from sobres.data.base import FACTOR_COLUMNS
from sobres.data.cache import ObservationCache
from sobres.data.fixtures import FixtureKenFrenchSource
from sobres.data.ken_french import (
    KenFrenchProvider,
    LiveKenFrenchSource,
    parse_factor_csv,
    unzip_csv,
)
from sobres.data.storage.base import Storage
from tests.data.contracts import contract_test_factor_provider

PROVIDERS = {"ken_french": lambda src: KenFrenchProvider(source=src)}


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_factor_provider_contract(name: str, ken_french_source: FixtureKenFrenchSource) -> None:
    contract_test_factor_provider(PROVIDERS[name](ken_french_source))


def test_ff5_columns_exact(ken_french_source: FixtureKenFrenchSource) -> None:
    provider = KenFrenchProvider(source=ken_french_source)
    for model, columns in FACTOR_COLUMNS.items():
        frame = provider.get_factors(model, "monthly", date(2015, 1, 1), date(2015, 12, 31))  # type: ignore[arg-type]
        assert tuple(frame.columns) == columns and len(frame) == 12
        daily = provider.get_factors(model, "daily", date(2015, 1, 1), date(2015, 1, 31))  # type: ignore[arg-type]
        assert tuple(daily.columns) == columns and len(daily) > 15
    with pytest.raises(ValueError):
        provider.get_factors("ff9", "monthly")  # type: ignore[arg-type]


def test_known_month_matches_published_value(ken_french_source: FixtureKenFrenchSource) -> None:
    """July 1926, the first row of the Fama-French 3-factor file: Mkt-RF 2.96%."""
    frame = KenFrenchProvider(source=ken_french_source).get_factors(
        "ff3", "monthly", date(1926, 7, 1), date(1926, 7, 31)
    )
    row = frame.iloc[0]
    assert frame.index[0] == __import__("pandas").Timestamp("1926-07-31")
    assert row["Mkt-RF"] == pytest.approx(2.96 / 100)
    assert row["SMB"] == pytest.approx(-2.56 / 100)
    assert row["HML"] == pytest.approx(-2.43 / 100)
    assert row["RF"] == pytest.approx(0.22 / 100)


def test_unexpected_layout_raises_provider_error() -> None:
    with pytest.raises(ProviderError, match="unexpected factor columns"):
        parse_factor_csv(
            ",Mkt-RF,SMB,RF\n192607,1,2,3\n", "monthly", ("Mkt-RF", "SMB", "HML", "RF")
        )
    with pytest.raises(ProviderError, match="no monthly table"):
        parse_factor_csv("just some notes\n\n", "monthly", ("Mkt-RF",))
    with pytest.raises(ProviderError, match="no daily table"):
        parse_factor_csv(",Mkt-RF\n192607, 1.0\n", "daily", ("Mkt-RF",))


def test_parser_skips_a_table_of_the_other_frequency() -> None:
    text = "notes\n\n,Mom\n1927,  10.0\n\n,Mom\n192701,   1.5\n192702,  -0.5\n"
    frame = parse_factor_csv(text, "monthly", ("Mom",))
    assert list(frame["Mom"]) == [0.015, -0.005]


def test_cached_through_the_port(
    storage: Storage, ken_french_source: FixtureKenFrenchSource
) -> None:
    provider = KenFrenchProvider(
        source=ken_french_source, cache=ObservationCache(storage.observations)
    )
    first = provider.get_factors("ff5+mom", "monthly", date(2020, 1, 1), date(2020, 12, 31))
    calls = len(ken_french_source.calls)
    again = provider.get_factors("ff5+mom", "monthly", date(2020, 3, 1), date(2020, 6, 30))
    assert len(ken_french_source.calls) == calls and len(again) == 4
    assert list(again.columns) == list(first.columns)


def test_unzip_csv_rules() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("F.CSV", "x")
    assert unzip_csv(buf.getvalue(), "F") == "x"
    with pytest.raises(ProviderError, match="not a zip"):
        unzip_csv(b"nope", "F")
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as z:
        z.writestr("a.csv", "x")
        z.writestr("b.csv", "y")
    with pytest.raises(ProviderError, match="expected one CSV"):
        unzip_csv(two.getvalue(), "F")


class _Transport(httpx.BaseTransport):
    def __init__(self, status: int, content: bytes = b"", exc: Exception | None = None) -> None:
        self.status, self.content, self.exc = status, content, exc

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, content=self.content, request=request)


def test_live_source() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("F.CSV", "csv-text")
    assert (
        LiveKenFrenchSource(httpx.Client(transport=_Transport(200, buf.getvalue()))).csv_text("F")
        == "csv-text"
    )
    with pytest.raises(ProviderError, match="HTTP 404"):
        LiveKenFrenchSource(httpx.Client(transport=_Transport(404))).csv_text("F")
    with pytest.raises(ProviderError, match="ConnectError"):
        LiveKenFrenchSource(
            httpx.Client(transport=_Transport(200, exc=httpx.ConnectError("x")))
        ).csv_text("F")
