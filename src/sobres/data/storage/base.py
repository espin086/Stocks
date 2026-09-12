"""Repository protocols, phrased in domain terms, and the backend registry.

A port phrased as SQL is a SQL port. These protocols speak observations, date
ranges, series keys and key/value rows — never statements — so a DuckDB or
PostgreSQL adapter is a new file under ``adapters/`` plus one entry in the
conformance suite's fixture list, and nothing above the port changes.

``SOBRES_DB_URL`` selects the adapter; the default is
``sqlite:///<user-data-dir>/sobres.db``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import pandas as pd

from sobres.core.errors import ConfigurationError

# --------------------------------------------------------------------------- #
# Domain values
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, order=True)
class SeriesKey:
    """Identity of one cached series."""

    provider: str
    dataset: str
    symbol: str


@dataclass(frozen=True, order=True)
class DateRange:
    """Inclusive date range."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"DateRange end {self.end} precedes start {self.start}")

    def contains(self, other: DateRange) -> bool:
        return self.start <= other.start and other.end <= self.end

    def overlaps(self, other: DateRange) -> bool:
        return self.start <= other.end and other.start <= self.end


@dataclass(frozen=True)
class Observation:
    """One value of one series on one date. Identity is the first four fields."""

    provider: str
    dataset: str
    symbol: str
    date: date
    value: float

    @property
    def key(self) -> SeriesKey:
        return SeriesKey(self.provider, self.dataset, self.symbol)


@dataclass(frozen=True)
class ObservationQuery:
    provider: str
    dataset: str
    symbols: Sequence[str]
    start: date
    end: date


@dataclass(frozen=True)
class FetchRecord:
    """Which range of a series was actually requested from the provider, and when.

    Presence of rows cannot distinguish "no data on these dates" from "never
    asked"; this record can. ``ttl_seconds`` is stored per entry so a changed
    default never invalidates what is already on disk.
    """

    key: SeriesKey
    range: DateRange
    fetched_at: datetime
    ttl_seconds: int

    def expires_at(self) -> datetime:
        from datetime import timedelta

        return self.fetched_at + timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True)
class CacheStats:
    entries: int
    series: int
    oldest_fetch: datetime | None
    size_bytes: int


@dataclass(frozen=True)
class StorageInfo:
    backend: str
    location: str
    schema_version: int
    size_bytes: int
    table_rows: dict[str, int]


@dataclass(frozen=True)
class PortfolioRecord:
    """A saved, named ticker list with optional weights (an unweighted universe)."""

    name: str
    tickers: tuple[str, ...]
    weights: tuple[float, ...] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def holdings(self) -> int:
        return len(self.tickers)


@dataclass(frozen=True)
class WatchlistRecord:
    name: str
    symbols: tuple[str, ...]
    updated_at: datetime | None = None


@dataclass(frozen=True)
class GoalRecord:
    """A saved goal: its kind (retire, house, goal…), parameters and assumptions."""

    name: str
    kind: str
    params: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RunRecord:
    """One recorded analysis: resolved parameters, provenance and result."""

    id: str
    command: str
    params: dict[str, Any]
    result: dict[str, Any]
    summary: str
    estimators: dict[str, Any] = field(default_factory=dict)
    window: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


JobState = str  # queued | running | succeeded | failed | cancelled
JOB_STATES: tuple[str, ...] = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL_JOB_STATES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class JobRecord:
    """A unit of long-running work persisted so it survives a restart (0004 runs them)."""

    id: str
    command: str
    params: dict[str, Any]
    state: JobState = "queued"
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    run_id: str | None = None
    trace_context: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Repository protocols
# --------------------------------------------------------------------------- #


class ObservationStore(Protocol):
    """The observation cache, in domain terms."""

    def upsert_observations(self, rows: Sequence[Observation]) -> int:
        """Insert or overwrite by ``(provider, dataset, symbol, date)``; returns the row count."""
        ...

    def read_observations(self, query: ObservationQuery) -> pd.DataFrame:
        """A date-indexed frame with one column per requested symbol (NaN where absent)."""
        ...

    def record_fetch(self, record: FetchRecord) -> None: ...

    def fetched_ranges(self, key: SeriesKey) -> list[FetchRecord]: ...

    def put_series_meta(self, key: SeriesKey, meta: dict[str, Any]) -> None: ...

    def get_series_meta(self, key: SeriesKey) -> dict[str, Any] | None: ...

    def clear_observations(self, provider: str | None = None) -> int:
        """Remove cached observations (and their fetch log). Returns rows removed."""
        ...

    def cache_stats(self) -> CacheStats: ...


class KeyValueStore(Protocol):
    """Config-ish rows: small JSON values by key."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def delete(self, key: str) -> bool: ...

    def items(self) -> dict[str, Any]: ...


class PortfolioRepository(Protocol):
    def save(self, portfolio: PortfolioRecord, *, force: bool = False) -> PortfolioRecord:
        """Persist; ``StorageConflictError`` on an existing name unless ``force``."""
        ...

    def get(self, name: str) -> PortfolioRecord | None: ...

    def list(self) -> list[PortfolioRecord]: ...

    def delete(self, name: str) -> bool: ...


class WatchlistRepository(Protocol):
    def add(self, name: str, symbols: Sequence[str]) -> WatchlistRecord:
        """Add symbols, creating the list if absent; a present symbol is a no-op."""
        ...

    def remove(self, name: str, symbols: Sequence[str]) -> WatchlistRecord | None: ...

    def get(self, name: str) -> WatchlistRecord | None: ...

    def list(self) -> list[WatchlistRecord]: ...

    def delete(self, name: str) -> bool: ...


class GoalRepository(Protocol):
    def save(self, goal: GoalRecord, *, force: bool = False) -> GoalRecord: ...

    def get(self, name: str) -> GoalRecord | None: ...

    def list(self) -> list[GoalRecord]: ...

    def delete(self, name: str) -> bool: ...


class RunRepository(Protocol):
    def record(self, run: RunRecord) -> RunRecord: ...

    def get(self, run_id: str) -> RunRecord | None: ...

    def list(self, limit: int = 20, command: str | None = None) -> list[RunRecord]:
        """Newest first."""
        ...

    def delete(self, run_id: str) -> bool: ...


class JobRepository(Protocol):
    def create(self, job: JobRecord) -> JobRecord: ...

    def update(self, job_id: str, **changes: Any) -> JobRecord:
        """Merge ``changes`` (state, progress, result, error…) into the record."""
        ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def list(self, limit: int = 20, state: str | None = None) -> list[JobRecord]: ...

    def next_queued(self) -> JobRecord | None: ...


class Storage(Protocol):
    """One opened backend. Repositories hang off it; transactions wrap them."""

    backend: str
    url: str

    @property
    def location(self) -> str:
        """Where the data lives, for humans (a file path for SQLite)."""
        ...

    @property
    def observations(self) -> ObservationStore: ...

    @property
    def kv(self) -> KeyValueStore: ...

    @property
    def portfolios(self) -> PortfolioRepository: ...

    @property
    def watchlists(self) -> WatchlistRepository: ...

    @property
    def goals(self) -> GoalRepository: ...

    @property
    def runs(self) -> RunRepository: ...

    @property
    def jobs(self) -> JobRepository: ...

    def transaction(self) -> AbstractContextManager[None]:
        """A unit of work: every operation inside commits or rolls back together."""
        ...

    def schema_version(self) -> int: ...

    def code_schema_version(self) -> int: ...

    def pending_migrations(self) -> list[str]: ...

    def migrate(self) -> list[str]:
        """Apply pending migrations; returns their names."""
        ...

    def integrity_check(self) -> bool: ...

    def info(self) -> StorageInfo: ...

    def export_to(self, destination: Any) -> None:
        """A consistent copy of the whole state, safe while in use."""
        ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Backend registry and URL resolution
# --------------------------------------------------------------------------- #

BackendFactory = Callable[[str, "OpenOptions"], Storage]


@dataclass(frozen=True)
class OpenOptions:
    """How to open: apply migrations automatically, run the integrity check."""

    migrate: bool = True
    check_integrity: bool = True
    on_migration: Callable[[str], None] | None = None
    on_backup: Callable[[str], None] | None = None
    slow_query_ms: int = 500
    lock_retries: int = 5


_BACKENDS: dict[str, BackendFactory] = {}


def register_backend(scheme: str, factory: BackendFactory) -> None:
    _BACKENDS[scheme] = factory


def registered_backends() -> list[str]:
    _ensure_adapters_imported()
    return sorted(_BACKENDS)


def _ensure_adapters_imported() -> None:
    # Adapters register themselves on import; importing the package here keeps
    # the driver import confined to adapters/ while making the registry complete.
    import sobres.data.storage.adapters  # noqa: F401


def url_scheme(url: str) -> str:
    scheme, sep, _ = url.partition("://")
    if not sep:
        raise ConfigurationError(
            f"storage URL {url!r} has no scheme",
            hint="use a URL such as sqlite:////path/to/sobres.db",
        )
    return scheme.split("+", 1)[0].lower()


def open_storage(url: str, options: OpenOptions | None = None) -> Storage:
    """Open the backend the URL names. Unknown scheme → exit 3 listing backends."""
    _ensure_adapters_imported()
    scheme = url_scheme(url)
    factory = _BACKENDS.get(scheme)
    if factory is None:
        raise ConfigurationError(
            f"no storage backend for URL scheme {scheme!r}",
            hint=f"this build supports: {', '.join(registered_backends())}",
        )
    return factory(url, options or OpenOptions())


def iter_backends() -> Iterator[tuple[str, BackendFactory]]:
    _ensure_adapters_imported()
    yield from _BACKENDS.items()
