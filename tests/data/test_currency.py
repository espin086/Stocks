"""The currency model: typed pairs, exact conversion, sub-unit normalization.

Scenarios: Pairs are typed; Call sites never multiply or divide by a rate;
Inversion is exact where it must be; Cross rates are triangulated consistently;
Sub-unit quotations; Unknown currency; Currency is discovered, not assumed;
Converting a price series; Converting a return series; Mixed currencies are
refused, not guessed; Single-currency work is unaffected; Price frames carry
currency; Round-trip properties; Algebraic properties.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sobres.core.errors import ProviderError, UsageError
from sobres.data.currency import (
    CurrencyPair,
    FxRates,
    convert,
    convert_frame,
    convert_returns,
    convert_series,
    frame_currencies,
    fx_returns,
    normalize_currency_code,
    normalize_subunit,
    pairs_for,
    require_single_currency,
)


def _rates() -> FxRates:
    index = pd.bdate_range("2020-01-01", periods=5)
    frame = pd.DataFrame(
        {"EURUSD": [1.10, 1.11, 1.12, 1.13, 1.14], "EURGBP": [0.85, 0.86, 0.85, 0.84, 0.83]},
        index=index,
    )
    return FxRates(frame, "EUR", source="test")


def test_pairs_are_typed_and_directional() -> None:
    pair = CurrencyPair("EUR", "USD")
    assert pair.code == "EURUSD" and pair.inverse() == CurrencyPair("USD", "EUR")
    assert CurrencyPair.parse("eur/usd") == pair and CurrencyPair.parse("EUR-USD") == pair
    with pytest.raises(ValueError):
        CurrencyPair("eur", "USD")
    with pytest.raises(UsageError):
        CurrencyPair.parse("EURUS")
    rates = _rates()
    assert rates.rate(pair, date(2020, 1, 1)) == 1.10  # one euro buys 1.10 dollars
    assert convert(100.0, "EUR", "USD", on=date(2020, 1, 1), rates=rates) == pytest.approx(110.0)
    assert convert(110.0, "USD", "EUR", on=date(2020, 1, 1), rates=rates) == pytest.approx(100.0)
    assert convert(5.0, "USD", "usd", on=date(2020, 1, 1), rates=rates) == 5.0


def test_round_trip_conversion_is_exact() -> None:
    rates = _rates()
    out = convert(1234.5678, "USD", "GBP", on=date(2020, 1, 2), rates=rates)
    back = convert(out, "GBP", "USD", on=date(2020, 1, 2), rates=rates)
    assert back == pytest.approx(1234.5678, rel=1e-12)


@settings(max_examples=50, deadline=None)
@given(amount=st.floats(min_value=1e-3, max_value=1e9, allow_nan=False, allow_infinity=False))
def test_round_trip_property_over_generated_amounts(amount: float) -> None:
    rates = _rates()
    out = convert(amount, "USD", "GBP", on=date(2020, 1, 3), rates=rates)
    assert convert(out, "GBP", "USD", on=date(2020, 1, 3), rates=rates) == pytest.approx(
        amount, rel=1e-9
    )


def test_cross_rate_consistent_with_its_two_legs() -> None:
    rates = _rates()
    on = date(2020, 1, 2)
    usd_per_eur = rates.rate(CurrencyPair("EUR", "USD"), on)
    gbp_per_eur = rates.rate(CurrencyPair("EUR", "GBP"), on)
    usd_per_gbp = rates.rate(CurrencyPair("GBP", "USD"), on)
    assert usd_per_gbp == pytest.approx(usd_per_eur / gbp_per_eur, rel=1e-12)
    assert rates.rate(CurrencyPair("USD", "USD"), on) == 1.0
    assert rates.rate(CurrencyPair("EUR", "EUR"), on) == 1.0
    # A quote stored in the inverse direction is still usable.
    inverse = FxRates(
        pd.DataFrame({"USDEUR": [0.5]}, index=pd.DatetimeIndex([pd.Timestamp("2020-01-01")])), "EUR"
    )
    assert inverse.rate(CurrencyPair("EUR", "USD"), date(2020, 1, 1)) == pytest.approx(2.0)
    with pytest.raises(UsageError, match="no rate for"):
        rates.rate(CurrencyPair("EUR", "JPY"), on)


def test_carry_forward_recorded_not_silent() -> None:
    rates = _rates()
    saturday = date(2020, 1, 4)
    assert rates.rate(CurrencyPair("EUR", "USD"), saturday) == 1.12
    assert rates.carry_forwards == [{"pair": "EURUSD", "date": "2020-01-04", "from": "2020-01-03"}]
    with pytest.raises(UsageError, match="on or before"):
        rates.rate(CurrencyPair("EUR", "USD"), date(2019, 12, 1))


def test_pence_quoted_listing_normalized_to_major_unit() -> None:
    series = pd.Series([22000.0, 22500.0])
    out, code = normalize_subunit(series, "GBp", symbol="VOD.L")
    assert code == "GBP" and list(out) == [220.0, 225.0]
    same, code = normalize_subunit(series, "USD", symbol="AAPL")
    assert code == "USD" and same is series
    assert normalize_currency_code("ZAc", symbol="X") == ("ZAR", 100)
    assert normalize_currency_code("ILA", symbol="X") == ("ILS", 100)
    assert normalize_currency_code(" usd ", symbol="X") == ("USD", 1)


def test_unknown_currency_is_never_guessed() -> None:
    with pytest.raises(ProviderError, match="no currency metadata"):
        normalize_currency_code(None, symbol="XYZ")
    with pytest.raises(ProviderError, match="no currency metadata"):
        normalize_currency_code("  ", symbol="XYZ")
    with pytest.raises(ProviderError, match="unrecognized"):
        normalize_currency_code("DOLLARS", symbol="XYZ")


def test_mixed_currency_without_target_raises_usage_error() -> None:
    with pytest.raises(UsageError) as exc:
        require_single_currency(["USD", "GBP", "USD"])
    assert exc.value.exit_code == 2 and "GBP" in str(exc.value) and "USD" in str(exc.value)
    assert require_single_currency(["USD", "GBP"], target="eur") == "EUR"
    assert require_single_currency(["USD", "USD"]) == "USD"
    with pytest.raises(UsageError):
        require_single_currency([])


def test_converting_a_price_series_updates_attrs() -> None:
    rates = _rates()
    prices = pd.Series([100.0, 100.0], index=pd.DatetimeIndex(["2020-01-01", "2020-01-04"]))
    prices.attrs["currency"] = "EUR"
    out = convert_series(prices, "EUR", "USD", rates=rates)
    assert list(out) == pytest.approx([110.0, 112.0])
    assert out.attrs["currency"] == "USD" and out.attrs["converted_from"] == "EUR"
    assert out.attrs["carry_forward"] == ["2020-01-04"]
    unchanged = convert_series(prices, "EUR", "EUR", rates=rates)
    assert unchanged.attrs["currency"] == "EUR" and list(unchanged) == [100.0, 100.0]
    early = pd.Series([1.0], index=pd.DatetimeIndex(["2019-01-01"]))
    with pytest.raises(UsageError):
        convert_series(early, "EUR", "USD", rates=rates)


def test_return_identity_matches_converting_prices_then_differencing() -> None:
    rates = _rates()
    index = pd.bdate_range("2020-01-01", periods=5)
    local = pd.Series([100.0, 101.0, 99.5, 102.0, 103.0], index=index)
    converted = convert_series(local, "EUR", "USD", rates=rates)
    via_prices = converted.pct_change().dropna()
    r_local = local.pct_change().dropna()
    r_fx = fx_returns(rates, CurrencyPair("EUR", "USD"), pd.DatetimeIndex(index)).dropna()
    via_identity = convert_returns(r_local, r_fx)
    pd.testing.assert_series_equal(via_prices, via_identity, check_names=False, rtol=1e-12)
    # The additive approximation is *not* equal: the cross term is real.
    assert not np.allclose(via_prices.to_numpy(), (r_local + r_fx).to_numpy())


@settings(max_examples=50, deadline=None)
@given(
    r_local=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False),
    r_fx=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False),
)
def test_convert_returns_algebra(r_local: float, r_fx: float) -> None:
    out = convert_returns(r_local, r_fx)
    assert out == pytest.approx((1 + r_local) * (1 + r_fx) - 1)
    assert convert_returns(r_local, 0.0) == pytest.approx(r_local)


def test_convert_frame_single_currency_touches_no_rate() -> None:
    frame = pd.DataFrame({"A": [1.0], "B": [2.0]}, index=pd.DatetimeIndex(["2020-01-01"]))
    frame.attrs["currency"] = "USD"
    out = convert_frame(frame, "usd", rates=None)  # no rates supplied and none needed
    pd.testing.assert_frame_equal(out, frame)
    assert out.attrs["currency"] == "USD"
    assert frame_currencies(frame) == {"A": "USD", "B": "USD"}
    assert frame_currencies(pd.DataFrame()) == {}


def test_convert_frame_mixed_needs_rates_and_records_them() -> None:
    rates = _rates()
    index = pd.DatetimeIndex(["2020-01-01", "2020-01-02"])
    frame = pd.DataFrame({"E": [100.0, 100.0], "G": [100.0, 100.0]}, index=index)
    frame.attrs["currency"] = {"E": "EUR", "G": "GBP"}
    with pytest.raises(UsageError):
        convert_frame(frame, "USD", rates=None)
    out = convert_frame(frame, "USD", rates=rates)
    assert out["E"].iloc[0] == pytest.approx(110.0)
    assert out["G"].iloc[0] == pytest.approx(100.0 * 1.10 / 0.85)
    assert out.attrs["currency"] == "USD"
    assert out.attrs["converted_from"] == {"E": "EUR", "G": "GBP"}
    assert out.attrs["rate_source"] == "test" and out.attrs["carry_forward"] == {}
    frame.attrs["currency"] = {"E": "EUR"}
    with pytest.raises(ProviderError, match="no currency declared"):
        convert_frame(frame, "USD", rates=rates)


def test_pairs_for_targets() -> None:
    assert pairs_for(["USD", "GBP", "usd", "EUR"], "EUR") == [
        CurrencyPair("GBP", "EUR"),
        CurrencyPair("USD", "EUR"),
    ]
