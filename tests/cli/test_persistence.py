"""``sobres portfolio``, ``watchlist``, ``run`` and ``db`` through the real CLI.

Scenarios: Save; Weights are optional; Use a saved portfolio anywhere tickers
are accepted; Name collision; Listing and deletion; Watchlist; Saved goals;
Recording a run; Resolved parameters, not raw argv; Inspecting runs; Comparing
runs; Runs are not promises of reproducibility; Inspect; Export; Cache and user
data are never conflated; Destructive operations confirm; Repair;
Backend-agnostic repositories; New repositories join the conformance suite;
Switching backends is configuration; Repositories perform no computation;
Operations are logged and spanned; One file is the whole state; The same file
works in a container; Post-upgrade migration.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

OPT = ["--start", "2019-01-01", "--end", "2019-12-31", "--fill", "ffill"]


def test_save_list_show_delete_and_collision(cli: Callable[..., Any]) -> None:
    saved = cli("portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--weights", "0.6", "0.4")
    assert saved.exit_code == 0 and "2 holdings (weighted)" in saved.stdout
    listing = json.loads(cli("portfolio", "list", "--format", "json").stdout)["rows"]
    assert listing[0]["name"] == "core" and listing[0]["holdings"] == 2 and listing[0]["weighted"]
    shown = json.loads(cli("portfolio", "show", "core", "--format", "json").stdout)["rows"]
    assert shown == [{"ticker": "AAPL", "weight": 0.6}, {"ticker": "MSFT", "weight": 0.4}]
    clash = cli("portfolio", "save", "core", "--tickers", "AAPL")
    assert (
        clash.exit_code == 2
        and "'core' already exists" in clash.stderr
        and "--force" in clash.stderr
    )
    forced = cli("portfolio", "save", "core", "--tickers", "AAPL", "JNJ", "--force")
    assert forced.exit_code == 0 and "unweighted universe" in forced.stdout
    declined = cli("portfolio", "delete", "core", input="n\n")
    assert declined.exit_code == 2 and "cancelled" in declined.stderr
    assert cli("portfolio", "delete", "core", "--yes").exit_code == 0
    assert cli("portfolio", "show", "core").exit_code == 2
    assert cli("portfolio", "delete", "core", "--yes").exit_code == 2


def test_weights_validated_before_anything_is_written(cli: Callable[..., Any]) -> None:
    bad = cli("portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--weights", "0.7", "0.4")
    assert bad.exit_code == 2 and "sum to 1.100000" in bad.stderr
    count = cli("portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--weights", "1.0")
    assert count.exit_code == 2 and "1 weights for 2 tickers" in count.stderr
    assert json.loads(cli("portfolio", "list", "--format", "json").stdout)["rows"] == []


def test_portfolio_substitutes_for_tickers(cli: Callable[..., Any]) -> None:
    cli(
        "portfolio",
        "save",
        "core",
        "--tickers",
        "AAPL",
        "MSFT",
        "JNJ",
        "--weights",
        "0.5",
        "0.3",
        "0.2",
    )
    both = cli("optimize", "markowitz", "--portfolio", "core", "--tickers", "AAPL", *OPT)
    assert both.exit_code == 2 and "mutually exclusive" in both.stderr
    neither = cli("optimize", "markowitz", *OPT)
    assert neither.exit_code == 2 and "one of --tickers or --portfolio" in neither.stderr
    missing = cli("optimize", "markowitz", "--portfolio", "nope", *OPT)
    assert missing.exit_code == 2 and "no portfolio named 'nope'" in missing.stderr
    result = json.loads(
        cli("optimize", "markowitz", "--portfolio", "core", *OPT, "--format", "json").stdout
    )
    assert [r["ticker"] for r in result["rows"]] == ["AAPL", "MSFT", "JNJ"]
    risk = json.loads(
        cli("optimize", "risk", "--portfolio", "core", *OPT, "--format", "json").stdout
    )
    assert risk["weights"] == {"AAPL": 0.5, "MSFT": 0.3, "JNJ": 0.2}
    frontier = cli(
        "optimize", "frontier", "--portfolio", "core", *OPT, "--points", "3", "--format", "csv"
    )
    assert frontier.stdout.splitlines()[0].startswith("ret,vol,sharpe,AAPL,MSFT,JNJ")
    cli("portfolio", "save", "bare", "--tickers", "AAPL", "MSFT")
    no_weights = cli("optimize", "risk", "--portfolio", "bare", *OPT)
    assert no_weights.exit_code == 2 and "has no weights" in no_weights.stderr
    needs = cli("optimize", "risk", "--tickers", "AAPL", *OPT)
    assert needs.exit_code == 2 and "--weights is required" in needs.stderr


def test_watchlist_round_trip(cli: Callable[..., Any]) -> None:
    first = cli("watchlist", "add", "tech", "nvda", "AMD")
    assert first.exit_code == 0 and "added 2, now 2" in first.stdout
    again = cli("watchlist", "add", "tech", "AMD", "INTC")
    assert "added 1, now 3" in again.stdout
    shown = json.loads(cli("watchlist", "show", "tech", "--format", "json").stdout)["rows"]
    assert [r["symbol"] for r in shown] == ["NVDA", "AMD", "INTC"]
    assert (
        json.loads(cli("watchlist", "list", "--format", "json").stdout)["rows"][0]["symbols"] == 3
    )
    assert "now 2 symbols" in cli("watchlist", "remove", "tech", "AMD").stdout
    assert cli("watchlist", "remove", "nope", "X").exit_code == 2
    assert cli("watchlist", "show", "nope").exit_code == 2
    assert cli("watchlist", "delete", "tech", input="n\n").exit_code == 2
    assert cli("watchlist", "delete", "tech", "--yes").exit_code == 0
    assert cli("watchlist", "delete", "tech", "--yes").exit_code == 2


def test_save_run_records_resolved_parameters(cli: Callable[..., Any]) -> None:
    result = cli(
        "optimize", "markowitz", "--tickers", "AAPL", "MSFT", *OPT, "--save-run", "--format", "json"
    )
    assert result.exit_code == 0 and "saved run " in result.stderr
    run_id = result.stderr.split("saved run ")[1].split(" ")[0]
    listing = json.loads(cli("run", "list", "--format", "json").stdout)
    assert (
        listing["rows"][0]["id"] == run_id and listing["rows"][0]["command"] == "optimize.markowitz"
    )
    assert listing["rows"][0]["summary"].startswith("objective: max_sharpe")
    shown = json.loads(cli("run", "show", run_id, "--format", "json").stdout)
    run = shown["run"]
    assert run["params"]["covariance"] == "ledoit_wolf"  # a default, resolved and stored
    assert run["params"]["objective"] == "max_sharpe" and "save_run" not in run["params"]
    assert run["estimators"]["covariance"] == "ledoit_wolf"
    assert run["window"] == {"start": "2019-01-03", "end": "2019-12-31"}
    assert run["result"]["rows"] and "revised" in shown["note"]
    table = cli("run", "show", run_id, "--format", "table")
    assert "revised" in table.stdout
    assert "revised" in cli("run", "list", "--format", "table").stdout


def test_run_diff_and_delete(cli: Callable[..., Any]) -> None:
    def save(*extra: str) -> str:
        out = cli("optimize", "markowitz", "--tickers", "AAPL", "MSFT", *OPT, *extra, "--save-run")
        return out.stderr.split("saved run ")[1].split(" ")[0]

    a = save()
    b = save("--objective", "min_variance")
    diff = json.loads(cli("run", "diff", a, b, "--format", "json").stdout)["rows"]
    assert {"section": "params", "key": "objective", "a": "max_sharpe", "b": "min_variance"} in diff
    assert any(r["section"] == "result" for r in diff)
    risk = cli(
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "MSFT",
        "--weights",
        "0.5",
        "0.5",
        *OPT,
        "--save-run",
    )
    c = risk.stderr.split("saved run ")[1].split(" ")[0]
    mismatch = cli("run", "diff", a, c)
    assert mismatch.exit_code == 2 and "different commands" in mismatch.stderr
    assert cli("run", "show", "zzz").exit_code == 2
    assert cli("run", "delete", a, input="n\n").exit_code == 2
    assert cli("run", "delete", a, "--yes").exit_code == 0
    assert cli("run", "show", a).exit_code == 2
    only = json.loads(cli("run", "list", "--command", "optimize.risk", "--format", "json").stdout)[
        "rows"
    ]
    assert [r["id"] for r in only] == [c]


def test_db_info_export_and_repair(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    cli("portfolio", "save", "core", "--tickers", "AAPL")
    info = {
        r["item"]: r["value"]
        for r in json.loads(cli("db", "info", "--format", "json").stdout)["rows"]
    }
    assert (
        info["backend"] == "sqlite" and info["schema_version"] == 2 and info["rows:portfolio"] == 1
    )
    assert info["location"].endswith("sobres.db") and info["size_bytes"] > 0
    dest = tmp_path / "backup" / "copy.sqlite"
    exported = cli("db", "export", "--to", str(dest))
    assert exported.exit_code == 0 and dest.exists()
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT count(*) FROM portfolio").fetchone()[0] == 1
    copy.close()
    assert cli("db", "export", "--to", str(dest)).exit_code == 2
    healthy = cli("db", "repair")
    assert healthy.exit_code == 0 and "nothing to repair" in healthy.stdout
    # Damage the file: repair recovers into a new file and leaves the original alone.
    path = Path(env["SOBRES_DB_URL"].removeprefix("sqlite:///"))
    for side in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        side.unlink(missing_ok=True)
    data = bytearray(path.read_bytes())
    data[4000:4100] = b"\xff" * 100
    path.write_bytes(data)
    broken = cli("portfolio", "list")
    assert broken.exit_code == 3 and "sobres db repair" in broken.stderr
    before = path.read_bytes()
    repaired = cli("db", "repair")
    assert repaired.exit_code == 0, repaired.stderr
    assert "recovered into" in repaired.stdout and "left in place" in repaired.stdout
    assert path.read_bytes() == before
    recovered = path.with_name(path.name + ".recovered")
    assert recovered.exists()
    assert cli("db", "repair").exit_code == 2  # the recovery target now exists


def test_cache_clear_reports_preserved_user_data(cli: Callable[..., Any]) -> None:
    cli("portfolio", "save", "core", "--tickers", "AAPL")
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    cleared = cli("cache", "clear", "--yes")
    assert "portfolios, goals and runs untouched" in cleared.stdout
    assert (
        json.loads(cli("portfolio", "list", "--format", "json").stdout)["rows"][0]["name"] == "core"
    )


def test_one_file_is_the_whole_state(
    cli: Callable[..., Any], env: dict[str, str], tmp_path: Path
) -> None:
    cli("portfolio", "save", "core", "--tickers", "AAPL")
    cli("watchlist", "add", "w", "MSFT")
    cli("data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31")
    moved = tmp_path / "elsewhere" / "sobres.db"
    cli("db", "export", "--to", str(moved))
    other = {"SOBRES_DB_URL": f"sqlite:///{moved.as_posix()}"}
    assert (
        json.loads(cli("portfolio", "list", "--format", "json", env_extra=other).stdout)["rows"][0][
            "name"
        ]
        == "core"
    )
    assert (
        json.loads(cli("watchlist", "list", "--format", "json", env_extra=other).stdout)["rows"][0][
            "name"
        ]
        == "w"
    )
    assert (
        json.loads(cli("cache", "info", "--format", "json", env_extra=other).stdout)["rows"][2][
            "value"
        ]
        > 0
    )


def test_repository_operations_are_logged(cli: Callable[..., Any]) -> None:
    result = cli("-vv", "portfolio", "save", "core", "--tickers", "AAPL")
    assert '"op": "portfolio_save"' in result.stderr and '"entity": "portfolio"' in result.stderr
