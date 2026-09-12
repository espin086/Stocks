"""Missing data has a policy, never a default.

Scenarios: Gaps are classified; Filling is explicit; Too little data is an
error, not a shorter answer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.errors import InsufficientDataError
from sobres.data.gaps import apply_fill_policy, classify_gaps


def _frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.bdate_range("2020-01-01", periods=6))
    return pd.DataFrame(
        {
            "NEW": [np.nan, np.nan, 3.0, 4.0, 5.0, 6.0],  # listed on day 3
            "GAP": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0],  # provider gap on day 3
            "OLD": [1.0, 2.0, 3.0, 4.0, np.nan, np.nan],  # delisted after day 4
        },
        index=index,
    )


def test_only_provider_gaps_are_fillable() -> None:
    kinds = classify_gaps(_frame())
    assert kinds.iloc[0]["NEW"] == "not_listed"
    assert kinds.iloc[2]["GAP"] == "provider_gap"
    assert kinds.iloc[5]["OLD"] == "delisted"
    assert pd.isna(kinds.iloc[3]["GAP"])
    filled = apply_fill_policy(_frame(), "ffill")
    assert filled.loc["2020-01-03", "GAP"] == 2.0
    assert pd.isna(filled.loc["2020-01-01", "NEW"])  # listing gap untouched
    assert pd.isna(filled.loc["2020-01-08", "OLD"])  # delisting gap untouched
    assert filled.attrs["filled"] == {"policy": "ffill", "filled": 1, "dropped_rows": 0}


def test_market_closed_when_a_calendar_is_given() -> None:
    frame = pd.DataFrame(
        {"A": [1.0, np.nan, 3.0]},
        index=pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )
    calendar = pd.DatetimeIndex(["2020-01-01", "2020-01-03"])
    assert classify_gaps(frame, calendar).iloc[1]["A"] == "market_closed"


def test_fill_policy_has_no_default() -> None:
    import inspect

    assert (
        inspect.signature(apply_fill_policy).parameters["policy"].default is inspect.Parameter.empty
    )
    with pytest.raises(ValueError):
        apply_fill_policy(_frame(), "guess")  # type: ignore[arg-type]


def test_drop_removes_rows_with_provider_gaps_and_reports() -> None:
    out = apply_fill_policy(_frame(), "drop")
    assert len(out) == 5 and "2020-01-03" not in out.index.strftime("%Y-%m-%d")
    assert out.attrs["filled"] == {"policy": "drop", "filled": 0, "dropped_rows": 1}


def test_raise_names_the_first_gap() -> None:
    with pytest.raises(InsufficientDataError) as exc:
        apply_fill_policy(_frame(), "raise")
    assert exc.value.exit_code == 5
    assert "GAP" in str(exc.value) and "2020-01-03" in str(exc.value)


def test_no_gaps_is_a_no_op_under_every_policy() -> None:
    clean = _frame().dropna()
    for policy in ("drop", "ffill", "raise"):
        out = apply_fill_policy(clean, policy)  # type: ignore[arg-type]
        assert out.attrs["filled"]["filled"] == 0 and len(out) == len(clean)
