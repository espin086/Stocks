"""Invariants that must hold for every registered command — enumerated, not sampled.

Scenarios: Enumerated, not sampled; Required invariants; Instrumentation does
not change results; Machine output stays parseable; stdout is results only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from sobres.registry import all_commands
from tests.conftest import SENTINEL_KEY

# One runnable, offline invocation per command. A new command must add an entry
# here or ``test_every_command_has_a_sample`` fails.
SAMPLE_ARGS: dict[str, list[str]] = {
    "analyze.factors": [
        "analyze",
        "factors",
        "AAPL",
        "--start",
        "2015-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
    ],
    "analyze.stock": [
        "analyze",
        "stock",
        "AAPL",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
        "--fill",
        "drop",
    ],
    "cache.clear": ["cache", "clear", "--yes"],
    "cache.info": ["cache", "info"],
    "commands": ["commands"],
    "config.path": ["config", "path"],
    "config.set": ["config", "set", "log_level", "WARNING"],
    "config.show": ["config", "show"],
    "config.unset": ["config", "unset", "log_level"],
    "data.factors": [
        "data",
        "factors",
        "--model",
        "ff3",
        "--start",
        "2020-01-01",
        "--end",
        "2020-06-30",
    ],
    "data.fx": ["data", "fx", "EURUSD", "--start", "2020-01-01", "--end", "2020-01-31"],
    "data.macro": ["data", "macro", "DGS10", "--start", "2020-01-01", "--end", "2020-01-31"],
    "data.prices": [
        "data",
        "prices",
        "AAPL",
        "MSFT",
        "--start",
        "2020-01-01",
        "--end",
        "2020-01-31",
    ],
    "db.export": ["db", "export", "--to", "{tmp}/export.sqlite"],
    "db.info": ["db", "info"],
    "db.repair": ["db", "repair"],
    "deploy.check": ["deploy", "check", "--offline", "--host", "127.0.0.1"],
    "deploy.compose": ["deploy", "compose"],
    "deploy.env": ["deploy", "env"],
    "deploy.health": ["deploy", "health", "--port", "8799"],
    "doctor": ["doctor", "--offline"],
    "econ.diagnose": [
        "econ",
        "diagnose",
        "DEXUSEU",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
    ],
    "econ.forecast": [
        "econ",
        "forecast",
        "CPIAUCSL",
        "--horizon",
        "6",
        "--order",
        "1,1,0",
        "--start",
        "2015-01-01",
        "--end",
        "2024-12-31",
    ],
    "econ.regress": [
        "econ",
        "regress",
        "--y",
        "AAPL",
        "--x",
        "MSFT",
        "DGS10",
        "--start",
        "2020-01-01",
        "--end",
        "2024-12-31",
    ],
    "econ.volatility": [
        "econ",
        "volatility",
        "AAPL",
        "--horizon",
        "5",
        "--simulations",
        "100",
        "--seed",
        "1",
        "--start",
        "2022-01-01",
        "--end",
        "2024-12-31",
    ],
    "fx.attribution": [
        "fx",
        "attribution",
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
    ],
    "fx.convert": ["fx", "convert", "1000", "--from", "USD", "--to", "GBP", "--on", "2024-06-03"],
    "fx.hedge": [
        "fx",
        "hedge",
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
    ],
    "fx.rates": ["fx", "rates", "EURUSD", "GBPUSD", "--start", "2024-01-01", "--end", "2024-03-31"],
    "init": ["init", "--non-interactive", "--offline"],
    "open": ["open", "--print-url", "--port", "8797"],
    "optimize.backtest": [
        "optimize",
        "backtest",
        "--tickers",
        "AAPL",
        "MSFT",
        "JNJ",
        "--start",
        "2018-01-01",
        "--end",
        "2019-12-31",
        "--fill",
        "ffill",
        "--lookback",
        "6m",
        "--rebalance",
        "quarterly",
    ],
    "optimize.frontier": [
        "optimize",
        "frontier",
        "--tickers",
        "AAPL",
        "MSFT",
        "JNJ",
        "--start",
        "2019-01-01",
        "--end",
        "2019-12-31",
        "--fill",
        "ffill",
        "--points",
        "5",
    ],
    "optimize.markowitz": [
        "optimize",
        "markowitz",
        "--tickers",
        "AAPL",
        "MSFT",
        "JNJ",
        "--start",
        "2019-01-01",
        "--end",
        "2019-12-31",
        "--fill",
        "ffill",
    ],
    "optimize.risk": [
        "optimize",
        "risk",
        "--tickers",
        "AAPL",
        "MSFT",
        "--weights",
        "0.6",
        "0.4",
        "--start",
        "2019-01-01",
        "--end",
        "2019-12-31",
        "--fill",
        "ffill",
    ],
    "plan.car": [
        "plan",
        "car",
        "--price",
        "45000",
        "--by",
        "2027-01-01",
        "--simulate",
        "200",
        "--seed",
        "1",
    ],
    "plan.education": [
        "plan",
        "education",
        "--annual-cost",
        "35000",
        "--years",
        "4",
        "--starting",
        "2038",
        "--simulate",
        "200",
        "--seed",
        "1",
        "--seed",
        "1",
    ],
    "plan.goal": [
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
        "1",
        "--seed",
        "1",
    ],
    "plan.house": [
        "plan",
        "house",
        "--price",
        "950000",
        "--down-pct",
        "0.2",
        "--by",
        "2029-06-01",
        "--monthly",
        "3000",
        "--simulate",
        "200",
        "--seed",
        "1",
        "--seed",
        "1",
    ],
    "plan.retire": [
        "plan",
        "retire",
        "--income",
        "200000",
        "--expenses",
        "90000",
        "--portfolio",
        "400000",
        "--simulate",
        "200",
        "--seed",
        "1",
        "--seed",
        "1",
    ],
    "ppp.adjust_goal": [
        "ppp",
        "adjust-goal",
        "--target",
        "2100000",
        "--to",
        "PRT",
        "--on",
        "2024-06-03",
    ],
    "ppp.compare": [
        "ppp",
        "compare",
        "--base",
        "USD",
        "--vs",
        "EUR",
        "GBP",
        "JPY",
        "--on",
        "2024-06-03",
    ],
    "ppp.reer": ["ppp", "reer", "USA", "GBR", "--start", "2020-01-01", "--end", "2024-12-31"],
    "ppp.relative": ["ppp", "relative", "USDGBP", "--anchor", "2016-01-04", "--end", "2024-12-31"],
    "portfolio.delete": ["portfolio", "delete", "core", "--yes"],
    "portfolio.list": ["portfolio", "list"],
    "portfolio.save": ["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"],
    "portfolio.show": ["portfolio", "show", "core"],
    "run.delete": ["run", "delete", "{run}", "--yes"],
    "run.diff": ["run", "diff", "{run}", "{run}"],
    "run.list": ["run", "list"],
    "run.show": ["run", "show", "{run}"],
    "serve": ["serve", "--port", "8798"],
    "serve.token.rotate": ["serve", "token", "rotate"],
    "upgrade": ["upgrade", "--check"],
    "watchlist.add": ["watchlist", "add", "tech", "NVDA", "AMD"],
    "watchlist.delete": ["watchlist", "delete", "tech", "--yes"],
    "watchlist.list": ["watchlist", "list"],
    "watchlist.remove": ["watchlist", "remove", "tech", "AMD"],
    "watchlist.show": ["watchlist", "show", "tech"],
}
# Commands whose sample needs state that an earlier command creates.
PREPARE: dict[str, list[list[str]]] = {
    "cache.clear": [["data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31"]],
    "watchlist.add": [["watchlist", "delete", "tech", "--yes"]],
    "portfolio.show": [["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"]],
    "portfolio.delete": [["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"]],
    "watchlist.show": [["watchlist", "add", "tech", "NVDA"]],
    "watchlist.remove": [["watchlist", "add", "tech", "NVDA", "AMD"]],
    "watchlist.delete": [["watchlist", "add", "tech", "NVDA"]],
    "run.show": [["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"]],
    "run.diff": [["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"]],
    "run.delete": [["portfolio", "save", "core", "--tickers", "AAPL", "MSFT", "--force"]],
}
RUN_SAMPLE = [
    "optimize",
    "risk",
    "--tickers",
    "AAPL",
    "MSFT",
    "--weights",
    "0.6",
    "0.4",
    "--start",
    "2019-01-01",
    "--end",
    "2019-06-30",
    "--fill",
    "ffill",
    "--save-run",
    "--format",
    "json",
]
ENV = {"SOBRES_FRED_API_KEY": SENTINEL_KEY}


def test_every_command_has_a_sample() -> None:
    assert {c.name for c in all_commands()} == set(SAMPLE_ARGS)


def _prepare(name: str, cli: Callable[..., Any], tmp_path: Any) -> list[str]:
    """Run the state-setting commands a sample needs; return the sample with ids filled in."""
    for args in PREPARE.get(name, []):
        cli(*args, env_extra=ENV)
    args = list(SAMPLE_ARGS[name])
    if any("{run}" in a for a in args):
        out = cli(*RUN_SAMPLE, env_extra=ENV)
        run_id = out.stderr.split("saved run ")[1].split(" ")[0]
        args = [a.replace("{run}", run_id) for a in args]
    if any("{tmp}" in a for a in args):
        target = tmp_path / "exports"
        if target.exists():
            for stale in target.glob("*"):
                stale.unlink()
        args = [a.replace("{tmp}", str(target)) for a in args]
    return args


@pytest.fixture(autouse=True)
def _no_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    from sobres import doctor as doc
    from sobres.cli.commands import serve as serve_mod

    monkeypatch.setattr(doc, "latest_release", lambda: None)
    # `serve`/`open` never bind a real socket here: the server is a stand-in that
    # reports ready immediately, and the browser launch is recorded, not run.
    import threading

    def fake_run_server(
        host: str, port: int, ctx: Any, *, ready: threading.Event | None = None
    ) -> None:
        if ready is not None:
            ready.set()

    monkeypatch.setattr(serve_mod, "run_server", fake_run_server)
    monkeypatch.setattr(serve_mod, "probe", lambda url, timeout=1.0: None)
    monkeypatch.setattr(serve_mod.webbrowser, "open", lambda url: False)
    # `deploy health` asks a running server; here one answers "ready" without a socket.
    from sobres.cli.commands import deploy as deploy_mod

    class _Ready:
        def json(self) -> dict[str, Any]:
            return {"app": "sobres", "ready": True, "version": "test", "checks": {}}

    monkeypatch.setattr(deploy_mod.httpx, "get", lambda url, timeout: _Ready())


VOLATILE_KEYS = {
    "fetched_at",
    "updated_at",
    "created_at",
    "elapsed",
    "changed",
    "cache",
    "id",
    "a",
    "b",
    "run",
}
STATEFUL = {
    "cache.clear",
    "db.export",
    "db.repair",
    "portfolio.delete",
    "portfolio.save",
    "run.delete",
    "run.diff",
    "run.list",
    "run.show",
    "watchlist.add",
    "watchlist.delete",
    "watchlist.remove",
}
VOLATILE_ROWS = {"size_bytes", "oldest_entry_age_days"}


def _canon(value: Any) -> Any:
    """Drop what legitimately changes between runs: timestamps, cache state, sizes."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [
            _canon(v)
            for v in value
            if not (
                isinstance(v, dict)
                and (
                    v.get("metric", v.get("item")) in VOLATILE_ROWS
                    or str(v.get("key", "")).startswith("otel_")
                    or str(v.get("name", v.get("check", ""))).startswith("setting:otel_")
                    or v.get("name", v.get("check")) in {"cache", "disk-space"}
                )
            )
        ]
    return value


_HEX_ID = re.compile(r"\b[0-9a-f]{12}\b")


def _strip_volatile(text: str) -> Any:
    try:
        return _canon(json.loads(text))
    except ValueError:
        kept = [line for line in text.splitlines() if "run id" not in line]
        return _HEX_ID.sub("<id>", "\n".join(kept))


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_json_is_one_parseable_document_at_debug(
    name: str, cli: Callable[..., Any], tmp_path: Any
) -> None:
    cmd = next(c for c in all_commands() if c.name == name)
    sample = _prepare(name, cli, tmp_path)
    args = [*sample, "--format", "json"] if cmd.emits_data else sample
    result = cli("-vv", *args, env_extra=ENV)
    assert result.exit_code == 0, result.stderr
    if cmd.emits_data:
        json.loads(result.stdout)  # exactly one document, nothing else on stdout
    assert result.stderr  # DEBUG logging produced records, all on stderr


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_stdout_identical_across_log_levels_and_tracing(
    name: str, cli: Callable[..., Any], tmp_path: Any
) -> None:
    cmd = next(c for c in all_commands() if c.name == name)

    def args() -> list[str]:
        sample = _prepare(name, cli, tmp_path)
        return [*sample, "--format", "json"] if cmd.emits_data else sample

    quiet = cli(*args(), env_extra=ENV)
    loud = cli("-vv", *args(), env_extra=ENV)
    traced = cli(*args(), env_extra={**ENV, "OTEL_TRACES_EXPORTER": "console"})
    assert quiet.exit_code == loud.exit_code == traced.exit_code == 0
    assert _strip_volatile(quiet.stdout) == _strip_volatile(loud.stdout)
    assert _strip_volatile(quiet.stdout) == _strip_volatile(traced.stdout)


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_same_inputs_produce_identical_output_twice(
    name: str, cli: Callable[..., Any], tmp_path: Any
) -> None:
    cmd = next(c for c in all_commands() if c.name == name)
    if name in STATEFUL:
        return  # the second run legitimately differs (rows removed, ids created)
    sample = _prepare(name, cli, tmp_path)
    args = [*sample, "--format", "json"] if cmd.emits_data else sample
    first = cli(*args, env_extra=ENV)
    for a in PREPARE.get(name, []):
        cli(*a, env_extra=ENV)
    second = cli(*args, env_extra=ENV)
    assert _strip_volatile(first.stdout) == _strip_volatile(second.stdout)


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_disclaimer_rule_per_command(name: str, cli: Callable[..., Any], tmp_path: Any) -> None:
    from sobres.cli.render import DISCLAIMER

    cmd = next(c for c in all_commands() if c.name == name)
    if not cmd.emits_data:
        return
    table = cli(*_prepare(name, cli, tmp_path), "--format", "table", env_extra=ENV)
    assert (DISCLAIMER in table.stdout) == cmd.report
    for fmt in ("json", "csv"):
        out = cli(*_prepare(name, cli, tmp_path), "--format", fmt, env_extra=ENV)
        assert DISCLAIMER not in out.stdout
