"""Goal planning: the funding solver and its named specializations.

Everything is a variation on one identity — the future value of a balance plus a
level contribution stream at a periodic rate ``r`` over ``n`` periods:

    FV = P (1+r)^n + C · [((1+r)^n - 1) / r] · (1 + r·due)      (ordinary annuity: due=0;
                                                                annuity-due: due=1)

with ``FV = P + C n`` when ``r = 0``. ``solve`` inverts it for whichever of
target, periods, contribution or rate is missing (rate by bisection; periods in
closed form, ``n = ln((FV r + C') / (P r + C')) / ln(1+r)``, ``C' = C(1 + r·due)``).

Real versus nominal is the caller's explicit choice: pass a real return with a
real target or a nominal return with a nominal target, never mixed. Fisher:
``(1 + nominal) / (1 + inflation) - 1`` converts one to the other.

The FIRE pieces (``savings_rate``, ``fi_number``, ``project``) are ported from
espin086/fire-calculator (MIT) and proved identical against its golden fixture.

Sources: Brealey, Myers & Allen, *Principles of Corporate Finance*, ch. 2 (annuity
formulas); Bengen (1994) and the Trinity study (Cooley, Hubbard & Walz 1998) for the
4% withdrawal rate; Fisher (1930) for the real/nominal identity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import InsufficientDataError, UsageError

Timing = Literal["end", "begin"]
Mode = Literal["real", "nominal"]
DEFAULT_WITHDRAWAL_RATE = 0.04
WITHDRAWAL_RATE_ORIGIN = (
    "the 4% rule (Bengen 1994; Trinity study 1998) — 30-year US history, not a guarantee"
)
FALLBACK_INFLATION = 0.025
DEFAULT_EDUCATION_INFLATION = 0.05
MONTHS = PERIODS_PER_YEAR["monthly"]
TAX_NOTE = "taxes are not modeled; every input is assumed after-tax"


# --------------------------------------------------------------------------- #
# Conversions
# --------------------------------------------------------------------------- #


def real_rate(nominal: float, inflation: float) -> float:
    """Fisher: ``(1 + nominal) / (1 + inflation) - 1``, not the ``nominal - inflation`` shortcut."""
    return float((1.0 + nominal) / (1.0 + inflation) - 1.0)


def periodic_rate(annual: float, periods_per_year: int) -> float:
    """The per-period rate that compounds to ``annual`` over a year."""
    return float((1.0 + annual) ** (1.0 / periods_per_year) - 1.0)


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end`` (the horizon of a dated goal)."""
    months = (end.year - start.year) * MONTHS + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


# --------------------------------------------------------------------------- #
# The funding identity and its inverses
# --------------------------------------------------------------------------- #


def future_value(
    present: float, contribution: float, r: float, periods: float, timing: Timing = "end"
) -> float:
    due = 1.0 if timing == "begin" else 0.0
    if abs(r) < 1e-12:
        return present + contribution * periods
    growth = (1.0 + r) ** periods
    return float(present * growth + contribution * ((growth - 1.0) / r) * (1.0 + r * due))


def periods_to_target(
    target: float, present: float, contribution: float, r: float, timing: Timing = "end"
) -> float:
    """Periods until ``future_value`` reaches ``target``; 0 when already there.

    Raises ``InsufficientDataError`` when the balance can never get there:
    no contribution and no growth, or both pulling the wrong way.
    """
    if present >= target:
        return 0.0
    due = 1.0 if timing == "begin" else 0.0
    c = contribution * (1.0 + r * due)
    if abs(r) < 1e-12:
        if c <= 0:
            raise InsufficientDataError(
                f"target {target:,.0f} is unreachable: no return and a contribution of "
                f"{contribution:,.0f} per period",
                hint="raise the contribution or the assumed return",
            )
        return float((target - present) / c)
    numerator = target * r + c
    denominator = present * r + c
    if numerator <= 0 or denominator <= 0 or (r < 0 and numerator >= denominator):
        raise InsufficientDataError(
            f"target {target:,.0f} is unreachable from {present:,.0f} with contribution "
            f"{contribution:,.0f} per period at {r:.4%} per period",
            hint="raise the contribution or the assumed return, or lower the target",
        )
    n = float(math.log(numerator / denominator) / math.log(1.0 + r))
    if n < 0 or not math.isfinite(n):
        raise InsufficientDataError(
            f"target {target:,.0f} is unreachable with a contribution of {contribution:,.0f}",
            hint="raise the contribution or the assumed return",
        )
    return n


def contribution_for(
    target: float, present: float, r: float, periods: float, timing: Timing = "end"
) -> float:
    """The level contribution that reaches ``target`` in ``periods``; may be negative if ahead."""
    if periods <= 0:
        raise UsageError("the horizon must be at least one period")
    due = 1.0 if timing == "begin" else 0.0
    if abs(r) < 1e-12:
        return (target - present) / periods
    growth = (1.0 + r) ** periods
    return float((target - present * growth) / (((growth - 1.0) / r) * (1.0 + r * due)))


def rate_for(
    target: float,
    present: float,
    contribution: float,
    periods: float,
    timing: Timing = "end",
    *,
    low: float = -0.99,
    high: float = 10.0,
    tolerance: float = 1e-12,
) -> float:
    """The per-period r that reaches ``target``; bisection on the monotone identity."""
    if periods <= 0:
        raise UsageError("the horizon must be at least one period")

    def f(r: float) -> float:
        return future_value(present, contribution, r, periods, timing) - target

    if f(low) > 0:
        return low  # already funded even at the worst r
    if f(high) < 0:
        raise InsufficientDataError(
            f"target {target:,.0f} is unreachable in {periods:g} periods even at "
            f"{high:.0%} per period",
            hint="raise the contribution or lengthen the horizon",
        )
    for _ in range(300):
        mid = (low + high) / 2.0
        if f(mid) < 0:
            low = mid
        else:
            high = mid
        if high - low < tolerance:
            break
    return (low + high) / 2.0


@dataclass(frozen=True)
class Funding:
    """One solved funding problem: every quantity present, the solved one named."""

    target: float
    present: float
    contribution: float
    rate: float
    periods: float
    timing: Timing
    solved_for: Literal["target", "periods", "contribution", "rate"]


def solve(
    *,
    present: float,
    target: float | None = None,
    periods: float | None = None,
    contribution: float | None = None,
    rate: float | None = None,
    timing: Timing = "end",
) -> Funding:
    """Solve for the one unknown among target, periods, contribution and rate."""
    given = {
        "target": target,
        "periods": periods,
        "contribution": contribution,
        "rate": rate,
    }
    missing = [k for k, v in given.items() if v is None]
    if not missing:
        raise UsageError(
            "target, time, contribution and return are all given; omit the one to solve for"
        )
    if len(missing) > 1:
        raise UsageError(
            "give all but one of target, time, contribution and return; "
            f"missing {', '.join(missing)}"
        )
    unknown = missing[0]
    if unknown == "target":
        assert periods is not None and contribution is not None and rate is not None
        value = future_value(present, contribution, rate, periods, timing)
        return Funding(value, present, contribution, rate, periods, timing, "target")
    if unknown == "periods":
        assert target is not None and contribution is not None and rate is not None
        n = periods_to_target(target, present, contribution, rate, timing)
        return Funding(target, present, contribution, rate, n, timing, "periods")
    if unknown == "contribution":
        assert target is not None and periods is not None and rate is not None
        c = contribution_for(target, present, rate, periods, timing)
        return Funding(target, present, c, rate, periods, timing, "contribution")
    assert target is not None and periods is not None and contribution is not None
    r = rate_for(target, present, contribution, periods, timing)
    return Funding(target, present, contribution, r, periods, timing, "rate")


# --------------------------------------------------------------------------- #
# FIRE (ported from espin086/fire-calculator, MIT)
# --------------------------------------------------------------------------- #


def savings_rate(income: float, expenses: float) -> float:
    """Fraction of income saved; 0.0 for non-positive income (fire-calculator semantics)."""
    if income <= 0:
        return 0.0
    return (income - expenses) / income


def fi_number(annual_expenses: float, withdrawal_rate: float = DEFAULT_WITHDRAWAL_RATE) -> float:
    """The portfolio that funds ``annual_expenses`` at ``withdrawal_rate``: 25x at 4%."""
    if withdrawal_rate <= 0:
        raise UsageError("withdrawal_rate must be positive")
    return annual_expenses / withdrawal_rate


@dataclass(frozen=True)
class Projection:
    savings_rate: float
    fi_number: float
    years_to_fi: float | None
    schedule: list[tuple[int, float]]


def project(
    income: float,
    expenses: float,
    annual_return: float,
    starting_balance: float = 0.0,
    withdrawal_rate: float = DEFAULT_WITHDRAWAL_RATE,
    max_years: int = 60,
) -> Projection:
    """Annual compounding of ``income - expenses``; years_to_fi interpolated within the year."""
    target = fi_number(expenses, withdrawal_rate)
    contribution = income - expenses
    balance = starting_balance
    schedule: list[tuple[int, float]] = []
    years_to_fi: float | None = None
    for year in range(1, max_years + 1):
        prev = balance
        balance = balance * (1 + annual_return) + contribution
        schedule.append((year, balance))
        if years_to_fi is None and balance >= target:
            gained = balance - prev
            fraction = 0.0 if gained <= 0 else (target - prev) / gained
            years_to_fi = (year - 1) + min(max(fraction, 0.0), 1.0)
    return Projection(savings_rate(income, expenses), target, years_to_fi, schedule)


def coast_fi_balance(target: float, annual_return: float, years: float) -> float:
    """The balance today that grows to ``target`` in ``years`` with no further contributions."""
    if years <= 0:
        return target
    return float(target / (1.0 + annual_return) ** years)


# --------------------------------------------------------------------------- #
# Named goals
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GoalPlan:
    """A dated goal: the target at the horizon, the monthly saving it needs, and the verdict."""

    kind: str
    target: float
    months: int
    present: float
    required_monthly: float
    supplied_monthly: float | None
    projected_balance: float | None
    on_track: bool | None
    notes: tuple[str, ...] = ()


def _plan(
    kind: str,
    target: float,
    months: int,
    present: float,
    monthly_rate: float,
    supplied_monthly: float | None,
    timing: Timing,
    notes: tuple[str, ...] = (),
) -> GoalPlan:
    if months <= 0:
        raise UsageError("the goal date must be at least one month away")
    required = contribution_for(target, present, monthly_rate, months, timing)
    projected = (
        None
        if supplied_monthly is None
        else future_value(present, supplied_monthly, monthly_rate, months, timing)
    )
    on_track = None if projected is None else projected >= target - 1e-9
    return GoalPlan(
        kind,
        target,
        months,
        present,
        max(required, 0.0),
        supplied_monthly,
        projected,
        on_track,
        notes,
    )


def house_plan(
    *,
    price: float,
    down_pct: float,
    months: int,
    present: float,
    monthly_rate: float,
    supplied_monthly: float | None = None,
    price_growth: float = 0.0,
    timing: Timing = "end",
) -> GoalPlan:
    """Down-payment target, grown with ``price_growth`` (annual) over the horizon."""
    if not 0 < down_pct <= 1:
        raise UsageError("--down-pct is a fraction of the price between 0 and 1")
    grown_price = price * (1.0 + price_growth) ** (months / MONTHS)
    target = grown_price * down_pct
    notes: tuple[str, ...] = ()
    if price_growth:
        notes = (
            f"price grows {price_growth:.2%} a year: {price:,.0f} today becomes "
            f"{grown_price:,.0f} at the goal date",
        )
    return _plan("house", target, months, present, monthly_rate, supplied_monthly, timing, notes)


def car_plan(
    *,
    price: float,
    months: int,
    present: float,
    monthly_rate: float,
    supplied_monthly: float | None = None,
    depreciation: float | None = None,
    resale_years: float | None = None,
    timing: Timing = "end",
) -> GoalPlan:
    notes: tuple[str, ...] = ()
    if depreciation is not None and resale_years is not None:
        resale = price * (1.0 - depreciation) ** resale_years
        notes = (
            f"at {depreciation:.0%} a year the car is worth about {resale:,.0f} "
            f"after {resale_years:g} years",
        )
    return _plan("car", price, months, present, monthly_rate, supplied_monthly, timing, notes)


def education_plan(
    *,
    annual_cost: float,
    years: int,
    starting_year: int,
    today: date,
    present: float,
    monthly_rate: float,
    supplied_monthly: float | None = None,
    cost_inflation: float = DEFAULT_EDUCATION_INFLATION,
    timing: Timing = "end",
) -> GoalPlan:
    """Total cost inflated year by year at ``cost_inflation``, saved for by the first year."""
    if years <= 0:
        raise UsageError("--years must be at least 1")
    years_until = starting_year - today.year
    total = sum(annual_cost * (1.0 + cost_inflation) ** (years_until + k) for k in range(years))
    months = months_between(today, date(starting_year, 9, 1))
    notes = (
        f"education costs inflate at {cost_inflation:.1%} a year (separate from CPI): "
        f"{years} years from {starting_year} total {total:,.0f}",
    )
    return _plan("education", total, months, present, monthly_rate, supplied_monthly, timing, notes)
