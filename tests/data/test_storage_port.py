"""The storage port, the backend registry and the SQLite adapter's own behavior.

Scenarios: Drivers are confined to adapters; Call sites depend on the port;
Backend selection is configuration; Unknown backend; Default backend;
SQLite-specific tuning stays in its adapter; The single-file property is
preserved as the default, not the contract; Corrupt database; Concurrent access;
One database file; Database location; Backup before migrating; Applied through
the port; One migration set.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from sobres.core.errors import (
    ConfigurationError,
    CorruptDatabaseError,
    StorageConflictError,
    StorageConstraintError,
    StorageError,
    StorageLockedError,
)
from sobres.data.storage.adapters import sqlite as adapter
from sobres.data.storage.adapters.migrations import CURRENT_VERSION, MIGRATIONS
from sobres.data.storage.base import (
    DateRange,
    OpenOptions,
    open_storage,
    registered_backends,
    url_scheme,
)


def test_unknown_url_scheme_exits_3_listing_backends() -> None:
    with pytest.raises(ConfigurationError) as exc:
        open_storage("postgresql://localhost/db")
    assert exc.value.exit_code == 3
    assert "postgresql" in str(exc.value) and "sqlite" in str(exc.value)
    with pytest.raises(ConfigurationError):
        url_scheme("no-scheme-here")
    assert url_scheme("sqlite+pysqlite:///x") == "sqlite"
    assert registered_backends() == ["sqlite"]


def test_date_range_validates_order() -> None:
    with pytest.raises(ValueError):
        DateRange(date(2020, 1, 2), date(2020, 1, 1))
    r = DateRange(date(2020, 1, 1), date(2020, 1, 31))
    assert r.contains(DateRange(date(2020, 1, 5), date(2020, 1, 6)))
    assert r.overlaps(DateRange(date(2020, 1, 31), date(2020, 2, 5)))
    assert not r.overlaps(DateRange(date(2020, 2, 1), date(2020, 2, 5)))


def test_default_sqlite_file_is_created_with_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "dir" / "sobres.db"
    store = open_storage(f"sqlite:///{path.as_posix()}")
    try:
        assert path.exists()
        assert store.location == str(path)
        assert store.backend == "sqlite"
        with store._engine.connect() as conn:  # type: ignore[attr-defined]
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == adapter.BUSY_TIMEOUT_MS
        assert store.schema_version() == CURRENT_VERSION
        assert store.size_bytes() > 0
    finally:
        store.close()


def test_memory_url_has_no_file() -> None:
    store = open_storage("sqlite:///:memory:")
    try:
        assert store.location == ":memory:"
        assert store.size_bytes() == 0
        with pytest.raises(StorageError):
            store.export_to(Path("/tmp/never.db"))
    finally:
        store.close()
    assert adapter._sqlite_path("sqlite://") is None


def test_corrupt_database_exits_without_recreating(tmp_path: Path) -> None:
    path = tmp_path / "bad.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    before = path.read_bytes()
    with pytest.raises(CorruptDatabaseError) as exc:
        open_storage(f"sqlite:///{path.as_posix()}")
    assert exc.value.exit_code == 3
    assert str(path) in str(exc.value) and "sobres db repair" in str(exc.value)
    assert path.read_bytes() == before  # not recreated, not touched


def test_migration_backs_up_existing_database_first(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    # Simulate a database at "version 0 of a real prior state": tables absent.
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO schema_version VALUES (0, 'seed', '2020-01-01T00:00:00.000000Z')")
    conn.commit()
    conn.close()
    applied: list[str] = []
    backups: list[str] = []
    store = open_storage(
        f"sqlite:///{path.as_posix()}",
        OpenOptions(on_migration=applied.append, on_backup=backups.append),
    )
    try:
        assert applied == [m.name for m in MIGRATIONS]
        assert len(backups) == 1 and Path(backups[0]).exists()
        assert Path(backups[0]).name.startswith("old.db.bak-")
        assert store.schema_version() == CURRENT_VERSION
    finally:
        store.close()


def test_open_without_migrating_reports_pending(tmp_path: Path) -> None:
    store = open_storage(f"sqlite:///{(tmp_path / 'p.db').as_posix()}", OpenOptions(migrate=False))
    try:
        assert store.schema_version() == 0
        assert store.pending_migrations() == [m.name for m in MIGRATIONS]
        assert store.migrate() == [m.name for m in MIGRATIONS]
    finally:
        store.close()


def test_locked_database_retries_then_raises_translated_error(tmp_path: Path) -> None:
    path = tmp_path / "locked.db"
    store = open_storage(f"sqlite:///{path.as_posix()}", OpenOptions(lock_retries=2))
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("PRAGMA busy_timeout=0")
        holder.execute("BEGIN EXCLUSIVE")
        adapter.BUSY_TIMEOUT_MS = 50  # keep the test fast; restored below
        with store._engine.connect() as conn:  # type: ignore[attr-defined]
            conn.exec_driver_sql("PRAGMA busy_timeout=50")
        with pytest.raises(StorageLockedError) as exc:
            store.kv.set("k", 1)
        assert exc.value.exit_code == 1
        assert "locked" in str(exc.value) and "sobres serve" in str(exc.value)
    finally:
        adapter.BUSY_TIMEOUT_MS = 5000
        holder.execute("ROLLBACK")
        holder.close()
        store.close()


def test_error_translation_covers_every_family() -> None:
    from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

    unique = IntegrityError("s", {}, Exception("UNIQUE constraint failed"))
    assert isinstance(adapter.translate(unique), StorageConflictError)
    notnull = IntegrityError("s", {}, Exception("NOT NULL constraint failed"))
    assert isinstance(adapter.translate(notnull), StorageConstraintError)
    locked = OperationalError("s", {}, Exception("database is locked"))
    assert isinstance(adapter.translate(locked), StorageLockedError)
    other = SQLAlchemyError("boom")
    assert type(adapter.translate(other)) is StorageError
    assert not adapter._is_lock_error(OperationalError("s", {}, Exception("syntax")))


def test_export_uses_backup_api_while_open(tmp_path: Path) -> None:
    store = open_storage(f"sqlite:///{(tmp_path / 'live.db').as_posix()}")
    try:
        store.kv.set("k", "v")
        dest = tmp_path / "backups" / "copy.db"
        store.export_to(dest)
        copy = sqlite3.connect(dest)
        assert copy.execute("SELECT count(*) FROM kv").fetchone()[0] == 1
        copy.close()
    finally:
        store.close()


def test_slow_operation_logs_at_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from sobres.observability import configure_logging

    configure_logging("DEBUG", "json")
    store = open_storage(
        f"sqlite:///{(tmp_path / 'slow.db').as_posix()}", OpenOptions(slow_query_ms=-1)
    )
    try:
        store.kv.set("k", 1)
    finally:
        store.close()
    err = capsys.readouterr().err
    assert '"storage.slow"' in err
