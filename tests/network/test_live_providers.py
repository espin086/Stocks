"""Live provider contracts: the recorded fixture shape against today's payload.

Run deliberately with ``pytest -m network``; excluded from CI.

Scenarios: Provider drift is caught, not guessed; Re-recording is deliberate.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RE_RECORD = "shape changed — re-record with: python scripts/record_fixtures.py --only {name}"

pytestmark = pytest.mark.network


def test_yfinance_live_matches_fixture_shape() -> None:
    from sobres.data.yfinance_provider import LiveYahooSource

    live = LiveYahooSource().history("AAPL", date(2024, 1, 2), date(2024, 1, 10))
    recorded = pd.read_csv(FIXTURES / "yfinance" / "AAPL.csv", index_col=0, nrows=1)
    assert set(recorded.columns) <= set(live.frame.columns), RE_RECORD.format(name="yfinance")
    assert live.currency == "USD", RE_RECORD.format(name="yfinance")


def test_ecb_live_matches_fixture_shape() -> None:
    from sobres.data.ecb_provider import LiveEcbSource, parse_sdmx_csv

    text = LiveEcbSource().csv("USD", date(2024, 1, 2), date(2024, 1, 10))
    assert not parse_sdmx_csv("USD", text).empty, RE_RECORD.format(name="ecb")


def test_ken_french_live_matches_fixture_shape() -> None:
    from sobres.data.ken_french import EXPECTED_HEADERS, LiveKenFrenchSource, parse_factor_csv

    text = LiveKenFrenchSource().csv_text("F-F_Research_Data_5_Factors_2x3")
    frame = parse_factor_csv(text, "monthly", EXPECTED_HEADERS["ff5"])
    assert list(frame.columns) == list(EXPECTED_HEADERS["ff5"]), RE_RECORD.format(name="ken_french")


def test_fred_live_matches_fixture_shape() -> None:
    from sobres.config import resolve
    from sobres.data.fred_provider import LiveFredSource

    key = resolve().get("fred_api_key")
    if not key:
        pytest.skip("SOBRES_FRED_API_KEY not configured")
    rows = LiveFredSource(str(key)).observations("DGS10", date(2024, 1, 2), date(2024, 1, 10))
    recorded = json.loads((FIXTURES / "fred" / "DGS10.json").read_text())["observations"][0]
    assert set(recorded) <= set(rows[0]), RE_RECORD.format(name="fred")
