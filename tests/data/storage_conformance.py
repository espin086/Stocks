"""The shared storage conformance suite: what "a supported backend" means.

Parametrized over ``ADAPTERS`` in ``test_storage_conformance.py``; adding a
backend means one entry there and nothing here. It covers round-tripping every
persisted type, upsert semantics, transaction rollback, a concurrent reader
during a write, migration from every prior schema version, and the exact
exceptions raised on conflict and on constraint violation.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from sobres.core.errors import ConfigurationError, StorageConflictError
from sobres.data.storage.adapters.migrations import CURRENT_VERSION
from sobres.data.storage.base import (
    DateRange,
    FetchRecord,
    GoalRecord,
    JobRecord,
    Observation,
    ObservationQuery,
    PortfolioRecord,
    RunRecord,
    SeriesKey,
    Storage,
)

KEY = SeriesKey("test", "prices_adj_close", "AAPL")


def _obs(day: int, value: float, symbol: str = "AAPL") -> Observation:
    return Observation("test", "prices_adj_close", symbol, date(2020, 1, day), value)


class StorageConformance:
    """Subclass with a ``storage`` fixture that yields an opened, empty backend."""

    def test_observation_round_trip(self, storage: Storage) -> None:
        rows = [_obs(2, 1.0), _obs(3, 2.0), _obs(6, float("nan")), _obs(2, 5.0, "MSFT")]
        assert storage.observations.upsert_observations(rows) == 4
        frame = storage.observations.read_observations(
            ObservationQuery(
                "test", "prices_adj_close", ["AAPL", "MSFT"], date(2020, 1, 1), date(2020, 1, 31)
            )
        )
        assert list(frame.columns) == ["AAPL", "MSFT"]
        assert frame.index.name == "date"
        assert frame.index.tz is None
        assert frame.loc["2020-01-02", "AAPL"] == 1.0
        assert frame.loc["2020-01-02", "MSFT"] == 5.0
        assert pd.isna(frame.loc["2020-01-03", "MSFT"])
        assert pd.isna(frame.loc["2020-01-06", "AAPL"])
        assert str(frame.dtypes["AAPL"]) == "float64"

    def test_read_of_empty_range_has_requested_columns(self, storage: Storage) -> None:
        frame = storage.observations.read_observations(
            ObservationQuery("test", "x", ["A", "B"], date(2020, 1, 1), date(2020, 1, 2))
        )
        assert list(frame.columns) == ["A", "B"] and frame.empty
        assert isinstance(frame.index, pd.DatetimeIndex)

    def test_upsert_overwrites_same_identity(self, storage: Storage) -> None:
        storage.observations.upsert_observations([_obs(2, 1.0)])
        storage.observations.upsert_observations([_obs(2, 9.0)])
        frame = storage.observations.read_observations(
            ObservationQuery(
                "test", "prices_adj_close", ["AAPL"], date(2020, 1, 1), date(2020, 1, 31)
            )
        )
        assert len(frame) == 1 and frame.iloc[0, 0] == 9.0
        assert storage.observations.upsert_observations([]) == 0

    def test_fetch_log_round_trips_utc_timestamps(self, storage: Storage) -> None:
        when = datetime(2024, 5, 1, 12, 30, 15, 123456, tzinfo=UTC)
        record = FetchRecord(KEY, DateRange(date(2020, 1, 1), date(2020, 12, 31)), when, 86400)
        storage.observations.record_fetch(record)
        [back] = storage.observations.fetched_ranges(KEY)
        assert back == record
        assert back.fetched_at.tzinfo is not None and back.fetched_at.utcoffset() == timedelta(0)
        assert back.expires_at() == when + timedelta(days=1)
        assert storage.observations.fetched_ranges(SeriesKey("test", "x", "NONE")) == []

    def test_series_meta_json_round_trip(self, storage: Storage) -> None:
        assert storage.observations.get_series_meta(KEY) is None
        meta = {"currency": "GBP", "flags": [{"rule": "x"}], "n": 2, "ok": True}
        storage.observations.put_series_meta(KEY, meta)
        assert storage.observations.get_series_meta(KEY) == meta
        storage.observations.put_series_meta(KEY, {"currency": "USD"})
        assert storage.observations.get_series_meta(KEY) == {"currency": "USD"}

    def test_key_value_round_trip(self, storage: Storage) -> None:
        assert storage.kv.get("missing") is None
        storage.kv.set("a", {"x": [1, 2.5, "s", None, True]})
        storage.kv.set("b", 3)
        assert storage.kv.get("a") == {"x": [1, 2.5, "s", None, True]}
        assert storage.kv.items() == {"a": {"x": [1, 2.5, "s", None, True]}, "b": 3}
        storage.kv.set("b", 4)
        assert storage.kv.get("b") == 4
        assert storage.kv.delete("b") is True
        assert storage.kv.delete("b") is False

    def test_transaction_rolls_back_as_a_unit(self, storage: Storage) -> None:
        with pytest.raises(RuntimeError), storage.transaction():
            storage.kv.set("inside", 1)
            storage.observations.upsert_observations([_obs(2, 1.0)])
            raise RuntimeError("abort")
        assert storage.kv.get("inside") is None
        assert storage.observations.cache_stats().entries == 0
        with storage.transaction():
            storage.kv.set("kept", 1)
            with storage.transaction():  # nested joins the outer unit
                storage.kv.set("nested", 2)
        assert storage.kv.get("kept") == 1 and storage.kv.get("nested") == 2

    def test_conflict_raises_translated_error(self, storage: Storage) -> None:
        when = datetime.now(UTC)
        record = FetchRecord(KEY, DateRange(date(2020, 1, 1), date(2020, 1, 2)), when, 1)
        storage.observations.record_fetch(record)
        storage.observations.record_fetch(record)  # ids are application-generated: no clash
        with pytest.raises(StorageConflictError):
            storage.duplicate_kv_insert("dup")  # type: ignore[attr-defined]

    def test_constraint_violation_raises_translated_error(self, storage: Storage) -> None:
        from sobres.core.errors import StorageConstraintError

        with pytest.raises(StorageConstraintError):
            storage.null_violation()  # type: ignore[attr-defined]

    def test_concurrent_reader_during_write(self, storage: Storage) -> None:
        storage.observations.upsert_observations([_obs(2, 1.0)])
        seen: list[int] = []

        def reader() -> None:
            seen.append(storage.observations.cache_stats().entries)

        with storage.transaction():
            storage.observations.upsert_observations([_obs(d, float(d)) for d in range(3, 20)])
            t = threading.Thread(target=reader)
            t.start()
            t.join(timeout=10)
        assert seen and seen[0] >= 1

    def test_migration_from_every_prior_version(self, storage: Storage) -> None:
        assert storage.schema_version() == CURRENT_VERSION
        assert storage.code_schema_version() == CURRENT_VERSION
        assert storage.pending_migrations() == []
        assert storage.migrate() == []

    def test_newer_schema_than_code_refuses(self, storage: Storage) -> None:
        storage.bump_schema_version(CURRENT_VERSION + 5)  # type: ignore[attr-defined]
        with pytest.raises(ConfigurationError) as exc:
            storage.pending_migrations()
        assert "sobres upgrade" in str(exc.value)
        with pytest.raises(ConfigurationError):
            storage.migrate()

    def test_clear_observations_scoped_by_provider(self, storage: Storage) -> None:
        storage.observations.upsert_observations([_obs(2, 1.0)])
        storage.observations.upsert_observations(
            [Observation("other", "d", "S", date(2020, 1, 2), 1.0)]
        )
        storage.observations.record_fetch(
            FetchRecord(KEY, DateRange(date(2020, 1, 1), date(2020, 1, 2)), datetime.now(UTC), 1)
        )
        storage.observations.put_series_meta(KEY, {"a": 1})
        storage.kv.set("user", "row")
        assert storage.observations.clear_observations("test") == 3
        assert storage.observations.cache_stats().entries == 1
        assert storage.kv.get("user") == "row"
        assert storage.observations.clear_observations() == 1
        assert storage.observations.cache_stats().entries == 0

    def test_cache_stats_and_info(self, storage: Storage) -> None:
        stats = storage.observations.cache_stats()
        assert stats.entries == 0 and stats.series == 0 and stats.oldest_fetch is None
        storage.observations.upsert_observations([_obs(2, 1.0), _obs(3, 1.0), _obs(2, 1.0, "MSFT")])
        when = datetime(2024, 1, 1, tzinfo=UTC)
        storage.observations.record_fetch(
            FetchRecord(KEY, DateRange(date(2020, 1, 1), date(2020, 1, 2)), when, 1)
        )
        stats = storage.observations.cache_stats()
        assert stats.entries == 3 and stats.series == 2 and stats.oldest_fetch == when
        info = storage.info()
        assert info.schema_version == CURRENT_VERSION
        assert info.table_rows["observation"] == 3
        assert info.backend == storage.backend


# ------------------------------------------------------------------ 0003 repositories


def _portfolio(
    name: str = "core", weights: tuple[float, ...] | None = (0.6, 0.4)
) -> PortfolioRecord:
    return PortfolioRecord(name=name, tickers=("AAPL", "MSFT"), weights=weights)


class ApplicationStateConformance:
    """Portfolios, watchlists, goals, runs and jobs behind the same port."""

    def test_portfolio_round_trip_and_conflict(self, storage: Storage) -> None:
        saved = storage.portfolios.save(_portfolio())
        assert saved.tickers == ("AAPL", "MSFT") and saved.weights == (0.6, 0.4)
        assert saved.created_at is not None and saved.created_at.tzinfo is not None
        with pytest.raises(StorageConflictError):
            storage.portfolios.save(_portfolio(weights=None))
        replaced = storage.portfolios.save(_portfolio(weights=None), force=True)
        assert replaced.weights is None and replaced.created_at == saved.created_at
        assert replaced.updated_at is not None and replaced.updated_at >= saved.created_at
        assert [p.name for p in storage.portfolios.list()] == ["core"]
        assert storage.portfolios.get("missing") is None
        assert storage.portfolios.delete("core") is True
        assert storage.portfolios.delete("core") is False

    def test_watchlist_add_is_idempotent(self, storage: Storage) -> None:
        first = storage.watchlists.add("tech", ["nvda", "AMD"])
        assert first.symbols == ("NVDA", "AMD")
        again = storage.watchlists.add("tech", ["AMD", "INTC"])
        assert again.symbols == ("NVDA", "AMD", "INTC")
        assert [w.name for w in storage.watchlists.list()] == ["tech"]
        trimmed = storage.watchlists.remove("tech", ["nvda"])
        assert trimmed is not None and trimmed.symbols == ("AMD", "INTC")
        assert storage.watchlists.remove("absent", ["X"]) is None
        assert storage.watchlists.delete("tech") is True and storage.watchlists.get("tech") is None

    def test_goal_round_trip(self, storage: Storage) -> None:
        goal = GoalRecord(name="fire", kind="retire", params={"income": 200000, "real": True})
        saved = storage.goals.save(goal)
        assert saved.params == goal.params and saved.kind == "retire"
        with pytest.raises(StorageConflictError):
            storage.goals.save(goal)
        updated = storage.goals.save(GoalRecord("fire", "retire", {"income": 1}), force=True)
        assert updated.params == {"income": 1}
        assert [g.name for g in storage.goals.list()] == ["fire"]
        assert storage.goals.delete("fire") and storage.goals.get("fire") is None

    def test_run_history_newest_first(self, storage: Storage) -> None:
        for i in range(3):
            storage.runs.record(
                RunRecord(
                    id=f"r{i}",
                    command="optimize.markowitz" if i < 2 else "optimize.risk",
                    params={"tickers": ["AAPL"], "n": i},
                    result={"sharpe": i / 10},
                    summary=f"run {i}",
                    estimators={"covariance": "ledoit_wolf"},
                    window={"start": "2020-01-01", "end": "2020-12-31"},
                    created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
                )
            )
        listed = storage.runs.list()
        assert [r.id for r in listed] == ["r2", "r1", "r0"]
        assert [r.id for r in storage.runs.list(limit=1)] == ["r2"]
        assert [r.id for r in storage.runs.list(command="optimize.risk")] == ["r2"]
        got = storage.runs.get("r1")
        assert (
            got is not None
            and got.params["n"] == 1
            and got.estimators["covariance"] == "ledoit_wolf"
        )
        with pytest.raises(StorageConflictError):
            storage.runs.record(RunRecord("r1", "x", {}, {}, ""))
        assert storage.runs.delete("r1") and storage.runs.get("r1") is None

    def test_job_lifecycle(self, storage: Storage) -> None:
        from sobres.core.errors import StorageError

        job = storage.jobs.create(JobRecord(id="j1", command="optimize.backtest", params={"a": 1}))
        assert job.state == "queued" and job.progress == 0.0 and job.finished_at is None
        assert storage.jobs.next_queued() is not None and storage.jobs.next_queued().id == "j1"  # type: ignore[union-attr]
        running = storage.jobs.update("j1", state="running", progress=0.5, run_id="abc")
        assert running.state == "running" and running.progress == 0.5 and running.run_id == "abc"
        assert storage.jobs.next_queued() is None
        done = storage.jobs.update("j1", state="succeeded", result={"ok": True})
        assert done.finished_at is not None and done.result == {"ok": True}
        assert [j.id for j in storage.jobs.list(state="succeeded")] == ["j1"]
        with pytest.raises(ValueError):
            storage.jobs.update("j1", bogus=1)
        with pytest.raises(StorageError):
            storage.jobs.update("nope", state="failed")
        assert storage.jobs.get("nope") is None

    def test_cache_clear_never_touches_user_rows(self, storage: Storage) -> None:
        storage.portfolios.save(_portfolio())
        storage.watchlists.add("w", ["A"])
        storage.goals.save(GoalRecord("g", "goal", {}))
        storage.runs.record(RunRecord("r", "c", {}, {}, "s"))
        storage.jobs.create(JobRecord("j", "c", {}))
        storage.observations.upsert_observations([_obs(2, 1.0)])
        assert storage.observations.clear_observations() == 1
        assert storage.portfolios.get("core") and storage.watchlists.get("w")
        assert storage.goals.get("g") and storage.runs.get("r") and storage.jobs.get("j")

    def test_info_counts_every_table(self, storage: Storage) -> None:
        info = storage.info()
        for table in ("portfolio", "watchlist", "goal", "run", "job", "observation"):
            assert table in info.table_rows
