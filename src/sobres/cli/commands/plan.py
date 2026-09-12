"""``sobres plan`` — retirement, house, car, education and generic goals.

Adapters only: inflation comes from the macro provider, history for the
bootstrap from the price provider, every number from ``core/goals.py`` and
``core/simulate.py``. Real is the default mode: the return you give is
nominal, it is converted with Fisher's identity to a real return, and every
money figure is in today's dollars and says so. ``--nominal`` skips the
conversion and labels accordingly. Taxes are not modeled.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, ClassVar, Literal

import pandas as pd
from pydantic import Field, model_validator

from sobres.cli.context import Context
from sobres.core import goals as g
from sobres.core import simulate as sim
from sobres.core.conventions import PERIODS_PER_YEAR
from sobres.core.errors import UsageError
from sobres.registry import Params, TickerList, register
from sobres.results import Provenance, RecordsResult
from sobres.settings import FRED_API_KEY

Mode = Literal["real", "nominal"]
CPI_SERIES = "CPIAUCSL"
CPI_YEARS = 10
DEFAULT_VOL = 0.15
DEFAULT_RETURN = 0.07


# --------------------------------------------------------------------------- #
# Shared parameters and result
# --------------------------------------------------------------------------- #


class PlanParams(Params):
    real: bool = Field(
        default=False,
        description="Today's dollars: the return is deflated by inflation (the default).",
    )
    nominal: bool = Field(default=False, description="Nominal dollars: no inflation adjustment.")
    inflation: float | None = Field(
        default=None,
        description="Annual inflation for --real; default: trailing 10-year CPI (FRED CPIAUCSL).",
    )
    return_: float | None = Field(
        default=None,
        alias="return",
        description=f"Expected annual return (nominal), decimal; default {DEFAULT_RETURN:.0%}.",
    )
    vol: float = Field(
        default=DEFAULT_VOL, ge=0, description="Annual return volatility for the simulation."
    )
    timing: g.Timing = Field(
        default="end", description="Contribution timing: end (ordinary annuity) or begin (due)."
    )
    simulate: int = Field(
        default=10_000, ge=0, description="Simulated paths; 0 for a deterministic answer only."
    )
    method: sim.Method = Field(default="montecarlo", description="Simulation method.")
    seed: int | None = Field(default=None, description="Seed; printed even when auto-generated.")
    history: TickerList | None = Field(
        default=None,
        description="Tickers whose equal-weight monthly returns the bootstrap resamples.",
    )
    history_start: date = Field(
        default=date(2000, 1, 1), description="First date of the bootstrap history."
    )
    block: int = Field(default=sim.DEFAULT_BLOCK, ge=1, description="Bootstrap block length.")
    save_goal: str | None = Field(
        default=None, description="Save the target and inputs under this name (for sobres ppp)."
    )

    @model_validator(mode="after")
    def _bootstrap_needs_history(self) -> PlanParams:
        if self.method == "bootstrap" and self.simulate and not self.history:
            raise ValueError("--method bootstrap needs --history <tickers>")
        if self.real and self.nominal:
            raise ValueError("--real and --nominal are mutually exclusive")
        return self

    @property
    def mode(self) -> Mode:
        return "nominal" if self.nominal else "real"

    @property
    def expected_return(self) -> float:
        return DEFAULT_RETURN if self.return_ is None else float(self.return_)


class PlanResult(RecordsResult):
    report: ClassVar[bool] = True
    column_kinds: ClassVar[dict[str, str]] = {"metric": "text", "value": "value", "unit": "text"}
    kind: str
    mode: str
    unit_label: str
    assumptions: list[str]
    simulation: dict[str, Any] | None
    seed: int | None

    def header_lines(self) -> list[str]:
        lines = [f"{self.kind}: amounts are {self.unit_label}", *self.assumptions]
        if self.simulation:
            s = self.simulation
            lines.append(
                f"simulation: {s['method']}, {s['n_paths']} paths, seed {s['seed']}; "
                f"success probability {s['success_probability']:.1%}"
            )
            if s.get("history_window"):
                lines.append(
                    f"bootstrap history {s['history_window'][0]} → {s['history_window'][1]}, "
                    f"blocks of {s['block']} months"
                )
            lines.append("the deterministic figures are the median case, not the answer")
        elif self.seed is not None:
            lines.append(f"seed {self.seed} (simulation disabled with --simulate 0)")
        lines.append(g.TAX_NOTE)
        return [*lines, *super().header_lines()]


def _label(mode: str) -> str:
    return "(today's dollars)" if mode == "real" else "(nominal)"


def _inflation(p: PlanParams, ctx: Context) -> tuple[float, str]:
    """The inflation rate for --real and where it came from."""
    if p.inflation is not None:
        return float(p.inflation), "given"
    if ctx.config.get(FRED_API_KEY.key):
        try:
            end = ctx.today()
            start = date(end.year - CPI_YEARS, end.month, 1)
            frame = ctx.macro_provider().get_series([CPI_SERIES], start, end)
            series = frame[CPI_SERIES].dropna()
            years = (series.index[-1] - series.index[0]).days / 365.25
            rate = float((series.iloc[-1] / series.iloc[0]) ** (1.0 / years) - 1.0)
            window = f"{series.index[0].date()} → {series.index[-1].date()}"
            return rate, f"FRED {CPI_SERIES} trailing {years:.1f}-year CAGR, {window}"
        except Exception as exc:  # the plan still runs; the assumption is visible
            ctx.log.warning("inflation.fallback", reason=f"{type(exc).__name__}: {exc}")
            ctx.note(
                f"note: CPI unavailable ({type(exc).__name__}); using {g.FALLBACK_INFLATION:.1%}"
            )
            return g.FALLBACK_INFLATION, "2.5% fallback (FRED unavailable)"
    ctx.note(f"note: no FRED key; using {g.FALLBACK_INFLATION:.1%} inflation for --real")
    return g.FALLBACK_INFLATION, "2.5% fallback (no FRED key)"


def _rates(p: PlanParams, ctx: Context) -> tuple[float, float, list[str]]:
    """Annual return in the chosen mode, the inflation used, and the assumption lines."""
    origin = "given" if p.return_ is not None else "default"
    notes = [
        f"expected return {p.expected_return:.2%} nominal ({origin}), "
        f"volatility {p.vol:.2%} ({'given' if p.vol != DEFAULT_VOL else 'default'})"
    ]
    if p.mode == "nominal":
        return p.expected_return, 0.0, [*notes, "mode: nominal — no inflation adjustment"]
    inflation, source = _inflation(p, ctx)
    real = g.real_rate(p.expected_return, inflation)
    notes.append(f"mode: real — inflation {inflation:.2%} ({source}); real return {real:.2%}")
    return real, inflation, notes


def _history(p: PlanParams, ctx: Context) -> pd.Series | None:
    if p.method != "bootstrap" or not p.simulate:
        return None
    prices = ctx.price_provider().get_prices(list(p.history or []), p.history_start, ctx.today())
    monthly = prices.resample("ME").last().pct_change().dropna(how="all")
    out = pd.Series(monthly.mean(axis=1))
    out.name = "history"
    return out


def _simulate(
    p: PlanParams,
    ctx: Context,
    *,
    present: float,
    monthly: float,
    months: int,
    target: float,
    annual: float,
) -> tuple[dict[str, Any] | None, int | None]:
    if not p.simulate:
        return None, p.seed
    history = _history(p, ctx)
    result = sim.simulate(
        present=present,
        contribution=monthly,
        periods=months,
        target=target,
        frequency="monthly",
        method=p.method,
        annual_mean=annual,
        annual_vol=p.vol,
        history=history,
        block=p.block,
        n_paths=p.simulate,
        seed=p.seed,
        timing=p.timing,
    )
    doc = {
        "method": result.method,
        "n_paths": result.n_paths,
        "seed": result.seed,
        "success_probability": result.success_probability,
        "percentiles": {str(k): v for k, v in result.percentiles.items()},
        "history_window": result.history_window,
        "block": result.block,
    }
    return doc, result.seed


def _sim_rows(doc: dict[str, Any] | None, unit: str) -> list[dict[str, Any]]:
    if doc is None:
        return []
    rows = [
        {
            "metric": "success_probability",
            "value": doc["success_probability"],
            "unit": "probability",
        }
    ]
    for k, v in doc["percentiles"].items():
        rows.append({"metric": f"p{k}_balance", "value": v, "unit": unit})
    return rows


def _row(metric: str, value: Any, unit: str = "") -> dict[str, Any]:
    return {"metric": metric, "value": value, "unit": unit}


def _save_goal(
    p: PlanParams,
    ctx: Context,
    kind: str,
    *,
    target: float,
    monthly: float | None,
    current: float,
    annual: float,
) -> None:
    """Persist the target and its inputs so `sobres ppp adjust-goal --goal` can restate it."""
    if not p.save_goal:
        return
    from sobres.data.storage.base import GoalRecord

    ctx.storage.goals.save(
        GoalRecord(
            name=p.save_goal,
            kind=kind,
            params={
                "target": target,
                "monthly": monthly,
                "current": current,
                "annual_return": annual,
                "mode": p.mode,
            },
        ),
        force=True,
    )
    ctx.note(f"saved goal {p.save_goal!r} ({kind}, target {target:,.0f})")


# --------------------------------------------------------------------------- #
# plan retire
# --------------------------------------------------------------------------- #


class RetireParams(PlanParams):
    income: float = Field(gt=0, description="Annual after-tax income.")
    expenses: float = Field(gt=0, description="Annual expenses (today's dollars).")
    portfolio: float = Field(default=0.0, ge=0, description="Current invested balance.")
    withdrawal_rate: float = Field(
        default=g.DEFAULT_WITHDRAWAL_RATE, gt=0, lt=1, description="Safe withdrawal rate."
    )
    coast: bool = Field(default=False, description="Also report the Coast FI balance.")
    age: int | None = Field(default=None, ge=0, description="Current age (for --coast).")
    retire_age: int | None = Field(default=None, ge=0, description="Target age (for --coast).")

    @model_validator(mode="after")
    def _coast_needs_ages(self) -> RetireParams:
        if self.coast and (
            self.age is None or self.retire_age is None or self.retire_age <= self.age
        ):
            raise ValueError("--coast needs --age and a later --retire-age")
        return self


@register(
    "plan.retire",
    "FI number, savings rate, years to FI and the probability of getting there.",
    result=PlanResult,
)
def retire(p: RetireParams, ctx: Context) -> PlanResult:
    annual, _inflation_used, notes = _rates(p, ctx)
    unit = _label(p.mode)
    target = g.fi_number(p.expenses, p.withdrawal_rate)
    projection = g.project(p.income, p.expenses, annual, p.portfolio, p.withdrawal_rate)
    contribution = p.income - p.expenses
    rows = [
        _row("savings_rate", projection.savings_rate, "fraction"),
        _row("annual_contribution", contribution, unit),
        _row("fi_number", target, unit),
        _row("withdrawal_rate", p.withdrawal_rate, "fraction"),
        _row("years_to_fi", projection.years_to_fi, "years"),
    ]
    today = ctx.today()
    if projection.years_to_fi is not None:
        fi_date = date(today.year + int(projection.years_to_fi), today.month, 1) + pd.DateOffset(
            months=round((projection.years_to_fi % 1) * PERIODS_PER_YEAR["monthly"])
        )
        rows.append(_row("fi_date", str(pd.Timestamp(fi_date).date()), "date"))
    assumptions = [
        *notes,
        f"withdrawal rate {p.withdrawal_rate:.2%}: {g.WITHDRAWAL_RATE_ORIGIN}",
    ]
    if p.coast:
        assert p.age is not None and p.retire_age is not None
        years = p.retire_age - p.age
        coast = g.coast_fi_balance(target, annual, years)
        rows += [
            _row("coast_fi_balance", coast, unit),
            _row("coast_fi_met", p.portfolio >= coast, "bool"),
        ]
        assumptions.append(
            f"coast FI: {coast:,.0f} today grows to the FI number by age {p.retire_age} "
            "with no further contributions: "
            f"{'already met' if p.portfolio >= coast else 'not yet met'}"
        )
    months = (
        max(1, math.ceil(projection.years_to_fi * PERIODS_PER_YEAR["monthly"]))
        if projection.years_to_fi is not None
        else 40 * PERIODS_PER_YEAR["monthly"]
    )
    doc, seed = _simulate(
        p,
        ctx,
        present=p.portfolio,
        monthly=contribution / PERIODS_PER_YEAR["monthly"],
        months=months,
        target=target,
        annual=annual,
    )
    if doc is not None:
        assumptions.append(
            f"simulation horizon: {months} months (the deterministic years-to-FI, rounded up)"
        )
    rows += _sim_rows(doc, unit)
    _save_goal(
        p,
        ctx,
        "retire",
        target=target,
        monthly=contribution / PERIODS_PER_YEAR["monthly"],
        current=p.portfolio,
        annual=annual,
    )
    return PlanResult(
        rows=rows,
        columns=["metric", "value", "unit"],
        kind="retire",
        mode=p.mode,
        unit_label=unit,
        assumptions=assumptions,
        simulation=doc,
        seed=seed,
        provenance=Provenance(),
    )


# --------------------------------------------------------------------------- #
# dated goals: house, car, education, goal
# --------------------------------------------------------------------------- #


def _dated(
    p: PlanParams, ctx: Context, plan: g.GoalPlan, annual: float, notes: list[str]
) -> PlanResult:
    unit = _label(p.mode)
    monthly_rate = g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"])
    rows = [
        _row("target", plan.target, unit),
        _row("months", plan.months, "months"),
        _row("current", plan.present, unit),
        _row("required_monthly", plan.required_monthly, unit),
    ]
    if plan.supplied_monthly is not None:
        rows += [
            _row("supplied_monthly", plan.supplied_monthly, unit),
            _row("projected_balance", plan.projected_balance, unit),
            _row("on_track", plan.on_track, "bool"),
        ]
    contribution = (
        plan.supplied_monthly if plan.supplied_monthly is not None else plan.required_monthly
    )
    doc, seed = _simulate(
        p,
        ctx,
        present=plan.present,
        monthly=contribution,
        months=plan.months,
        target=plan.target,
        annual=annual,
    )
    rows += _sim_rows(doc, unit)
    _save_goal(
        p,
        ctx,
        plan.kind,
        target=plan.target,
        monthly=contribution,
        current=plan.present,
        annual=annual,
    )
    assumptions = [
        *notes,
        *plan.notes,
        f"monthly rate {monthly_rate:.4%}, contributions at period {p.timing}",
    ]
    return PlanResult(
        rows=rows,
        columns=["metric", "value", "unit"],
        kind=plan.kind,
        mode=p.mode,
        unit_label=unit,
        assumptions=assumptions,
        simulation=doc,
        seed=seed,
        provenance=Provenance(),
    )


class HouseParams(PlanParams):
    price: float = Field(gt=0, description="Purchase price today.")
    down_pct: float = Field(default=0.20, gt=0, le=1, description="Down payment as a fraction.")
    by: date = Field(description="Target purchase date.")
    current: float = Field(default=0.0, ge=0, description="Saved so far.")
    monthly: float | None = Field(default=None, ge=0, description="What you can save monthly.")
    price_growth: float = Field(default=0.0, description="Annual house-price growth.")


@register("plan.house", "Down-payment target and the monthly saving it needs.", result=PlanResult)
def house(p: HouseParams, ctx: Context) -> PlanResult:
    annual, _, notes = _rates(p, ctx)
    plan = g.house_plan(
        price=p.price,
        down_pct=p.down_pct,
        months=g.months_between(ctx.today(), p.by),
        present=p.current,
        monthly_rate=g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"]),
        supplied_monthly=p.monthly,
        price_growth=p.price_growth,
        timing=p.timing,
    )
    return _dated(p, ctx, plan, annual, notes)


class CarParams(PlanParams):
    price: float = Field(gt=0, description="Purchase price.")
    by: date = Field(description="Target purchase date.")
    current: float = Field(default=0.0, ge=0, description="Saved so far.")
    monthly: float | None = Field(default=None, ge=0, description="What you can save monthly.")
    depreciation: float | None = Field(
        default=None, ge=0, lt=1, description="Annual depreciation, for the resale estimate."
    )
    resale_years: float = Field(
        default=5.0, gt=0, description="Years until resale (with --depreciation)."
    )


@register(
    "plan.car", "Monthly saving for a car, with an optional resale estimate.", result=PlanResult
)
def car(p: CarParams, ctx: Context) -> PlanResult:
    annual, _, notes = _rates(p, ctx)
    plan = g.car_plan(
        price=p.price,
        months=g.months_between(ctx.today(), p.by),
        present=p.current,
        monthly_rate=g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"]),
        supplied_monthly=p.monthly,
        depreciation=p.depreciation,
        resale_years=p.resale_years if p.depreciation is not None else None,
        timing=p.timing,
    )
    return _dated(p, ctx, plan, annual, notes)


class EducationParams(PlanParams):
    annual_cost: float = Field(gt=0, description="Cost per year in today's dollars.")
    years: int = Field(default=4, ge=1, description="Years of study.")
    starting: int = Field(description="First year of study.")
    current: float = Field(default=0.0, ge=0, description="Saved so far.")
    monthly: float | None = Field(default=None, ge=0, description="What you can save monthly.")
    cost_inflation: float = Field(
        default=g.DEFAULT_EDUCATION_INFLATION,
        description="Education-cost inflation (separate from CPI).",
    )


@register(
    "plan.education",
    "Inflated total cost of an education and the monthly saving.",
    result=PlanResult,
)
def education(p: EducationParams, ctx: Context) -> PlanResult:
    annual, _, notes = _rates(p, ctx)
    today = ctx.today()
    if p.starting <= today.year:
        raise UsageError(f"--starting must be after {today.year}")
    plan = g.education_plan(
        annual_cost=p.annual_cost,
        years=p.years,
        starting_year=p.starting,
        today=today,
        present=p.current,
        monthly_rate=g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"]),
        supplied_monthly=p.monthly,
        cost_inflation=p.cost_inflation,
        timing=p.timing,
    )
    return _dated(p, ctx, plan, annual, notes)


class GoalParams(PlanParams):
    target: float | None = Field(default=None, gt=0, description="Amount to reach.")
    by: date | None = Field(default=None, description="Date to reach it by.")
    monthly: float | None = Field(default=None, description="Monthly contribution.")
    current: float = Field(default=0.0, ge=0, description="Saved so far.")
    solve_return: bool = Field(
        default=False,
        description="Solve for the return that makes the plan work (give the others).",
    )


@register(
    "plan.goal",
    "Generic funding: give three of target, date, monthly and return; the fourth is solved.",
    result=PlanResult,
)
def goal(p: GoalParams, ctx: Context) -> PlanResult:
    annual, _, notes = _rates(p, ctx)
    unit = _label(p.mode)
    months = None if p.by is None else g.months_between(ctx.today(), p.by)
    if months is not None and months <= 0:
        raise UsageError("--by must be at least one month away")
    monthly_rate = g.periodic_rate(annual, PERIODS_PER_YEAR["monthly"])
    all_three = p.target is not None and months is not None and p.monthly is not None
    if p.solve_return and not all_three:
        raise UsageError("--solve-return needs --target, --by and --monthly")
    if all_three and p.return_ is not None and not p.solve_return:
        raise UsageError(
            "target, date, monthly and return are all given; omit --return to check the plan "
            "at the default return, omit one of the others to solve for it, "
            "or pass --solve-return"
        )
    check = all_three and not p.solve_return
    if check:
        # A check: does this monthly reach the target by the date at the default return?
        assert p.target is not None and months is not None and p.monthly is not None
        funding = g.Funding(
            p.target, p.current, p.monthly, monthly_rate, months, p.timing, "target"
        )
        projected = g.future_value(p.current, p.monthly, monthly_rate, months, p.timing)
        funding_note = (
            f"projected balance {projected:,.0f} versus target {p.target:,.0f}: "
            f"{'on track' if projected >= p.target else 'short'} at the default return"
        )
    else:
        funding = g.solve(
            present=p.current,
            target=p.target,
            periods=months,
            contribution=p.monthly,
            rate=None if p.solve_return else monthly_rate,
            timing=p.timing,
        )
        funding_note = f"solved for {funding.solved_for}"
    annual_solved = (1.0 + funding.rate) ** PERIODS_PER_YEAR["monthly"] - 1.0
    rows = [
        _row("solved_for", "feasibility" if check else funding.solved_for, "text"),
        _row("target", funding.target, unit),
        _row("months", funding.periods, "months"),
        _row("monthly", funding.contribution, unit),
        _row("annual_return", annual_solved, f"fraction {p.mode}"),
        _row("current", funding.present, unit),
    ]
    if funding.solved_for == "periods":
        finish = pd.Timestamp(ctx.today()) + pd.DateOffset(months=math.ceil(funding.periods))
        rows.append(_row("reached_by", str(finish.date()), "date"))
    if check:
        assert p.target is not None
        projected = g.future_value(
            p.current, funding.contribution, monthly_rate, funding.periods, p.timing
        )
        required = g.contribution_for(p.target, p.current, monthly_rate, funding.periods, p.timing)
        rows += [
            _row("projected_balance", projected, unit),
            _row("on_track", projected >= p.target, "bool"),
            _row("required_monthly", max(required, 0.0), unit),
        ]
    horizon = max(1, math.ceil(funding.periods))
    doc, seed = _simulate(
        p,
        ctx,
        present=funding.present,
        monthly=funding.contribution,
        months=horizon,
        target=funding.target,
        annual=annual_solved if p.solve_return else annual,
    )
    rows += _sim_rows(doc, unit)
    _save_goal(
        p,
        ctx,
        "goal",
        target=funding.target,
        monthly=funding.contribution,
        current=funding.present,
        annual=annual_solved if p.solve_return else annual,
    )
    return PlanResult(
        rows=rows,
        columns=["metric", "value", "unit"],
        kind="goal",
        mode=p.mode,
        unit_label=unit,
        assumptions=[*notes, funding_note, f"contributions at period {p.timing}"],
        simulation=doc,
        seed=seed,
        provenance=Provenance(),
    )
