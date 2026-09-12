"""Migrations against real prior schema states.

Scenarios: Automatic upgrade; Migrations are tested against real prior states;
Forward-only; Backup before migrating; Newer database than the installed tool;
Migrations are visible; One migration set; Applied through the port.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
from pathlib import Path

import pytest

from sobres.data.storage.adapters.migrations import CURRENT_VERSION, MIGRATIONS
from sobres.data.storage.base import OpenOptions, open_storage
from sobres.observability import configure_logging

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "schema"
SHIPPED = sorted(int(p.stem[1:]) for p in FIXTURES.glob("v*.sql"))


def test_every_prior_version_has_a_fixture() -> None:
    assert list(range(1, CURRENT_VERSION)) == SHIPPED


def test_migrations_are_forward_only_and_contiguous() -> None:
    assert [m.version for m in MIGRATIONS] == list(range(1, CURRENT_VERSION + 1))
    assert len({m.name for m in MIGRATIONS}) == len(MIGRATIONS)


@pytest.mark.parametrize("version", SHIPPED)
def test_fixture_database_migrates_to_current_intact(version: int, tmp_path: Path) -> None:
    path = tmp_path / f"v{version}.db"
    conn = sqlite3.connect(path)
    conn.executescript((FIXTURES / f"v{version}.sql").read_text(encoding="utf-8"))
    conn.close()
    err = io.StringIO()
    configure_logging("INFO", "json", stream=err)
    applied: list[str] = []
    backups: list[str] = []
    store = open_storage(
        f"sqlite:///{path.as_posix()}",
        OpenOptions(on_migration=applied.append, on_backup=backups.append),
    )
    try:
        assert store.schema_version() == CURRENT_VERSION
        assert applied == [m.name for m in MIGRATIONS if m.version > version]
        assert len(backups) == 1 and Path(backups[0]).exists()
        # The rows the fixture carried are still there, unchanged.
        stats = store.observations.cache_stats()
        assert stats.entries == 2 and stats.series == 1
        assert store.kv.get("greeting") == {"hello": "world"}
        from sobres.data.storage.base import SeriesKey

        assert store.observations.get_series_meta(
            SeriesKey("yfinance", "prices_adj_close", "AAPL")
        ) == {"currency": "USD"}
        # And the new repositories work on the upgraded file.
        from sobres.data.storage.base import PortfolioRecord

        store.portfolios.save(PortfolioRecord("p", ("AAPL",)))
        assert store.portfolios.get("p") is not None
    finally:
        store.close()
    records = [json.loads(line) for line in err.getvalue().splitlines() if line.strip()]
    migrated = [r for r in records if r["event"] == "storage.migrated"]
    assert [r["version"] for r in migrated] == [
        m.version for m in MIGRATIONS if m.version > version
    ]
    assert all(r["level"] == "info" for r in migrated)
    backup_logs = [r for r in records if r["event"] == "storage.backup"]
    assert backup_logs and backup_logs[0]["level"] == "warning"


def test_fixture_sql_is_the_recorded_version() -> None:
    for version in SHIPPED:
        text = (FIXTURES / f"v{version}.sql").read_text(encoding="utf-8")
        assert re.search(rf"INSERT INTO \"?schema_version\"? VALUES\({version},", text)
