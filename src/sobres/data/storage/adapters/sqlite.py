"""The SQLite adapter: SQLAlchemy Core engine, pragmas, migrations, retries.

Everything SQLite-specific lives here — WAL mode, the busy timeout, foreign-key
enforcement, ``PRAGMA integrity_check``, the file backup before a migration —
and nothing outside this module names the backend. Driver exceptions are
translated into the 0001 taxonomy before they leave.
"""

from __future__ import annotations

import contextlib
import shutil
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from sobres.core.errors import (
    ConfigurationError,
    CorruptDatabaseError,
    StorageConflictError,
    StorageConstraintError,
    StorageError,
    StorageLockedError,
)
from sobres.data.storage.adapters import schema
from sobres.data.storage.adapters.migrations import CURRENT_VERSION, MIGRATIONS
from sobres.data.storage.base import (
    CacheStats,
    DateRange,
    FetchRecord,
    Observation,
    ObservationQuery,
    OpenOptions,
    SeriesKey,
    StorageInfo,
    register_backend,
)
from sobres.observability import get_logger, span

T = TypeVar("T")

BACKEND = "sqlite"
BUSY_TIMEOUT_MS = 5000
_LOCK_BACKOFF_S = (0.05, 0.1, 0.2, 0.4, 0.8)


def _is_lock_error(exc: OperationalError) -> bool:
    text = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
    return "locked" in text or "busy" in text


def translate(exc: SQLAlchemyError) -> StorageError:
    """Map a driver exception to the taxonomy. Never lets the driver's escape."""
    if isinstance(exc, IntegrityError):
        text = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
        if "unique" in text or "primary key" in text:
            return StorageConflictError(f"row already exists: {exc.orig}")
        return StorageConstraintError(f"constraint violated: {exc.orig}")
    if isinstance(exc, OperationalError) and _is_lock_error(exc):
        return StorageLockedError(
            "the database stayed locked by another writer",
            hint="close other sobres processes (a running `sobres serve`?) and retry",
        )
    return StorageError(f"storage operation failed: {exc}")


def _sqlite_path(url: str) -> Path | None:
    """``sqlite:///rel.db`` and ``sqlite:////abs.db``; ``:memory:`` → None."""
    rest = url.split("://", 1)[1]
    if rest.startswith("/"):
        rest = rest[1:]
    if rest in ("", ":memory:"):
        return None
    return Path(rest)


class SqliteStorage:
    """One opened SQLite database."""

    backend = BACKEND

    def __init__(self, url: str, options: OpenOptions) -> None:
        self.url = url
        self.path = _sqlite_path(url)
        self._options = options
        self._log = get_logger("sobres.storage.sqlite")
        self._tx_conn: Connection | None = None
        self._existed = (
            self.path is not None and self.path.exists() and self.path.stat().st_size > 0
        )
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = sa.create_engine(url, future=True)

        @event.listens_for(self._engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.observations = _Observations(self)
        self.kv = _KeyValue(self)
        if options.check_integrity and not self.integrity_check():
            raise CorruptDatabaseError(
                f"database {self.location} failed its integrity check",
                hint="run: sobres db repair  (the file is left untouched; do not delete it)",
            )
        if options.migrate:
            self.migrate()

    # ----------------------------------------------------------------- basics
    @property
    def location(self) -> str:
        return str(self.path) if self.path is not None else ":memory:"

    def close(self) -> None:
        if self._tx_conn is not None:
            with contextlib.suppress(Exception):
                self._tx_conn.close()
            self._tx_conn = None
        self._engine.dispose()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        if self._tx_conn is not None:  # nested: join the outer unit of work
            yield
            return
        conn = self._engine.connect()
        tx = conn.begin()
        self._tx_conn = conn
        try:
            yield
        except BaseException:
            tx.rollback()
            raise
        else:
            tx.commit()
        finally:
            self._tx_conn = None
            conn.close()

    def _run(self, op: str, fn: Callable[[Connection], T], **attrs: Any) -> T:
        """Execute ``fn`` in a transaction with translation, retry, log and span."""
        started = time.perf_counter()
        attempt = 0
        with span(f"storage.{op}", {"db.system": BACKEND, **attrs}) as sp:
            while True:
                try:
                    if self._tx_conn is not None:
                        result = fn(self._tx_conn)
                    else:
                        with self._engine.begin() as conn:
                            result = fn(conn)
                    break
                except OperationalError as exc:
                    if _is_lock_error(exc) and attempt < self._options.lock_retries:
                        delay = _LOCK_BACKOFF_S[min(attempt, len(_LOCK_BACKOFF_S) - 1)]
                        attempt += 1
                        self._log.debug("storage.locked_retry", op=op, attempt=attempt)
                        time.sleep(delay)
                        continue
                    raise translate(exc) from exc
                except SQLAlchemyError as exc:
                    raise translate(exc) from exc
            elapsed_ms = (time.perf_counter() - started) * 1000
            rows = result if isinstance(result, int) else None
            sp.set_attribute("db.rows", rows if rows is not None else -1)
            sp.set_attribute("elapsed_ms", round(elapsed_ms, 3))
            if elapsed_ms > self._options.slow_query_ms:
                self._log.warning("storage.slow", op=op, elapsed_ms=round(elapsed_ms, 1), rows=rows)
            else:
                self._log.debug("storage.op", op=op, elapsed_ms=round(elapsed_ms, 3), rows=rows)
        return result

    # ------------------------------------------------------------- migrations
    def _has_version_table(self, conn: Connection) -> bool:
        return sa.inspect(conn).has_table("schema_version")

    def schema_version(self) -> int:
        def read(conn: Connection) -> int:
            if not self._has_version_table(conn):
                return 0
            row = conn.execute(sa.select(sa.func.max(schema.schema_version.c.version))).scalar()
            return int(row or 0)

        return self._run("schema_version", read)

    def code_schema_version(self) -> int:
        return CURRENT_VERSION

    def pending_migrations(self) -> list[str]:
        current = self.schema_version()
        if current > CURRENT_VERSION:
            raise ConfigurationError(
                f"database {self.location} is at schema version {current}, newer than this "
                f"sobres knows ({CURRENT_VERSION})",
                hint="run: sobres upgrade",
            )
        return [m.name for m in MIGRATIONS if m.version > current]

    def migrate(self) -> list[str]:
        current = self.schema_version()
        pending = [m for m in MIGRATIONS if m.version > current]
        if current > CURRENT_VERSION:
            self.pending_migrations()  # raises the exit-3 error
        if not pending:
            return []
        if self._existed:
            self._backup_before_migration()
            self._existed = False

        def apply(conn: Connection) -> int:
            for migration in pending:
                migration.apply(conn)
                conn.execute(
                    schema.schema_version.insert().values(
                        version=migration.version,
                        name=migration.name,
                        applied_at=datetime.now(UTC),
                    )
                )
                self._log.info("storage.migrated", version=migration.version, name=migration.name)
                if self._options.on_migration is not None:
                    self._options.on_migration(migration.name)
            return len(pending)

        self._run("migrate", apply, pending=len(pending))
        return [m.name for m in pending]

    def _backup_before_migration(self) -> None:
        if self.path is None or not self.path.exists():
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        shutil.copy2(self.path, backup)
        self._log.warning("storage.backup", path=str(backup))
        if self._options.on_backup is not None:
            self._options.on_backup(str(backup))

    # -------------------------------------------------------------- admin
    def integrity_check(self) -> bool:
        try:
            with self._engine.connect() as conn:
                result = conn.exec_driver_sql("PRAGMA integrity_check").scalar()
        except SQLAlchemyError:
            return False
        return result == "ok"

    def size_bytes(self) -> int:
        if self.path is None or not self.path.exists():
            return 0
        total = self.path.stat().st_size
        for suffix in ("-wal", "-shm"):
            side = self.path.with_name(self.path.name + suffix)
            if side.exists():
                total += side.stat().st_size
        return total

    def info(self) -> StorageInfo:
        def count_rows(conn: Connection) -> dict[str, int]:
            counts: dict[str, int] = {}
            inspector = sa.inspect(conn)
            for table in schema.metadata.sorted_tables:
                if inspector.has_table(table.name):
                    counts[table.name] = int(
                        conn.execute(sa.select(sa.func.count()).select_from(table)).scalar() or 0
                    )
            return counts

        return StorageInfo(
            backend=BACKEND,
            location=self.location,
            schema_version=self.schema_version(),
            size_bytes=self.size_bytes(),
            table_rows=self._run("info", count_rows),
        )

    def export_to(self, destination: Path) -> None:
        """Consistent copy via SQLite's online backup API; safe while in use."""
        import sqlite3

        if self.path is None:
            raise StorageError("an in-memory database cannot be exported")
        destination.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        try:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()


class _Observations:
    """``ObservationStore`` over the shared schema."""

    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def upsert_observations(self, rows: Sequence[Observation]) -> int:
        if not rows:
            return 0
        payload = [
            {
                "provider": r.provider,
                "dataset": r.dataset,
                "symbol": r.symbol,
                "date": r.date,
                "value": None if r.value is None or pd.isna(r.value) else float(r.value),
            }
            for r in rows
        ]

        def write(conn: Connection) -> int:
            stmt = sqlite_insert(schema.observation)
            stmt = stmt.on_conflict_do_update(
                index_elements=["provider", "dataset", "symbol", "date"],
                set_={"value": stmt.excluded.value},
            )
            for start in range(0, len(payload), 500):
                conn.execute(stmt, payload[start : start + 500])
            return len(payload)

        return self._s._run("upsert_observations", write, rows=len(payload))

    def read_observations(self, query: ObservationQuery) -> pd.DataFrame:
        symbols = list(query.symbols)

        def read(conn: Connection) -> pd.DataFrame:
            t = schema.observation
            stmt = (
                sa.select(t.c.symbol, t.c.date, t.c.value)
                .where(t.c.provider == query.provider)
                .where(t.c.dataset == query.dataset)
                .where(t.c.symbol.in_(symbols))
                .where(t.c.date >= query.start)
                .where(t.c.date <= query.end)
                .order_by(t.c.date)
            )
            records = conn.execute(stmt).all()
            frame = pd.DataFrame(records, columns=["symbol", "date", "value"])
            if frame.empty:
                out = pd.DataFrame(columns=symbols, dtype="float64")
                out.index = pd.DatetimeIndex([], name="date")
                return out
            frame["date"] = pd.to_datetime(frame["date"])
            wide = frame.pivot(index="date", columns="symbol", values="value")
            wide = wide.reindex(columns=symbols).astype("float64").sort_index()
            wide.index.name = "date"
            wide.columns.name = None
            return wide

        return self._s._run("read_observations", read, symbols=len(symbols))

    def record_fetch(self, record: FetchRecord) -> None:
        def write(conn: Connection) -> int:
            conn.execute(
                schema.fetch_log.insert().values(
                    id=uuid.uuid4().hex,
                    provider=record.key.provider,
                    dataset=record.key.dataset,
                    symbol=record.key.symbol,
                    range_start=record.range.start,
                    range_end=record.range.end,
                    fetched_at=record.fetched_at,
                    ttl_seconds=record.ttl_seconds,
                )
            )
            return 1

        self._s._run("record_fetch", write)

    def fetched_ranges(self, key: SeriesKey) -> list[FetchRecord]:
        def read(conn: Connection) -> list[FetchRecord]:
            t = schema.fetch_log
            stmt = (
                sa.select(t.c.range_start, t.c.range_end, t.c.fetched_at, t.c.ttl_seconds)
                .where(t.c.provider == key.provider)
                .where(t.c.dataset == key.dataset)
                .where(t.c.symbol == key.symbol)
                .order_by(t.c.fetched_at)
            )
            return [
                FetchRecord(
                    key=key,
                    range=DateRange(_as_date(row.range_start), _as_date(row.range_end)),
                    fetched_at=row.fetched_at,
                    ttl_seconds=int(row.ttl_seconds),
                )
                for row in conn.execute(stmt)
            ]

        return self._s._run("fetched_ranges", read)

    def put_series_meta(self, key: SeriesKey, meta: dict[str, Any]) -> None:
        def write(conn: Connection) -> int:
            stmt = sqlite_insert(schema.series_meta).values(
                provider=key.provider,
                dataset=key.dataset,
                symbol=key.symbol,
                meta=meta,
                updated_at=datetime.now(UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["provider", "dataset", "symbol"],
                set_={"meta": stmt.excluded.meta, "updated_at": stmt.excluded.updated_at},
            )
            conn.execute(stmt)
            return 1

        self._s._run("put_series_meta", write)

    def get_series_meta(self, key: SeriesKey) -> dict[str, Any] | None:
        def read(conn: Connection) -> dict[str, Any] | None:
            t = schema.series_meta
            row = conn.execute(
                sa.select(t.c.meta)
                .where(t.c.provider == key.provider)
                .where(t.c.dataset == key.dataset)
                .where(t.c.symbol == key.symbol)
            ).first()
            return None if row is None else dict(row.meta)

        return self._s._run("get_series_meta", read)

    def clear_observations(self, provider: str | None = None) -> int:
        def delete(conn: Connection) -> int:
            removed = 0
            for table in (schema.observation, schema.fetch_log, schema.series_meta):
                stmt = sa.delete(table)
                if provider is not None:
                    stmt = stmt.where(table.c.provider == provider)
                removed += int(conn.execute(stmt).rowcount or 0)
            return removed

        return self._s._run("clear_observations", delete)

    def cache_stats(self) -> CacheStats:
        def read(conn: Connection) -> CacheStats:
            o, f = schema.observation, schema.fetch_log
            entries = int(conn.execute(sa.select(sa.func.count()).select_from(o)).scalar() or 0)
            series = int(
                conn.execute(
                    sa.select(sa.func.count()).select_from(
                        sa.select(o.c.provider, o.c.dataset, o.c.symbol).distinct().subquery()
                    )
                ).scalar()
                or 0
            )
            oldest = conn.execute(sa.select(sa.func.min(f.c.fetched_at))).scalar()
            oldest_dt = (
                schema.UtcTimestamp().process_result_value(oldest, None)
                if isinstance(oldest, str)
                else oldest
            )
            return CacheStats(
                entries=entries,
                series=series,
                oldest_fetch=oldest_dt,
                size_bytes=self._s.size_bytes(),
            )

        return self._s._run("cache_stats", read)


class _KeyValue:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def get(self, key: str) -> Any | None:
        def read(conn: Connection) -> Any | None:
            row = conn.execute(sa.select(schema.kv.c.value).where(schema.kv.c.key == key)).first()
            return None if row is None else row.value

        return self._s._run("kv_get", read)

    def set(self, key: str, value: Any) -> None:
        def write(conn: Connection) -> int:
            stmt = sqlite_insert(schema.kv).values(
                key=key, value=value, updated_at=datetime.now(UTC)
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"],
                set_={"value": stmt.excluded.value, "updated_at": stmt.excluded.updated_at},
            )
            conn.execute(stmt)
            return 1

        self._s._run("kv_set", write)

    def delete(self, key: str) -> bool:
        def write(conn: Connection) -> int:
            return int(conn.execute(sa.delete(schema.kv).where(schema.kv.c.key == key)).rowcount)

        return self._s._run("kv_delete", write) > 0

    def items(self) -> dict[str, Any]:
        def read(conn: Connection) -> dict[str, Any]:
            return {
                row.key: row.value
                for row in conn.execute(sa.select(schema.kv.c.key, schema.kv.c.value))
            }

        return self._s._run("kv_items", read)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _factory(url: str, options: OpenOptions) -> SqliteStorage:
    return SqliteStorage(url, options)


register_backend(BACKEND, _factory)
