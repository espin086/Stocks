"""Portability guards: the schema stays inside the SQLite/PostgreSQL/DuckDB intersection.

Scenarios: Portable types only; Timestamps are unambiguous; Decimal-free
monetary handling; No backend-specific SQL in shared code; Identifier
generation is not delegated; Portability guards apply to new tables.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Float, Integer

from sobres.data.storage.adapters import schema

STORAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "sobres" / "data" / "storage"


def test_schema_uses_only_portable_types() -> None:
    for table in schema.metadata.sorted_tables:
        for column in table.columns:
            assert isinstance(column.type, schema.PORTABLE_TYPES), (
                f"{table.name}.{column.name} uses {type(column.type).__name__}"
            )


def test_no_autoincrement_or_sequences() -> None:
    for table in schema.metadata.sorted_tables:
        for column in table.columns:
            assert column.server_default is None, f"{table.name}.{column.name} has a server default"
            assert getattr(column, "identity", None) is None


def test_timestamps_round_trip_as_utc_aware() -> None:
    t = schema.UtcTimestamp()
    local = datetime(2024, 6, 1, 8, 30, 0, 5, tzinfo=timezone(timedelta(hours=-5)))
    stored = t.process_bind_param(local, None)
    assert stored == "2024-06-01T13:30:00.000005Z"
    back = t.process_result_value(stored, None)
    assert back is not None and back.tzinfo is not None and back == local
    assert back.utcoffset() == timedelta(0)
    assert t.process_bind_param(None, None) is None and t.process_result_value(None, None) is None
    with pytest.raises(ValueError):
        t.process_bind_param(datetime(2024, 1, 1), None)  # naive is refused
    assert t.process_bind_param(datetime(2024, 1, 1, tzinfo=UTC), None) is not None


def test_json_as_text_round_trip() -> None:
    j = schema.JsonText()
    assert j.process_bind_param({"b": 1, "a": [1, 2]}, None) == '{"a":[1,2],"b":1}'
    assert j.process_result_value('{"a":[1,2],"b":1}', None) == {"a": [1, 2], "b": 1}
    assert j.process_bind_param(None, None) is None and j.process_result_value(None, None) is None


def test_monetary_values_are_floats_not_decimals() -> None:
    assert isinstance(schema.observation.c.value.type, Float)
    assert isinstance(schema.fetch_log.c.ttl_seconds.type, Integer)


def test_no_backend_specific_sql_outside_adapters() -> None:
    banned = re.compile(
        r"\b(PRAGMA|on_conflict_do_update|sqlite_insert|AUTOINCREMENT|SERIAL|RETURNING)\b"
    )
    for path in STORAGE_DIR.rglob("*.py"):
        if "adapters" in path.parts and path.name in {"sqlite.py"}:
            continue
        text = path.read_text()
        assert not banned.search(text), f"{path.name} carries backend-specific SQL"
