"""``sobres ppp`` end to end, offline.

Scenarios: Over- and undervaluation; Direction is unambiguous; Each result
names its method; Mandatory framing; No implied trade; Persistent gaps are
expected, not anomalies; Relative PPP; Real exchange rate; Real effective
exchange rates are taken, not invented; Restating a goal; The basket
limitation is stated; Effect on the plan; Nothing beyond price levels is
modeled; Income and target currency may differ; Provider protocol; Keyless
default; Vintage is carried; Stale data is flagged; Missing coverage; Country
codes are unambiguous.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from tests.conftest import SENTINEL_KEY

KEY = {"SOBRES_FRED_API_KEY": SENTINEL_KEY}
ON = ["--on", "2024-06-03"]


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_compare_reports_gaps_in_words_with_framing_and_vintage(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli("ppp", "compare", "--base", "USD", "--vs", "EUR", "GBP", "JPY", *ON, "--format", "json")
    )
    assert [r["currency"] for r in doc["rows"]] == ["EUR", "GBP", "JPY"]
    for r in doc["rows"]:
        assert r["gap"] == r["market_rate"] / r["ppp_rate"] - 1
        assert ("undervalued against USD" in r["verdict"]) or (
            "overvalued against USD" in r["verdict"]
        )
        assert "equivalently USD is" in r["verdict"]  # direction both ways, in words
    assert doc["method"] == "absolute"
    table = cli("ppp", "compare", "--base", "USD", "--vs", "EUR", "GBP", *ON, "--format", "table")
    out = table.stdout
    assert "long-run relationship with little short-run predictive power" in out
    assert "valuation gap, not an expected move" in out
    assert "sustained deviations from PPP are normal" in out
    assert "method: absolute PPP" in out
    assert "benchmark 2023" in out and "released 2025-07-01" in out  # the vintage travels
    assert "STALE" in out  # 2023 benchmark seen from 2026 is past the 3-year threshold
    for banned in ("cheap", "expensive", "opportunity", "converge"):
        assert banned not in out.lower()
    fresh = cli(
        "ppp",
        "compare",
        "--base",
        "USD",
        "--vs",
        "EUR",
        *ON,
        "--format",
        "table",
        env_extra={"SOBRES_PPP_STALE_YEARS": "10"},
    )
    assert "STALE" not in fresh.stdout
    assert (
        cli("ppp", "compare", "--base", "USD", "--vs", "PT", *ON).exit_code == 2
    )  # alpha-2 refused
    missing = cli("ppp", "compare", "--base", "USD", "--vs", "ARS", *ON)
    assert missing.exit_code == 5 and "ARG" in missing.stderr


def test_oecd_is_available_as_an_alternative(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "ppp",
            "compare",
            "--base",
            "USD",
            "--vs",
            "GBP",
            *ON,
            "--format",
            "json",
            env_extra={"SOBRES_PPP_PROVIDER": "oecd"},
        )
    )
    assert doc["provenance"]["provider"] == "oecd" and any("OECD PPP" in v for v in doc["vintages"])
    default = _json(cli("ppp", "compare", "--base", "USD", "--vs", "GBP", *ON, "--format", "json"))
    assert default["provenance"]["provider"] == "worldbank"


def test_relative_ppp_and_real_rate_name_the_anchor_and_indices(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "ppp",
            "relative",
            "USDGBP",
            "--anchor",
            "2016-01-04",
            "--end",
            "2024-12-31",
            "--format",
            "json",
            env_extra=KEY,
        )
    )
    assert (
        doc["columns"] == ["market", "relative_ppp", "real_rate"] and doc["anchor"] == "2016-01-04"
    )
    assert doc["indices"] == {"USD": "CPIAUCSL", "GBP": "GBRCPIALLMINMEI"}
    first = doc["rows"][0]
    assert first["relative_ppp"] == doc["anchor_rate"]  # the level is the anchor's
    table = cli(
        "ppp",
        "relative",
        "USDGBP",
        "--anchor",
        "2016-01-04",
        "--end",
        "2024-12-31",
        "--format",
        "table",
        env_extra=KEY,
    )
    assert "method: relative PPP from the anchor 2016-01-04" in table.stdout
    assert "real exchange rate" in table.stdout and "index base = anchor" in table.stdout
    assert (
        cli(
            "ppp",
            "relative",
            "USDJPY",
            "--anchor",
            "2016-01-04",
            "--end",
            "2024-12-31",
            env_extra=KEY,
        ).exit_code
        == 5
    )


def test_reer_is_published_not_constructed(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "ppp",
            "reer",
            "USA",
            "GBR",
            "--start",
            "2024-01-01",
            "--end",
            "2024-06-30",
            "--format",
            "json",
        )
    )
    assert doc["columns"] == ["USA", "GBR"] and len(doc["rows"]) == 6
    table = cli(
        "ppp", "reer", "USA", "--start", "2024-01-01", "--end", "2024-03-31", "--format", "table"
    )
    assert (
        "as published by the BIS" in table.stdout
        and "no trade weights are constructed" in table.stdout
    )
    assert cli("ppp", "reer", "PRT", "--start", "2024-01-01").exit_code == 5


def test_adjust_goal_restates_with_ppp_beside_the_market_rate(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "ppp",
            "adjust-goal",
            "--target",
            "2100000",
            "--to",
            "PRT",
            "--monthly",
            "3000",
            *ON,
            "--format",
            "json",
        )
    )
    rows = {r["metric"]: r for r in doc["rows"]}
    assert (
        rows["adjusted_target"]["value"]
        == rows["original_target"]["value"] * rows["ppp_factor"]["value"]
    )
    assert (
        rows["at_market_rate"]["value"]
        == rows["original_target"]["value"] * rows["market_rate"]["value"]
    )
    assert rows["adjusted_target"]["value"] != rows["at_market_rate"]["value"]
    assert rows["months_to_goal_adjusted"]["value"] != rows["months_to_goal_original"]["value"]
    assert rows["projected_date_adjusted"]["value"] != rows["projected_date_original"]["value"]
    table = cli(
        "ppp", "adjust-goal", "--target", "2100000", "--to", "PRT", *ON, "--format", "table"
    )
    out = table.stdout
    assert "national consumption basket" in out and "scale factor with its basis named" in out
    assert (
        "tax, residency, healthcare" in out
        and "nothing here ranks or recommends destinations" in out
    )
    assert "exchange-rate risk" in out and "no constant future rate is assumed" in out
    assert "benchmark 2023" in out and "PA.NUS.PPP" in out
    assert cli("ppp", "adjust-goal", "--to", "PRT", *ON).exit_code == 2
    assert cli("ppp", "adjust-goal", "--target", "1", "--to", "PORTUGAL", *ON).exit_code == 2


def test_adjust_goal_reads_a_goal_saved_by_plan(cli: Callable[..., Any]) -> None:
    saved = cli(
        "plan",
        "retire",
        "--income",
        "200000",
        "--expenses",
        "90000",
        "--portfolio",
        "400000",
        "--simulate",
        "0",
        "--nominal",
        "--save-goal",
        "fire",
    )
    assert saved.exit_code == 0 and "saved goal 'fire'" in saved.stderr
    doc = _json(cli("ppp", "adjust-goal", "--goal", "fire", "--to", "PRT", *ON, "--format", "json"))
    rows = {r["metric"]: r for r in doc["rows"]}
    assert rows["original_target"]["value"] == 2_250_000 and "kind: retire" in doc["basis"]
    assert "months_to_goal_adjusted" in rows
    assert cli("ppp", "adjust-goal", "--goal", "nope", "--to", "PRT", *ON).exit_code == 2
