"""``sobres plan`` end to end, offline.

Scenarios: Mode selection; Labeling; Inflation source; Solve for time; Solve
for contribution; Contribution timing; Over-specified input; FI number;
Savings rate and date; Coast FI; House; Car; Education; Simulation is run by
default; Reported distribution; The deterministic path is labeled; Bootstrap
mode; Reproducibility; Not advice.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from tests.conftest import SENTINEL_KEY

RETIRE = ["plan", "retire", "--income", "200000", "--expenses", "90000", "--portfolio", "400000"]
FAST = ["--simulate", "300", "--seed", "7"]


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def _rows(doc: dict[str, Any]) -> dict[str, Any]:
    return {r["metric"]: r for r in doc["rows"]}


def test_mode_selection_defaults_to_real_and_labels_every_amount(cli: Callable[..., Any]) -> None:
    real = _json(cli(*RETIRE, *FAST, "--format", "json"))
    assert real["mode"] == "real" and real["unit_label"] == "(today's dollars)"
    assert all(r["unit"] == "(today's dollars)" for r in real["rows"] if r["metric"] == "fi_number")
    nominal = _json(cli(*RETIRE, *FAST, "--nominal", "--format", "json"))
    assert nominal["mode"] == "nominal" and nominal["unit_label"] == "(nominal)"
    assert _rows(nominal)["years_to_fi"]["value"] < _rows(real)["years_to_fi"]["value"]
    explicit = _json(cli(*RETIRE, *FAST, "--real", "--format", "json"))
    assert explicit["mode"] == "real"
    both = cli(*RETIRE, *FAST, "--real", "--nominal")
    assert both.exit_code == 2 and "mutually exclusive" in both.stderr
    table = cli(*RETIRE, *FAST, "--format", "table")
    assert "(today's dollars)" in table.stdout
    assert "(nominal)" in cli(*RETIRE, *FAST, "--nominal", "--format", "table").stdout


def test_inflation_source_is_cpi_with_a_key_and_a_stated_fallback_without(
    cli: Callable[..., Any],
) -> None:
    keyed = cli(
        *RETIRE, *FAST, "--format", "table", env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY}
    )
    assert keyed.exit_code == 0, keyed.stderr
    assert "FRED CPIAUCSL trailing" in keyed.stdout and "-year CAGR" in keyed.stdout
    unkeyed = cli(*RETIRE, *FAST, "--format", "table")
    assert "2.5% fallback (no FRED key)" in unkeyed.stdout
    assert "using 2.5% inflation" in unkeyed.stderr  # the stderr note
    given = cli(*RETIRE, *FAST, "--inflation", "0.03", "--format", "table")
    assert "inflation 3.00% (given)" in given.stdout
    assert "real return" in given.stdout  # Fisher, stated


def test_fi_number_savings_rate_and_date(cli: Callable[..., Any]) -> None:
    doc = _json(cli(*RETIRE, "--simulate", "0", "--nominal", "--format", "json"))
    rows = _rows(doc)
    assert rows["fi_number"]["value"] == 2_250_000  # 90,000 / 0.04
    assert rows["withdrawal_rate"]["value"] == 0.04
    assert rows["savings_rate"]["value"] == 0.55
    assert 9 < rows["years_to_fi"]["value"] < 11
    assert rows["fi_date"]["value"].startswith("203")
    assert any("4% rule (Bengen 1994; Trinity study 1998)" in a for a in doc["assumptions"])
    custom = _rows(
        _json(cli(*RETIRE, "--withdrawal-rate", "0.035", "--simulate", "0", "--format", "json"))
    )
    assert custom["fi_number"]["value"] == 90_000 / 0.035


def test_coast_fi(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            *RETIRE,
            "--coast",
            "--age",
            "35",
            "--retire-age",
            "60",
            "--simulate",
            "0",
            "--nominal",
            "--format",
            "json",
        )
    )
    rows = _rows(doc)
    assert rows["coast_fi_balance"]["value"] == 2_250_000 / 1.07**25
    assert rows["coast_fi_met"]["value"] is False
    assert any("no further contributions" in a and "not yet met" in a for a in doc["assumptions"])
    rich = _rows(
        _json(
            cli(
                *RETIRE[:-2],
                "--portfolio",
                "500000",
                "--coast",
                "--age",
                "35",
                "--retire-age",
                "60",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    assert rich["coast_fi_met"]["value"] is True
    assert cli(*RETIRE, "--coast", "--simulate", "0").exit_code == 2


def test_house_reports_target_required_and_verdict(cli: Callable[..., Any]) -> None:
    base = ["plan", "house", "--price", "950000", "--down-pct", "0.20", "--by", "2029-06-01"]
    doc = _json(cli(*base, "--monthly", "3000", *FAST, "--nominal", "--format", "json"))
    rows = _rows(doc)
    assert rows["target"]["value"] == 190_000 and rows["on_track"]["value"] is False
    assert rows["required_monthly"]["value"] > 3000 and rows["supplied_monthly"]["value"] == 3000
    grown = _rows(
        _json(
            cli(*base, "--price-growth", "0.03", "--simulate", "0", "--nominal", "--format", "json")
        )
    )
    assert (
        grown["target"]["value"] > 190_000
        and grown["required_monthly"]["value"] > rows["required_monthly"]["value"]
    )


def test_car_with_depreciation_states_resale(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "plan",
            "car",
            "--price",
            "45000",
            "--by",
            "2027-01-01",
            "--current",
            "5000",
            "--depreciation",
            "0.15",
            *FAST,
            "--format",
            "json",
        )
    )
    rows = _rows(doc)
    assert rows["required_monthly"]["value"] > 0 and rows["target"]["value"] == 45_000
    assert any("worth about" in a and "after 5 years" in a for a in doc["assumptions"])


def test_education_inflates_costs_at_five_percent_by_default(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "plan",
            "education",
            "--annual-cost",
            "35000",
            "--years",
            "4",
            "--starting",
            "2038",
            *FAST,
            "--nominal",
            "--format",
            "json",
        )
    )
    rows = _rows(doc)
    years_until = 2038 - date.today().year  # the CLI uses the real clock
    expected = sum(35_000 * 1.05 ** (years_until + k) for k in range(4))
    assert rows["target"]["value"] == expected
    assert any("5.0% a year (separate from CPI)" in a for a in doc["assumptions"])
    assert (
        cli(
            "plan", "education", "--annual-cost", "1", "--starting", "2020", "--simulate", "0"
        ).exit_code
        == 2
    )


def test_simulation_runs_by_default_and_reports_the_distribution(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "plan",
            "goal",
            "--target",
            "250000",
            "--by",
            "2032-01-01",
            "--monthly",
            "1500",
            "--seed",
            "1",
            "--format",
            "json",
        )
    )
    assert doc["simulation"] is not None and doc["simulation"]["n_paths"] == 10_000
    rows = _rows(doc)
    assert 0.0 <= rows["success_probability"]["value"] <= 1.0
    assert (
        rows["p10_balance"]["value"] < rows["p25_balance"]["value"] < rows["p50_balance"]["value"]
    )
    assert (
        rows["p50_balance"]["value"] < rows["p75_balance"]["value"] < rows["p90_balance"]["value"]
    )
    table = cli(
        "plan",
        "goal",
        "--target",
        "250000",
        "--by",
        "2032-01-01",
        "--monthly",
        "1500",
        *FAST,
        "--format",
        "table",
    )
    assert "the deterministic figures are the median case, not the answer" in table.stdout
    assert "success probability" in table.stdout
    off = _json(
        cli(
            "plan",
            "goal",
            "--target",
            "250000",
            "--by",
            "2032-01-01",
            "--monthly",
            "1500",
            "--simulate",
            "0",
            "--format",
            "json",
        )
    )
    assert off["simulation"] is None and "success_probability" not in _rows(off)


def test_reproducibility_prints_the_seed_even_when_auto_generated(cli: Callable[..., Any]) -> None:
    args = [
        "plan",
        "goal",
        "--target",
        "250000",
        "--by",
        "2032-01-01",
        "--monthly",
        "1500",
        "--simulate",
        "200",
    ]
    first = _json(cli(*args, "--format", "json"))
    seed = first["simulation"]["seed"]
    assert isinstance(seed, int)
    again = _json(cli(*args, "--seed", str(seed), "--format", "json"))
    assert again["rows"] == first["rows"]
    assert f"seed {seed}" in cli(*args, "--seed", str(seed), "--format", "table").stdout


def test_bootstrap_mode_states_its_window(cli: Callable[..., Any]) -> None:
    args = [
        "plan",
        "goal",
        "--target",
        "250000",
        "--by",
        "2032-01-01",
        "--monthly",
        "1500",
        "--simulate",
        "200",
        "--seed",
        "3",
    ]
    doc = _json(
        cli(
            *args,
            "--method",
            "bootstrap",
            "--history",
            "AAPL",
            "MSFT",
            "--history-start",
            "2015-01-01",
            "--format",
            "json",
        )
    )
    assert doc["simulation"]["method"] == "bootstrap" and doc["simulation"]["block"] == 12
    assert doc["simulation"]["history_window"][0].startswith("2015-02")
    table = cli(
        *args,
        "--method",
        "bootstrap",
        "--history",
        "AAPL",
        "--history-start",
        "2015-01-01",
        "--format",
        "table",
    )
    assert "bootstrap history 2015-02-28" in table.stdout and "blocks of 12 months" in table.stdout
    assert cli(*args, "--method", "bootstrap").exit_code == 2


def test_generic_goal_solves_time_contribution_and_return(cli: Callable[..., Any]) -> None:
    time = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--monthly",
                "1500",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    assert time["solved_for"]["value"] == "periods" and time["months"]["value"] > 100
    assert time["reached_by"]["value"].startswith("203")
    contribution = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--by",
                "2032-01-01",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    assert (
        contribution["solved_for"]["value"] == "contribution"
        and contribution["monthly"]["value"] > 1500
    )
    rate = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--by",
                "2032-01-01",
                "--monthly",
                "1500",
                "--solve-return",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    assert rate["solved_for"]["value"] == "rate" and rate["annual_return"]["value"] > 0.07
    end = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--by",
                "2032-01-01",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    begin = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--by",
                "2032-01-01",
                "--timing",
                "begin",
                "--simulate",
                "0",
                "--nominal",
                "--format",
                "json",
            )
        )
    )
    assert begin["monthly"]["value"] < end["monthly"]["value"]  # annuity-due earns one more period
    unreachable = cli("plan", "goal", "--target", "250000", "--monthly", "-100", "--simulate", "0")
    assert unreachable.exit_code == 5 and "unreachable" in unreachable.stderr


def test_over_specified_input_names_what_to_omit(cli: Callable[..., Any]) -> None:
    result = cli(
        "plan",
        "goal",
        "--target",
        "250000",
        "--by",
        "2032-01-01",
        "--monthly",
        "1500",
        "--return",
        "0.05",
        "--simulate",
        "0",
    )
    assert (
        result.exit_code == 2
        and "omit --return" in result.stderr
        and "--solve-return" in result.stderr
    )
    check = _rows(
        _json(
            cli(
                "plan",
                "goal",
                "--target",
                "250000",
                "--by",
                "2032-01-01",
                "--monthly",
                "1500",
                "--simulate",
                "0",
                "--format",
                "json",
            )
        )
    )
    assert check["solved_for"]["value"] == "feasibility" and check["on_track"]["value"] is False
    too_few = cli("plan", "goal", "--target", "250000", "--simulate", "0")
    assert too_few.exit_code == 2


def test_not_advice_and_taxes_not_modeled(cli: Callable[..., Any]) -> None:
    table = cli(*RETIRE, *FAST, "--format", "table")
    assert "For research and education only. Not investment advice." in table.stdout
    assert "taxes are not modeled; every input is assumed after-tax" in table.stdout
    doc = _json(cli(*RETIRE, *FAST, "--format", "json"))
    assert "Not investment advice" not in json.dumps(doc)
