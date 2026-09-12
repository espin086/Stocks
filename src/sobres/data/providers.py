"""The provider registry: every data source declared once for doctor and the CLI.

A milestone that adds a provider adds a ``ProviderSpec`` here; a test asserts
every spec has a doctor check.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    kind: str  # price | macro | factor | fx
    description: str
    reachability_url: str
    requires_setting: str | None = None
    extra: str | None = None  # the pip extra that installs its client library


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="yfinance",
        kind="price",
        description="Prices, dividends and splits from Yahoo Finance (keyless).",
        reachability_url="https://query2.finance.yahoo.com/v8/finance/chart/AAPL?range=1d",
        extra="data",
    ),
    ProviderSpec(
        name="fred",
        kind="macro",
        description="Federal Reserve economic series (free API key).",
        reachability_url="https://api.stlouisfed.org/fred/series?series_id=DGS10&file_type=json",
        requires_setting="fred_api_key",
    ),
    ProviderSpec(
        name="ken_french",
        kind="factor",
        description="Fama-French factor returns from the Ken French Data Library (keyless).",
        reachability_url="https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html",
    ),
    ProviderSpec(
        name="ecb",
        kind="fx",
        description="Daily euro reference exchange rates from the ECB (keyless).",
        reachability_url="https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=1",
    ),
)


def provider_names() -> list[str]:
    return [p.name for p in PROVIDERS]
