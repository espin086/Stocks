"""Typed results: every handler returns a declared type, never a bare frame.

A result carries the provenance the renderers need — provider, field, window,
currency, cache outcome, data-quality flags — so one renderer handles every
result and no command formats its own output.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

ColumnKind = str  # price | return | weight | tstat | rate | int | text | pct

PRECISION: dict[str, int] = {
    "price": 2,
    "return": 4,
    "weight": 4,
    "rate": 4,
    "tstat": 2,
    "pct": 4,
    "int": 0,
    "value": 4,
}


class Provenance(BaseModel):
    """Where a result came from and what shaped it."""

    provider: str | None = None
    field: str | None = None
    return_kind: str | None = None
    currency: str | dict[str, str] | None = None
    start: str | None = None
    end: str | None = None
    cache: str | None = None
    fetched_at: str | None = None
    flags: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.provider:
            out.append(f"source: {self.provider}" + (f" ({self.field})" if self.field else ""))
        if self.return_kind:
            out.append(f"prices are {self.return_kind}")
        if self.currency:
            if isinstance(self.currency, dict):
                pairs = ", ".join(f"{k}={v}" for k, v in sorted(self.currency.items()))
                out.append(f"currency: mixed ({pairs})")
            else:
                out.append(f"currency: {self.currency}")
        if self.start or self.end:
            out.append(f"window: {self.start or '…'} → {self.end or '…'}")
        if self.cache:
            out.append(f"cache: {self.cache}")
        for flag in self.flags:
            out.append(f"flag: {flag.get('symbol')} {flag.get('date')} {flag.get('detail')}")
        out.extend(self.notes)
        return out

    @classmethod
    def from_attrs(cls, attrs: Mapping[Any, Any], **extra: Any) -> Provenance:
        cache = attrs.get("cache")
        return cls(
            provider=attrs.get("provider"),
            field=attrs.get("field"),
            return_kind=attrs.get("return_kind"),
            currency=attrs.get("currency"),
            cache=cache.get("status") if isinstance(cache, dict) else cache,
            fetched_at=attrs.get("fetched_at"),
            flags=list(attrs.get("flags", [])),
            **extra,
        )


class Result(BaseModel):
    """Base of every command result."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    report: ClassVar[bool] = False
    """True when the result is analysis-shaped and the disclaimer footer applies."""
    column_kinds: ClassVar[dict[str, ColumnKind]] = {}
    default_kind: ClassVar[ColumnKind] = "value"
    index_label: ClassVar[str | None] = None

    provenance: Provenance = Field(default_factory=Provenance)

    def table(self) -> pd.DataFrame:
        raise NotImplementedError

    def kind_of(self, column: str) -> ColumnKind:
        return self.column_kinds.get(column, self.default_kind)

    def header_lines(self) -> list[str]:
        return self.provenance.lines()

    def summary_line(self) -> str:
        """One line for run listings: the first header line, or the row count."""
        lines = self.header_lines()
        if lines:
            return lines[0]
        return f"{len(self.table())} rows"

    def payload(self) -> dict[str, Any]:
        """The JSON document: full precision, never rounded."""
        frame = self.table()
        data = self.model_dump(mode="json", exclude={"frame"})
        data["columns"] = [str(c) for c in frame.columns]
        data["rows"] = [
            {
                **({"index": _json_scalar(idx)} if self.index_label is not None else {}),
                **{str(c): _json_scalar(v) for c, v in zip(frame.columns, row, strict=True)},
            }
            for idx, row in zip(frame.index, frame.to_numpy().tolist(), strict=True)
        ]
        return data


def _json_scalar(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _json_scalar(value.item())
    return value


class FrameResult(Result):
    """A date-indexed (or otherwise indexed) table."""

    index_label: ClassVar[str | None] = "date"

    frame: pd.DataFrame

    def table(self) -> pd.DataFrame:
        return self.frame


class RecordsResult(Result):
    """Rows of key/value records — settings, cache info, listings."""

    index_label: ClassVar[str | None] = None

    rows: list[dict[str, Any]]
    columns: Sequence[str] = ()

    def table(self) -> pd.DataFrame:
        columns = list(self.columns) or (list(self.rows[0]) if self.rows else [])
        return pd.DataFrame(self.rows, columns=columns)


class MessageResult(Result):
    """A short human message with optional structured detail."""

    index_label: ClassVar[str | None] = None

    message: str
    detail: dict[str, Any] = Field(default_factory=dict)

    def table(self) -> pd.DataFrame:
        rows = [{"key": k, "value": v} for k, v in self.detail.items()]
        return pd.DataFrame(rows, columns=["key", "value"])

    def header_lines(self) -> list[str]:
        return [self.message, *super().header_lines()]

    def render_rich(self, console: Any) -> None:
        for key, value in self.detail.items():
            console.print(f"  {key}: {value}", markup=False, soft_wrap=True)


# ----------------------------------------------------------------- 0001 results


class PriceTable(FrameResult):
    """``sobres data prices``: one column per ticker."""

    default_kind: ClassVar[ColumnKind] = "price"


class MacroTable(FrameResult):
    """``sobres data macro``: one column per FRED series."""

    default_kind: ClassVar[ColumnKind] = "value"


class FactorTable(FrameResult):
    """``sobres data factors``: factor returns plus ``RF``, decimal."""

    default_kind: ClassVar[ColumnKind] = "return"
    model: str
    frequency: str


class FxTable(FrameResult):
    """``sobres data fx``: one column per currency pair, quote per one base."""

    default_kind: ClassVar[ColumnKind] = "rate"
    base: str


class CommandListing(RecordsResult):
    """``sobres commands``: the registry, queryable."""

    commands: list[dict[str, Any]] = Field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {"commands": self.commands}
