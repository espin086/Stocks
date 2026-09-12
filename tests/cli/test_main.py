"""Root app, error boundary and global options.

Scenarios: Version; Bare invocation; Command groups; Exit code contract;
Actionable messages; Debug escape hatch; Levels; Correlation; First-run hint;
A stale environment variable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from sobres import __version__
from sobres.core.errors import ProviderError


def test_version(cli: Callable[..., Any]) -> None:
    result = cli("--version")
    assert result.exit_code == 0 and result.stdout.strip() == __version__


def test_bare_shows_help_exit_0(cli: Callable[..., Any]) -> None:
    result = cli()
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_help_lists_exactly_the_shipped_groups(cli: Callable[..., Any]) -> None:
    result = cli("--help")
    for group in ("data", "cache", "config", "optimize", "analyze"):
        assert f"\n  {group} " in result.output
    assert "\n  econ " not in result.output  # 0009 has not shipped


def test_provider_error_exits_4_without_traceback(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.data import yfinance_provider

    def boom(self: Any, *a: Any, **k: Any) -> Any:
        raise ProviderError("upstream down", provider="yfinance", hint="retry later")

    monkeypatch.setattr(yfinance_provider.YFinanceProvider, "get_prices", boom)
    result = cli("data", "prices", "AAPL", "--start", "2020-01-01")
    assert result.exit_code == 4
    assert "error: yfinance: upstream down" in result.stderr
    assert "next: retry later" in result.stderr
    assert "run id:" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_debug_prints_traceback(cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from sobres.data import yfinance_provider

    def boom(self: Any, *a: Any, **k: Any) -> Any:
        raise ProviderError("upstream down", provider="yfinance")

    monkeypatch.setattr(yfinance_provider.YFinanceProvider, "get_prices", boom)
    result = cli("--debug", "data", "prices", "AAPL", "--start", "2020-01-01")
    assert result.exit_code == 4 and "Traceback" in result.stderr


def test_internal_error_exits_1_with_run_id(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.data import yfinance_provider

    def boom(self: Any, *a: Any, **k: Any) -> Any:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(yfinance_provider.YFinanceProvider, "get_prices", boom)
    result = cli("data", "prices", "AAPL", "--start", "2020-01-01")
    assert result.exit_code == 1
    assert "internal error (RuntimeError: unexpected)" in result.stderr
    assert "--debug" in result.stderr and "run id" in result.stderr


def test_usage_error_exits_2(cli: Callable[..., Any]) -> None:
    result = cli("data", "prices", "AAPL", "--start", "yesterday")
    assert result.exit_code == 2 and "start" in result.stderr


def test_unknown_format_exits_3(cli: Callable[..., Any]) -> None:
    result = cli("commands", "--format", "xml")
    assert result.exit_code == 3 and "table, json, csv" in result.stderr


def test_first_run_hint_on_stderr_only(cli: Callable[..., Any]) -> None:
    result = cli("commands", "--format", "json")
    assert "run `sobres init`" in result.stderr
    assert "sobres init" not in result.stdout
    cli("config", "set", "log_level", "WARNING")
    result = cli("commands", "--format", "json")
    assert "run `sobres init`" not in result.stderr


def test_stale_legacy_env_var_refuses_to_start(cli: Callable[..., Any]) -> None:
    legacy = "".join(("QUANT", "FOLIO", "_DB_URL"))
    result = cli("commands", env_extra={legacy: "sqlite:///x"})
    assert result.exit_code == 3
    assert "SOBRES_DB_URL" in result.stderr


def test_verbosity_flags_select_levels(cli: Callable[..., Any]) -> None:
    quiet = cli("commands", "--format", "json")
    assert '"command.start"' not in quiet.stderr
    info = cli("-v", "commands", "--format", "json")
    assert '"command.start"' in info.stderr and '"level": "info"' in info.stderr
    debug = cli("-vv", "cache", "info", "--format", "json")
    assert '"storage.op"' in debug.stderr
    explicit = cli("--log-level", "debug", "cache", "info", "--format", "json")
    assert '"storage.op"' in explicit.stderr
    from_env = cli("cache", "info", "--format", "json", env_extra={"SOBRES_LOG_LEVEL": "DEBUG"})
    assert '"storage.op"' in from_env.stderr


def test_bad_log_level_is_reported_not_crashed(cli: Callable[..., Any]) -> None:
    result = cli("--log-level", "LOUD", "commands")
    assert result.exit_code == 3 and "LOUD" in result.stderr


def test_log_file_sink_writes_json(cli: Callable[..., Any], tmp_path: Any) -> None:
    log = tmp_path / "logs" / "sobres.log"
    result = cli("-v", "commands", "--format", "json", env_extra={"SOBRES_LOG_FILE": str(log)})
    assert result.exit_code == 0 and log.exists()
    assert '"command.start"' in log.read_text(encoding="utf-8")
