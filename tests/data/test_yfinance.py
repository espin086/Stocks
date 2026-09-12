"""``YFinanceProvider`` against recorded payloads.

Scenarios: Adjusted close is the default; Provider outage; A requested ticker
does not exist; Partial history; Delisted and renamed tickers; Sub-unit
quotations; Price frames carry currency; Currency is discovered, not assumed;
Recorded payloads; Call sites are vendor-agnostic; Adjusted close is total return.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from sobres.core.errors import ProviderError, UnknownTickerError
from sobres.data.fixtures import FixtureYahooSource
from sobres.data.yfinance_provider import LiveYahooSource, RawHistory, YFinanceProvider
from tests.data.contracts import contract_test_price_provider

PROVIDERS = {"yfinance": lambda src: YFinanceProvider(source=src)}


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_price_provider_contract(name: str, yahoo_source: FixtureYahooSource) -> None:
    contract_test_price_provider(PROVIDERS[name](yahoo_source))


def test_adjusted_close_is_the_default(yahoo_source: FixtureYahooSource) -> None:
    provider = YFinanceProvider(source=yahoo_source)
    adj = provider.get_prices(["AAPL"], date(2020, 8, 1), date(2020, 9, 30))
    close = provider.get_prices(["AAPL"], date(2020, 8, 1), date(2020, 9, 30), field="close")
    assert adj.attrs["field"] == "adj_close" and close.attrs["field"] == "close"
    assert close.attrs["return_kind"] == "price return"
    # The fixture carries a 4:1 split on 2020-08-31: the raw close halves twice,
    # the adjusted series does not.
    raw_move = close["AAPL"].pct_change().loc["2020-08-31"]
    adj_move = adj["AAPL"].pct_change().loc["2020-08-31"]
    assert raw_move < -0.5 and abs(adj_move) < 0.2
    assert [f["rule"] for f in close.attrs["flags"]] == ["implausible-move"]


def test_unknown_ticker_raises_naming_symbol(yahoo_source: FixtureYahooSource) -> None:
    provider = YFinanceProvider(source=yahoo_source)
    with pytest.raises(UnknownTickerError) as exc:
        provider.get_prices(["AAPL", "NOPE"], date(2020, 1, 1), date(2020, 1, 31))
    assert exc.value.symbol == "NOPE" and exc.value.exit_code == 4


def test_partial_history_keeps_nan_rows(yahoo_source: FixtureYahooSource) -> None:
    provider = YFinanceProvider(source=yahoo_source)
    frame = provider.get_prices(["AAPL"], date(2014, 12, 1), date(2015, 1, 31))
    # Fixture history starts 2015-01-02; no row is invented before it, and the
    # frame keeps what the provider returned rather than dropping the ticker.
    assert frame.index.min() == pd.Timestamp("2015-01-02")
    frame2 = provider.get_prices(["AAPL"], date(2015, 1, 1), date(2015, 1, 31), field="volume")
    assert frame2.attrs["field"] == "volume"


def test_pence_quoted_listing_normalized(yahoo_source: FixtureYahooSource) -> None:
    provider = YFinanceProvider(source=yahoo_source)
    frame = provider.get_prices(["VOD.L", "AAPL"], date(2020, 1, 1), date(2020, 1, 31))
    assert frame.attrs["currency"] == {"VOD.L": "GBP", "AAPL": "USD"}
    raw = yahoo_source.history("VOD.L", date(2020, 1, 1), date(2020, 1, 31))
    assert raw.currency == "GBp"
    assert frame["VOD.L"].iloc[0] == pytest.approx(raw.frame["Adj Close"].iloc[0] / 100)
    assert frame.attrs["series_meta"]["VOD.L"]["quoted_currency"] == "GBp"


class _Source:
    def __init__(self, raw: RawHistory | Exception) -> None:
        self.raw = raw

    def history(self, ticker: str, start: date, end: date) -> RawHistory:
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def _raw(currency: str | None, **meta: Any) -> RawHistory:
    index = pd.bdate_range("2020-01-01", periods=3, tz="America/New_York")
    frame = pd.DataFrame(
        {
            "Open": [1.0, 1.0, 1.0],
            "Close": [1.0, 1.1, 1.2],
            "Adj Close": [0.9, 1.0, 1.2],
            "Volume": [1, 1, 1],
        },
        index=index,
    )
    return RawHistory(frame=frame, currency=currency, meta=meta)


def test_missing_currency_metadata_is_a_provider_error() -> None:
    provider = YFinanceProvider(source=_Source(_raw(None)))
    with pytest.raises(ProviderError, match="no currency metadata for X"):
        provider.get_prices(["X"], date(2020, 1, 1), date(2020, 1, 10))


def test_upstream_exception_becomes_provider_error() -> None:
    provider = YFinanceProvider(source=_Source(ProviderError("rate limited", provider="yfinance")))
    with pytest.raises(ProviderError) as exc:
        provider.get_prices(["X"], date(2020, 1, 1), date(2020, 1, 10))
    assert exc.value.exit_code == 4 and "rate limited" in str(exc.value)


def test_missing_column_is_a_shape_error() -> None:
    raw = _raw("USD")
    raw.frame = raw.frame.drop(columns=["Adj Close"])
    provider = YFinanceProvider(source=_Source(raw))
    with pytest.raises(ProviderError, match="no 'Adj Close' column"):
        provider.get_prices(["X"], date(2020, 1, 1), date(2020, 1, 10))


def test_delisted_ticker_records_last_quote_and_reason() -> None:
    provider = YFinanceProvider(source=_Source(_raw("USD", reason="delisted 2020")))
    frame = provider.get_prices(["OLD"], date(2020, 1, 1), date(2020, 6, 30))
    meta = frame.attrs["series_meta"]["OLD"]
    assert meta["last_quote"] == "2020-01-03" and meta["delisted"] is True
    assert meta["reason"] == "delisted 2020"
    assert frame.index.tz is None


def test_tz_aware_vendor_index_is_normalized() -> None:
    provider = YFinanceProvider(source=_Source(_raw("USD")))
    frame = provider.get_prices(["X"], date(2020, 1, 1), date(2020, 1, 3))
    assert frame.index.tz is None and len(frame) == 3


def test_invalid_field_rejected() -> None:
    provider = YFinanceProvider(source=_Source(_raw("USD")))
    with pytest.raises(ValueError):
        provider.get_prices(["X"], date(2020, 1, 1), field="typo")  # type: ignore[arg-type]


def test_live_source_wraps_vendor_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import yfinance

    class _Boom:
        def __init__(self, ticker: str) -> None:
            pass

        def history(self, **kwargs: Any) -> pd.DataFrame:
            raise RuntimeError("no network in tests")

    monkeypatch.setattr(yfinance, "Ticker", _Boom)
    with pytest.raises(ProviderError) as exc:
        LiveYahooSource().history("AAPL", date(2020, 1, 1), date(2020, 1, 2))
    assert "RuntimeError" in str(exc.value) and exc.value.provider == "yfinance"


def test_live_source_reads_currency_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import yfinance

    calls: dict[str, Any] = {}

    class _Ticker:
        def __init__(self, ticker: str) -> None:
            calls["ticker"] = ticker

        def history(self, **kwargs: Any) -> pd.DataFrame:
            calls.update(kwargs)
            return _raw("USD").frame

        def get_history_metadata(self) -> dict[str, Any]:
            return {"currency": "GBp"}

    monkeypatch.setattr(yfinance, "Ticker", _Ticker)
    raw = LiveYahooSource().history("VOD.L", date(2020, 1, 1), date(2020, 1, 2))
    assert raw.currency == "GBp" and calls["auto_adjust"] is False
    assert calls["end"] == "2020-01-03"  # inclusive request → exclusive vendor end
