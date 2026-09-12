"""``align_frames`` is the one sanctioned way to combine sources.

Scenarios: Prices aligned to factor returns; Alignment reports what it dropped;
Partial history; Calendar mismatch is explicit.
"""

from __future__ import annotations

import pandas as pd
import pytest

from sobres.core.errors import AlignmentError, InsufficientDataError
from sobres.data import align_frames


def _prices() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=5, name="date")
    frame = pd.DataFrame({"AAPL": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=index)
    frame.attrs = {"provider": "yfinance", "currency": "USD"}
    return frame


def _factors() -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.bdate_range("2020-01-03", periods=5), tz="UTC")
    frame = pd.DataFrame({"Mkt-RF": [0.1, 0.2, 0.3, 0.4, 0.5]}, index=index)
    frame.attrs = {"provider": "ken_french"}
    return frame


def test_inner_join_on_trading_days() -> None:
    out = align_frames(_prices(), _factors(), how="inner")
    assert list(out.index.strftime("%Y-%m-%d")) == ["2020-01-03", "2020-01-06", "2020-01-07"]
    assert list(out.columns) == ["AAPL", "Mkt-RF"]
    assert out.index.tz is None
    assert out.attrs["alignment"] == {
        "how": "inner",
        "rows": 3,
        "dropped": {"yfinance": 2, "ken_french": 2},
    }
    assert out.attrs["provider"] == "yfinance" and out.attrs["currency"] == "USD"


def test_outer_join_keeps_every_date() -> None:
    out = align_frames(_prices(), _factors(), how="outer")
    assert len(out) == 7
    assert out.attrs["alignment"]["dropped"] == {"yfinance": 0, "ken_french": 0}


def test_empty_overlap_raises() -> None:
    late = _factors()
    late.index = late.index + pd.Timedelta(days=365)
    with pytest.raises(AlignmentError) as exc:
        align_frames(_prices(), late)
    assert exc.value.exit_code == 5
    assert "yfinance" in str(exc.value) and "ken_french" in str(exc.value)


def test_min_rows_names_the_constraining_source() -> None:
    with pytest.raises(InsufficientDataError) as exc:
        align_frames(_prices(), _factors(), min_rows=4)
    assert "3 aligned observations" in str(exc.value) and "4 are required" in str(exc.value)


def test_needs_at_least_one_frame() -> None:
    with pytest.raises(ValueError):
        align_frames()


def test_unnamed_sources_get_positional_names() -> None:
    a = pd.DataFrame({"x": [1.0]}, index=pd.DatetimeIndex(["2020-01-01"]))
    b = pd.DataFrame({"y": ["s"]}, index=pd.DatetimeIndex(["2020-01-01"]))
    out = align_frames(a, b)
    assert out.attrs["alignment"]["dropped"] == {"source1": 0, "source2": 0}
    assert out["y"].iloc[0] == "s"  # a non-float frame is joined without float coercion
