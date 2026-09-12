"""``sobres econ`` end to end, offline.

Scenarios: Tests reported; ACF and PACF; Stationarity is enforced before
fitting; Order selection is transparent; Intervals are mandatory; Residual
diagnostics; GARCH fit; Annualized output; Robust standard errors;
Multicollinearity; Diagnostics reported; Missing extra.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from sobres.core.timeseries import ECON_HINT
from tests.conftest import SENTINEL_KEY

pytest.importorskip("statsmodels")
pytest.importorskip("arch")
KEY = {"SOBRES_FRED_API_KEY": SENTINEL_KEY}
WINDOW = ["--start", "2015-01-01", "--end", "2024-12-31"]


def _json(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_diagnose_reports_both_tests_and_the_acf_pacf_table(cli: Callable[..., Any]) -> None:
    doc = _json(cli("econ", "diagnose", "DEXUSEU", *WINDOW, "--format", "json", env_extra=KEY))
    assert doc["adf"]["conclusion"] in ("stationary", "non-stationary")
    assert doc["kpss"]["conclusion"] in ("stationary", "non-stationary")
    assert isinstance(doc["agree"], bool) and doc["verdict"]
    assert [r["lag"] for r in doc["rows"]] == list(range(1, 21))
    assert all(
        {"acf", "pacf", "acf_significant", "pacf_significant"} <= set(r) for r in doc["rows"]
    )
    table = cli("econ", "diagnose", "DEXUSEU", *WINDOW, "--format", "table", env_extra=KEY)
    assert "ADF (H0 unit root)" in table.stdout and "KPSS (H0 stationary)" in table.stdout
    assert "significance bound" in table.stdout
    if not doc["agree"]:
        assert "the tests disagree" in table.stdout
    ticker = _json(cli("econ", "diagnose", "ticker:AAPL", *WINDOW, "--format", "json"))
    assert ticker["series"] == "AAPL"


def test_forecast_enforces_stationarity_and_reports_the_selection(cli: Callable[..., Any]) -> None:
    doc = _json(
        cli(
            "econ",
            "forecast",
            "CPIAUCSL",
            "--horizon",
            "6",
            "--max-p",
            "1",
            "--max-q",
            "1",
            *WINDOW,
            "--format",
            "json",
            env_extra=KEY,
        )
    )
    assert doc["d_reported"] >= 1 and doc["order"][1] == doc["d_reported"]  # a price level is I(1)
    assert doc["criterion"] == "aic" and len(doc["candidates"]) == 3
    assert doc["candidates"][0]["order"] == doc["order"]
    assert doc["candidates"][0]["aic"] <= doc["candidates"][1]["aic"] <= doc["candidates"][2]["aic"]
    table = cli(
        "econ",
        "forecast",
        "CPIAUCSL",
        "--horizon",
        "6",
        "--max-p",
        "1",
        "--max-q",
        "1",
        *WINDOW,
        "--format",
        "table",
        env_extra=KEY,
    )
    assert "selected by aic:" in table.stdout and "differenced d=" in table.stdout
    assert "Ljung-Box on residuals" in table.stdout
    fixed = _json(
        cli(
            "econ",
            "forecast",
            "CPIAUCSL",
            "--horizon",
            "3",
            "--order",
            "1,1,0",
            *WINDOW,
            "--format",
            "json",
            env_extra=KEY,
        )
    )
    assert fixed["order"] == [1, 1, 0] and len(fixed["candidates"]) == 1
    bad = cli("econ", "forecast", "CPIAUCSL", "--order", "1,1", *WINDOW, env_extra=KEY)
    assert bad.exit_code == 2 and "p,d,q" in bad.stderr


def test_intervals_are_mandatory_in_every_format(cli: Callable[..., Any]) -> None:
    args = ["econ", "forecast", "CPIAUCSL", "--horizon", "4", "--order", "0,1,1", *WINDOW]
    doc = _json(cli(*args, "--format", "json", env_extra=KEY))
    assert doc["columns"] == ["forecast", "lower80", "upper80", "lower95", "upper95"]
    for row in doc["rows"]:
        assert (
            row["lower95"] <= row["lower80"] <= row["forecast"] <= row["upper80"] <= row["upper95"]
        )
    csv = cli(*args, "--format", "csv", env_extra=KEY)
    assert csv.stdout.splitlines()[0] == "date,forecast,lower80,upper80,lower95,upper95"
    table = cli(*args, "--format", "table", env_extra=KEY)
    assert "lower95" in table.stdout and "upper95" in table.stdout
    assert "not a prediction on its own" in table.stdout


def test_volatility_is_annualized_with_intervals_and_a_printed_seed(
    cli: Callable[..., Any],
) -> None:
    args = [
        "econ",
        "volatility",
        "AAPL",
        "--horizon",
        "5",
        "--simulations",
        "150",
        "--start",
        "2022-01-01",
        "--end",
        "2024-12-31",
    ]
    doc = _json(cli(*args, "--seed", "1", "--format", "json"))
    assert doc["model"] == "garch" and doc["seed"] == 1 and doc["frequency"] == "daily"
    assert set(doc["params"]) >= {"omega", "alpha[1]", "beta[1]"}
    assert doc["columns"] == ["volatility", "lower80", "upper80", "lower95", "upper95"]
    assert 0.05 < doc["rows"][0]["volatility"] < 1.0  # annualized, not a daily number
    table = cli(*args, "--seed", "1", "--format", "table")
    assert "volatility is annualized" in table.stdout and "seed 1" in table.stdout
    auto = _json(cli(*args, "--format", "json"))
    assert isinstance(auto["seed"], int)
    for model in ("egarch", "ewma"):
        alt = _json(cli(*args, "--model", model, "--seed", "2", "--format", "json"))
        assert alt["model"] == model and len(alt["rows"]) == 5


def test_regress_names_the_covariance_and_reports_vif_and_diagnostics(
    cli: Callable[..., Any],
) -> None:
    base = [
        "econ",
        "regress",
        "--y",
        "AAPL",
        "--x",
        "MSFT",
        "fred:DEXUSEU",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
    ]
    doc = _json(cli(*base, "--format", "json", env_extra=KEY))
    assert doc["robust"] == "hac" and isinstance(doc["hac_lags"], int)
    assert [r["term"] for r in doc["rows"]] == ["const", "MSFT", "DEXUSEU"]
    assert set(doc["vif"]) == {"MSFT", "DEXUSEU"} and isinstance(doc["vif_flags"], list)
    for key in ("r2", "adj_r2", "f_statistic", "f_pvalue", "durbin_watson"):
        assert key in doc
    assert {"statistic", "pvalue"} <= set(doc["breusch_pagan"])
    assert doc["transforms"] == {
        "AAPL": "simple returns",
        "MSFT": "simple returns",
        "DEXUSEU": "first differences",
    }
    table = cli(*base, "--format", "table", env_extra=KEY)
    assert "HAC (Newey-West" in table.stdout and "VIF:" in table.stdout
    assert "Durbin-Watson" in table.stdout and "Breusch-Pagan" in table.stdout
    for kind in ("hc0", "hc3", "none"):
        out = cli(*base, "--robust", kind, "--format", "table", env_extra=KEY)
        assert out.exit_code == 0
        assert ("classical OLS" in out.stdout) if kind == "none" else (kind.upper() in out.stdout)
    assert cli(*base, "--robust", "bootstrap", env_extra=KEY).exit_code == 2
    twice = cli(
        "econ",
        "regress",
        "--y",
        "AAPL",
        "--x",
        "MSFT",
        "MSFT",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        env_extra=KEY,
    )
    assert twice.exit_code == 2 and "appears twice" in twice.stderr


def test_missing_extra_exits_3_with_the_install_hint(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.core import timeseries as ts
    from sobres.core.errors import ConfigurationError

    def absent() -> None:
        raise ConfigurationError(ECON_HINT)

    monkeypatch.setattr(ts, "require_econ", absent)
    result = cli("econ", "diagnose", "DEXUSEU", *WINDOW, env_extra=KEY)
    assert result.exit_code == 3
    assert (
        "This command needs the econ extra. Install it with: pip install 'sobres[econ]'"
        in result.stderr
    )
    assert "Traceback" not in result.stderr and "ImportError" not in result.stderr
