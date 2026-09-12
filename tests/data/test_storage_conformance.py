"""Run the shared conformance suite against every registered adapter.

Scenarios: One suite, every adapter; The suite defines the contract; Behavior
is identical across backends; Unit of work; Errors are translated; Contention;
Automatic upgrade; Migrations are tested against real prior states;
Newer database than the installed tool; Cache and user data are never conflated;
Timestamps are unambiguous; Identifier generation is not delegated.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from sobres.data.storage.adapters import schema
from sobres.data.storage.adapters.sqlite import SqliteStorage
from sobres.data.storage.base import OpenOptions, Storage, open_storage, registered_backends
from tests.data.storage_conformance import StorageConformance

# One entry per adapter: (scheme, factory taking a tmp dir). Adding a backend
# means adding to this list and nothing else in the suite.
ADAPTERS: dict[str, object] = {
    "sqlite": lambda tmp: f"sqlite:///{(tmp / 'conformance.db').as_posix()}",
}


def test_every_registered_backend_is_in_the_fixture_list() -> None:
    assert set(registered_backends()) == set(ADAPTERS)


def _add_probe_methods(store: Storage) -> None:
    """Backend-neutral hooks the suite uses to provoke driver errors."""
    if isinstance(store, SqliteStorage):

        def duplicate_kv_insert(key: str) -> None:
            def insert(conn: sa.engine.Connection) -> int:
                from datetime import UTC, datetime

                for _ in range(2):
                    conn.execute(
                        schema.kv.insert().values(key=key, value=1, updated_at=datetime.now(UTC))
                    )
                return 2

            store._run("probe", insert)

        def null_violation() -> None:
            def insert(conn: sa.engine.Connection) -> int:
                conn.execute(schema.schema_version.insert().values(version=99, name=None))
                return 1

            store._run("probe", insert)

        def bump_schema_version(version: int) -> None:
            def insert(conn: sa.engine.Connection) -> int:
                from datetime import UTC, datetime

                conn.execute(
                    schema.schema_version.insert().values(
                        version=version, name="future", applied_at=datetime.now(UTC)
                    )
                )
                return 1

            store._run("probe", insert)

        store.duplicate_kv_insert = duplicate_kv_insert  # type: ignore[attr-defined]
        store.null_violation = null_violation  # type: ignore[attr-defined]
        store.bump_schema_version = bump_schema_version  # type: ignore[attr-defined]


@pytest.fixture(params=sorted(ADAPTERS))
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Storage]:
    url = ADAPTERS[request.param](tmp_path)  # type: ignore[operator]
    store = open_storage(url, OpenOptions())
    _add_probe_methods(store)
    yield store
    store.close()


class TestConformance(StorageConformance):
    pass
