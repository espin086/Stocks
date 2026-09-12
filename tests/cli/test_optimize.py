"""``sobres optimize`` — the four subcommands through the real CLI on fixtures.

Scenarios: Markowitz; Frontier; Backtest; Risk panel of a given portfolio;
Weights supplied must be valid; Single currency needs no ceremony; Mixed
currencies require a base; Conversion precedes estimation; Results name their
base; Concentration warning; Insufficient lookback; Sharpe ratio definition;
Survivorship is stated, not hidden; In-sample results are labelled as such.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any

import pytest

from sobres.cli.commands.optimize import parse_lookback
from sobres.core.errors import UsageError
from tests.conftest import SENTINEL_KEY

BASE = ["--start", "2019-01-01", "--end", "2020-12-31", "--fill", "ffill"]
TICKERS = ["--tickers", "AAPL", "MSFT", "JNJ", "XOM"]


def test_header_names_estimators(cli: Callable[..., Any]) -> None:
    result = cli("optimize", "markowitz", *TICKERS, *BASE, "--format", "table")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert "mean_historical expected returns, ledoit_wolf covariance, shrinkage" in out
    assert "objective: max_sharpe" in out and "sharpe" in out
    assert "survivorship:" in out and "in-sample:" in out and "seed: 0" in out
    assert "For research and education only. Not investment advice." in out
    doc = json.loads(cli("optimize", "markowitz", *TICKERS, *BASE, "--format", "json").stdout)
    weights = {r["ticker"]: r["weight"] for r in doc["rows"]}
    assert abs(sum(weights.values()) - 1) < 1e-8 and all(w >= -1e-9 for w in weights.values())
    assert doc["estimators"]["covariance"] == "ledoit_wolf"
    assert doc["provenance"]["currency"] == "USD"


def test_objectives_and_constraints_reach_the_solver(cli: Callable[..., Any]) -> None:
    capped = json.loads(
        cli(
            "optimize", "markowitz", *TICKERS, *BASE, "--max-weight", "0.3", "--format", "json"
        ).stdout
    )
    assert max(r["weight"] for r in capped["rows"]) <= 0.3 + 1e-8
    minvar = json.loads(
        cli(
            "optimize",
            "markowitz",
            *TICKERS,
            *BASE,
            "--objective",
            "min_variance",
            "--format",
            "json",
        ).stdout
    )
    assert minvar["objective"] == "min_variance"
    infeasible = cli("optimize", "markowitz", *TICKERS, *BASE, "--max-weight", "0.1")
    assert infeasible.exit_code == 2 and "infeasible" in infeasible.stderr
    too_high = cli(
        "optimize", "markowitz", *TICKERS, *BASE, "--objective", "target_return", "--target", "5"
    )
    assert too_high.exit_code == 5 and "attainable" in too_high.stderr


def test_concentration_warning_reaches_stderr(cli: Callable[..., Any]) -> None:
    result = cli("optimize", "markowitz", "--tickers", "AAPL", "GLD", *BASE, "--format", "json")
    doc = json.loads(result.stdout)
    if max(r["weight"] for r in doc["rows"]) > 0.5:
        assert "--max-weight" in "".join(doc["warnings"])
        assert "optimize.concentration" in result.stderr


def test_csv_columns_are_ret_vol_sharpe_then_tickers(cli: Callable[..., Any]) -> None:
    result = cli("optimize", "frontier", *TICKERS, *BASE, "--points", "8", "--format", "csv")
    assert result.exit_code == 0, result.stderr
    header = result.stdout.splitlines()[0]
    assert header == "ret,vol,sharpe,AAPL,MSFT,JNJ,XOM,min_variance,max_sharpe"
    assert len(result.stdout.splitlines()) == 1 + 9  # 8 points plus the max-Sharpe point
    doc = json.loads(
        cli("optimize", "frontier", *TICKERS, *BASE, "--points", "5", "--format", "json").stdout
    )
    vols = [r["vol"] for r in doc["rows"]]
    assert all(b >= a - 1e-8 for a, b in itertools.pairwise(vols))
    assert sum(r["min_variance"] for r in doc["rows"]) == 1


def test_output_states_oos_window_and_costs(cli: Callable[..., Any]) -> None:
    result = cli(
        "optimize",
        "backtest",
        *TICKERS,
        "--start",
        "2017-01-01",
        "--end",
        "2020-12-31",
        "--fill",
        "ffill",
        "--lookback",
        "12m",
        "--rebalance",
        "quarterly",
        "--format",
        "table",
    )
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert "out-of-sample window: 2017-01-0" in out  # history before --start feeds the lookback
    assert "transaction costs 10 bps" in out and "total cost" in out
    assert "strategy" in out and "benchmark" in out and "sharpe" in out
    assert "why-your-backtest-looks-too-good" in out
    assert "backtest.progress" not in out
    doc = json.loads(
        cli(
            "optimize",
            "backtest",
            *TICKERS,
            "--start",
            "2017-01-01",
            "--end",
            "2020-12-31",
            "--fill",
            "ffill",
            "--lookback",
            "12m",
            "--format",
            "json",
        ).stdout
    )
    assert doc["n_rebalances"] >= 10 and doc["cost_bps"] == 10
    assert set(doc["equity_curve"]) == set(doc["benchmark_curve"])
    assert doc["shifted_start"] is False
    shifted = json.loads(
        cli(
            "optimize",
            "backtest",
            *TICKERS,
            "--start",
            "2015-06-01",
            "--end",
            "2017-12-31",
            "--fill",
            "ffill",
            "--lookback",
            "12m",
            "--format",
            "json",
        ).stdout
    )  # the fixture's history starts 2015-01-02: a 12-month lookback cannot reach back from June
    assert shifted["shifted_start"] is True and shifted["oos_start"] > "2015-06-01"


def test_backtest_lookback_parsing_and_short_data(cli: Callable[..., Any]) -> None:
    assert parse_lookback("36m", "daily") == 756 and parse_lookback("3y", "monthly") == 36
    assert parse_lookback("500", "daily") == 500 and parse_lookback("1m", "monthly") == 2
    with pytest.raises(UsageError):
        parse_lookback("soon", "daily")
    result = cli(
        "optimize",
        "backtest",
        *TICKERS,
        "--start",
        "2015-02-01",
        "--end",
        "2015-03-31",
        "--fill",
        "ffill",
        "--lookback",
        "36m",
    )  # the fixture history begins 2015-01-02: three years of lookback cannot exist
    assert result.exit_code == 5


def test_risk_panel_of_a_fixed_portfolio(cli: Callable[..., Any]) -> None:
    result = cli(
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "MSFT",
        "--weights",
        "0.6",
        "0.4",
        *BASE,
        "--format",
        "json",
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    metrics = {r["metric"]: r["value"] for r in doc["rows"]}
    assert {
        "annualized_return",
        "volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
        "var_95",
        "cvar_95",
    } <= set(metrics)
    assert doc["weights"] == {"AAPL": 0.6, "MSFT": 0.4}
    assert metrics["sharpe"] == pytest.approx(
        (metrics["annualized_return"] - 0.0) / metrics["volatility"]
    )
    table = cli(
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "MSFT",
        "--weights",
        "0.6",
        "0.4",
        *BASE,
        "--format",
        "table",
    )
    assert "weights: AAPL 0.6000, MSFT 0.4000" in table.stdout


def test_weights_must_match_ticker_count_and_sum_to_one(cli: Callable[..., Any]) -> None:
    wrong_count = cli("optimize", "risk", "--tickers", "AAPL", "MSFT", "--weights", "1.0", *BASE)
    assert wrong_count.exit_code == 2 and "1 weights for 2 tickers" in wrong_count.stderr
    wrong_sum = cli(
        "optimize", "risk", "--tickers", "AAPL", "MSFT", "--weights", "0.6", "0.6", *BASE
    )
    assert wrong_sum.exit_code == 2 and "sum to 1.200000" in wrong_sum.stderr


def test_fill_policy_has_no_default(cli: Callable[..., Any]) -> None:
    result = cli("optimize", "markowitz", *TICKERS, "--start", "2019-01-01")
    assert result.exit_code == 2 and "fill" in result.stderr


def test_mixed_currencies_require_a_base_and_convert_before_estimation(
    cli: Callable[..., Any],
) -> None:
    mixed = cli("optimize", "markowitz", "--tickers", "AAPL", "VOD.L", *BASE)
    assert (
        mixed.exit_code == 2
        and "GBP" in mixed.stderr
        and "USD" in mixed.stderr
        and "--base" in mixed.stderr
    )
    result = cli(
        "-v",
        "optimize",
        "markowitz",
        "--tickers",
        "AAPL",
        "VOD.L",
        *BASE,
        "--base",
        "USD",
        "--format",
        "json",
    )
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["currency"] == "USD" and doc["provenance"]["currency"] == "USD"
    assert any("converted to USD from GBP, USD" in n for n in doc["provenance"]["notes"])
    assert any("specific to this base" in n for n in doc["provenance"]["notes"])
    assert "currency.converted" in result.stderr
    # A single-currency run never touches the FX provider.
    single = cli("-vv", "optimize", "markowitz", *TICKERS, *BASE, "--format", "json")
    assert "provider.get_rates" not in single.stderr and '"dataset": "fx"' not in single.stderr


def test_risk_free_from_fred_when_configured(cli: Callable[..., Any]) -> None:
    without = json.loads(cli("optimize", "markowitz", *TICKERS, *BASE, "--format", "json").stdout)
    assert without["risk_free"] == 0.0
    assert any("0.0 fallback" in n for n in without["provenance"]["notes"])
    with_key = json.loads(
        cli(
            "optimize",
            "markowitz",
            *TICKERS,
            *BASE,
            "--format",
            "json",
            env_extra={"SOBRES_FRED_API_KEY": SENTINEL_KEY},
        ).stdout
    )
    assert with_key["risk_free"] > 0 and any(
        "FRED DTB3" in n for n in with_key["provenance"]["notes"]
    )
    given = json.loads(
        cli(
            "optimize", "markowitz", *TICKERS, *BASE, "--risk-free", "0.03", "--format", "json"
        ).stdout
    )
    assert given["risk_free"] == 0.03
