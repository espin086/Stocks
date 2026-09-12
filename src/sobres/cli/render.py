"""One renderer for every result: ``render(result, fmt, stream)``.

Table output is a Rich table for humans; CSV is the default when stdout is
not a TTY; JSON is a single parseable document at full precision. Everything
that is not the result — logs, progress, the disclaimer in machine formats —
stays off stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

import pandas as pd
from rich.console import Console
from rich.table import Table

from sobres.results import PRECISION, Result

DISCLAIMER = "For research and education only. Not investment advice."


def default_format(stream: TextIO | None = None) -> str:
    target = stream if stream is not None else sys.stdout
    return "table" if bool(getattr(target, "isatty", lambda: False)()) else "csv"


def _format_cell(value: Any, precision: int) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}" if abs(value) >= 10000 else str(value)
    if isinstance(value, float):
        if precision == 0:
            return f"{value:,.0f}"
        return f"{value:,.{precision}f}"
    return str(value)


def _index_cell(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    return str(value)


def render_table(result: Result, out: TextIO, *, disclaimer: bool = True) -> None:
    console = Console(file=out, force_terminal=False, width=max(80, _width(out)), highlight=False)
    for line in result.header_lines():
        # A header line is a path or a one-line message: never wrap it to the console width.
        console.print(line, markup=False, soft_wrap=True)
    custom = getattr(result, "render_rich", None)
    if custom is not None:
        custom(console)
        if disclaimer and result.report:
            console.print(DISCLAIMER, markup=False, style="dim")
        return
    frame = result.table()
    table = Table(show_header=True, header_style="bold", pad_edge=False)
    if result.index_label is not None:
        table.add_column(result.index_label)
    for column in frame.columns:
        kind = result.kind_of(str(column))
        table.add_column(str(column), justify="right" if kind != "text" else "left")
    for index, row in zip(frame.index, frame.itertuples(index=False), strict=True):
        cells = [
            _format_cell(v, PRECISION.get(result.kind_of(str(c)), 4))
            for c, v in zip(frame.columns, row, strict=True)
        ]
        if result.index_label is not None:
            cells.insert(0, _index_cell(index))
        table.add_row(*cells)
    console.print(table)
    if disclaimer and result.report:
        console.print(DISCLAIMER, markup=False, style="dim")


def _width(out: TextIO) -> int:
    try:
        import shutil

        return shutil.get_terminal_size((120, 24)).columns
    except Exception:  # pragma: no cover - defensive
        return 120


def render_csv(result: Result, out: TextIO) -> None:
    frame = result.table()
    if result.index_label is not None:
        frame = frame.copy()
        frame.index.name = result.index_label
        index = pd.Index([_index_cell(v) for v in frame.index], name=result.index_label)
        frame.index = index
        out.write(frame.to_csv(index=True, lineterminator="\n"))
    else:
        out.write(frame.to_csv(index=False, lineterminator="\n"))


def render_json(result: Result, out: TextIO) -> None:
    out.write(json.dumps(result.payload(), indent=2, default=_json_default, allow_nan=False))
    out.write("\n")


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def render(result: Result, fmt: str | None, out: TextIO | None = None) -> None:
    """Render ``result`` as table, json or csv (default by TTY detection)."""
    stream = out if out is not None else sys.stdout
    chosen = fmt or default_format(stream)
    if chosen == "table":
        render_table(result, stream)
    elif chosen == "csv":
        render_csv(result, stream)
    elif chosen == "json":
        render_json(result, stream)
    else:
        raise ValueError(f"unknown format {chosen!r}")
    stream.flush()
