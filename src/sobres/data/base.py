"""Provider protocols, the canonical frame, and validation on ingest.

Every disagreement about "what is a price series" is settled once, here:

* index: ``DatetimeIndex`` named ``date``, tz-naive, ascending, no duplicates;
* columns: symbols, uppercase, in the order requested;
* values: ``float64``, ``NaN`` for a genuinely missing observation;
* ``frame.attrs``: ``field``, ``provider``, ``fetched_at``, ``currency`` and
  ``flags`` (data-quality findings a report should show beside its result).

Providers are ``typing.Protocol`` classes: plain classes implement them and
nothing inherits, so a paid adapter later is a drop-in and a test double is a
few lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

import numpy as np
import pandas as pd

from sobres.core.errors import ProviderError

PriceField = Literal["adj_close", "close", "open", "high", "low", "volume"]
PRICE_FIELDS: tuple[str, ...] = ("adj_close", "close", "open", "high", "low", "volume")
FactorModel = Literal["ff3", "ff5", "ff5+mom"]
FACTOR_MODELS: tuple[str, ...] = ("ff3", "ff5", "ff5+mom")
FactorFrequency = Literal["daily", "monthly"]

FACTOR_COLUMNS: dict[str, tuple[str, ...]] = {
    "ff3": ("Mkt-RF", "SMB", "HML", "RF"),
    "ff5": ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"),
    "ff5+mom": ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF"),
}

DEFAULT_IMPLAUSIBLE_MOVE = 0.5


class PriceProvider(Protocol):
    name: str

    def get_prices(
        self,
        tickers: Sequence[str],
        start: date,
        end: date | None = None,
        field: PriceField = "adj_close",
    ) -> pd.DataFrame: ...


class MacroProvider(Protocol):
    name: str

    def get_series(
        self, series_ids: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame: ...


class FactorProvider(Protocol):
    name: str

    def get_factors(
        self,
        model: FactorModel,
        frequency: FactorFrequency,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame: ...


class FxProvider(Protocol):
    name: str
    base_currency: str

    def get_rates(
        self, pairs: Sequence[Any], start: date, end: date | None = None
    ) -> pd.DataFrame: ...

    def rates_table(self, currencies: Sequence[str], start: date, end: date | None = None) -> Any:
        """An ``FxRates`` table covering every pair between ``currencies`` and the base."""
        ...


# --------------------------------------------------------------------------- #
# Canonical frame
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QualityFlag:
    """One data-quality finding, kept in ``attrs["flags"]`` beside the result."""

    symbol: str
    date: str
    rule: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "date": self.date, "rule": self.rule, "detail": self.detail}


def canonical_frame(frame: pd.DataFrame, columns: Sequence[str] | None = None) -> pd.DataFrame:
    """Coerce to the canonical shape: tz-naive ``date`` index, float64, ordered columns."""
    out = frame.copy()
    index = pd.DatetimeIndex(out.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    out.index = index
    out = out.sort_index(kind="stable")  # so "last" below means the latest intraday stamp
    out.index = pd.DatetimeIndex(out.index).normalize()
    out.index.name = "date"
    out = out[~out.index.duplicated(keep="last")]
    if columns is not None:
        out = out.reindex(columns=list(columns))
    out = out.astype("float64")
    out.columns.name = None
    out.attrs = dict(frame.attrs)
    return out


def validate_price_frame(
    frame: pd.DataFrame,
    *,
    implausible_move: float = DEFAULT_IMPLAUSIBLE_MOVE,
    allow_nonpositive: bool = False,
) -> pd.DataFrame:
    """Reject structural defects; keep-and-flag implausible moves.

    Raises ``ProviderError`` naming the symbol, date and rule for a tz-aware or
    duplicated or non-monotonic index, a non-float column, a non-positive
    price, or a non-finite value that is not ``NaN``. A single-day move above
    ``implausible_move`` is kept and recorded in ``attrs["flags"]``.
    """
    provider = str(frame.attrs.get("provider", "provider"))
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ProviderError("index is not a DatetimeIndex (rule: index-type)", provider=provider)
    if frame.index.tz is not None:
        raise ProviderError("index is timezone-aware (rule: tz-naive)", provider=provider)
    if frame.index.has_duplicates:
        dup = frame.index[frame.index.duplicated()][0]
        raise ProviderError(f"duplicated date {dup.date()} (rule: unique-index)", provider=provider)
    if not frame.index.is_monotonic_increasing:
        raise ProviderError("index is not ascending (rule: monotonic-index)", provider=provider)
    flags: list[dict[str, str]] = list(frame.attrs.get("flags", []))
    for symbol in frame.columns:
        series = frame[symbol]
        if series.dtype != np.float64:
            raise ProviderError(
                f"{symbol}: dtype {series.dtype} is not float64 (rule: float64)", provider=provider
            )
        values = series.to_numpy()
        infinite = ~np.isfinite(values) & ~np.isnan(values)
        if infinite.any():
            when = frame.index[infinite][0].date()
            raise ProviderError(
                f"{symbol}: non-finite value on {when} (rule: finite)", provider=provider
            )
        if not allow_nonpositive:
            bad = values <= 0
            if bad.any():
                when = frame.index[bad][0].date()
                raise ProviderError(
                    f"{symbol}: non-positive price {values[bad][0]!r} on {when} "
                    "(rule: positive-price)",
                    provider=provider,
                )
        moves = series.dropna().pct_change().dropna()
        big = moves[moves.abs() > implausible_move]
        for when, move in zip(pd.DatetimeIndex(big.index), big.to_numpy(), strict=True):
            flags.append(
                QualityFlag(
                    symbol=str(symbol),
                    date=str(when.date()),
                    rule="implausible-move",
                    detail=f"single-day return {move:+.1%} exceeds {implausible_move:.0%}",
                ).as_dict()
            )
    frame.attrs["flags"] = flags
    return frame


def check_adjustment_consistency(
    adjusted: pd.Series, unadjusted: pd.Series, symbol: str
) -> list[dict[str, str]]:
    """Flag a non-monotone adjustment factor (``adj_close / close``).

    For a series with only splits and cash dividends the factor is monotone
    non-increasing going back in time — equivalently non-decreasing forward —
    so a decrease going forward indicates a provider data error.
    """
    both = pd.concat([adjusted.rename("a"), unadjusted.rename("u")], axis=1).dropna()
    if both.empty:
        return []
    factor = (both["a"] / both["u"]).to_numpy()
    flags: list[dict[str, str]] = []
    # Tolerate float noise: a decrease of more than one part in a million.
    drops = np.where(np.diff(factor) < -1e-6)[0]
    for i in drops[:5]:
        when = both.index[i + 1]
        flags.append(
            QualityFlag(
                symbol=symbol,
                date=str(pd.Timestamp(when).date()),
                rule="adjustment-factor",
                detail=f"adjustment factor fell from {factor[i]:.6f} to {factor[i + 1]:.6f}",
            ).as_dict()
        )
    return flags
