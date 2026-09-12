"""PPP conversion factors and real effective exchange rates, behind protocols.

``PppProvider`` returns absolute PPP conversion factors (local currency units per
international dollar) per country and year, with the vintage — benchmark year,
reference period, release date — carried on the frame. ``WorldBankPppProvider``
(ICP ``PA.NUS.PPP``, keyless) is the default; ``OecdPppProvider`` is the
alternative. ``BisReerProvider`` returns the BIS published real effective
exchange rate: taken, never constructed. Only the ``Live*Source`` classes talk
HTTP; the parsers run on recorded payloads in the suite.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

import httpx
import pandas as pd

from sobres.core.errors import InsufficientDataError, ProviderError
from sobres.data.base import canonical_frame
from sobres.data.cache import ObservationCache
from sobres.observability import get_logger, span

WORLD_BANK = "worldbank"
OECD = "oecd"
BIS = "bis"
WB_INDICATOR = "PA.NUS.PPP"
WB_URL = (
    "https://api.worldbank.org/v2/country/{country}/indicator/PA.NUS.PPP?format=json&per_page=100"
)
OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE4,1.0/"
    "A.{country}.....PPP_B1GQ.....?format=csvfilewithlabels"
)
BIS_URL = "https://stats.bis.org/api/v1/data/WS_EER/M.R.B.{country}?format=csv"
TIMEOUT_S = 5.0


# --------------------------------------------------------------------------- #
# Protocols and sources
# --------------------------------------------------------------------------- #


class PppSource(Protocol):
    def payload(self, country: str) -> str:
        """The provider's raw document for one country (JSON or CSV text)."""
        ...


class PppProvider(Protocol):
    name: str

    def get_ppp(
        self, countries: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame:
        """Annual PPP factors, one column per country, ``attrs["vintage"]`` per country."""
        ...


class ReerProvider(Protocol):
    name: str

    def get_reer(
        self, countries: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame: ...


class _LiveHttp:
    def __init__(self, url: str, name: str, client: httpx.Client | None = None) -> None:
        self._url = url
        self._name = name
        self._client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True)

    def payload(self, country: str) -> str:
        try:
            response = self._client.get(self._url.format(country=country))
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"request failed: {type(exc).__name__}",
                provider=self._name,
                hint="check your network and retry",
            ) from exc
        if response.status_code == 404:
            raise InsufficientDataError(
                f"{self._name} has no series for {country}",
                hint="check the ISO 3166-1 alpha-3 code",
            )
        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code} for {country}",
                provider=self._name,
                hint="retry later",
            )
        return response.text


class LiveWorldBankSource(_LiveHttp):
    def __init__(self, client: httpx.Client | None = None) -> None:
        super().__init__(WB_URL, WORLD_BANK, client)


class LiveOecdSource(_LiveHttp):
    def __init__(self, client: httpx.Client | None = None) -> None:
        super().__init__(OECD_URL, OECD, client)


class LiveBisSource(_LiveHttp):
    def __init__(self, client: httpx.Client | None = None) -> None:
        super().__init__(BIS_URL, BIS, client)


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def parse_world_bank(country: str, text: str) -> tuple[pd.Series, dict[str, Any]]:
    """``[meta, [ {date, value, ...}, ... ]]``; the latest non-null year is the vintage."""
    import json

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ProviderError("payload is not JSON", provider=WORLD_BANK) from exc
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        if (
            isinstance(payload, list)
            and payload
            and isinstance(payload[0], dict)
            and "message" in payload[0]
        ):
            raise InsufficientDataError(
                f"World Bank returned no {WB_INDICATOR} series for {country}",
                hint="check the ISO 3166-1 alpha-3 code",
            )
        raise ProviderError(
            "unexpected World Bank payload shape",
            provider=WORLD_BANK,
            hint="the API shape changed; re-record the fixture and update the parser",
        )
    meta, rows = payload[0], payload[1]
    dates, values = [], []
    for row in rows:
        try:
            year = int(row["date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"row without a year: {row!r}", provider=WORLD_BANK) from exc
        value = row.get("value")
        dates.append(pd.Timestamp(year=year, month=12, day=31))
        values.append(float("nan") if value is None else float(value))
    series = pd.Series(values, index=pd.DatetimeIndex(dates), name=country).sort_index()
    latest = series.dropna()
    if latest.empty:
        raise InsufficientDataError(
            f"World Bank {WB_INDICATOR} has no observations for {country}",
            hint="the country may not take part in the ICP",
        )
    vintage = {
        "benchmark_year": int(latest.index[-1].year),
        "reference_period": f"{int(latest.index[0].year)}-{int(latest.index[-1].year)}",
        "release_date": str(meta.get("lastupdated", "unknown")),
        "source": f"World Bank ICP {WB_INDICATOR}",
    }
    return series, vintage


def parse_oecd(country: str, text: str) -> tuple[pd.Series, dict[str, Any]]:
    """SDMX-CSV with labels: ``REF_AREA``, ``TIME_PERIOD``, ``OBS_VALUE`` (+ ``LAST_UPDATE``)."""
    reader = csv.DictReader(io.StringIO(text))
    dates, values = [], []
    updated = "unknown"
    for row in reader:
        if row.get("REF_AREA", country) != country:
            continue
        try:
            year = int(str(row["TIME_PERIOD"])[:4])
            value = float(row["OBS_VALUE"])
        except (KeyError, TypeError, ValueError):
            continue
        updated = row.get("LAST_UPDATE") or updated
        dates.append(pd.Timestamp(year=year, month=12, day=31))
        values.append(value)
    if not dates:
        raise InsufficientDataError(
            f"OECD has no PPP observations for {country}",
            hint="OECD covers its members and partners only; try --ppp-provider worldbank",
        )
    series = pd.Series(values, index=pd.DatetimeIndex(dates), name=country).sort_index()
    vintage = {
        "benchmark_year": int(series.index[-1].year),
        "reference_period": f"{int(series.index[0].year)}-{int(series.index[-1].year)}",
        "release_date": str(updated),
        "source": "OECD PPP (PPP_B1GQ)",
    }
    return series, vintage


def parse_bis(country: str, text: str) -> pd.Series:
    """BIS SDMX-CSV: ``TIME_PERIOD`` (YYYY-MM) and ``OBS_VALUE``; index 2020 = 100."""
    reader = csv.DictReader(io.StringIO(text))
    dates, values = [], []
    for row in reader:
        try:
            dates.append(
                pd.Period(str(row["TIME_PERIOD"]), freq="M").to_timestamp(how="end").normalize()
            )
            values.append(float(row["OBS_VALUE"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not dates:
        raise InsufficientDataError(
            f"BIS publishes no real effective exchange rate for {country}",
            hint="BIS covers about 60 economies; check the code",
        )
    return pd.Series(values, index=pd.DatetimeIndex(dates), name=country).sort_index()


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


class _PppBase:
    name: str
    parser: Any

    def __init__(
        self, source: PppSource, cache: ObservationCache | None = None, *, refresh: bool = False
    ) -> None:
        self._source = source
        self._cache = cache
        self._refresh = refresh
        self._log = get_logger(f"sobres.data.{self.name}")

    def _fetch(self, countries: Sequence[str], start: date, end: date) -> pd.DataFrame:
        columns: dict[str, pd.Series] = {}
        vintages: dict[str, dict[str, Any]] = {}
        for c in countries:
            series, vintage = self.parser(c, self._source.payload(c))
            columns[c] = series
            vintages[c] = vintage
        frame = canonical_frame(pd.DataFrame(columns), list(countries))
        frame.attrs["provider"] = self.name
        frame.attrs["series_meta"] = {c: {"vintage": v} for c, v in vintages.items()}
        return frame

    def get_ppp(
        self, countries: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame:
        codes = [c.upper() for c in countries]
        last = end or date.today()
        with span("provider.get_ppp", {"provider": self.name, "countries": len(codes)}):
            if self._cache is None:
                frame = self._fetch(codes, start, last)
                frame = frame.loc[str(start) : str(last)]
            else:
                frame = self._cache.get(
                    self.name, "ppp", codes, start, last, self._fetch, refresh=self._refresh
                )
        meta = frame.attrs.get("series_meta", {})
        missing = [c for c in codes if frame[c].dropna().empty]
        if missing:
            available = [c for c in codes if c not in missing]
            series_name = WB_INDICATOR if self.name == WORLD_BANK else "PPP"
            raise InsufficientDataError(
                f"no PPP observations for {', '.join(missing)} ({self.name} {series_name})"
                + (f"; available: {', '.join(available)}" if available else ""),
                hint="check the country code or try the other --ppp-provider",
            )
        frame.attrs["vintage"] = {c: dict(meta.get(c, {}).get("vintage", {})) for c in codes}
        frame.attrs["provider"] = self.name
        frame.attrs["field"] = "ppp"
        return frame


class WorldBankPppProvider(_PppBase):
    name = WORLD_BANK
    parser = staticmethod(parse_world_bank)

    def __init__(
        self,
        source: PppSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        super().__init__(
            source if source is not None else LiveWorldBankSource(), cache, refresh=refresh
        )


class OecdPppProvider(_PppBase):
    name = OECD
    parser = staticmethod(parse_oecd)

    def __init__(
        self,
        source: PppSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        super().__init__(source if source is not None else LiveOecdSource(), cache, refresh=refresh)


class BisReerProvider:
    name = BIS

    def __init__(
        self,
        source: PppSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        self._source: PppSource = source if source is not None else LiveBisSource()
        self._cache = cache
        self._refresh = refresh
        self._log = get_logger("sobres.data.bis")

    def _fetch(self, countries: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = canonical_frame(
            pd.DataFrame({c: parse_bis(c, self._source.payload(c)) for c in countries}),
            list(countries),
        )
        frame.attrs["provider"] = self.name
        return frame

    def get_reer(
        self, countries: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame:
        codes = [c.upper() for c in countries]
        last = end or date.today()
        with span("provider.get_reer", {"provider": self.name, "countries": len(codes)}):
            if self._cache is None:
                frame = self._fetch(codes, start, last).loc[str(start) : str(last)]
            else:
                frame = self._cache.get(
                    self.name, "reer", codes, start, last, self._fetch, refresh=self._refresh
                )
        frame.attrs.update({"provider": self.name, "field": "reer", "index_base": "2020 = 100"})
        return frame
