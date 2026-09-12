"""One forward-only migration set, applied by the adapter, no branching on backend.

Lives under ``adapters/`` because it is expressed through SQLAlchemy Core, the
dialect layer that must never be imported above the port.

A migration is never edited after release; a correction is a new migration.
Each step receives a SQLAlchemy Core connection and creates or alters tables
through the shared ``schema`` metadata, so it runs unchanged on every backend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sobres.data.storage.adapters import schema


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Any], None]


def _v1_initial(conn: Any) -> None:
    schema.metadata.create_all(
        conn,
        tables=[
            schema.schema_version,
            schema.observation,
            schema.fetch_log,
            schema.series_meta,
            schema.kv,
        ],
    )


MIGRATIONS: tuple[Migration, ...] = (Migration(1, "initial-cache-and-kv", _v1_initial),)

CURRENT_VERSION = MIGRATIONS[-1].version
