#!/usr/bin/env python3
"""Record ``tests/fixtures/schema/v<N>.sql``: a database at a shipped schema version.

Run this once when a migration ships, *before* the next one exists, so the
fixture is the real prior state the migration test upgrades from. The SQL
dump is committed rather than a binary file so a review can read it.

    python scripts/schema_fixture.py <version>
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from sobres.data.storage.adapters import schema
from sobres.data.storage.adapters.migrations import MIGRATIONS
from sobres.data.storage.adapters.sqlite import SqliteStorage
from sobres.data.storage.base import DateRange, FetchRecord, Observation, OpenOptions, SeriesKey

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "schema"


def build(version: int) -> Path:
    tmp = Path(tempfile.mkdtemp()) / f"v{version}.db"
    store = SqliteStorage(f"sqlite:///{tmp.as_posix()}", OpenOptions(migrate=False))
    with store._engine.begin() as conn:
        for migration in MIGRATIONS:
            if migration.version > version:
                break
            migration.apply(conn)
            conn.execute(
                schema.schema_version.insert().values(
                    version=migration.version,
                    name=migration.name,
                    applied_at=datetime(2026, 9, 12, tzinfo=UTC),
                )
            )
    key = SeriesKey("yfinance", "prices_adj_close", "AAPL")
    store.observations.upsert_observations(
        [
            Observation("yfinance", "prices_adj_close", "AAPL", date(2020, 1, 2), 100.5),
            Observation("yfinance", "prices_adj_close", "AAPL", date(2020, 1, 3), 101.0),
        ]
    )
    store.observations.record_fetch(
        FetchRecord(
            key,
            DateRange(date(2020, 1, 1), date(2020, 1, 31)),
            datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
            86400,
        )
    )
    store.observations.put_series_meta(key, {"currency": "USD"})
    store.kv.set("greeting", {"hello": "world"})
    store.close()
    conn = sqlite3.connect(tmp)
    lines = list(conn.iterdump())
    conn.close()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"v{version}.sql"
    out.write_text(
        f"-- schema version {version} with sample rows; produced by scripts/schema_fixture.py\n"
        + "\n".join(lines)
        + "\n"
    )
    return out


if __name__ == "__main__":
    print(build(int(sys.argv[1]) if len(sys.argv) > 1 else MIGRATIONS[-1].version))
