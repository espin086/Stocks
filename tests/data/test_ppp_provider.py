"""World Bank, OECD and BIS parsers against recorded payload shapes; the cache path.

Scenarios: Provider protocol; Keyless default; Vintage is carried; Missing
coverage; Real effective exchange rates are taken, not invented.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sobres.core.errors import InsufficientDataError
from sobres.data.cache import ObservationCache
from sobres.data.fixtures import FixtureDocumentSource
from sobres.data.ppp_provider import (
    BisReerProvider,
    OecdPppProvider,
    WorldBankPppProvider,
    parse_bis,
    parse_oecd,
    parse_world_bank,
)
from sobres.data.storage.base import Storage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_world_bank_is_the_keyless_default_and_carries_its_vintage() -> None:
    provider = WorldBankPppProvider(source=FixtureDocumentSource(FIXTURES, "worldbank", "json"))
    frame = provider.get_ppp(["USA", "PRT"], date(2010, 1, 1), date(2024, 12, 31))
    assert list(frame.columns) == ["USA", "PRT"]
    assert frame["USA"].dropna().iloc[-1] == 1.0  # the international dollar
    vintage = frame.attrs["vintage"]["PRT"]
    assert vintage["benchmark_year"] == 2023 and vintage["release_date"] == "2025-07-01"
    assert vintage["reference_period"] == "2010-2023" and "World Bank ICP" in vintage["source"]
    assert frame.attrs["provider"] == "worldbank"


def test_oecd_is_the_alternative_with_the_same_shape() -> None:
    provider = OecdPppProvider(source=FixtureDocumentSource(FIXTURES, "oecd", "csv"))
    frame = provider.get_ppp(["GBR"], date(2010, 1, 1), date(2024, 12, 31))
    assert frame["GBR"].dropna().iloc[-1] > 0
    assert frame.attrs["vintage"]["GBR"]["source"].startswith("OECD PPP")
    assert frame.attrs["vintage"]["GBR"]["release_date"] == "2025-06-15"


def test_missing_coverage_names_the_country_and_what_was_available() -> None:
    provider = WorldBankPppProvider(source=FixtureDocumentSource(FIXTURES, "worldbank", "json"))
    with pytest.raises(InsufficientDataError) as exc:
        provider.get_ppp(["USA", "ZZZ"], date(2010, 1, 1), date(2024, 12, 31))
    assert "ZZZ" in str(exc.value)
    with pytest.raises(InsufficientDataError):
        parse_world_bank("ZZZ", '[{"message":[{"id":"120","value":"Invalid value"}]}]')
    with pytest.raises(InsufficientDataError):
        parse_oecd("ZZZ", "REF_AREA,TIME_PERIOD,OBS_VALUE\n")
    with pytest.raises(InsufficientDataError):
        parse_bis("ZZ", "TIME_PERIOD,OBS_VALUE\n")


def test_reer_is_taken_as_published() -> None:
    provider = BisReerProvider(source=FixtureDocumentSource(FIXTURES, "bis", "csv"))
    frame = provider.get_reer(["US", "GB"], date(2020, 1, 1), date(2020, 12, 31))
    assert list(frame.columns) == ["US", "GB"] and len(frame) == 12
    assert frame.attrs["index_base"] == "2020 = 100" and frame.attrs["provider"] == "bis"
    series = parse_bis("US", (FIXTURES / "bis" / "US.csv").read_text())
    assert series.loc["2020-06-30"] == pytest.approx(100.0, abs=0.01)  # the base month


def test_ppp_goes_through_the_cache_like_any_other_observation(storage: Storage) -> None:
    source = FixtureDocumentSource(FIXTURES, "worldbank", "json")
    cache = ObservationCache(storage.observations)
    provider = WorldBankPppProvider(source=source, cache=cache)
    first = provider.get_ppp(["GBR"], date(2015, 1, 1), date(2024, 12, 31))
    second = provider.get_ppp(["GBR"], date(2015, 1, 1), date(2024, 12, 31))
    assert source.calls == ["GBR"]  # the second read came from storage
    assert first["GBR"].dropna().tolist() == second["GBR"].dropna().tolist()
    assert (
        second.attrs["vintage"]["GBR"]["benchmark_year"] == 2023
    )  # the vintage survived the cache
