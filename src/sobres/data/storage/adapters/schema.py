"""The shared schema, inside the SQLite / PostgreSQL / DuckDB intersection.

Portable column types only (integer, real, text, boolean, date, UTC timestamp,
JSON-as-text), application-generated identifiers, no backend-specific SQL.
``tests/data/test_portability.py`` walks this metadata and fails on anything
outside the portable set.

SQLAlchemy Core is the dialect layer *below* the port; nothing outside
``data/storage/`` sees a ``Table`` or a ``Row``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
)
from sqlalchemy.types import TypeDecorator


class UtcTimestamp(TypeDecorator[datetime]):
    """A timestamp stored as ISO-8601 UTC text and read back tz-aware.

    Every candidate backend handles local time differently; storing the
    canonical UTC string removes the question rather than answering it per
    dialect.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware UTC before storage")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def process_result_value(self, value: str | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


class JsonText(TypeDecorator[Any]):
    """JSON encoded as text; the application encodes and decodes."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None
        return json.loads(value)


PORTABLE_TYPES: tuple[type[Any], ...] = (
    Integer,
    Float,
    Text,
    Boolean,
    Date,
    UtcTimestamp,
    JsonText,
)

metadata = MetaData()

schema_version = Table(
    "schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("applied_at", UtcTimestamp, nullable=False),
)

observation = Table(
    "observation",
    metadata,
    Column("provider", Text, nullable=False),
    Column("dataset", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("date", Date, nullable=False),
    Column("value", Float, nullable=True),
    PrimaryKeyConstraint("provider", "dataset", "symbol", "date", name="pk_observation"),
)

fetch_log = Table(
    "fetch_log",
    metadata,
    Column("id", Text, primary_key=True),  # application-generated
    Column("provider", Text, nullable=False),
    Column("dataset", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("range_start", Date, nullable=False),
    Column("range_end", Date, nullable=False),
    Column("fetched_at", UtcTimestamp, nullable=False),
    Column("ttl_seconds", Integer, nullable=False),
)

series_meta = Table(
    "series_meta",
    metadata,
    Column("provider", Text, nullable=False),
    Column("dataset", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("meta", JsonText, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False),
    PrimaryKeyConstraint("provider", "dataset", "symbol", name="pk_series_meta"),
)

kv = Table(
    "kv",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JsonText, nullable=True),
    Column("updated_at", UtcTimestamp, nullable=False),
)

# --------------------------------------------------------------------- 0003
portfolio = Table(
    "portfolio",
    metadata,
    Column("name", Text, primary_key=True),
    Column("tickers", JsonText, nullable=False),
    Column("weights", JsonText, nullable=True),
    Column("created_at", UtcTimestamp, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False),
)

watchlist = Table(
    "watchlist",
    metadata,
    Column("name", Text, primary_key=True),
    Column("symbols", JsonText, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False),
)

goal = Table(
    "goal",
    metadata,
    Column("name", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("params", JsonText, nullable=False),
    Column("created_at", UtcTimestamp, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False),
)

run = Table(
    "run",
    metadata,
    Column("id", Text, primary_key=True),  # application-generated
    Column("command", Text, nullable=False),
    Column("params", JsonText, nullable=False),
    Column("estimators", JsonText, nullable=False),
    Column("window", JsonText, nullable=False),
    Column("result", JsonText, nullable=False),
    Column("summary", Text, nullable=False),
    Column("created_at", UtcTimestamp, nullable=False),
)

job = Table(
    "job",
    metadata,
    Column("id", Text, primary_key=True),  # application-generated
    Column("command", Text, nullable=False),
    Column("params", JsonText, nullable=False),
    Column("state", Text, nullable=False),
    Column("progress", Float, nullable=False),
    Column("result", JsonText, nullable=True),
    Column("error", JsonText, nullable=True),
    Column("run_id", Text, nullable=True),
    Column("trace_context", JsonText, nullable=True),
    Column("created_at", UtcTimestamp, nullable=False),
    Column("updated_at", UtcTimestamp, nullable=False),
    Column("finished_at", UtcTimestamp, nullable=True),
)

CACHE_TABLES: tuple[str, ...] = ("observation", "fetch_log", "series_meta")
"""Tables ``sobres cache clear`` may touch. Everything else is user-authored."""

USER_TABLES: tuple[str, ...] = ("portfolio", "watchlist", "goal", "run", "job")
"""Tables that hold user-authored state: never touched by cache maintenance."""
