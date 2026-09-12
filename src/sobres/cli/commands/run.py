"""``sobres run`` — browse, inspect, compare and delete recorded analysis runs.

A stored run is a record of an analysis, not a promise of reproducibility:
upstream data may have been revised since, and every display says so.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from sobres.cli.context import Context
from sobres.core.errors import UsageError
from sobres.data.storage.base import RunRecord
from sobres.registry import Params, positional, register
from sobres.results import MessageResult, RecordsResult, Result

REVISION_NOTE = (
    "stored runs record what was computed at the time; upstream data may have been revised "
    "since, so re-running may not reproduce these numbers"
)


class RunListParams(Params):
    limit: int = Field(default=20, ge=1, le=1000, description="How many runs to show.")
    command: str | None = Field(default=None, description="Only runs of this command.")


class RunListing(RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {"id": "text", "command": "text", "summary": "text"}

    def header_lines(self) -> list[str]:
        return [REVISION_NOTE, *super().header_lines()]


@register("run.list", "List recorded runs, newest first.", result=RunListing)
def run_list(p: RunListParams, ctx: Context) -> RunListing:
    rows: list[dict[str, Any]] = [
        {
            "id": r.id,
            "command": r.command,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "summary": r.summary,
        }
        for r in ctx.storage.runs.list(limit=p.limit, command=p.command)
    ]
    return RunListing(rows=rows, columns=["id", "command", "created_at", "summary"])


class RunShowParams(Params):
    id: str = positional(description="Run id (see `sobres run list`).")


class RunDetail(Result):
    index_label: ClassVar[str | None] = None
    run: dict[str, Any]

    def table(self) -> Any:
        import pandas as pd

        rows = [{"field": k, "value": _brief(v)} for k, v in self.run.items() if k != "result"]
        return pd.DataFrame(rows, columns=["field", "value"])

    def header_lines(self) -> list[str]:
        return [REVISION_NOTE, *super().header_lines()]

    def payload(self) -> dict[str, Any]:
        return {"run": self.run, "note": REVISION_NOTE}


def _brief(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 120 else text[:117] + "..."


@register("run.show", "Show one recorded run in full.", result=RunDetail)
def run_show(p: RunShowParams, ctx: Context) -> RunDetail:
    return RunDetail(run=_as_dict(resolve_run(p.id, ctx)))


class RunDiffParams(Params):
    a: str = positional(description="First run id.")
    b: str = positional(description="Second run id.")


class RunDiff(RecordsResult):
    column_kinds: ClassVar[dict[str, str]] = {
        "section": "text",
        "key": "text",
        "a": "text",
        "b": "text",
    }

    def header_lines(self) -> list[str]:
        return [REVISION_NOTE, *super().header_lines()]


def diff_records(a: RunRecord, b: RunRecord) -> list[dict[str, Any]]:
    """Side-by-side differences in resolved parameters and results."""
    rows: list[dict[str, Any]] = []
    for section, left, right in (("params", a.params, b.params), ("result", a.result, b.result)):
        for key in sorted(set(left) | set(right)):
            if left.get(key) != right.get(key):
                rows.append(
                    {
                        "section": section,
                        "key": key,
                        "a": _brief(left.get(key)),
                        "b": _brief(right.get(key)),
                    }
                )
    return rows


@register("run.diff", "Compare two runs of the same command side by side.", result=RunDiff)
def run_diff(p: RunDiffParams, ctx: Context) -> RunDiff:
    a, b = resolve_run(p.a, ctx), resolve_run(p.b, ctx)
    if a.command != b.command:
        raise UsageError(
            f"runs {a.id} ({a.command}) and {b.id} ({b.command}) are of different commands",
            hint="compare two runs of the same command",
        )
    return RunDiff(rows=diff_records(a, b), columns=["section", "key", "a", "b"])


class RunDeleteParams(Params):
    id: str = positional(description="Run id.")
    yes: bool = Field(default=False, description="Skip the confirmation prompt.")


@register("run.delete", "Delete a recorded run.", result=MessageResult, emits_data=False)
def run_delete(p: RunDeleteParams, ctx: Context) -> MessageResult:
    resolve_run(p.id, ctx)
    if not p.yes and not ctx.ask_confirm(f"Delete run {p.id}?"):
        raise UsageError("delete cancelled", hint="pass --yes to skip the prompt")
    ctx.storage.runs.delete(p.id)
    return MessageResult(message=f"deleted run {p.id}")


def resolve_run(run_id: str, ctx: Context) -> RunRecord:
    record = ctx.storage.runs.get(run_id)
    if record is None:
        raise UsageError(f"no run with id {run_id!r}", hint="run: sobres run list")
    return record


def _as_dict(r: RunRecord) -> dict[str, Any]:
    return {
        "id": r.id,
        "command": r.command,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "summary": r.summary,
        "params": r.params,
        "estimators": r.estimators,
        "window": r.window,
        "result": r.result,
    }
