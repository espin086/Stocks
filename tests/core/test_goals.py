"""The funding solver, FIRE math and named goals against closed forms and the prior fixture.

Scenarios: Solve for time; Solve for contribution; Contribution timing;
Over-specified input; FI number; Savings rate and date; Coast FI; Parity with
the prior implementation; House; Car; Education; Mode selection.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import InsufficientDataError, UsageError
from sobres.core.goals import (
    DEFAULT_WITHDRAWAL_RATE,
    car_plan,
    coast_fi_balance,
    contribution_for,
    education_plan,
    fi_number,
    future_value,
    house_plan,
    months_between,
    periodic_rate,
    periods_to_target,
    project,
    rate_for,
    real_rate,
    savings_rate,
    solve,
)

GOLDEN = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "fire_calculator" / "golden.json"
    ).read_text(encoding="utf-8")
)
TOL = 1e-6  # the golden file's own tolerance


def test_future_value_matches_the_annuity_formula() -> None:
    # 100 at 1% a period for 10 periods plus 10 a period (ordinary annuity):
    # 100·1.01^10 + 10·(1.01^10 − 1)/0.01 = 110.4622 + 104.6221 = 215.0843
    assert future_value(100, 10, 0.01, 10) == pytest.approx(
        215.0843, abs=1e-4
    )  # hand-computed to four decimals
    # Annuity-due: the contribution stream is one period richer, ×1.01.
    assert future_value(100, 10, 0.01, 10, "begin") == pytest.approx(
        110.4622 + 104.6221 * 1.01, abs=1e-4
    )
    assert future_value(100, 10, 0.0, 10) == 200.0  # no growth: straight sum


def test_solve_for_time_closed_form_and_unreachable() -> None:
    # n = ln((FV r + C)/(P r + C)) / ln(1+r); the identity must hold at the solved n.
    n = periods_to_target(1000, 0, 100, 0.01)
    assert future_value(0, 100, 0.01, n) == pytest.approx(1000, abs=1e-9)
    assert periods_to_target(500, 500, 0, 0.01) == 0.0  # already there
    assert periods_to_target(1000, 0, 100, 0.0) == pytest.approx(10.0)
    with pytest.raises(InsufficientDataError, match="unreachable"):
        periods_to_target(1000, 0, 0, 0.0)  # nothing moves
    with pytest.raises(InsufficientDataError, match="unreachable"):
        periods_to_target(1000, 100, -50, 0.01)  # withdrawing faster than growth
    solved = solve(present=0, target=1000, contribution=100, rate=0.01)
    assert solved.solved_for == "periods" and solved.periods == pytest.approx(n)


def test_solve_for_contribution_and_rate_invert_the_identity() -> None:
    c = contribution_for(10_000, 1_000, 0.005, 36)
    assert future_value(1_000, c, 0.005, 36) == pytest.approx(10_000, abs=1e-9)
    assert contribution_for(1_200, 0, 0.0, 12) == pytest.approx(100.0)
    r = rate_for(10_000, 1_000, 200, 36)
    assert future_value(1_000, 200, r, 36) == pytest.approx(
        10_000, abs=1e-6
    )  # bisection/float-sum tolerance
    assert solve(
        present=1_000, target=10_000, periods=36, rate=0.005
    ).contribution == pytest.approx(c)
    assert solve(present=1_000, target=10_000, periods=36, contribution=200).rate == pytest.approx(
        r, abs=1e-9
    )
    assert solve(present=1_000, periods=36, contribution=200, rate=r).target == pytest.approx(
        10_000, abs=1e-6
    )
    with pytest.raises(InsufficientDataError):
        rate_for(1e12, 0, 1, 2)
    with pytest.raises(UsageError):
        contribution_for(1, 0, 0.01, 0)


def test_contribution_timing_end_versus_begin() -> None:
    end = contribution_for(10_000, 0, 0.01, 24, "end")
    begin = contribution_for(10_000, 0, 0.01, 24, "begin")
    assert begin == pytest.approx(end / 1.01)  # each due contribution earns one more period
    assert periods_to_target(10_000, 0, end, 0.01, "end") == pytest.approx(24)
    assert periods_to_target(10_000, 0, begin, 0.01, "begin") == pytest.approx(24)


def test_over_specified_and_under_specified_input() -> None:
    with pytest.raises(UsageError, match="omit the one to solve for"):
        solve(present=0, target=1, periods=1, contribution=1, rate=0.01)
    with pytest.raises(UsageError, match="missing periods, contribution"):
        solve(present=0, target=1, rate=0.01)


# ------------------------------------------------------------------ FIRE
def test_fi_number_is_expenses_over_the_withdrawal_rate() -> None:
    assert DEFAULT_WITHDRAWAL_RATE == 0.04
    assert fi_number(90_000) == pytest.approx(2_250_000)  # 25x
    assert fi_number(90_000, 0.05) == pytest.approx(1_800_000)
    with pytest.raises(UsageError):
        fi_number(90_000, 0)


def test_savings_rate_and_years_to_fi() -> None:
    assert savings_rate(200_000, 90_000) == pytest.approx(0.55)
    assert savings_rate(0, 100) == 0.0
    p = project(200_000, 90_000, 0.07, 400_000)
    assert p.fi_number == pytest.approx(2_250_000) and p.savings_rate == pytest.approx(0.55)
    assert p.years_to_fi is not None and 9 < p.years_to_fi < 12
    assert p.schedule[0] == (1, pytest.approx(400_000 * 1.07 + 110_000))
    assert project(50_000, 60_000, 0.05, max_years=10).years_to_fi is None


def test_coast_fi_balance_discounts_the_target() -> None:
    # 2,250,000 / 1.07^25 = 484,... : the balance that coasts to FI in 25 years.
    assert coast_fi_balance(2_250_000, 0.07, 25) == pytest.approx(2_250_000 / 1.07**25)
    assert coast_fi_balance(2_250_000, 0.07, 0) == 2_250_000


@pytest.mark.parametrize("case", GOLDEN["fi_number"])
def test_parity_fi_number(case: dict[str, float]) -> None:
    assert fi_number(case["annual_expenses"], case["withdrawal_rate"]) == pytest.approx(
        case["expected"], rel=TOL
    )


@pytest.mark.parametrize("case", GOLDEN["savings_rate"])
def test_parity_savings_rate(case: dict[str, float]) -> None:
    assert savings_rate(case["income"], case["expenses"]) == pytest.approx(
        case["expected"], abs=TOL
    )


@pytest.mark.parametrize("case", GOLDEN["project"])
def test_parity_project(case: dict[str, float]) -> None:
    p = project(
        case["income"],
        case["expenses"],
        case["annual_return"],
        case["starting_balance"],
        case["withdrawal_rate"],
        int(case["max_years"]),
    )
    assert p.savings_rate == pytest.approx(
        case["savings_rate"], rel=TOL
    )  # the fixture's own tolerance
    assert p.fi_number == pytest.approx(case["fi_number"], rel=TOL)  # the fixture's own tolerance
    assert p.years_to_fi == pytest.approx(
        case["years_to_fi"], rel=TOL
    )  # the fixture's own tolerance
    assert len(p.schedule) == case["schedule_len"]
    assert p.schedule[0][1] == pytest.approx(
        case["first_balance"], rel=TOL
    )  # the fixture's own tolerance
    assert p.schedule[-1][1] == pytest.approx(
        case["last_balance"], rel=TOL
    )  # the fixture's own tolerance


# ------------------------------------------------------------ named goals
def test_house_target_grows_with_price_growth() -> None:
    rate = periodic_rate(0.05, PERIODS_PER_YEAR["monthly"])
    flat = house_plan(
        price=950_000, down_pct=0.2, months=36, present=0, monthly_rate=rate, supplied_monthly=3000
    )
    assert flat.target == pytest.approx(190_000) and flat.on_track is False
    assert flat.projected_balance == pytest.approx(future_value(0, 3000, rate, 36))
    grown = house_plan(
        price=950_000, down_pct=0.2, months=36, present=0, monthly_rate=rate, price_growth=0.03
    )
    assert grown.target == pytest.approx(950_000 * 1.03**3 * 0.2)
    assert grown.required_monthly > flat.required_monthly and "price grows" in grown.notes[0]
    with pytest.raises(UsageError):
        house_plan(price=1, down_pct=1.5, months=12, present=0, monthly_rate=rate)


def test_car_resale_uses_geometric_depreciation() -> None:
    plan = car_plan(
        price=45_000, months=12, present=5_000, monthly_rate=0.0, depreciation=0.15, resale_years=5
    )
    assert plan.required_monthly == pytest.approx(40_000 / 12)
    assert f"{45_000 * 0.85**5:,.0f}" in plan.notes[0]


def test_education_total_is_inflated_year_by_year() -> None:
    today = date(2026, 9, 12)
    plan = education_plan(
        annual_cost=35_000, years=4, starting_year=2038, today=today, present=0, monthly_rate=0.0
    )
    expected = sum(35_000 * 1.05 ** (12 + k) for k in range(4))
    assert plan.target == pytest.approx(expected)
    assert plan.months == months_between(today, date(2038, 9, 1))
    assert "5.0% a year (separate from CPI)" in plan.notes[0]


def test_real_versus_nominal_is_fisher_not_subtraction() -> None:
    assert real_rate(0.07, 0.025) == pytest.approx(1.07 / 1.025 - 1)
    assert real_rate(0.07, 0.025) != pytest.approx(0.045)
    assert periodic_rate(0.12, PERIODS_PER_YEAR["monthly"]) == pytest.approx(1.12 ** (1 / 12) - 1)
    assert months_between(date(2026, 9, 12), date(2027, 1, 1)) == 3
    assert months_between(date(2026, 9, 12), date(2029, 6, 1)) == 32
