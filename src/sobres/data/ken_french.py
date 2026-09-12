"""``KenFrenchProvider``: Fama-French factor returns, no API key.

The Data Library ships each dataset as a zip holding one CSV with several
tables (monthly, then annual; or daily) separated by blank lines and preceded
by free-text notes. The parser is its own tested unit: it locates the header
row, reads the first table whose dates match the requested frequency, and
fails loudly on any layout it does not recognize rather than mis-slicing.

Ken French publishes percent; this provider divides by 100.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from datetime import date
from typing import Protocol

import httpx
import pandas as pd

from sobres.core.errors import ProviderError
from sobres.data.base import FACTOR_COLUMNS, FactorFrequency, FactorModel, canonical_frame
from sobres.data.cache import ObservationCache
from sobres.observability import get_logger, span

PROVIDER_NAME = "ken_french"
BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
TIMEOUT_S = 20.0

FILES: dict[tuple[str, str], str] = {
    ("ff3", "monthly"): "F-F_Research_Data_Factors",
    ("ff3", "daily"): "F-F_Research_Data_Factors_daily",
    ("ff5", "monthly"): "F-F_Research_Data_5_Factors_2x3",
    ("ff5", "daily"): "F-F_Research_Data_5_Factors_2x3_daily",
    ("mom", "monthly"): "F-F_Momentum_Factor",
    ("mom", "daily"): "F-F_Momentum_Factor_daily",
}
EXPECTED_HEADERS: dict[str, tuple[str, ...]] = {
    "ff3": ("Mkt-RF", "SMB", "HML", "RF"),
    "ff5": ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"),
    "mom": ("Mom",),
}
_MONTHLY = re.compile(r"^\d{6}$")
_DAILY = re.compile(r"^\d{8}$")


class KenFrenchSource(Protocol):
    def csv_text(self, file_stem: str) -> str: ...


class LiveKenFrenchSource:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_S, follow_redirects=True)

    def csv_text(self, file_stem: str) -> str:
        url = f"{BASE_URL}/{file_stem}_CSV.zip"
        try:
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"request failed: {type(exc).__name__}",
                provider=PROVIDER_NAME,
                hint="check your network and retry",
            ) from exc
        if response.status_code != 200:
            raise ProviderError(
                f"HTTP {response.status_code} for {file_stem}",
                provider=PROVIDER_NAME,
                hint="retry later; the Data Library may be down",
            )
        return unzip_csv(response.content, file_stem)


def unzip_csv(payload: bytes, file_stem: str) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ProviderError(
                    f"expected one CSV inside {file_stem}_CSV.zip, found {names}",
                    provider=PROVIDER_NAME,
                )
            return archive.read(names[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise ProviderError(
            f"{file_stem}_CSV.zip is not a zip archive",
            provider=PROVIDER_NAME,
            hint="the Data Library layout changed; re-record the fixture",
        ) from exc


def parse_factor_csv(
    text: str, frequency: FactorFrequency, expected: Sequence[str]
) -> pd.DataFrame:
    """Read the first table whose dates match ``frequency``; percent → decimal.

    Raises ``ProviderError`` describing what it expected if the header is
    missing, carries different columns, or no rows of the frequency exist.
    """
    pattern = _MONTHLY if frequency == "monthly" else _DAILY
    lines = text.splitlines()
    i = 0
    header: list[str] | None = None
    rows: list[list[str]] = []
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(",") and header is None:
            candidate = [c.strip() for c in line.split(",")][1:]
            if tuple(candidate) != tuple(expected):
                raise ProviderError(
                    f"unexpected factor columns {candidate}; expected {list(expected)}",
                    provider=PROVIDER_NAME,
                    hint="the Data Library layout changed; update FILES/EXPECTED_HEADERS",
                )
            header = candidate
            i += 1
            while i < len(lines) and lines[i].strip():
                cells = [c.strip() for c in lines[i].split(",")]
                if pattern.match(cells[0]) and len(cells) == len(header) + 1:
                    rows.append(cells)
                elif rows:
                    break  # a different table started without a blank separator
                i += 1
            if rows:
                break
            header = None  # a table of another frequency; keep scanning
        i += 1
    if header is None or not rows:
        raise ProviderError(
            f"no {frequency} table with columns {list(expected)} found in the CSV",
            provider=PROVIDER_NAME,
            hint="the Data Library layout changed; re-record the fixture and update the parser",
        )
    if frequency == "monthly":
        index = pd.DatetimeIndex(
            [
                pd.Period(r[0][:4] + "-" + r[0][4:], freq="M").to_timestamp(how="end").normalize()
                for r in rows
            ]
        )
    else:
        index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows])
    data = {col: [float(r[j + 1]) / 100.0 for r in rows] for j, col in enumerate(header)}
    frame = pd.DataFrame(data, index=index)
    frame.index.name = "date"
    return frame


class KenFrenchProvider:
    name = PROVIDER_NAME

    def __init__(
        self,
        source: KenFrenchSource | None = None,
        cache: ObservationCache | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        self._source: KenFrenchSource = source if source is not None else LiveKenFrenchSource()
        self._cache = cache
        self._refresh = refresh
        self._log = get_logger("sobres.data.ken_french")

    def get_factors(
        self,
        model: FactorModel,
        frequency: FactorFrequency,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        if model not in FACTOR_COLUMNS:
            raise ValueError(f"model must be one of {sorted(FACTOR_COLUMNS)}, got {model!r}")
        columns = list(FACTOR_COLUMNS[model])
        first = start or date(1926, 7, 1)
        last = end or date.today()
        dataset = f"factors_{model}_{frequency}"
        with span("provider.get_factors", {"provider": self.name, "model": model}):
            if self._cache is None:
                frame = self._fetch(model, frequency)
                frame = frame.loc[str(first) : str(last)]
            else:
                frame = self._cache.get(
                    self.name,
                    dataset,
                    columns,
                    first,
                    last,
                    lambda syms, s, e: self._fetch(model, frequency).loc[str(s) : str(e)],
                    refresh=self._refresh,
                )
        frame = frame.reindex(columns=columns)
        frame.attrs.update(
            {"provider": self.name, "field": "return", "model": model, "frequency": frequency}
        )
        return frame

    def _fetch(self, model: str, frequency: FactorFrequency) -> pd.DataFrame:
        base = "ff5" if model.startswith("ff5") else "ff3"
        frame = parse_factor_csv(
            self._source.csv_text(FILES[(base, frequency)]), frequency, EXPECTED_HEADERS[base]
        )
        if model == "ff5+mom":
            mom = parse_factor_csv(
                self._source.csv_text(FILES[("mom", frequency)]), frequency, EXPECTED_HEADERS["mom"]
            )
            frame = frame.join(mom.rename(columns={"Mom": "MOM"}), how="inner")
        out = canonical_frame(frame, list(FACTOR_COLUMNS[model]))
        out.attrs["provider"] = self.name
        return out
