"""The currency model: typed pairs, one conversion function, sub-unit normalization.

Direction is carried by a type. ``CurrencyPair(base, quote)`` means **units of
``quote`` per one unit of ``base``**: ``CurrencyPair("EUR", "USD")`` at 1.08 is
one euro buying 1.08 dollars. Call sites never touch a raw rate — they call
``convert`` — so inversion cannot be got wrong where it would be silent.

Converting returns uses the exact identity ``(1 + r_local)(1 + r_fx) - 1``
(``convert_returns``), never the additive approximation.

This module is the only place in the codebase that multiplies or divides by an
exchange rate; ``tests/architecture/`` enforces it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from sobres.core.errors import ProviderError, UsageError

_CODE = re.compile(r"^[A-Z]{3}$")

SUB_UNITS: dict[str, tuple[str, int]] = {
    # provider code → (major unit, divisor). Pence, cents and agorot.
    "GBp": ("GBP", 100),
    "GBX": ("GBP", 100),
    "ZAc": ("ZAR", 100),
    "ZAC": ("ZAR", 100),
    "ILA": ("ILS", 100),
    "USX": ("USD", 100),
}


def normalize_currency_code(code: str | None, *, symbol: str) -> tuple[str, int]:
    """Map a provider's currency code to ``(ISO major unit, divisor)``.

    A sub-unit quotation (GBp, ZAc, ILA) returns its major unit and 100;
    a missing code raises ``ProviderError`` naming the symbol — never a guess.
    """
    if code is None or not str(code).strip():
        raise ProviderError(
            f"no currency metadata for {symbol}",
            hint="the tool will not guess a currency; try --refresh or another symbol",
        )
    text = str(code).strip()
    if text in SUB_UNITS:
        return SUB_UNITS[text]
    upper = text.upper()
    if not _CODE.match(upper):
        raise ProviderError(f"unrecognized currency code {text!r} for {symbol}")
    return upper, 1


def normalize_subunit(series: pd.Series, code: str, *, symbol: str) -> tuple[pd.Series, str]:
    """Divide a sub-unit quoted series into its major unit; a no-op otherwise."""
    major, divisor = normalize_currency_code(code, symbol=symbol)
    if divisor == 1:
        return series, major
    return series / divisor, major


@dataclass(frozen=True, order=True)
class CurrencyPair:
    """Units of ``quote`` per one unit of ``base``."""

    base: str
    quote: str

    def __post_init__(self) -> None:
        for code in (self.base, self.quote):
            if not _CODE.match(code):
                raise ValueError(f"currency code must be three uppercase letters, got {code!r}")

    @property
    def code(self) -> str:
        return f"{self.base}{self.quote}"

    def inverse(self) -> CurrencyPair:
        return CurrencyPair(self.quote, self.base)

    @classmethod
    def parse(cls, text: str) -> CurrencyPair:
        cleaned = text.upper().replace("/", "").replace("-", "").replace("_", "")
        if len(cleaned) != 6:
            raise UsageError(f"currency pair {text!r} is not of the form EURUSD or EUR/USD")
        return cls(cleaned[:3], cleaned[3:])


def frame_currencies(frame: pd.DataFrame) -> dict[str, str]:
    """Per-column currency from ``attrs`` (a single code or a column mapping)."""
    attr = frame.attrs.get("currency")
    if isinstance(attr, dict):
        return {str(k): str(v) for k, v in attr.items()}
    if attr is None:
        return {}
    return {str(c): str(attr) for c in frame.columns}


def require_single_currency(currencies: Iterable[str], *, target: str | None = None) -> str:
    """The one currency every input shares, or the target; mixed + no target → exit 2."""
    found = sorted({c for c in currencies if c})
    if target is not None:
        return target.upper()
    if len(found) > 1:
        raise UsageError(
            f"inputs are denominated in more than one currency: {', '.join(found)}",
            hint="pass --base <CCY> to convert everything before computing",
        )
    if not found:
        raise UsageError("no currency is declared on the inputs")
    return found[0]


class FxRates:
    """A table of rates quoted by one provider against its base currency.

    ``frame`` is date-indexed with one column per pair code the provider
    quotes (``EURUSD`` for an ECB table). Pairs the provider does not quote
    are derived through the base: ``A→B = base→B / base→A``. A date the market
    did not quote uses the most recent prior quote and is recorded.
    """

    def __init__(self, frame: pd.DataFrame, base: str, source: str = "fx") -> None:
        self.frame = frame
        self.base = base.upper()
        self.source = source
        self.carry_forwards: list[dict[str, str]] = []

    def _column(self, quote: str) -> pd.Series:
        pair = CurrencyPair(self.base, quote)
        if quote == self.base:
            return pd.Series(1.0, index=self.frame.index)
        if pair.code in self.frame.columns:
            return self.frame[pair.code]
        if pair.inverse().code in self.frame.columns:
            return 1.0 / self.frame[pair.inverse().code]
        raise UsageError(
            f"no rate for {pair.base}/{pair.quote} from the FX provider",
            hint="fetch it first with: sobres data fx " + pair.code,
        )

    def series(self, pair: CurrencyPair) -> pd.Series:
        """Rate series for any pair, triangulated through the base if needed."""
        if pair.base == pair.quote:
            return pd.Series(1.0, index=self.frame.index, name=pair.code)
        rates = self._column(pair.quote) / self._column(pair.base)
        return rates.rename(pair.code)

    def rate(self, pair: CurrencyPair, on: date) -> float:
        """The rate on ``on``, carrying the last prior quote forward if needed."""
        series = self.series(pair).dropna()
        stamp = pd.Timestamp(on)
        if stamp in series.index:
            return float(series.loc[stamp])
        prior = series.loc[:stamp]
        if prior.empty:
            raise UsageError(
                f"no {pair.code} rate on or before {on}",
                hint="widen the FX window with --start",
            )
        self.carry_forwards.append(
            {"pair": pair.code, "date": on.isoformat(), "from": str(prior.index[-1].date())}
        )
        return float(prior.iloc[-1])


def convert(amount: float, from_ccy: str, to_ccy: str, *, on: date, rates: FxRates) -> float:
    """Convert ``amount`` from one currency to another on a date. The only way to."""
    if from_ccy.upper() == to_ccy.upper():
        return float(amount)
    return float(amount) * rates.rate(CurrencyPair(from_ccy.upper(), to_ccy.upper()), on)


def convert_series(prices: pd.Series, from_ccy: str, to_ccy: str, *, rates: FxRates) -> pd.Series:
    """Convert a date-indexed price series, one rate per observation date.

    Dates the FX market did not quote use the carry-forward rule; each is
    recorded on the returned series' ``attrs["carry_forward"]``.
    """
    if from_ccy.upper() == to_ccy.upper():
        out = prices.copy()
        out.attrs = dict(prices.attrs)
        out.attrs["currency"] = to_ccy.upper()
        return out
    pair = CurrencyPair(from_ccy.upper(), to_ccy.upper())
    quoted = rates.series(pair).dropna()
    aligned = quoted.reindex(quoted.index.union(prices.index)).ffill().reindex(prices.index)
    carried = [d for d in prices.index if d not in quoted.index]
    if aligned.isna().any():
        first = prices.index[aligned.isna()][0]
        raise UsageError(
            f"no {pair.code} rate on or before {pd.Timestamp(first).date()}",
            hint="widen the FX window with --start",
        )
    out = prices * aligned
    out.attrs = dict(prices.attrs)
    out.attrs["currency"] = to_ccy.upper()
    out.attrs["converted_from"] = from_ccy.upper()
    out.attrs["carry_forward"] = [str(pd.Timestamp(d).date()) for d in carried]
    return out


def convert_frame(frame: pd.DataFrame, to_ccy: str, *, rates: FxRates | None) -> pd.DataFrame:
    """Convert every column to ``to_ccy`` using the per-column currency in ``attrs``.

    A single-currency frame already in ``to_ccy`` is returned unchanged with no
    rate touched, so the common case costs nothing.
    """
    currencies = frame_currencies(frame)
    target = to_ccy.upper()
    if all(c == target for c in currencies.values()):
        out = frame.copy()
        out.attrs = dict(frame.attrs)
        out.attrs["currency"] = target
        return out
    if rates is None:
        raise UsageError(
            f"inputs are not all in {target} and no exchange rates were supplied",
            hint="the caller must fetch rates through the FX provider first",
        )
    out = frame.copy()
    out.attrs = dict(frame.attrs)
    carried: dict[str, list[str]] = {}
    for column in frame.columns:
        from_ccy = currencies.get(str(column))
        if from_ccy is None:
            raise ProviderError(f"no currency declared for {column}")
        converted = convert_series(frame[column], from_ccy, target, rates=rates)
        out[column] = converted
        if converted.attrs.get("carry_forward"):
            carried[str(column)] = list(converted.attrs["carry_forward"])
    out.attrs["currency"] = target
    out.attrs["converted_from"] = currencies
    out.attrs["rate_source"] = rates.source
    out.attrs["carry_forward"] = carried
    return out


def convert_returns(r_local: Any, r_fx: Any) -> Any:
    """``(1 + r_local) * (1 + r_fx) - 1`` — exact, never ``r_local + r_fx``.

    Works on floats, arrays, Series and frames alike. Source: the standard
    decomposition of a foreign asset's return in the investor's currency,
    e.g. Solnik & McLeavey, *Global Investments*, ch. 2.
    """
    return (1.0 + r_local) * (1.0 + r_fx) - 1.0


def fx_returns(rates: FxRates, pair: CurrencyPair, index: pd.DatetimeIndex) -> pd.Series:
    """Period returns of the rate series aligned to ``index`` (carry-forward)."""
    quoted = rates.series(pair).dropna()
    aligned = quoted.reindex(quoted.index.union(index)).ffill().reindex(index)
    out = aligned.pct_change()
    out.name = pair.code
    return out


def pairs_for(currencies: Sequence[str], target: str) -> list[CurrencyPair]:
    """The distinct pairs needed to convert ``currencies`` into ``target``."""
    return sorted(
        {CurrencyPair(c.upper(), target.upper()) for c in currencies if c.upper() != target.upper()}
    )


def as_float_array(values: Any) -> Any:
    return np.asarray(values, dtype="float64")
