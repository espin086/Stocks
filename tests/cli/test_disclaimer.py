"""The not-advice footer: table only, never in machine formats.

Scenarios: Report-style output.
"""

from __future__ import annotations

import io
from typing import ClassVar

import pandas as pd

from sobres.cli.render import DISCLAIMER, render
from sobres.results import FrameResult


class _Report(FrameResult):
    report: ClassVar[bool] = True


class _Plain(FrameResult):
    report: ClassVar[bool] = False


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"x": [1.0]}, index=pd.DatetimeIndex(["2020-01-01"], name="date"))


def test_absent_from_json_and_csv() -> None:
    for fmt in ("json", "csv"):
        out = io.StringIO()
        render(_Report(frame=_frame()), fmt, out)
        assert DISCLAIMER not in out.getvalue()


def test_present_in_table_for_report_results_only() -> None:
    out = io.StringIO()
    render(_Report(frame=_frame()), "table", out)
    assert DISCLAIMER in out.getvalue()
    out = io.StringIO()
    render(_Plain(frame=_frame()), "table", out)
    assert DISCLAIMER not in out.getvalue()
    assert DISCLAIMER == "For research and education only. Not investment advice."
