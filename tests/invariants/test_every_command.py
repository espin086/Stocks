"""Invariants that must hold for every registered command — enumerated, not sampled.

Scenarios: Enumerated, not sampled; Required invariants; Instrumentation does
not change results; Machine output stays parseable; stdout is results only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from sobres.registry import all_commands
from tests.conftest import SENTINEL_KEY

# One runnable, offline invocation per command. A new command must add an entry
# here or ``test_every_command_has_a_sample`` fails.
SAMPLE_ARGS: dict[str, list[str]] = {
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
    "doctor": ["doctor", "--offline"],
    "init": ["init", "--non-interactive", "--offline"],
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
    "upgrade": ["upgrade", "--check"],
}
ENV = {"SOBRES_FRED_API_KEY": SENTINEL_KEY}


def test_every_command_has_a_sample() -> None:
    assert {c.name for c in all_commands()} == set(SAMPLE_ARGS)


@pytest.fixture(autouse=True)
def _no_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    from sobres import doctor as doc

    monkeypatch.setattr(doc, "latest_release", lambda: None)


VOLATILE_KEYS = {"fetched_at", "updated_at", "elapsed", "changed", "cache"}
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
                    v.get("metric") in VOLATILE_ROWS
                    or str(v.get("key", "")).startswith("otel_")
                    or str(v.get("name", v.get("check", ""))).startswith("setting:otel_")
                    or v.get("name", v.get("check")) in {"cache", "disk-space"}
                )
            )
        ]
    return value


def _strip_volatile(text: str) -> Any:
    try:
        return _canon(json.loads(text))
    except ValueError:
        return "\n".join(line for line in text.splitlines() if "run id" not in line)


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_json_is_one_parseable_document_at_debug(name: str, cli: Callable[..., Any]) -> None:
    cmd = next(c for c in all_commands() if c.name == name)
    args = [*SAMPLE_ARGS[name], "--format", "json"] if cmd.emits_data else SAMPLE_ARGS[name]
    result = cli("-vv", *args, env_extra=ENV)
    assert result.exit_code == 0, result.stderr
    if cmd.emits_data:
        json.loads(result.stdout)  # exactly one document, nothing else on stdout
    assert result.stderr  # DEBUG logging produced records, all on stderr


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_stdout_identical_across_log_levels_and_tracing(name: str, cli: Callable[..., Any]) -> None:
    cmd = next(c for c in all_commands() if c.name == name)
    args = [*SAMPLE_ARGS[name], "--format", "json"] if cmd.emits_data else SAMPLE_ARGS[name]
    quiet = cli(*args, env_extra=ENV)
    loud = cli("-vv", *args, env_extra=ENV)
    traced = cli(*args, env_extra={**ENV, "OTEL_TRACES_EXPORTER": "console"})
    assert quiet.exit_code == loud.exit_code == traced.exit_code == 0
    assert _strip_volatile(quiet.stdout) == _strip_volatile(loud.stdout)
    assert _strip_volatile(quiet.stdout) == _strip_volatile(traced.stdout)


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_same_inputs_produce_identical_output_twice(name: str, cli: Callable[..., Any]) -> None:
    cmd = next(c for c in all_commands() if c.name == name)
    args = [*SAMPLE_ARGS[name], "--format", "json"] if cmd.emits_data else SAMPLE_ARGS[name]
    first = cli(*args, env_extra=ENV)
    second = cli(*args, env_extra=ENV)
    if name == "cache.clear":
        return  # the second run legitimately reports fewer rows removed
    assert _strip_volatile(first.stdout) == _strip_volatile(second.stdout)


@pytest.mark.parametrize("name", sorted(SAMPLE_ARGS))
def test_disclaimer_rule_per_command(name: str, cli: Callable[..., Any]) -> None:
    from sobres.cli.render import DISCLAIMER

    cmd = next(c for c in all_commands() if c.name == name)
    if not cmd.emits_data:
        return
    table = cli(*SAMPLE_ARGS[name], "--format", "table", env_extra=ENV)
    assert (DISCLAIMER in table.stdout) == cmd.report
    for fmt in ("json", "csv"):
        out = cli(*SAMPLE_ARGS[name], "--format", fmt, env_extra=ENV)
        assert DISCLAIMER not in out.stdout
