"""One renderer for every result.

Scenarios: Default is human-readable; Piping is machine-readable by default;
JSON is parseable and complete; Float precision; Rendering is generic;
Report-style output.
"""

from __future__ import annotations

import io
import json
from typing import ClassVar

import pandas as pd
import pytest

from sobres.cli.render import DISCLAIMER, default_format, render
from sobres.results import (
    FrameResult,
    MessageResult,
    PriceTable,
    Provenance,
    RecordsResult,
)


class _Report(FrameResult):
    report: ClassVar[bool] = True
    column_kinds: ClassVar[dict[str, str]] = {"w": "weight", "t": "tstat", "n": "int"}
    default_kind: ClassVar[str] = "price"


def _frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(["2020-01-02", "2020-01-03"], name="date")
    return pd.DataFrame(
        {
            "p": [123.456789, float("nan")],
            "w": [0.123456, 0.5],
            "t": [2.345, -1.0],
            "n": [3, 12345],
        },
        index=index,
    )


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_non_tty_defaults_to_csv() -> None:
    assert default_format(io.StringIO()) == "csv"
    assert default_format(_Tty()) == "table"


def test_json_is_sole_stdout_document() -> None:
    out = io.StringIO()
    render(_Report(frame=_frame(), provenance=Provenance(provider="x")), "json", out)
    doc = json.loads(out.getvalue())
    assert doc["columns"] == ["p", "w", "t", "n"]
    assert doc["rows"][0]["index"] == "2020-01-02"
    assert doc["rows"][0]["p"] == 123.456789  # full precision, unrounded
    assert doc["rows"][1]["p"] is None
    assert doc["provenance"]["provider"] == "x"
    assert DISCLAIMER not in out.getvalue()


def test_table_precision_and_disclaimer() -> None:
    out = io.StringIO()
    render(
        _Report(frame=_frame(), provenance=Provenance(provider="x", field="adj_close")),
        "table",
        out,
    )
    text = out.getvalue()
    assert "123.46" in text  # price: 2 decimals
    assert "0.1235" in text  # weight: 4 decimals
    assert "2.35" in text  # t-stat: 2 decimals
    assert "12,345" in text  # int: thousands separator, no decimals
    assert "source: x (adj_close)" in text
    assert DISCLAIMER in text


def test_csv_has_no_chrome() -> None:
    out = io.StringIO()
    render(_Report(frame=_frame()), "csv", out)
    lines = out.getvalue().splitlines()
    assert lines[0] == "date,p,w,t,n"
    assert lines[1].startswith("2020-01-02,123.456789,")
    assert DISCLAIMER not in out.getvalue()


def test_records_and_message_results_render_in_every_format() -> None:
    rec = RecordsResult(rows=[{"k": "a", "v": 1}], columns=["k", "v"])
    msg = MessageResult(message="done", detail={"n": 2})
    for fmt in ("table", "csv", "json"):
        for result in (rec, msg):
            out = io.StringIO()
            render(result, fmt, out)
            assert out.getvalue()
    out = io.StringIO()
    render(msg, "table", out)
    assert "done" in out.getvalue()
    out = io.StringIO()
    render(RecordsResult(rows=[]), "csv", out)
    assert out.getvalue() == "\n"


def test_unknown_format_raises() -> None:
    with pytest.raises(ValueError):
        render(PriceTable(frame=_frame()), "xml", io.StringIO())


def test_provenance_lines_cover_every_field() -> None:
    prov = Provenance(
        provider="yfinance",
        field="adj_close",
        return_kind="total return",
        currency={"AAPL": "USD", "VOD.L": "GBP"},
        start="2020-01-01",
        end="2020-12-31",
        cache="hit",
        flags=[{"symbol": "AAPL", "date": "2020-03-16", "detail": "big move"}],
        notes=["note"],
    )
    lines = prov.lines()
    assert any("mixed" in line for line in lines)
    assert any("window: 2020-01-01" in line for line in lines)
    assert any("cache: hit" in line for line in lines)
    assert any("flag: AAPL" in line for line in lines)
    assert "note" in lines
    assert "currency: USD" in Provenance(currency="USD").lines()
