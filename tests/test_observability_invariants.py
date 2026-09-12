"""Observability may never change a result.

Scenarios: Instrumentation does not change results; stdout is results only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ARGS = ["data", "prices", "AAPL", "--start", "2020-01-01", "--end", "2020-01-31", "--format", "csv"]


def test_stdout_identical_across_log_levels(cli: Callable[..., Any]) -> None:
    quiet = cli(*ARGS)
    loud = cli("-vv", *ARGS)
    assert quiet.stdout == loud.stdout and loud.stderr


def test_stdout_identical_with_and_without_tracing(cli: Callable[..., Any]) -> None:
    plain = cli(*ARGS)
    traced = cli(*ARGS, env_extra={"OTEL_TRACES_EXPORTER": "console"})
    assert plain.stdout == traced.stdout
