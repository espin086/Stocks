"""Canonical frame validation and data quality on ingest.

Scenarios: Multi-ticker request; Structural validation; Implausible moves are
flagged; Adjustment consistency; Timezone safety; A concrete provider satisfies
the protocol; Adjusted close is total return.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sobres.core.errors import ProviderError
from sobres.data.base import (
    FACTOR_COLUMNS,
    QualityFlag,
    canonical_frame,
    check_adjustment_consistency,
    validate_price_frame,
)


def _frame(values: list[float], symbol: str = "AAPL") -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=len(values), name="date")
    frame = pd.DataFrame({symbol: values}, index=index, dtype="float64")
    frame.attrs["provider"] = "test"
    return frame


def test_validate_rejects_tz_aware_index() -> None:
    frame = _frame([1.0, 2.0])
    frame.index = frame.index.tz_localize("UTC")
    with pytest.raises(ProviderError, match="tz-naive"):
        validate_price_frame(frame)


def test_validate_rejects_duplicate_index() -> None:
    frame = _frame([1.0, 2.0])
    frame.index = pd.DatetimeIndex(["2020-01-01", "2020-01-01"])
    with pytest.raises(ProviderError, match="unique-index"):
        validate_price_frame(frame)


def test_validate_rejects_descending_index() -> None:
    frame = _frame([1.0, 2.0]).iloc[::-1]
    with pytest.raises(ProviderError, match="monotonic-index"):
        validate_price_frame(frame)


def test_validate_rejects_non_float_dtype() -> None:
    frame = _frame([1.0, 2.0]).astype("int64")
    with pytest.raises(ProviderError, match="float64"):
        validate_price_frame(frame)


def test_validate_rejects_non_positive_price_naming_symbol_date_rule() -> None:
    with pytest.raises(ProviderError) as exc:
        validate_price_frame(_frame([1.0, 0.0, 2.0]))
    assert "AAPL" in str(exc.value) and "2020-01-02" in str(exc.value)
    assert "positive-price" in str(exc.value)
    validate_price_frame(_frame([1.0, 0.0]), allow_nonpositive=True)


def test_validate_rejects_infinite_but_keeps_nan() -> None:
    with pytest.raises(ProviderError, match="finite"):
        validate_price_frame(_frame([1.0, np.inf]))
    out = validate_price_frame(_frame([1.0, np.nan, 1.2]))
    assert out.attrs["flags"] == []


def test_validate_rejects_non_datetime_index() -> None:
    frame = pd.DataFrame({"A": [1.0]}, index=[1])
    with pytest.raises(ProviderError, match="index-type"):
        validate_price_frame(frame)


def test_implausible_move_kept_and_flagged() -> None:
    frame = _frame([100.0, 100.0, 170.0, 171.0])
    out = validate_price_frame(frame, implausible_move=0.5)
    assert len(out) == 4  # kept
    [flag] = out.attrs["flags"]
    assert flag["symbol"] == "AAPL" and flag["rule"] == "implausible-move"
    assert flag["date"] == "2020-01-03" and "+70.0%" in flag["detail"]
    assert validate_price_frame(_frame([100.0, 140.0]), implausible_move=0.5).attrs["flags"] == []


def test_adjustment_factor_violation_flagged() -> None:
    index = pd.bdate_range("2020-01-01", periods=4)
    close = pd.Series([100.0, 100.0, 100.0, 100.0], index=index)
    good = pd.Series([90.0, 90.0, 95.0, 100.0], index=index)  # factor rises forward: ok
    assert check_adjustment_consistency(good, close, "X") == []
    bad = pd.Series([95.0, 90.0, 95.0, 100.0], index=index)  # factor falls forward: error
    [flag] = check_adjustment_consistency(bad, close, "X")
    assert flag["rule"] == "adjustment-factor" and flag["date"] == "2020-01-02"
    assert check_adjustment_consistency(pd.Series(dtype=float), pd.Series(dtype=float), "X") == []


def test_canonical_frame_normalizes_tz_duplicates_order_and_dtype() -> None:
    index = pd.DatetimeIndex(
        ["2020-01-03 15:00", "2020-01-02 15:00", "2020-01-02 09:00"], tz="America/New_York"
    )
    frame = pd.DataFrame({"b": [3, 2, 1], "a": [30, 20, 10]}, index=index)
    frame.attrs["provider"] = "p"
    out = canonical_frame(frame, ["a", "b", "c"])
    assert out.index.tz is None and out.index.name == "date"
    assert list(out.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03"]
    assert list(out.columns) == ["a", "b", "c"]
    assert out.loc["2020-01-02", "a"] == 20.0  # keep="last" on duplicates
    assert all(str(d) == "float64" for d in out.dtypes)
    assert out.attrs["provider"] == "p"


def test_quality_flag_as_dict() -> None:
    flag = QualityFlag("A", "2020-01-01", "r", "d").as_dict()
    assert flag == {"symbol": "A", "date": "2020-01-01", "rule": "r", "detail": "d"}


def test_factor_column_sets_are_exact() -> None:
    assert FACTOR_COLUMNS["ff3"] == ("Mkt-RF", "SMB", "HML", "RF")
    assert FACTOR_COLUMNS["ff5"] == ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF")
    assert FACTOR_COLUMNS["ff5+mom"] == ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF")
