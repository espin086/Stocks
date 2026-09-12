"""Shared provider contract suites, parametrized over every registered provider.

Adding a provider means adding one entry to the fixture list in the test
module that uses these; the suite itself does not change.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from sobres.data.base import (
    FACTOR_COLUMNS,
    FactorProvider,
    FxProvider,
    MacroProvider,
    PriceProvider,
)


def _assert_canonical(frame: pd.DataFrame, columns: list[str]) -> None:
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.name == "date"
    assert frame.index.tz is None
    assert frame.index.is_monotonic_increasing and not frame.index.has_duplicates
    assert list(frame.columns) == columns
    assert all(str(d) == "float64" for d in frame.dtypes)
    assert "provider" in frame.attrs and "field" in frame.attrs


def contract_test_price_provider(provider: PriceProvider) -> None:
    frame = provider.get_prices(["aapl", "MSFT"], date(2020, 1, 1), date(2020, 3, 31))
    _assert_canonical(frame, ["AAPL", "MSFT"])
    assert frame.attrs["field"] == "adj_close"
    assert frame.attrs["provider"] == provider.name
    assert frame.attrs["currency"] == "USD"
    assert frame.attrs["return_kind"] == "total return"
    assert (frame.dropna() > 0).all().all()


def contract_test_macro_provider(provider: MacroProvider) -> None:
    frame = provider.get_series(["dgs10"], date(2020, 1, 1), date(2020, 3, 31))
    _assert_canonical(frame, ["DGS10"])
    assert frame.attrs["provider"] == provider.name


def contract_test_factor_provider(provider: FactorProvider) -> None:
    for model, columns in FACTOR_COLUMNS.items():
        frame = provider.get_factors(model, "monthly", date(2020, 1, 1), date(2020, 12, 31))  # type: ignore[arg-type]
        _assert_canonical(frame, list(columns))
        assert frame.attrs["model"] == model
        assert frame.abs().max().max() < 1.0  # decimal, not percent


def contract_test_fx_provider(provider: FxProvider) -> None:
    frame = provider.get_rates(["EURUSD", "USDGBP"], date(2020, 1, 1), date(2020, 3, 31))
    _assert_canonical(frame, ["EURUSD", "USDGBP"])
    assert frame.attrs["base"] == provider.base_currency
    assert (frame.dropna() > 0).all().all()
