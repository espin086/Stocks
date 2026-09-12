"""``EcbProvider``: keyless daily euro reference rates from the ECB.

The ECB publishes one row per business day per currency as SDMX CSV
(``KEY,FREQ,CURRENCY,CURRENCY_DENOM,...,TIME_PERIOD,OBS_VALUE``), quoting units
of the currency per one euro — ``CurrencyPair("EUR", "USD")`` in this
codebase's terms. Only ``LiveEcbSource`` talks HTTP. Cross rates are
triangulated through the euro by ``FxRates``; non-trading days are resolved by
the carry-forward rule at conversion time and recorded.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

import httpx
import pandas as pd

from sobres.core.errors import ProviderError
from sobres.data.base import canonical_frame
from sobres.data.cache import ObservationCache
from sobres.data.currency import CurrencyPair, FxRates
from sobres.observability import get_logger, span

PROVIDER_NAME = "ecb"
BASE_CURRENCY = "EUR"
BASE_URL = "https://data-api.ecb.europa.eu/service/data/EXR"
TIMEOUT_S = 10.0


class EcbSource(Protocol):
    def csv(self, currency: str, start: date, end: date) -> str: ...


class LiveEcbSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def csv(self, currency: str, start: date, end: date) -> str:
        url = f"{BASE_URL}/D.{currency}.{BASE_CURRENCY}.SP00.A"
        params = {
            "format": "csvdata",
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
        }
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"request failed: {type(exc).__name__}",
                provider=PROVIDER_NAME,
                hint="check your network and retry",
            ) from exc
        if response.status_code == 404:
            raise ProviderError(
                f"the ECB publishes no reference rate for {currency}",
                provider=PROVIDER_NAME,
                hint="use a currency the ECB quotes against the euro, or FRED DEX* series",
            )
        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code} for {currency}",
                provider=PROVIDER_NAME,
                hint="retry later",
            )
        return response.text


def parse_sdmx_csv(currency: str, text: str) -> pd.Series:
    """Parse the ECB CSV into a date-indexed series of ``currency`` per euro."""
    if not text.strip():
        return pd.Series(dtype="float64", name=f"{BASE_CURRENCY}{currency}")
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    if "TIME_PERIOD" not in fields or "OBS_VALUE" not in fields:
        raise ProviderError(
            f"CSV for {currency} lacks TIME_PERIOD/OBS_VALUE columns (got {fields})",
            provider=PROVIDER_NAME,
            hint="the ECB feed shape changed; re-record the fixture and update the parser",
        )
    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for row in reader:
        raw = row.get("OBS_VALUE", "")
        if raw in ("", None):
            continue
        dates.append(pd.Timestamp(row["TIME_PERIOD"]))
        values.append(float(raw))
    return pd.Series(
        values, index=pd.DatetimeIndex(dates), name=f"{BASE_CURRENCY}{currency}", dtype="float64"
    )


class EcbProvider:
    name = PROVIDER_NAME
    base_currency = BASE_CURRENCY

    def __init__(
        self,
        source: EcbSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        self._source: EcbSource = source if source is not None else LiveEcbSource()
        self._cache = cache
        self._refresh = refresh
        self._log = get_logger("sobres.data.ecb")

    def get_rates(self, pairs: Sequence[Any], start: date, end: date | None = None) -> pd.DataFrame:
        """One column per requested pair, triangulated through the euro."""
        wanted = [p if isinstance(p, CurrencyPair) else CurrencyPair.parse(str(p)) for p in pairs]
        last = end or date.today()
        currencies = sorted({c for p in wanted for c in (p.base, p.quote) if c != BASE_CURRENCY})
        with span("provider.get_rates", {"provider": self.name, "pairs": len(wanted)}):
            if not currencies:
                quoted = pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
            elif self._cache is None:
                quoted = self._fetch(currencies, start, last)
            else:
                quoted = self._cache.get(
                    self.name, "fx", currencies, start, last, self._fetch, refresh=self._refresh
                )
        quoted.columns = [f"{BASE_CURRENCY}{c}" for c in quoted.columns]
        table = FxRates(quoted, BASE_CURRENCY)
        out = pd.DataFrame({p.code: table.series(p) for p in wanted}, index=quoted.index)
        out.index.name = "date"
        out = out.astype("float64")
        out.attrs.update(dict(quoted.attrs))
        out.attrs.update({"provider": self.name, "base": BASE_CURRENCY, "field": "rate"})
        return out

    def _fetch(self, currencies: Sequence[str], start: date, end: date) -> pd.DataFrame:
        columns = {c: parse_sdmx_csv(c, self._source.csv(c, start, end)) for c in currencies}
        for currency, series in columns.items():
            if series.empty:
                raise ProviderError(
                    f"no {currency} rates between {start} and {end}",
                    provider=self.name,
                    hint="widen the window; the ECB series starts in 1999",
                )
        frame = canonical_frame(pd.DataFrame(columns), list(currencies))
        frame.attrs["provider"] = self.name
        return frame

    def rates_table(
        self, currencies: Sequence[str], start: date, end: date | None = None
    ) -> FxRates:
        """An ``FxRates`` covering every pair between ``currencies`` and the euro."""
        pairs = [
            CurrencyPair(BASE_CURRENCY, c) for c in sorted(set(currencies)) if c != BASE_CURRENCY
        ]
        frame = self.get_rates(pairs, start, end)
        return FxRates(frame, BASE_CURRENCY, source="ECB reference rates")
