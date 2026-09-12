"""PPP arithmetic and framing against hand-computed cases.

Scenarios: Absolute PPP; Relative PPP; Each result names its method; They are
never combined silently; Real exchange rate; Over- and undervaluation;
Direction is unambiguous; Mandatory framing; No implied trade; Persistent gaps
are expected, not anomalies; Restating a goal; The basket limitation is
stated; Nothing beyond price levels is modeled; Income and target currency may
differ; Vintage is carried; Stale data is flagged; Country codes are
unambiguous.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from sobres.core.errors import UsageError
from sobres.core.ppp import (
    BASKET_NOTE,
    FX_RISK_NOTE,
    NOT_MODELED_NOTE,
    PERSISTENT_GAP_NOTE,
    PPP_FRAMING,
    PppFigure,
    Vintage,
    combine_guard,
    country,
    country_for_currency,
    ppp_rate,
    real_exchange_rate,
    relative_ppp,
    restate_goal,
    valuation_gap,
)

VINTAGE = Vintage(2023, "2010-2023", "2025-07-01", "World Bank ICP PA.NUS.PPP")
USA = PppFigure("USA", "USD", 1.0, "USD", VINTAGE)
GBR = PppFigure("GBR", "GBP", 0.69, "USD", VINTAGE)


def test_absolute_ppp_is_a_published_factor_with_its_vintage() -> None:
    assert GBR.method == "absolute" and GBR.factor == 0.69
    assert GBR.vintage.benchmark_year == 2023 and GBR.vintage.release_date == "2025-07-01"
    assert ppp_rate(GBR, USA) == pytest.approx(0.69)  # GBP per USD at PPP
    other = PppFigure("JPN", "JPY", 97.0, "EUR", VINTAGE)
    with pytest.raises(UsageError):
        ppp_rate(other, USA)


def test_relative_ppp_is_a_drift_from_an_anchor_and_names_its_method() -> None:
    idx = pd.date_range("2020-01-01", periods=4, freq="MS")
    home = pd.Series([100.0, 102.0, 104.0, 106.0], index=idx)  # home inflates faster
    foreign = pd.Series([100.0, 101.0, 102.0, 103.0], index=idx)
    path = relative_ppp(1.25, home, foreign, date(2020, 1, 1))
    assert path.iloc[0] == pytest.approx(1.25)  # the level is the anchor's
    assert path.iloc[-1] == pytest.approx(
        1.25 * (103 / 100) / (106 / 100)
    )  # home currency depreciates
    assert path.attrs["method"] == "relative" and path.attrs["anchor"] == "2020-01-01"
    with pytest.raises(UsageError):
        relative_ppp(1.25, home, foreign, date(2019, 1, 1))


def test_they_are_never_combined_silently() -> None:
    idx = pd.date_range("2020-01-01", periods=2, freq="MS")
    drift = pd.Series([1.0, 1.01], index=idx)
    with pytest.raises(UsageError, match="cannot be combined"):
        combine_guard(GBR, drift)
    combine_guard(GBR, None)
    combine_guard(None, drift)


def test_real_exchange_rate_adjusts_by_the_price_level_ratio() -> None:
    idx = pd.date_range("2020-01-01", periods=2, freq="MS")
    nominal = pd.Series([0.8, 0.8], index=idx)
    home = pd.Series([100.0, 110.0], index=idx)
    foreign = pd.Series([100.0, 100.0], index=idx)
    q = real_exchange_rate(nominal, home, foreign)
    assert q.iloc[0] == pytest.approx(0.8) and q.iloc[1] == pytest.approx(0.8 * 100 / 110)


def test_valuation_gap_direction_is_in_words_and_framed_as_a_gap() -> None:
    gap = valuation_gap("USD", "GBP", market_rate=0.80, ppp=0.69)
    assert gap.gap == pytest.approx(0.80 / 0.69 - 1)
    assert "GBP is undervalued against USD by 15.9%" in gap.statement
    assert "USD is overvalued against GBP" in gap.statement
    rev = valuation_gap("USD", "GBP", market_rate=0.60, ppp=0.69)
    assert "GBP is overvalued against USD" in rev.statement and rev.gap < 0
    for text in (PPP_FRAMING, PERSISTENT_GAP_NOTE):
        for banned in (
            "cheap",
            "expensive",
            "opportunity",
            "signal to",
            "will converge",
            "forecast:",
        ):
            assert banned not in text.lower()
    assert "long-run relationship" in PPP_FRAMING and "not an expected move" in PPP_FRAMING
    assert "productivity differences" in PERSISTENT_GAP_NOTE
    with pytest.raises(UsageError):
        valuation_gap("USD", "GBP", -1.0, 0.69)


def test_restating_a_goal_shows_ppp_and_market_figures_side_by_side() -> None:
    prt = PppFigure("PRT", "EUR", 0.58, "USD", VINTAGE)
    r = restate_goal(2_100_000, USA, prt, market_rate=0.92)
    assert r.ppp_factor == pytest.approx(0.58) and r.adjusted == pytest.approx(2_100_000 * 0.58)
    assert r.at_market_rate == pytest.approx(2_100_000 * 0.92)
    assert r.adjusted != r.at_market_rate  # the difference is the point
    assert "benchmark 2023" in r.basis and "released 2025-07-01" in r.basis
    assert (
        "national consumption basket" in BASKET_NOTE and "not a personalized budget" in BASKET_NOTE
    )
    assert (
        "tax, residency, healthcare" in NOT_MODELED_NOTE
        and "recommends destinations" in NOT_MODELED_NOTE
    )
    assert "exchange-rate risk" in FX_RISK_NOTE and "no constant future rate" in FX_RISK_NOTE


def test_vintage_staleness_and_country_codes() -> None:
    assert VINTAGE.is_stale(date(2027, 1, 1), 3) and not VINTAGE.is_stale(date(2025, 1, 1), 3)
    assert 3.0 < VINTAGE.age_years(date(2026, 9, 12)) < 4.0
    assert country("prt") == ("Portugal", "EUR", "PRT")
    with pytest.raises(UsageError, match="ISO 3166-1 alpha-3"):
        country("PT")  # alpha-2 is not resolved to a near match
    with pytest.raises(UsageError):
        country("PORTUGAL")
    assert country_for_currency("EUR") == "EMU" and country_for_currency("MXN") == "MEX"
    assert country_for_currency("PRT") == "PRT"
    with pytest.raises(UsageError):
        country_for_currency("XYZ")
