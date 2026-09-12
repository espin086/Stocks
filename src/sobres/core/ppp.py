"""Purchasing power parity: what a currency buys, kept apart from what it trades for.

    Absolute PPP:  a published conversion factor — local currency units per one unit of the
                   base currency buying an equivalent basket (World Bank ICP ``PA.NUS.PPP``,
                   OECD PPP). Taken from a statistical office, never computed from indices.
    Relative PPP:  the change in the nominal rate implied by the inflation differential from an
                   anchor date: S_t = S_0 · (P_home,t / P_home,0) / (P_foreign,t / P_foreign,0)
                   (Cassel 1918; Rogoff 1996 for why it holds only in the long run).
    Real rate:     q = S · P_foreign / P_home — the nominal rate adjusted by the price-level ratio.
    Valuation gap: market / PPP - 1, in words as well as sign. A gap, not a forecast.
    Goal restatement: target_dest = target_home · (PPP_dest / PPP_home), a scale factor over a
                   national basket; the market-rate figure is shown beside it because the two
                   differ and the difference is the point.

Every output carries the framing that PPP is a long-run relationship with little short-run
predictive power. Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from sobres.core.errors import UsageError

PPP_FRAMING = (
    "PPP is a long-run relationship with little short-run predictive power for exchange "
    "rates; the gap below is a valuation gap, not an expected move, a target or a signal"
)
PERSISTENT_GAP_NOTE = (
    "sustained deviations from PPP are normal, driven by productivity differences, "
    "non-traded goods and trade barriers"
)
BASKET_NOTE = (
    "PPP reflects a national consumption basket, which may not match your spending; the "
    "adjustment is a scale factor with its basis named, not a personalized budget"
)
NOT_MODELED_NOTE = (
    "tax, residency, healthcare and currency risk on the income stream are not modeled; "
    "nothing here ranks or recommends destinations"
)
FX_RISK_NOTE = (
    "the plan is funded in one currency and spent in another: it carries exchange-rate risk "
    "between them, and no constant future rate is assumed"
)
DEFAULT_STALE_YEARS = 3

# ISO 3166-1 alpha-3 → (name, currency, World Bank code). Deliberately a fixed table:
# an unrecognized code is an error, never a near match.
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "USA": ("United States", "USD", "USA"),
    "GBR": ("United Kingdom", "GBP", "GBR"),
    "JPN": ("Japan", "JPY", "JPN"),
    "CHE": ("Switzerland", "CHF", "CHE"),
    "CAN": ("Canada", "CAD", "CAN"),
    "AUS": ("Australia", "AUD", "AUS"),
    "MEX": ("Mexico", "MXN", "MEX"),
    "BRA": ("Brazil", "BRL", "BRA"),
    "IND": ("India", "INR", "IND"),
    "CHN": ("China", "CNY", "CHN"),
    "KOR": ("Korea", "KRW", "KOR"),
    "SGP": ("Singapore", "SGD", "SGP"),
    "NZL": ("New Zealand", "NZD", "NZL"),
    "NOR": ("Norway", "NOK", "NOR"),
    "SWE": ("Sweden", "SEK", "SWE"),
    "DNK": ("Denmark", "DKK", "DNK"),
    "POL": ("Poland", "PLN", "POL"),
    "CZE": ("Czechia", "CZK", "CZE"),
    "HUN": ("Hungary", "HUF", "HUN"),
    "TUR": ("Türkiye", "TRY", "TUR"),
    "ZAF": ("South Africa", "ZAR", "ZAF"),
    "ISR": ("Israel", "ILS", "ISR"),
    "THA": ("Thailand", "THB", "THA"),
    "COL": ("Colombia", "COP", "COL"),
    "CHL": ("Chile", "CLP", "CHL"),
    "ARG": ("Argentina", "ARS", "ARG"),
    "PRT": ("Portugal", "EUR", "PRT"),
    "ESP": ("Spain", "EUR", "ESP"),
    "FRA": ("France", "EUR", "FRA"),
    "DEU": ("Germany", "EUR", "DEU"),
    "ITA": ("Italy", "EUR", "ITA"),
    "NLD": ("Netherlands", "EUR", "NLD"),
    "IRL": ("Ireland", "EUR", "IRL"),
    "AUT": ("Austria", "EUR", "AUT"),
    "BEL": ("Belgium", "EUR", "BEL"),
    "FIN": ("Finland", "EUR", "FIN"),
    "GRC": ("Greece", "EUR", "GRC"),
    "EMU": ("Euro area", "EUR", "EMU"),
}
# A currency's reference economy for ``ppp compare`` (the euro area for the euro).
CURRENCY_COUNTRY: dict[str, str] = {
    "USD": "USA",
    "GBP": "GBR",
    "JPY": "JPN",
    "CHF": "CHE",
    "CAD": "CAN",
    "AUD": "AUS",
    "MXN": "MEX",
    "BRL": "BRA",
    "INR": "IND",
    "CNY": "CHN",
    "KRW": "KOR",
    "SGD": "SGP",
    "NZD": "NZL",
    "NOK": "NOR",
    "SEK": "SWE",
    "DKK": "DNK",
    "PLN": "POL",
    "CZK": "CZE",
    "HUF": "HUN",
    "TRY": "TUR",
    "ZAR": "ZAF",
    "ILS": "ISR",
    "THB": "THA",
    "COP": "COL",
    "CLP": "CHL",
    "ARS": "ARG",
    "EUR": "EMU",
}


def country(code: str) -> tuple[str, str, str]:
    """``(name, currency, world_bank_code)`` for an ISO 3166-1 alpha-3 code; else ``UsageError``."""
    key = code.strip().upper()
    if key not in COUNTRIES:
        raise UsageError(
            f"unrecognized country code {code!r}: use an ISO 3166-1 alpha-3 code",
            hint="known codes: " + ", ".join(sorted(COUNTRIES)),
        )
    return COUNTRIES[key]


def country_for_currency(currency: str) -> str:
    key = currency.strip().upper()
    if key in COUNTRIES:
        return key  # a country code was given
    if key not in CURRENCY_COUNTRY:
        raise UsageError(
            f"no reference economy for currency {currency!r}",
            hint="pass an ISO 3166-1 alpha-3 country code instead",
        )
    return CURRENCY_COUNTRY[key]


@dataclass(frozen=True)
class Vintage:
    """What travels with every PPP figure."""

    benchmark_year: int
    reference_period: str
    release_date: str
    source: str

    def is_stale(self, today: date, threshold_years: int = DEFAULT_STALE_YEARS) -> bool:
        return self.age_years(today) > threshold_years

    def age_years(self, today: date) -> float:
        return today.year - self.benchmark_year + (today.timetuple().tm_yday / 365.25)


@dataclass(frozen=True)
class PppFigure:
    country: str
    currency: str
    factor: float
    """Local currency units per one base-currency unit (an absolute PPP conversion factor)."""
    base_currency: str
    vintage: Vintage
    method: str = "absolute"


def ppp_rate(quote: PppFigure, base: PppFigure) -> float:
    """Units of ``quote.currency`` per one unit of ``base.currency`` implied by absolute PPP.

    Both factors are quoted against the same reference (the international dollar), so
    the cross-rate is their ratio.
    """
    if quote.base_currency != base.base_currency:
        raise UsageError("PPP factors must share a reference currency")
    if quote.method != "absolute" or base.method != "absolute":
        raise UsageError("a PPP cross-rate needs absolute conversion factors, not relative drift")
    return quote.factor / base.factor


@dataclass(frozen=True)
class ValuationGap:
    base: str
    quote: str
    market_rate: float
    ppp_rate: float
    gap: float
    """``market / ppp - 1``: positive means the quote currency is undervalued against the base."""

    @property
    def statement(self) -> str:
        pct = abs(self.gap)
        if abs(self.gap) < 1e-9:
            return f"{self.quote} trades at its PPP rate against {self.base}"
        if self.gap > 0:
            return (
                f"{self.quote} is undervalued against {self.base} by {pct:.1%} at the market rate "
                f"(equivalently {self.base} is overvalued against {self.quote})"
            )
        return (
            f"{self.quote} is overvalued against {self.base} by {pct:.1%} at the market rate "
            f"(equivalently {self.base} is undervalued against {self.quote})"
        )


def valuation_gap(base: str, quote: str, market_rate: float, ppp: float) -> ValuationGap:
    """Both rates as units of ``quote`` per one ``base``."""
    if ppp <= 0 or market_rate <= 0:
        raise UsageError("rates must be positive")
    return ValuationGap(base.upper(), quote.upper(), market_rate, ppp, market_rate / ppp - 1.0)


def relative_ppp(
    anchor_rate: float, home_prices: pd.Series, foreign_prices: pd.Series, anchor: date
) -> pd.Series:
    """The nominal rate path implied by the inflation differential since ``anchor``.

    Rate as units of foreign per one home; ``home_prices``/``foreign_prices`` are price
    indices. ``S_t = S_0 · (P_f,t/P_f,0) / (P_h,t/P_h,0)``: the currency of the
    higher-inflation economy depreciates.
    """
    both = pd.concat([home_prices.rename("h"), foreign_prices.rename("f")], axis=1, join="inner")
    both = both.dropna()
    stamp = pd.Timestamp(anchor)
    at = both.loc[:stamp]
    if at.empty:
        raise UsageError(f"no price observations on or before the anchor {anchor}")
    p_h0, p_f0 = float(at["h"].iloc[-1]), float(at["f"].iloc[-1])
    implied = anchor_rate * (both["f"] / p_f0) / (both["h"] / p_h0)
    out = pd.Series(implied.loc[at.index[-1] :])  # from the price observation the anchor rests on
    out.name = "relative_ppp"
    out.attrs = {"method": "relative", "anchor": anchor.isoformat(), "anchor_rate": anchor_rate}
    return out


def real_exchange_rate(
    nominal: pd.Series, home_prices: pd.Series, foreign_prices: pd.Series
) -> pd.Series:
    """``q = S · P_foreign / P_home`` on the common dates (level, not a base-period index)."""
    both = pd.concat(
        [nominal.rename("s"), home_prices.rename("h"), foreign_prices.rename("f")],
        axis=1,
        join="inner",
    ).dropna()
    out = both["s"] * both["f"] / both["h"]
    out.name = "real_rate"
    return pd.Series(out)


def combine_guard(absolute: PppFigure | None, relative_series: pd.Series | None) -> None:
    """Absolute factors and relative drift never meet silently."""
    if absolute is not None and relative_series is not None:
        raise UsageError(
            "an absolute PPP conversion factor cannot be combined with a relative-PPP drift; "
            "choose one method"
        )


@dataclass(frozen=True)
class GoalRestatement:
    original: float
    origin: str
    destination: str
    ppp_factor: float
    """``PPP_dest / PPP_origin``: the scale factor applied to the target."""
    adjusted: float
    """In the destination's currency at PPP."""
    at_market_rate: float
    """The same original converted at the market rate, for contrast."""
    origin_currency: str
    destination_currency: str
    basis: str


def restate_goal(
    original: float,
    origin: PppFigure,
    destination: PppFigure,
    market_rate: float,
) -> GoalRestatement:
    """Restate a target at the destination's price level; show the market-rate figure beside it."""
    factor = ppp_rate(destination, origin)
    return GoalRestatement(
        original=original,
        origin=origin.country,
        destination=destination.country,
        ppp_factor=factor,
        adjusted=original * factor,
        at_market_rate=original * market_rate,
        origin_currency=origin.currency,
        destination_currency=destination.currency,
        basis=(
            f"{destination.vintage.source} absolute PPP, "
            f"benchmark {destination.vintage.benchmark_year}, "
            f"released {destination.vintage.release_date}"
        ),
    )
