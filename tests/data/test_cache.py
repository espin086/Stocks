"""The observation cache over the storage port.

Scenarios: Cache hit; Partial-range reuse; Forced refresh; Observation
identity; Concurrent access; Rates are cached like any other observation;
Provider calls.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from sobres.data.cache import TTL_SECONDS, ObservationCache, missing_ranges, ttl_for
from sobres.data.storage.base import DateRange, Storage

D = date


def _fetcher(calls: list[tuple[list[str], date, date]]) -> Callable[..., pd.DataFrame]:
    def fetch(symbols: list[str], start: date, end: date) -> pd.DataFrame:
        calls.append((list(symbols), start, end))
        index = pd.bdate_range(start, end, name="date")
        frame = pd.DataFrame(
            {s: [float(i + 1) for i in range(len(index))] for s in symbols}, index=index
        )
        frame.attrs["series_meta"] = {s: {"currency": "USD"} for s in symbols}
        return frame

    return fetch


@pytest.fixture
def clock() -> list[datetime]:
    return [datetime(2024, 6, 1, tzinfo=UTC)]


@pytest.fixture
def cache(storage: Storage, clock: list[datetime]) -> ObservationCache:
    return ObservationCache(storage.observations, clock=lambda: clock[0])


def test_hit_avoids_fetch(cache: ObservationCache) -> None:
    calls: list[tuple[list[str], date, date]] = []
    first = cache.get(
        "p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls)
    )
    assert first.attrs["cache"]["status"] == "miss" and len(calls) == 1
    second = cache.get(
        "p", "prices_adj_close", ["aapl"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls)
    )
    assert second.attrs["cache"]["status"] == "hit" and len(calls) == 1
    pd.testing.assert_frame_equal(first, second)
    assert second.attrs["series_meta"] == {"AAPL": {"currency": "USD"}}


def test_subrange_of_cached_range_makes_no_network_call(cache: ObservationCache) -> None:
    calls: list[tuple[list[str], date, date]] = []
    cache.get("p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 12, 31), _fetcher(calls))
    out = cache.get(
        "p", "prices_adj_close", ["AAPL"], D(2020, 3, 1), D(2020, 3, 31), _fetcher(calls)
    )
    assert len(calls) == 1 and out.attrs["cache"]["status"] == "hit"
    assert out.index.min() >= pd.Timestamp("2020-03-01") and out.index.max() <= pd.Timestamp(
        "2020-03-31"
    )


def test_extension_fetches_only_the_missing_tail(cache: ObservationCache) -> None:
    calls: list[tuple[list[str], date, date]] = []
    cache.get("p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 6, 30), _fetcher(calls))
    out = cache.get(
        "p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 9, 30), _fetcher(calls)
    )
    assert len(calls) == 2
    assert calls[1] == (["AAPL"], D(2020, 7, 1), D(2020, 9, 30))
    assert out.attrs["cache"]["status"] == "partial"
    assert out.attrs["cache"]["fetched"] == [("2020-07-01", "2020-09-30")]


def test_new_symbol_alongside_cached_one_fetches_only_the_new(cache: ObservationCache) -> None:
    calls: list[tuple[list[str], date, date]] = []
    cache.get("p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls))
    out = cache.get(
        "p", "prices_adj_close", ["AAPL", "MSFT"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls)
    )
    assert calls[1][0] == ["MSFT"]
    assert list(out.columns) == ["AAPL", "MSFT"]


def test_ttl_expiry(cache: ObservationCache, clock: list[datetime]) -> None:
    calls: list[tuple[list[str], date, date]] = []
    cache.get("p", "macro", ["DGS10"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls))
    clock[0] += timedelta(hours=23)
    cache.get("p", "macro", ["DGS10"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls))
    assert len(calls) == 1
    clock[0] += timedelta(hours=2)
    out = cache.get("p", "macro", ["DGS10"], D(2020, 1, 1), D(2020, 1, 31), _fetcher(calls))
    assert len(calls) == 2 and out.attrs["cache"]["status"] == "miss"


def test_refetch_overwrites_revised_values(cache: ObservationCache) -> None:
    calls: list[tuple[list[str], date, date]] = []
    first = cache.get(
        "p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 1, 10), _fetcher(calls)
    )

    def revised(symbols: list[str], start: date, end: date) -> pd.DataFrame:
        frame = _fetcher(calls)(symbols, start, end)
        return frame * 10

    out = cache.get(
        "p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 1, 10), revised, refresh=True
    )
    assert out.attrs["cache"]["status"] == "refresh"
    assert (out["AAPL"] == first["AAPL"] * 10).all()
    assert len(out) == len(first)  # overwritten in place, not duplicated


def test_ttl_policy_by_dataset() -> None:
    today = D(2024, 6, 1)
    assert ttl_for("prices_adj_close", D(2020, 1, 1), today) == TTL_SECONDS["prices_historical"]
    assert ttl_for("prices_adj_close", today, today) == TTL_SECONDS["prices_live"]
    assert ttl_for("factors_ff5_monthly", today, today) == TTL_SECONDS["factors"]
    assert ttl_for("fx", today, today) == TTL_SECONDS["fx"]
    assert ttl_for("macro", today, today) == TTL_SECONDS["macro"]


def test_missing_ranges_arithmetic() -> None:
    req = DateRange(D(2020, 1, 1), D(2020, 12, 31))
    assert missing_ranges(req, []) == [req]
    assert missing_ranges(req, [req]) == []
    assert missing_ranges(req, [DateRange(D(2019, 1, 1), D(2021, 1, 1))]) == []
    assert missing_ranges(req, [DateRange(D(2020, 3, 1), D(2020, 6, 30))]) == [
        DateRange(D(2020, 1, 1), D(2020, 2, 29)),
        DateRange(D(2020, 7, 1), D(2020, 12, 31)),
    ]
    assert missing_ranges(
        req, [DateRange(D(2018, 1, 1), D(2018, 12, 31)), DateRange(D(2021, 1, 1), D(2021, 6, 1))]
    ) == [req]


def test_fetch_logged_at_debug(cache: ObservationCache, capsys: pytest.CaptureFixture[str]) -> None:
    from sobres.observability import configure_logging

    configure_logging("DEBUG", "json")
    cache.get("p", "prices_adj_close", ["AAPL"], D(2020, 1, 1), D(2020, 1, 10), _fetcher([]))
    err = capsys.readouterr().err
    assert '"cache.get"' in err and '"status": "miss"' in err and '"elapsed_ms"' in err
