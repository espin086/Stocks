"""The observation cache, over the storage port, importing no driver.

Observations are stored as rows keyed ``(provider, dataset, symbol, date)``, so
any sub-range of a cached range is free and extending a range fetches only the
missing tail. ``fetch_log`` records which *ranges* were requested and when, so
"no data on these dates" (a market holiday) and "never fetched" are different
answers, and a TTL can expire a range without pretending its rows are wrong.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from sobres.data.base import canonical_frame
from sobres.data.storage.base import (
    DateRange,
    FetchRecord,
    Observation,
    ObservationQuery,
    ObservationStore,
    SeriesKey,
)
from sobres.observability import get_logger, span

Fetcher = Callable[[Sequence[str], date, date], pd.DataFrame]
"""``fetch(symbols, start, end)`` returning a canonical frame for those symbols."""

Clock = Callable[[], datetime]

DAY = 24 * 3600

TTL_SECONDS: dict[str, int] = {
    "prices_historical": 30 * DAY,
    "prices_live": 1 * DAY,
    "macro": 1 * DAY,
    "factors": 7 * DAY,
    "fx": 1 * DAY,
}


def ttl_for(dataset: str, requested_end: date, today: date) -> int:
    """Per-dataset TTL: historical bars are stable; a range running to today moves."""
    if dataset.startswith("prices"):
        return (
            TTL_SECONDS["prices_live"]
            if requested_end >= today
            else TTL_SECONDS["prices_historical"]
        )
    if dataset.startswith("factors"):
        return TTL_SECONDS["factors"]
    if dataset.startswith("fx"):
        return TTL_SECONDS["fx"]
    return TTL_SECONDS["macro"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CacheOutcome:
    """What the cache did for one request; recorded in ``attrs["cache"]``."""

    status: str  # hit | miss | partial | refresh
    fetched_ranges: tuple[tuple[str, str], ...]


def missing_ranges(requested: DateRange, covered: Sequence[DateRange]) -> list[DateRange]:
    """The parts of ``requested`` no covered range includes, as a sorted list."""
    gaps: list[DateRange] = []
    cursor = requested.start
    for rng in sorted(covered):
        if rng.end < cursor:
            continue
        if rng.start > requested.end:
            break
        if rng.start > cursor:
            gaps.append(DateRange(cursor, min(rng.start - timedelta(days=1), requested.end)))
        cursor = max(cursor, rng.end + timedelta(days=1))
        if cursor > requested.end:
            break
    if cursor <= requested.end:
        gaps.append(DateRange(cursor, requested.end))
    return gaps


class ObservationCache:
    """Serve frames from the store, fetching only what is missing or stale."""

    def __init__(self, store: ObservationStore, clock: Clock = utc_now) -> None:
        self._store = store
        self._clock = clock
        self._log = get_logger("sobres.cache")

    def get(
        self,
        provider: str,
        dataset: str,
        symbols: Sequence[str],
        start: date,
        end: date,
        fetch: Fetcher,
        *,
        refresh: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Return ``symbols`` over ``[start, end]``, fetching the uncovered parts.

        ``fetch`` is called once per contiguous missing range with every symbol
        that is missing it; its result is validated by the caller-supplied
        function, written through the port, and the whole request is then read
        back so the result is byte-identical whether it came from disk or wire.
        """
        started = time.perf_counter()
        now = self._clock()
        requested = DateRange(start, end)
        symbols = [s.upper() for s in symbols]
        to_fetch: dict[DateRange, list[str]] = {}
        for symbol in symbols:
            key = SeriesKey(provider, dataset, symbol)
            if refresh:
                to_fetch.setdefault(requested, []).append(symbol)
                continue
            fresh = [r.range for r in self._store.fetched_ranges(key) if r.expires_at() > now]
            for gap in missing_ranges(requested, fresh):
                to_fetch.setdefault(gap, []).append(symbol)
        if refresh:
            status = "refresh"
        elif not to_fetch:
            status = "hit"
        elif any(r == requested for r in to_fetch):
            status = "miss"
        else:
            status = "partial"
        fetched: list[tuple[str, str]] = []
        with span(
            "cache.get",
            {"provider": provider, "dataset": dataset, "symbols": len(symbols), "status": status},
        ) as sp:
            for rng, missing in sorted(to_fetch.items()):
                frame = fetch(missing, rng.start, rng.end)
                rows = self._to_observations(provider, dataset, frame, missing)
                ttl = ttl_for(dataset, rng.end, now.date())
                self._store.upsert_observations(rows)
                for symbol in missing:
                    key = SeriesKey(provider, dataset, symbol)
                    self._store.record_fetch(FetchRecord(key, rng, now, ttl))
                    series_meta = dict(frame.attrs.get("series_meta", {}).get(symbol, {}))
                    if meta:
                        series_meta.update(meta)
                    if series_meta:
                        self._store.put_series_meta(key, series_meta)
                fetched.append((rng.start.isoformat(), rng.end.isoformat()))
            result = self._store.read_observations(
                ObservationQuery(provider, dataset, symbols, start, end)
            )
            result = canonical_frame(result, symbols)
            series_meta_all = {
                s: m
                for s in symbols
                if (m := self._store.get_series_meta(SeriesKey(provider, dataset, s)))
            }
            result.attrs.update(
                {
                    "provider": provider,
                    "dataset": dataset,
                    "fetched_at": now.isoformat(),
                    "cache": {"status": status, "fetched": fetched},
                    "series_meta": series_meta_all,
                }
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            sp.set_attribute("rows", len(result))
            sp.set_attribute("elapsed_ms", elapsed_ms)
            self._log.debug(
                "cache.get",
                provider=provider,
                dataset=dataset,
                symbols=symbols,
                start=start.isoformat(),
                end=end.isoformat(),
                status=status,
                rows=len(result),
                elapsed_ms=elapsed_ms,
            )
        return result

    @staticmethod
    def _to_observations(
        provider: str, dataset: str, frame: pd.DataFrame, symbols: Sequence[str]
    ) -> list[Observation]:
        rows: list[Observation] = []
        index = pd.DatetimeIndex(frame.index)
        for symbol in symbols:
            if symbol not in frame.columns:
                continue
            values = frame[symbol].to_numpy()
            for when, value in zip(index, values, strict=True):
                if pd.isna(value):
                    continue
                rows.append(Observation(provider, dataset, symbol, when.date(), float(value)))
        return rows
