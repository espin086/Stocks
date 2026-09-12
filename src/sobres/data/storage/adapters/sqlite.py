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
    TERMINAL_JOB_STATES,
    CacheStats,
    DateRange,
    FetchRecord,
    GoalRecord,
    JobRecord,
    Observation,
    ObservationQuery,
    OpenOptions,
    PortfolioRecord,
    RunRecord,
    SeriesKey,
    StorageInfo,
    WatchlistRecord,
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
        self.portfolios = _Portfolios(self)
        self.watchlists = _Watchlists(self)
        self.goals = _Goals(self)
        self.runs = _Runs(self)
        self.jobs = _Jobs(self)
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
            fields: dict[str, Any] = {"rows": rows, **attrs, "op": op}
            if elapsed_ms > self._options.slow_query_ms:
                self._log.warning("storage.slow", elapsed_ms=round(elapsed_ms, 1), **fields)
            else:
                self._log.debug("storage.op", elapsed_ms=round(elapsed_ms, 3), **fields)
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


def recover_sqlite(source: Path, destination: Path) -> dict[str, Any]:
    """Copy whatever can be read from a damaged file into a fresh one; never touch the source.

    Returns per-table row counts recovered and the tables that could not be
    read. The destination is a new database with the current schema applied,
    so anything recovered lands in tables the current code understands.
    """
    import sqlite3

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise StorageError(f"{destination} already exists; choose a new path for the recovery")
    fresh = SqliteStorage(f"sqlite:///{destination.as_posix()}", OpenOptions(check_integrity=False))
    fresh.close()
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    recovered: dict[str, int] = {}
    failed: dict[str, str] = {}
    try:
        for table in schema.metadata.sorted_tables:
            if table.name == "schema_version":
                continue
            try:
                rows = src.execute(f'SELECT * FROM "{table.name}"').fetchall()
                columns = [c[1] for c in src.execute(f'PRAGMA table_info("{table.name}")')]
            except sqlite3.DatabaseError as exc:
                failed[table.name] = str(exc)
                continue
            if not rows:
                recovered[table.name] = 0
                continue
            placeholders = ",".join("?" for _ in columns)
            quoted = ",".join(f'"{c}"' for c in columns)
            dst.executemany(
                f'INSERT OR REPLACE INTO "{table.name}" ({quoted}) VALUES ({placeholders})',
                rows,
            )
            recovered[table.name] = len(rows)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return {"recovered": recovered, "failed": failed, "destination": str(destination)}


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


class _Portfolios:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def save(self, portfolio: PortfolioRecord, *, force: bool = False) -> PortfolioRecord:
        now = datetime.now(UTC)

        def write(conn: Connection) -> int:
            t = schema.portfolio
            existing = conn.execute(
                sa.select(t.c.created_at).where(t.c.name == portfolio.name)
            ).first()
            if existing is not None and not force:
                raise sa.exc.IntegrityError(
                    "portfolio", {}, Exception(f"UNIQUE constraint: portfolio {portfolio.name!r}")
                )
            values = {
                "name": portfolio.name,
                "tickers": list(portfolio.tickers),
                "weights": None if portfolio.weights is None else list(portfolio.weights),
                "updated_at": now,
            }
            if existing is None:
                conn.execute(t.insert().values(created_at=now, **values))
            else:
                conn.execute(t.update().where(t.c.name == portfolio.name).values(**values))
            return 1

        self._s._run("portfolio_save", write, entity="portfolio")
        saved = self.get(portfolio.name)
        assert saved is not None
        return saved

    def get(self, name: str) -> PortfolioRecord | None:
        def read(conn: Connection) -> PortfolioRecord | None:
            t = schema.portfolio
            row = conn.execute(sa.select(t).where(t.c.name == name)).first()
            return None if row is None else _portfolio(row)

        return self._s._run("portfolio_get", read, entity="portfolio")

    def list(self) -> list[PortfolioRecord]:
        def read(conn: Connection) -> list[PortfolioRecord]:
            t = schema.portfolio
            return [_portfolio(r) for r in conn.execute(sa.select(t).order_by(t.c.name))]

        return self._s._run("portfolio_list", read, entity="portfolio")

    def delete(self, name: str) -> bool:
        def write(conn: Connection) -> int:
            t = schema.portfolio
            return int(conn.execute(sa.delete(t).where(t.c.name == name)).rowcount)

        return self._s._run("portfolio_delete", write, entity="portfolio") > 0


def _portfolio(row: Any) -> PortfolioRecord:
    return PortfolioRecord(
        name=row.name,
        tickers=tuple(row.tickers),
        weights=None if row.weights is None else tuple(float(w) for w in row.weights),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class _Watchlists:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def add(self, name: str, symbols: Sequence[str]) -> WatchlistRecord:
        def write(conn: Connection) -> int:
            t = schema.watchlist
            row = conn.execute(sa.select(t.c.symbols).where(t.c.name == name)).first()
            current: list[str] = [] if row is None else list(row.symbols)
            added = 0
            for symbol in symbols:
                upper = symbol.upper()
                if upper not in current:
                    current.append(upper)
                    added += 1
            now = datetime.now(UTC)
            if row is None:
                conn.execute(t.insert().values(name=name, symbols=current, updated_at=now))
            else:
                conn.execute(
                    t.update().where(t.c.name == name).values(symbols=current, updated_at=now)
                )
            return added

        self._s._run("watchlist_add", write, entity="watchlist")
        record = self.get(name)
        assert record is not None
        return record

    def remove(self, name: str, symbols: Sequence[str]) -> WatchlistRecord | None:
        def write(conn: Connection) -> int:
            t = schema.watchlist
            row = conn.execute(sa.select(t.c.symbols).where(t.c.name == name)).first()
            if row is None:
                return 0
            drop = {s.upper() for s in symbols}
            kept = [s for s in row.symbols if s not in drop]
            conn.execute(
                t.update()
                .where(t.c.name == name)
                .values(symbols=kept, updated_at=datetime.now(UTC))
            )
            return len(row.symbols) - len(kept)

        self._s._run("watchlist_remove", write, entity="watchlist")
        return self.get(name)

    def get(self, name: str) -> WatchlistRecord | None:
        def read(conn: Connection) -> WatchlistRecord | None:
            t = schema.watchlist
            row = conn.execute(sa.select(t).where(t.c.name == name)).first()
            return (
                None
                if row is None
                else WatchlistRecord(row.name, tuple(row.symbols), row.updated_at)
            )

        return self._s._run("watchlist_get", read, entity="watchlist")

    def list(self) -> list[WatchlistRecord]:
        def read(conn: Connection) -> list[WatchlistRecord]:
            t = schema.watchlist
            return [
                WatchlistRecord(r.name, tuple(r.symbols), r.updated_at)
                for r in conn.execute(sa.select(t).order_by(t.c.name))
            ]

        return self._s._run("watchlist_list", read, entity="watchlist")

    def delete(self, name: str) -> bool:
        def write(conn: Connection) -> int:
            t = schema.watchlist
            return int(conn.execute(sa.delete(t).where(t.c.name == name)).rowcount)

        return self._s._run("watchlist_delete", write, entity="watchlist") > 0


class _Goals:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def save(self, goal: GoalRecord, *, force: bool = False) -> GoalRecord:
        now = datetime.now(UTC)

        def write(conn: Connection) -> int:
            t = schema.goal
            existing = conn.execute(sa.select(t.c.created_at).where(t.c.name == goal.name)).first()
            if existing is not None and not force:
                raise sa.exc.IntegrityError(
                    "goal", {}, Exception(f"UNIQUE constraint: goal {goal.name!r}")
                )
            values = {
                "name": goal.name,
                "kind": goal.kind,
                "params": goal.params,
                "updated_at": now,
            }
            if existing is None:
                conn.execute(t.insert().values(created_at=now, **values))
            else:
                conn.execute(t.update().where(t.c.name == goal.name).values(**values))
            return 1

        self._s._run("goal_save", write, entity="goal")
        saved = self.get(goal.name)
        assert saved is not None
        return saved

    def get(self, name: str) -> GoalRecord | None:
        def read(conn: Connection) -> GoalRecord | None:
            t = schema.goal
            row = conn.execute(sa.select(t).where(t.c.name == name)).first()
            return None if row is None else _goal(row)

        return self._s._run("goal_get", read, entity="goal")

    def list(self) -> list[GoalRecord]:
        def read(conn: Connection) -> list[GoalRecord]:
            t = schema.goal
            return [_goal(r) for r in conn.execute(sa.select(t).order_by(t.c.name))]

        return self._s._run("goal_list", read, entity="goal")

    def delete(self, name: str) -> bool:
        def write(conn: Connection) -> int:
            t = schema.goal
            return int(conn.execute(sa.delete(t).where(t.c.name == name)).rowcount)

        return self._s._run("goal_delete", write, entity="goal") > 0


def _goal(row: Any) -> GoalRecord:
    return GoalRecord(
        name=row.name,
        kind=row.kind,
        params=dict(row.params),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class _Runs:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def record(self, run: RunRecord) -> RunRecord:
        created = run.created_at or datetime.now(UTC)

        def write(conn: Connection) -> int:
            conn.execute(
                schema.run.insert().values(
                    id=run.id,
                    command=run.command,
                    params=run.params,
                    estimators=run.estimators,
                    window=run.window,
                    result=run.result,
                    summary=run.summary,
                    created_at=created,
                )
            )
            return 1

        self._s._run("run_record", write, entity="run")
        saved = self.get(run.id)
        assert saved is not None
        return saved

    def get(self, run_id: str) -> RunRecord | None:
        def read(conn: Connection) -> RunRecord | None:
            t = schema.run
            row = conn.execute(sa.select(t).where(t.c.id == run_id)).first()
            return None if row is None else _run_record(row)

        return self._s._run("run_get", read, entity="run")

    def list(self, limit: int = 20, command: str | None = None) -> list[RunRecord]:
        def read(conn: Connection) -> list[RunRecord]:
            t = schema.run
            stmt = sa.select(t).order_by(t.c.created_at.desc(), t.c.id.desc()).limit(limit)
            if command is not None:
                stmt = stmt.where(t.c.command == command)
            return [_run_record(r) for r in conn.execute(stmt)]

        return self._s._run("run_list", read, entity="run")

    def delete(self, run_id: str) -> bool:
        def write(conn: Connection) -> int:
            t = schema.run
            return int(conn.execute(sa.delete(t).where(t.c.id == run_id)).rowcount)

        return self._s._run("run_delete", write, entity="run") > 0


def _run_record(row: Any) -> RunRecord:
    return RunRecord(
        id=row.id,
        command=row.command,
        params=dict(row.params),
        result=dict(row.result),
        summary=row.summary,
        estimators=dict(row.estimators),
        window=dict(row.window),
        created_at=row.created_at,
    )


class _Jobs:
    def __init__(self, storage: SqliteStorage) -> None:
        self._s = storage

    def create(self, job: JobRecord) -> JobRecord:
        now = datetime.now(UTC)

        def write(conn: Connection) -> int:
            conn.execute(
                schema.job.insert().values(
                    id=job.id,
                    command=job.command,
                    params=job.params,
                    state=job.state,
                    progress=job.progress,
                    result=job.result,
                    error=job.error,
                    run_id=job.run_id,
                    trace_context=job.trace_context,
                    created_at=job.created_at or now,
                    updated_at=now,
                    finished_at=job.finished_at,
                )
            )
            return 1

        self._s._run("job_create", write, entity="job")
        saved = self.get(job.id)
        assert saved is not None
        return saved

    def update(self, job_id: str, **changes: Any) -> JobRecord:
        allowed = {"state", "progress", "result", "error", "run_id", "trace_context", "finished_at"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot update job fields {sorted(unknown)}")
        now = datetime.now(UTC)
        if changes.get("state") in TERMINAL_JOB_STATES and "finished_at" not in changes:
            changes["finished_at"] = now

        def write(conn: Connection) -> int:
            t = schema.job
            result = conn.execute(
                t.update().where(t.c.id == job_id).values(updated_at=now, **changes)
            )
            return int(result.rowcount)

        if self._s._run("job_update", write, entity="job") == 0:
            raise StorageError(f"job {job_id!r} does not exist")
        saved = self.get(job_id)
        assert saved is not None
        return saved

    def get(self, job_id: str) -> JobRecord | None:
        def read(conn: Connection) -> JobRecord | None:
            t = schema.job
            row = conn.execute(sa.select(t).where(t.c.id == job_id)).first()
            return None if row is None else _job(row)

        return self._s._run("job_get", read, entity="job")

    def list(self, limit: int = 20, state: str | None = None) -> list[JobRecord]:
        def read(conn: Connection) -> list[JobRecord]:
            t = schema.job
            stmt = sa.select(t).order_by(t.c.created_at.desc(), t.c.id.desc()).limit(limit)
            if state is not None:
                stmt = stmt.where(t.c.state == state)
            return [_job(r) for r in conn.execute(stmt)]

        return self._s._run("job_list", read, entity="job")

    def next_queued(self) -> JobRecord | None:
        def read(conn: Connection) -> JobRecord | None:
            t = schema.job
            row = conn.execute(
                sa.select(t).where(t.c.state == "queued").order_by(t.c.created_at, t.c.id).limit(1)
            ).first()
            return None if row is None else _job(row)

        return self._s._run("job_next", read, entity="job")


def _job(row: Any) -> JobRecord:
    return JobRecord(
        id=row.id,
        command=row.command,
        params=dict(row.params),
        state=row.state,
        progress=float(row.progress),
        result=None if row.result is None else dict(row.result),
        error=None if row.error is None else dict(row.error),
        run_id=row.run_id,
        trace_context=None if row.trace_context is None else dict(row.trace_context),
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _factory(url: str, options: OpenOptions) -> SqliteStorage:
    return SqliteStorage(url, options)


register_backend(BACKEND, _factory)
