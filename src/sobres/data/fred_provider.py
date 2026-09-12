"""``FredProvider``: Federal Reserve economic series, behind a free API key.

Only ``LiveFredSource`` talks HTTP; the provider parses the documented JSON
payload (``observations`` with ``date`` and ``value``, where ``"."`` marks a
missing value) so recorded fixtures exercise the real parser.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

import httpx
import pandas as pd

from sobres.core.errors import ConfigurationError, ProviderError, UnknownTickerError
from sobres.data.base import canonical_frame
from sobres.data.cache import ObservationCache
from sobres.observability import get_logger, span
from sobres.settings import FRED_API_KEY, LiveResult

PROVIDER_NAME = "fred"
BASE_URL = "https://api.stlouisfed.org/fred"
OBTAIN_URL = "https://fred.stlouisfed.org/docs/api/api_key.html"
TIMEOUT_S = 5.0

RISK_FREE_SERIES: dict[str, str] = {"1m": "DTB4WK", "3m": "DTB3", "6m": "DTB6", "1y": "DGS1"}


def missing_key_error() -> ConfigurationError:
    return ConfigurationError(
        f"{FRED_API_KEY.env} is not set.",
        hint=(f"Get a free key at {OBTAIN_URL} then run: sobres config set fred_api_key <KEY>"),
    )


class FredSource(Protocol):
    def observations(self, series_id: str, start: date, end: date) -> list[dict[str, Any]]: ...


class LiveFredSource:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._key = api_key
        self._client = client or httpx.Client(timeout=TIMEOUT_S)

    def observations(self, series_id: str, start: date, end: date) -> list[dict[str, Any]]:
        params = {
            "series_id": series_id,
            "api_key": self._key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        try:
            response = self._client.get(f"{BASE_URL}/series/observations", params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"request failed: {type(exc).__name__}",
                provider=PROVIDER_NAME,
                hint="check your network and retry",
            ) from exc
        if response.status_code == 400 and "series" in response.text.lower():
            raise UnknownTickerError(series_id, provider=PROVIDER_NAME)
        if response.status_code in (400, 401, 403):
            raise ConfigurationError(
                f"FRED rejected the API key (HTTP {response.status_code})",
                hint=f"get a key at {OBTAIN_URL} then run: sobres config set fred_api_key <KEY>",
            )
        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code} for {series_id}",
                provider=PROVIDER_NAME,
                hint="retry later; FRED may be down",
            )
        payload = response.json()
        obs = payload.get("observations")
        if not isinstance(obs, list):
            raise ProviderError(
                "payload has no 'observations' list",
                provider=PROVIDER_NAME,
                hint="the API shape changed; re-record the fixture and update the parser",
            )
        return [dict(o) for o in obs]


def validate_api_key(value: str, client: httpx.Client | None = None) -> LiveResult:
    """One cheap request to confirm a key works. Never raises."""
    http = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        response = http.get(
            f"{BASE_URL}/series",
            params={"series_id": "DGS10", "api_key": value, "file_type": "json"},
        )
    except httpx.HTTPError as exc:
        return LiveResult(False, f"could not reach FRED ({type(exc).__name__})")
    if response.status_code == 200:
        return LiveResult(True, "FRED accepted the key")
    return LiveResult(False, f"FRED rejected the key (HTTP {response.status_code})")


def parse_observations(series_id: str, rows: Sequence[dict[str, Any]]) -> pd.Series:
    """FRED's ``"."`` is a missing value; anything else must parse as a number."""
    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for row in rows:
        try:
            when = pd.Timestamp(str(row["date"]))
        except (KeyError, ValueError) as exc:
            raise ProviderError(
                f"observation row for {series_id} has no parseable 'date': {row!r}",
                provider=PROVIDER_NAME,
            ) from exc
        raw = row.get("value", ".")
        if raw in (".", "", None):
            value = float("nan")
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ProviderError(
                    f"{series_id} on {when.date()} has non-numeric value {raw!r}",
                    provider=PROVIDER_NAME,
                ) from exc
        dates.append(when)
        values.append(value)
    return pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id, dtype="float64")


class FredProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str | None,
        source: FredSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        if source is None:
            if not api_key:
                raise missing_key_error()
            source = LiveFredSource(api_key)
        self._source = source
        self._cache = cache
        self._refresh = refresh
        self._log = get_logger("sobres.data.fred")

    def get_series(
        self, series_ids: Sequence[str], start: date, end: date | None = None
    ) -> pd.DataFrame:
        ids = [s.upper() for s in series_ids]
        last = end or date.today()
        with span("provider.get_series", {"provider": self.name, "symbols": len(ids)}):
            if self._cache is None:
                frame = self._fetch(ids, start, last)
            else:
                frame = self._cache.get(
                    self.name, "macro", ids, start, last, self._fetch, refresh=self._refresh
                )
        frame.attrs["provider"] = self.name
        frame.attrs["field"] = "value"
        return frame

    def _fetch(self, ids: Sequence[str], start: date, end: date) -> pd.DataFrame:
        columns = {}
        for series_id in ids:
            rows = self._source.observations(series_id, start, end)
            if not rows:
                raise UnknownTickerError(series_id, provider=self.name)
            columns[series_id] = parse_observations(series_id, rows)
        frame = canonical_frame(pd.DataFrame(columns), ids)
        frame.attrs["provider"] = self.name
        return frame


def get_risk_free_rate(
    provider: FredProvider, start: date, end: date | None = None, tenor: str = "3m"
) -> pd.Series:
    """A decimal annualized rate series (0.0525 for 5.25%), daily frequency.

    FRED publishes Treasury bill yields in percent (``DTB3`` for three months);
    this converts to the decimal convention the risk metrics expect.
    """
    try:
        series_id = RISK_FREE_SERIES[tenor]
    except KeyError:
        raise ValueError(
            f"tenor must be one of {sorted(RISK_FREE_SERIES)}, got {tenor!r}"
        ) from None
    frame = provider.get_series([series_id], start, end)
    rate = frame[series_id] / 100.0
    rate.name = f"rf_{tenor}"
    rate.attrs = {"source": f"FRED {series_id}", "convention": "decimal annual"}
    return rate
