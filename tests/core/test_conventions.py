"""Frequency conventions.

Scenarios: Annualization.
"""

from __future__ import annotations

import pandas as pd
import pytest

from sobres.core.conventions import FREQUENCIES, PERIODS_PER_YEAR, infer_frequency, periods_per_year


def test_periods_table_is_the_documented_one() -> None:
    assert PERIODS_PER_YEAR == {
        "daily": 252,
        "weekly": 52,
        "monthly": 12,
        "quarterly": 4,
        "annual": 1,
    }
    assert FREQUENCIES == ("daily", "weekly", "monthly", "quarterly", "annual")
    assert periods_per_year("monthly") == 12
    with pytest.raises(ValueError):
        periods_per_year("hourly")


def test_frequency_inference() -> None:
    assert infer_frequency(pd.bdate_range("2020-01-01", periods=30)) == "daily"
    assert infer_frequency(pd.date_range("2020-01-03", periods=10, freq="W-FRI")) == "weekly"
    assert infer_frequency(pd.date_range("2020-01-31", periods=10, freq="ME")) == "monthly"
    assert infer_frequency(pd.date_range("2020-03-31", periods=6, freq="QE")) == "quarterly"
    assert infer_frequency(pd.date_range("2015-12-31", periods=5, freq="YE")) == "annual"
    with pytest.raises(ValueError):
        infer_frequency(pd.DatetimeIndex(["2020-01-01", "2020-01-02"]))
