"""``sobres analyze stock`` and ``sobres analyze factors`` end to end, offline.

Scenarios: Default frequency; Stock dashboard; Fundamentals limitation is
stated; Missing fundamentals; Comparison table; Rolling betas; Alpha is
reported honestly; Robust standard errors; Minimum sample.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

WINDOW = ["--start", "2015-01-01", "--end", "2024-12-31", "--fill", "drop"]


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_stock_dashboard_has_every_section(cli: Callable[..., Any]) -> None:
    doc = _json(cli("analyze", "stock", "AAPL", *WINDOW, "--format", "json"))
    sections = {(r["section"], r["metric"]): r["value"] for r in doc["rows"]}
    for key in (("price", "first"), ("price", "last"), ("price", "high"), ("price", "low")):
        assert key in sections
    assert ("returns", "annualized_return") in sections
    assert ("returns", "annualized_volatility") in sections
    for metric in ("sharpe", "sortino", "max_drawdown", "var_95", "cvar_95", "skew", "kurtosis"):
        assert ("risk", metric) in sections, metric  # the full 0002 panel
    assert ("capm", "beta_mkt") in sections and sections[("capm", "n_months")] >= 36
    for metric in ("market_cap", "pe_ratio", "price_to_book", "dividend_yield", "sector"):
        assert ("fundamentals", metric) in sections, metric
    assert sections[("fundamentals", "sector")] == "Technology"
    assert doc["ticker"] == "AAPL" and doc["name"] == "Apple Inc."
    table = cli("analyze", "stock", "AAPL", *WINDOW, "--format", "table")
    assert "AAPL — Apple Inc." in table.stdout
    assert "Not investment advice" in table.stdout


def test_fundamentals_limitation_is_stated_whenever_values_show(cli: Callable[..., Any]) -> None:
    table = cli("analyze", "stock", "MSFT", *WINDOW, "--format", "table")
    assert "not point-in-time" in table.stdout and "unsuitable for backtesting" in table.stdout
    doc = _json(cli("analyze", "stock", "MSFT", *WINDOW, "--format", "json"))
    assert "not point-in-time" in doc["fundamentals_note"]


def test_missing_fundamentals_omits_the_block_and_keeps_the_rest(cli: Callable[..., Any]) -> None:
    doc = _json(cli("analyze", "stock", "GLD", *WINDOW, "--format", "json"))  # an ETF
    sections = {r["section"] for r in doc["rows"]}
    assert "fundamentals" not in sections and {"price", "returns", "risk"} <= sections
    assert "none reported for GLD" in doc["fundamentals_note"] and "ETF" in doc["fundamentals_note"]
    table = cli("analyze", "stock", "GLD", *WINDOW, "--format", "table")
    assert "section omitted" in table.stdout and "max_drawdown" in table.stdout


def test_default_frequency_is_monthly_and_daily_is_a_choice(cli: Callable[..., Any]) -> None:
    doc = _json(cli("analyze", "factors", "AAPL", "--model", "ff5", *WINDOW, "--format", "json"))
    assert doc["frequency"] == "monthly" and 100 <= doc["n_obs"] <= 120
    assert [r["term"] for r in doc["rows"]] == ["alpha", "Mkt-RF", "SMB", "HML", "RMW", "CMA"]
    for row in doc["rows"]:
        for column in ("coefficient", "se", "t", "p", "se_hac", "t_hac", "p_hac"):
            assert column in row, column  # Reported statistics, under OLS and HAC
    assert doc["rows"][0]["annualized"] == doc["annualized_alpha"]
    assert doc["hac_lags"] == 4  # floor(4 (119/100)^(2/9)); stated in the header
    table = cli("analyze", "factors", "AAPL", "--model", "ff5", *WINDOW, "--format", "table")
    assert "HAC (Newey-West) standard errors with 4 lag(s)" in table.stdout
    assert "R²" in table.stdout and "adjusted R²" in table.stdout
    daily = _json(
        cli("analyze", "factors", "AAPL", "--frequency", "daily", *WINDOW, "--format", "json")
    )
    assert daily["frequency"] == "daily" and daily["n_obs"] > 2000


def test_alpha_is_qualified_when_not_distinguishable_from_zero(cli: Callable[..., Any]) -> None:
    table = cli("analyze", "factors", "AAPL", "--model", "ff3", *WINDOW, "--format", "table")
    doc = _json(cli("analyze", "factors", "AAPL", "--model", "ff3", *WINDOW, "--format", "json"))
    if doc["alpha_p_hac"] > 0.05:
        assert "not statistically distinguishable from zero at the 5% level" in table.stdout
        assert "should not be read on its own" in table.stdout
    else:
        assert "distinguishable from zero at the 5% level" in table.stdout


def test_comparison_table_keeps_the_supplied_order(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "analyze",
            "factors",
            "--tickers",
            "MSFT",
            "GLD",
            "AAPL",
            "--model",
            "ff5",
            *WINDOW,
            "--format",
            "json",
        )
    )
    assert [r["ticker"] for r in doc["rows"]] == ["MSFT", "GLD", "AAPL"]
    assert doc["columns"][:6] == ["ticker", "Mkt-RF", "SMB", "HML", "RMW", "CMA"]
    for row in doc["rows"]:
        assert {"alpha_annualized", "alpha_t", "alpha_p", "r2", "n_obs"} <= set(row)
        assert row["significant"] in ("", "*")
    csv = cli(
        "analyze",
        "factors",
        "--tickers",
        "MSFT",
        "GLD",
        "AAPL",
        "--model",
        "ff5",
        *WINDOW,
        "--format",
        "csv",
    )
    assert csv.stdout.splitlines()[1].startswith("MSFT,")


def test_rolling_betas_are_a_frame_per_window(cli: Callable[..., Any]) -> None:
    doc = _json(cli("analyze", "factors", "AAPL", "--rolling", "36", *WINDOW, "--format", "json"))
    assert doc["columns"] == ["alpha", "Mkt-RF", "SMB", "HML"] and doc["window"] == 36
    assert len(doc["rows"]) >= 80 and doc["rows"][0]["index"].startswith("2018-01")
    bad = cli("analyze", "factors", "--tickers", "AAPL", "MSFT", "--rolling", "36", *WINDOW)
    assert bad.exit_code == 2 and "single ticker" in bad.stderr


def test_minimum_sample_is_an_insufficient_data_error(cli: Callable[..., Any]) -> None:
    short = cli(
        "analyze",
        "factors",
        "AAPL",
        "--start",
        "2023-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
    )
    assert short.exit_code == 5
    assert "monthly observations available, 36 required" in short.stderr


def test_exactly_one_universe_form(cli: Callable[..., Any]) -> None:
    neither = cli("analyze", "factors", *WINDOW)
    assert neither.exit_code == 2 and "exactly one of" in neither.stderr
    both = cli("analyze", "factors", "AAPL", "--tickers", "MSFT", *WINDOW)
    assert both.exit_code == 2
    saved = cli("portfolio", "save", "core", "--tickers", "AAPL", "MSFT")
    assert saved.exit_code == 0
    doc = _json(cli("analyze", "factors", "--portfolio", "core", *WINDOW, "--format", "json"))
    assert [r["ticker"] for r in doc["rows"]] == ["AAPL", "MSFT"]
