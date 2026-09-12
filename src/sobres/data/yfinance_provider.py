"""``YFinanceProvider``: keyless daily prices from Yahoo Finance via ``yfinance``.

The vendor library is confined to ``LiveYahooSource``; the provider itself
works against the small ``YahooSource`` boundary so tests run on recorded
payloads. Adjusted close is the default and the recommendation: total-return
math on unadjusted closes reads a 2-for-1 split as a -50% day.

Currency is discovered from the vendor's own metadata, never inferred from an
exchange suffix, and sub-unit quotations (GBp, ZAc, ILA) are normalized to the
major unit in this layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

import pandas as pd

from sobres.core.errors import ProviderError, UnknownTickerError
from sobres.data.base import (
    DEFAULT_IMPLAUSIBLE_MOVE,
    PriceField,
    canonical_frame,
    check_adjustment_consistency,
    validate_price_frame,
)
from sobres.data.cache import ObservationCache
from sobres.data.currency import normalize_currency_code
from sobres.observability import get_logger, span

PROVIDER_NAME = "yfinance"

FIELD_COLUMNS: dict[str, str] = {
    "adj_close": "Adj Close",
    "close": "Close",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "volume": "Volume",
}


@dataclass
class RawHistory:
    """What the vendor returns for one ticker: an OHLCV frame plus metadata."""

    frame: pd.DataFrame
    currency: str | None
    meta: dict[str, Any] = field(default_factory=dict)


class YahooSource(Protocol):
    def history(self, ticker: str, start: date, end: date) -> RawHistory: ...


class LiveYahooSource:
    """The network boundary. Only this class imports ``yfinance``."""

    def history(self, ticker: str, start: date, end: date) -> RawHistory:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - the [data] extra installs it
            raise ProviderError(
                "yfinance is not installed",
                provider=PROVIDER_NAME,
                hint="run: pip install 'sobres[data]'",
            ) from exc
        try:
            t = yf.Ticker(ticker)
            # yfinance's end is exclusive; the request is inclusive.
            frame = t.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=False,
                raise_errors=True,
            )
            meta = dict(t.get_history_metadata() or {})
        except Exception as exc:
            raise ProviderError(
                f"{type(exc).__name__}: {exc}",
                provider=PROVIDER_NAME,
                hint="check the symbol and your network, or retry with --refresh later",
            ) from exc
        currency = meta.get("currency")
        return RawHistory(frame=frame, currency=currency, meta=meta)


class YFinanceProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        source: YahooSource | None = None,
        cache: ObservationCache | None = None,
        *,
        implausible_move: float = DEFAULT_IMPLAUSIBLE_MOVE,
        refresh: bool = False,
    ) -> None:
        self._source: YahooSource = source if source is not None else LiveYahooSource()
        self._cache = cache
        self._implausible_move = implausible_move
        self._refresh = refresh
        self._log = get_logger("sobres.data.yfinance")

    def get_prices(
        self,
        tickers: Sequence[str],
        start: date,
        end: date | None = None,
        field: PriceField = "adj_close",
    ) -> pd.DataFrame:
        if field not in FIELD_COLUMNS:
            raise ValueError(f"unknown price field {field!r}")
        symbols = [t.upper() for t in tickers]
        last = end or date.today()
        dataset = f"prices_{field}"
        with span("provider.get_prices", {"provider": self.name, "symbols": len(symbols)}):
            if self._cache is None:
                frame = self._fetch(symbols, start, last, field)
                meta = dict(frame.attrs.get("series_meta", {}))
            else:
                frame = self._cache.get(
                    self.name,
                    dataset,
                    symbols,
                    start,
                    last,
                    lambda syms, s, e: self._fetch(syms, s, e, field),
                    refresh=self._refresh,
                )
                meta = dict(frame.attrs.get("series_meta", {}))
        frame.attrs["field"] = field
        frame.attrs["provider"] = self.name
        frame.attrs["return_kind"] = "total return" if field == "adj_close" else "price return"
        currencies = {s: str(meta.get(s, {}).get("currency", "")) for s in symbols}
        missing = [s for s, c in currencies.items() if not c]
        if missing:
            raise ProviderError(
                f"no currency metadata for {', '.join(missing)}",
                provider=self.name,
                hint="the tool will not guess a currency; try --refresh",
            )
        unique = set(currencies.values())
        frame.attrs["currency"] = next(iter(unique)) if len(unique) == 1 else currencies
        flags: list[dict[str, str]] = []
        for s in symbols:
            for flag in meta.get(s, {}).get("flags", []):
                if flag not in flags:
                    flags.append(flag)
        frame.attrs["flags"] = flags
        return frame

    def _fetch(self, symbols: Sequence[str], start: date, end: date, field: str) -> pd.DataFrame:
        columns: dict[str, pd.Series] = {}
        series_meta: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            raw = self._source.history(symbol, start, end)
            if raw.frame is None or raw.frame.empty:
                raise UnknownTickerError(symbol, provider=self.name)
            column = FIELD_COLUMNS[field]
            if column not in raw.frame.columns:
                raise ProviderError(
                    f"payload for {symbol} has no {column!r} column "
                    f"(got {list(raw.frame.columns)})",
                    provider=self.name,
                    hint="the vendor's shape changed; re-record the fixture and update the parser",
                )
            values = raw.frame[column].astype("float64")
            major, divisor = normalize_currency_code(raw.currency, symbol=symbol)
            if divisor != 1 and field != "volume":
                values = values / divisor
            values.index = pd.DatetimeIndex(values.index)
            if values.index.tz is not None:
                values.index = values.index.tz_localize(None)
            values.index = values.index.normalize()
            values = values[~values.index.duplicated(keep="last")].sort_index()
            columns[symbol] = values
            last_quote = values.dropna().index.max()
            info: dict[str, Any] = {
                "currency": major,
                "quoted_currency": str(raw.currency),
                "last_quote": None if pd.isna(last_quote) else str(last_quote.date()),
            }
            if end - last_quote.date() > timedelta(days=14):
                info["delisted"] = True
                info["reason"] = str(raw.meta.get("reason") or "no quotes after last_quote")
            if {"Adj Close", "Close"} <= set(raw.frame.columns):
                adj = raw.frame["Adj Close"].astype("float64")
                cls = raw.frame["Close"].astype("float64")
                adj.index = values.index[: len(adj)] if len(adj) == len(values) else adj.index
                cls.index = adj.index
                info["flags"] = check_adjustment_consistency(adj, cls, symbol)
            series_meta[symbol] = info
        frame = canonical_frame(pd.DataFrame(columns), symbols)
        frame.attrs["provider"] = self.name
        frame = validate_price_frame(
            frame,
            implausible_move=self._implausible_move,
            allow_nonpositive=(field == "volume"),
        )
        for flag in frame.attrs.get("flags", []):
            self._log.warning("data.quality", **flag)
            series_meta.setdefault(flag["symbol"], {}).setdefault("flags", []).append(flag)
        frame.attrs["series_meta"] = series_meta
        return frame
