"""Record the figures the landing page animates by actually running sobres.

Every number on the page comes from here: a computed frontier, a walk-forward
backtest, an in-sample solve over the same window, and the terminal transcript
of ``sobres optimize markowitz``. Nothing is written by hand to look plausible.

    python site/scripts/record_figures.py            # against the repository's fixtures
    python site/scripts/record_figures.py --live     # against the providers (network)

The fixtures under ``tests/fixtures`` are synthesized random walks until live
recordings replace them (see tests/fixtures/README.md); ``figures-meta.json``
records which was used so the page can say so.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "site" / "src" / "data"
TICKERS = ["AAPL", "MSFT", "NVDA", "JNJ", "XOM", "GLD"]
WINDOW = ("2021-01-01", "2024-12-31")
FRONTIER_WINDOW = ("2020-01-01", "2024-12-31")
BACKTEST = {"lookback": "1y", "rebalance": "quarterly", "cost_bps": 10}


def run(env: dict[str, str], *args: str, fmt: str | None = "json") -> str:
    cmd = ["sobres", *args]
    if fmt:
        cmd += ["--format", fmt]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"{' '.join(cmd)} exited {result.returncode}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use the live providers")
    opts = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "SOBRES_CONFIG_FILE": f"{tmp}/config.toml",
            "SOBRES_DB_URL": f"sqlite:///{tmp}/sobres.db",
            "SOBRES_LOG_LEVEL": "ERROR",
        }
        if not opts.live:
            env["SOBRES_FIXTURE_DIR"] = str(REPO / "tests" / "fixtures")
        universe = ["--tickers", *TICKERS, "--fill", "drop"]
        frontier = json.loads(
            run(
                env,
                "optimize",
                "frontier",
                *universe,
                "--start",
                FRONTIER_WINDOW[0],
                "--end",
                FRONTIER_WINDOW[1],
            )
        )
        backtest = json.loads(
            run(
                env,
                "optimize",
                "backtest",
                *universe,
                "--start",
                WINDOW[0],
                "--end",
                WINDOW[1],
                "--lookback",
                BACKTEST["lookback"],
                "--rebalance",
                BACKTEST["rebalance"],
                "--cost-bps",
                str(BACKTEST["cost_bps"]),
            )
        )
        in_sample = json.loads(
            run(env, "optimize", "markowitz", *universe, "--start", WINDOW[0], "--end", WINDOW[1])
        )
        markowitz_args = [
            "optimize",
            "markowitz",
            *universe,
            "--start",
            FRONTIER_WINDOW[0],
            "--end",
            FRONTIER_WINDOW[1],
        ]
        transcript = run(env, *markowitz_args, fmt="table")

    (OUT / "frontier.json").write_text(
        json.dumps(
            {
                "columns": frontier["columns"],
                "rows": frontier["rows"],
                "estimators": frontier["estimators"],
            },
            indent=1,
        )
        + "\n"
    )
    metrics = {r["metric"]: r for r in backtest["rows"]}
    (OUT / "backtest.json").write_text(
        json.dumps(
            {
                "equity_curve": backtest["equity_curve"],
                "benchmark_curve": backtest["benchmark_curve"],
                "oos_start": backtest["oos_start"],
                "oos_end": backtest["oos_end"],
                "n_rebalances": backtest["n_rebalances"],
                "cost_bps": backtest["cost_bps"],
                "total_cost": backtest["total_cost"],
                "walk_forward_sharpe": metrics["sharpe"]["strategy"],
                "benchmark_sharpe": metrics["sharpe"]["benchmark"],
                "max_drawdown": metrics["max_drawdown"]["strategy"],
                "in_sample_sharpe": in_sample["sharpe"],
                "in_sample_return": in_sample["expected_return"],
                "in_sample_volatility": in_sample["volatility"],
            },
            indent=1,
        )
        + "\n"
    )
    (OUT / "terminal.txt").write_text(transcript)
    meta_path = REPO / "tests" / "fixtures" / "yfinance" / "meta.json"
    fixture_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    synthetic = not opts.live and fixture_meta.get("recorded_at") is None
    (OUT / "figures-meta.json").write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(UTC).isoformat(),
                "tickers": TICKERS,
                "frontier_window": list(FRONTIER_WINDOW),
                "backtest_window": list(WINDOW),
                "backtest": BACKTEST,
                "estimators": frontier["estimators"],
                "commands": {
                    "frontier": "sobres optimize frontier --tickers "
                    + " ".join(TICKERS)
                    + f" --start {FRONTIER_WINDOW[0]} --end {FRONTIER_WINDOW[1]} --fill drop",
                    "backtest": "sobres optimize backtest --tickers "
                    + " ".join(TICKERS)
                    + f" --start {WINDOW[0]} --end {WINDOW[1]} --fill drop"
                    + f" --lookback {BACKTEST['lookback']} --rebalance {BACKTEST['rebalance']}"
                    + f" --cost-bps {BACKTEST['cost_bps']}",
                    "markowitz": "sobres " + " ".join(markowitz_args),
                },
                "data_source": "live providers"
                if opts.live
                else "the repository's recorded fixtures",
                "synthetic": synthetic,
                "note": (
                    "the fixtures are synthesized random walks in the providers' payload shapes, "
                    "not market data; rerun with --live after recording live fixtures"
                    if synthetic
                    else "recorded from the providers named in the provenance"
                ),
            },
            indent=1,
        )
        + "\n"
    )
    print(f"recorded figures into {OUT} (synthetic={synthetic})")


if __name__ == "__main__":
    main()
