"""Provider sources that replay recorded payloads from ``tests/fixtures/``.

Each source reads exactly what ``scripts/record_fixtures.py`` writes and feeds
it to the same parser the live source feeds, so the offline suite exercises the
real parsing path. ``SOBRES_FIXTURE_DIR`` points a whole run at a directory of
them — the test suite and CI's clean-install smoke test use that.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from sobres.core.errors import InsufficientDataError, ProviderError, UnknownTickerError
from sobres.data.yfinance_provider import RawHistory


class FixtureYahooSource:
    """``<dir>/yfinance/<TICKER>.csv`` plus ``<dir>/yfinance/meta.json``."""

    def __init__(self, root: Path) -> None:
        self.root = root / "yfinance"
        self.calls: list[tuple[str, date, date]] = []

    def history(self, ticker: str, start: date, end: date) -> RawHistory:
        self.calls.append((ticker, start, end))
        path = self.root / f"{ticker.upper()}.csv"
        if not path.exists():
            raise UnknownTickerError(ticker, provider="yfinance")
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame = frame.loc[str(start) : str(end)]
        meta_all = json.loads((self.root / "meta.json").read_text(encoding="utf-8"))
        meta = dict(meta_all.get("tickers", {}).get(ticker.upper(), {}))
        return RawHistory(frame=frame, currency=meta.get("currency"), meta=meta)

    def fundamentals(self, ticker: str) -> dict[str, Any] | None:
        """``<dir>/yfinance/fundamentals.json``: symbol → the vendor's ``info`` keys we use."""
        path = self.root / "fundamentals.json"
        if not path.exists():
            return None
        docs = json.loads(path.read_text(encoding="utf-8")).get("tickers", {})
        info = docs.get(ticker.upper())
        return dict(info) if info else None


class FixtureFredSource:
    """``<dir>/fred/<SERIES>.json`` — the API's JSON response body."""

    def __init__(self, root: Path) -> None:
        self.root = root / "fred"
        self.calls: list[tuple[str, date, date]] = []

    def observations(self, series_id: str, start: date, end: date) -> list[dict[str, Any]]:
        self.calls.append((series_id, start, end))
        path = self.root / f"{series_id.upper()}.json"
        if not path.exists():
            raise UnknownTickerError(series_id, provider="fred")
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise ProviderError("fixture has no 'observations' list", provider="fred")
        return [r for r in rows if start.isoformat() <= r["date"] <= end.isoformat()]


class FixtureEcbSource:
    """``<dir>/ecb/<CCY>.csv`` — the SDMX csvdata body."""

    def __init__(self, root: Path) -> None:
        self.root = root / "ecb"
        self.calls: list[tuple[str, date, date]] = []

    def csv(self, currency: str, start: date, end: date) -> str:
        self.calls.append((currency, start, end))
        path = self.root / f"{currency.upper()}.csv"
        if not path.exists():
            raise ProviderError(
                f"the ECB publishes no reference rate for {currency}", provider="ecb"
            )
        lines = path.read_text(encoding="utf-8").splitlines()
        header, rows = lines[0], lines[1:]
        columns = header.split(",")
        period = columns.index("TIME_PERIOD")
        kept = [r for r in rows if start.isoformat() <= r.split(",")[period] <= end.isoformat()]
        return "\n".join([header, *kept]) + "\n"


class FixtureKenFrenchSource:
    """``<dir>/ken_french/<FILE_STEM>.CSV`` — the CSV inside the published zip."""

    def __init__(self, root: Path) -> None:
        self.root = root / "ken_french"
        self.calls: list[str] = []

    def csv_text(self, file_stem: str) -> str:
        self.calls.append(file_stem)
        path = self.root / f"{file_stem}.CSV"
        if not path.exists():
            raise ProviderError(f"no fixture for {file_stem}", provider="ken_french")
        return path.read_text(encoding="utf-8")


class FixtureDocumentSource:
    """``<dir>/<provider>/<COUNTRY>.<ext>``: one raw document per country (WB, OECD, BIS)."""

    def __init__(self, root: Path, provider: str, ext: str) -> None:
        self.root = root / provider
        self.provider = provider
        self.ext = ext
        self.calls: list[str] = []

    def payload(self, country: str) -> str:
        self.calls.append(country)
        path = self.root / f"{country.upper()}.{self.ext}"
        if not path.exists():
            raise InsufficientDataError(
                f"{self.provider} has no series for {country}",
                hint="check the ISO 3166-1 alpha-3 code",
            )
        return path.read_text()


def fixture_source(provider: str, root: Path) -> Any:
    sources: dict[str, Any] = {
        "yfinance": FixtureYahooSource,
        "fred": FixtureFredSource,
        "ecb": FixtureEcbSource,
        "ken_french": FixtureKenFrenchSource,
        "worldbank": lambda r: FixtureDocumentSource(r, "worldbank", "json"),
        "oecd": lambda r: FixtureDocumentSource(r, "oecd", "csv"),
        "bis": lambda r: FixtureDocumentSource(r, "bis", "csv"),
    }
    return sources[provider](root)
