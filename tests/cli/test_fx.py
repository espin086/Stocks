"""``sobres fx`` end to end, offline.

Scenarios: Per-asset attribution; Risk decomposition; Correlation is not
assumed away; Net currency exposure; Assumptions are stated at the point of
use; Comparison; Missing rate data; Base currency is explicit; FX risk reaches
the covariance matrix; Hedged optimization; Rates; Conversion; No forecasting
surface; The cross term is reported, not hidden.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sobres.registry import all_commands
from tests.conftest import SENTINEL_KEY

KEY = {"SOBRES_FRED_API_KEY": SENTINEL_KEY}
UNIVERSE = [
    "--tickers",
    "AAPL",
    "VOD.L",
    "--base",
    "USD",
    "--start",
    "2020-01-01",
    "--end",
    "2024-12-31",
    "--fill",
    "drop",
]


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_rates_and_conversion_state_source_and_carry_forward(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "fx",
            "rates",
            "EURUSD",
            "GBPUSD",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-10",
            "--format",
            "json",
        )
    )
    assert doc["columns"] == ["EURUSD", "GBPUSD"] and doc["provenance"]["provider"] == "ecb"
    conv = _json(
        cli(
            "fx",
            "convert",
            "1000",
            "--from",
            "USD",
            "--to",
            "GBP",
            "--on",
            "2024-06-01",
            "--format",
            "json",
        )
    )
    assert conv["converted"] == conv["amount"] * conv["rate"]
    assert conv["carried_forward_from"] == "2024-05-31"  # a Saturday: the Friday quote, stated
    table = cli(
        "fx",
        "convert",
        "1000",
        "--from",
        "USD",
        "--to",
        "GBP",
        "--on",
        "2024-06-01",
        "--format",
        "table",
    )
    assert "carried forward from 2024-05-31" in table.stdout and "reference rates" in table.stdout
    same = _json(
        cli(
            "fx",
            "convert",
            "5",
            "--from",
            "USD",
            "--to",
            "USD",
            "--on",
            "2024-06-03",
            "--format",
            "json",
        )
    )
    assert same["converted"] == 5.0 and same["rate"] == 1.0


def test_per_asset_attribution_with_a_portfolio_row_and_the_cross_term(
    cli: Callable[..., Any],
) -> None:
    doc = _json(cli("fx", "attribution", *UNIVERSE, "--format", "json"))
    rows = {r["ticker"]: r for r in doc["rows"]}
    assert list(rows) == ["AAPL", "VOD.L", "portfolio"]
    assert rows["AAPL"]["currency"] == "USD" and rows["AAPL"]["fx"] == 0.0
    assert rows["VOD.L"]["currency"] == "GBP" and rows["VOD.L"]["fx"] != 0.0
    for r in doc["rows"]:
        assert r["total"] - (r["local"] + r["fx"] + r["cross"]) < 1e-12  # reconciles, cross shown
    assert doc["columns"] == ["ticker", "currency", "local", "fx", "cross", "total", "weight"]
    risk = doc["risk"]
    assert risk["exposures"] == {"USD": 0.5, "GBP": 0.5}
    assert risk["correlations"]["VOD.L"] is not None and risk["correlations"]["AAPL"] is None
    assert risk["total_volatility"] - risk["local_volatility"] == risk["currency_contribution"]
    table = cli("fx", "attribution", *UNIVERSE, "--format", "table")
    assert "currencies held fixed" in table.stdout and "not additive" in table.stdout
    assert "net currency exposure" in table.stdout and "cross term shown on its own" in table.stdout
    weighted = _json(
        cli("fx", "attribution", *UNIVERSE, "--weights", "0.8", "0.2", "--format", "json")
    )
    assert weighted["risk"]["exposures"] == {"USD": 0.8, "GBP": 0.2}


def test_hedge_comparison_states_its_assumptions_and_needs_both_legs(
    cli: Callable[..., Any],
) -> None:
    doc = _json(cli("fx", "hedge", *UNIVERSE, "--format", "json", env_extra=KEY))
    assert doc["columns"] == ["metric", "hedged", "unhedged"]
    metrics = {r["metric"]: r for r in doc["rows"]}
    assert "sharpe" in metrics and "max_drawdown" in metrics  # the 0002 panel, side by side
    assert doc["rates_used"] == {"USD": "DTB3", "GBP": "IR3TIB01GBM156N"}
    assert isinstance(doc["hedge_effect"], float)
    table = cli("fx", "hedge", *UNIVERSE, "--format", "table", env_extra=KEY)
    assert "excluding transaction costs, bid-ask spread and basis" in table.stdout
    assert "not an achievable realized return" in table.stdout
    assert "cumulative hedged minus unhedged" in table.stdout
    missing = cli(
        "fx",
        "hedge",
        "--tickers",
        "AAPL",
        "VOD.L",
        "--base",
        "JPY",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
        env_extra=KEY,
    )
    assert (
        missing.exit_code == 5 and "JPY" in missing.stderr and "IR3TIB01JPM156N" in missing.stderr
    )
    assert cli("fx", "hedge", *UNIVERSE, "--compare", "hedged", env_extra=KEY).exit_code == 2


def test_base_currency_is_explicit_and_hedged_optimization_is_labelled(
    cli: Callable[..., Any],
) -> None:
    mixed = cli(
        "optimize",
        "markowitz",
        "--tickers",
        "AAPL",
        "VOD.L",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
    )
    assert mixed.exit_code == 2 and "--base" in mixed.stderr
    based = _json(
        cli(
            "optimize",
            "markowitz",
            "--tickers",
            "AAPL",
            "VOD.L",
            "--base",
            "USD",
            "--start",
            "2020-01-01",
            "--end",
            "2024-12-31",
            "--fill",
            "drop",
            "--format",
            "json",
        )
    )
    assert based["currency"] == "USD"
    assert any("optimum is specific to this base" in n for n in based["provenance"]["notes"])
    hedged = cli(
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "VOD.L",
        "--weights",
        "0.5",
        "0.5",
        "--base",
        "USD",
        "--hedged",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
        "--format",
        "table",
        env_extra=KEY,
    )
    assert hedged.exit_code == 0, hedged.stderr
    assert "hedged returns:" in hedged.stdout and "covered interest parity" in hedged.stdout
    single = cli(
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "MSFT",
        "--weights",
        "0.5",
        "0.5",
        "--hedged",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
    )
    assert single.exit_code == 2 and "outside the base currency" in single.stderr


def test_fx_risk_reaches_the_covariance_matrix(cli: Callable[..., Any]) -> None:
    usd = _json(
        cli(
            "optimize",
            "risk",
            "--tickers",
            "AAPL",
            "VOD.L",
            "--weights",
            "0.5",
            "0.5",
            "--base",
            "USD",
            "--start",
            "2020-01-01",
            "--end",
            "2024-12-31",
            "--fill",
            "drop",
            "--format",
            "json",
        )
    )
    gbp = _json(
        cli(
            "optimize",
            "risk",
            "--tickers",
            "AAPL",
            "VOD.L",
            "--weights",
            "0.5",
            "0.5",
            "--base",
            "GBP",
            "--start",
            "2020-01-01",
            "--end",
            "2024-12-31",
            "--fill",
            "drop",
            "--format",
            "json",
        )
    )
    vol = lambda doc: next(r["value"] for r in doc["rows"] if r["metric"] == "volatility")  # noqa: E731
    assert vol(usd) != vol(gbp)  # the currency co-movement is in the moments, so the base matters


def test_no_forecasting_surface() -> None:
    names = [c.name for c in all_commands() if c.name.startswith(("fx.", "ppp."))]
    assert names and not any(
        word in n
        for n in names
        for word in ("forecast", "predict", "project", "signal", "recommend")
    )
    for c in all_commands():
        if c.name.startswith(("fx.", "ppp.")):
            assert not any(w in c.help.lower() for w in ("forecast", "predict", "recommend"))
