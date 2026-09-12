"""``sobres db`` — inspect, back up and repair the database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from sobres.cli.context import Context
from sobres.core.errors import CorruptDatabaseError, UsageError
from sobres.data.storage.base import OpenOptions, open_storage
from sobres.registry import Params, register
from sobres.results import MessageResult, RecordsResult


class DbInfoParams(Params):
    pass


@register(
    "db.info", "Database path, schema version, size and per-table row counts.", result=RecordsResult
)
def db_info(p: DbInfoParams, ctx: Context) -> RecordsResult:
    info = ctx.storage.info()
    rows: list[dict[str, Any]] = [
        {"item": "backend", "value": info.backend},
        {"item": "location", "value": info.location},
        {"item": "schema_version", "value": info.schema_version},
        {"item": "size_bytes", "value": info.size_bytes},
    ]
    rows.extend(
        {"item": f"rows:{table}", "value": count}
        for table, count in sorted(info.table_rows.items())
    )
    return RecordsResult(rows=rows, columns=["item", "value"])


class DbExportParams(Params):
    to: Path = Field(description="Destination file for the consistent copy.")


@register(
    "db.export",
    "Write a consistent copy of the database (safe while in use).",
    result=MessageResult,
    emits_data=False,
)
def db_export(p: DbExportParams, ctx: Context) -> MessageResult:
    destination = p.to.expanduser()
    if destination.exists():
        raise UsageError(f"{destination} already exists", hint="choose a new path")
    ctx.storage.export_to(destination)
    return MessageResult(
        message=f"exported {ctx.storage.location} to {destination}",
        detail={"bytes": destination.stat().st_size},
    )


class DbRepairParams(Params):
    to: Path | None = Field(default=None, description="Recovery file (default: <db>.recovered).")


@register(
    "db.repair",
    "Recover what can be read from a damaged database into a new file; the original is untouched.",
    result=MessageResult,
    emits_data=False,
)
def db_repair(p: DbRepairParams, ctx: Context) -> MessageResult:
    from sobres.data.storage.adapters.sqlite import recover_sqlite

    url = ctx.config.db_url
    try:
        probe = open_storage(url, OpenOptions(migrate=False, check_integrity=True))
    except CorruptDatabaseError:
        pass
    else:
        location = probe.location
        probe.close()
        return MessageResult(message=f"{location} passes its integrity check; nothing to repair")
    from sobres.data.storage.adapters.sqlite import _sqlite_path

    source = _sqlite_path(url)
    if source is None:
        raise UsageError("an in-memory database cannot be repaired")
    destination = p.to.expanduser() if p.to else source.with_name(source.name + ".recovered")
    if destination.exists():
        raise UsageError(
            f"{destination} already exists", hint="pass --to <new path> for the recovery file"
        )
    report = recover_sqlite(source, destination)
    recovered = ", ".join(f"{t}={n}" for t, n in sorted(report["recovered"].items())) or "nothing"
    failed = ", ".join(f"{t} ({e})" for t, e in sorted(report["failed"].items())) or "none"
    return MessageResult(
        message=f"recovered into {destination}; the original {source} was left in place",
        detail={
            "recovered": recovered,
            "not_recovered": failed,
            "next": f"set SOBRES_DB_URL=sqlite:///{destination.as_posix()} after checking it",
        },
    )
