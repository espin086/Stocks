"""The command registry and the generated Typer app.

Scenarios: Declaration shape; The CLI is generated; Help text has one source;
Defaults have one source; Validation before the handler; Shared types;
Cross-field rules live in the model; Result types are frozen dataclasses or
pydantic models; The registry is queryable; Registration is complete at import;
Names are an interface; Adding a parameter is backward compatible.
"""

from __future__ import annotations

import warnings
from typing import Any, ClassVar

import pytest
import typer
from pydantic import Field, ValidationError, model_validator
from typer.main import get_command as typer_get_command

from sobres.core.errors import UsageError
from sobres.registry import (
    Command,
    Params,
    TickerList,
    Weights,
    all_commands,
    build_app,
    command_schema,
    field_schema,
    get_command,
    register,
    validate_params,
)
from sobres.results import MessageResult, Result

EXPECTED_COMMANDS = [
    "cache.clear",
    "cache.info",
    "commands",
    "config.path",
    "config.set",
    "config.show",
    "config.unset",
    "data.factors",
    "data.fx",
    "data.macro",
    "data.prices",
    "db.export",
    "db.info",
    "db.repair",
    "deploy.check",
    "deploy.compose",
    "deploy.env",
    "deploy.health",
    "doctor",
    "init",
    "open",
    "optimize.backtest",
    "optimize.frontier",
    "optimize.markowitz",
    "optimize.risk",
    "portfolio.delete",
    "portfolio.list",
    "portfolio.save",
    "portfolio.show",
    "run.delete",
    "run.diff",
    "run.list",
    "run.show",
    "serve",
    "serve.token.rotate",
    "upgrade",
    "watchlist.add",
    "watchlist.delete",
    "watchlist.list",
    "watchlist.remove",
    "watchlist.show",
]


def test_registration_count_matches_explicit_list() -> None:
    assert [c.name for c in all_commands()] == EXPECTED_COMMANDS


def _click_commands(app: typer.Typer) -> dict[str, Any]:
    root = typer_get_command(app)
    found: dict[str, Any] = {}

    def walk(cmd: Any, prefix: str) -> None:
        for name, sub in getattr(cmd, "commands", {}).items():
            full = f"{prefix}{name}"
            if hasattr(sub, "commands"):
                if getattr(sub, "invoke_without_command", False) and sub.params:
                    found[full] = sub  # a command that is also a group runs as its default
                walk(sub, full + ".")
            elif not sub.hidden:
                found[full] = sub

    walk(root, "")
    return found


def test_typer_app_has_one_subcommand_per_registration() -> None:
    from sobres.cli.main import app

    found = _click_commands(app)
    assert sorted(found) == EXPECTED_COMMANDS
    for cmd in all_commands():
        click_cmd = found[cmd.name]
        names = {p.name for p in click_cmd.params}
        for field in cmd.params.model_fields:
            assert field in names, f"{cmd.name} lacks --{field}"
        if cmd.emits_data:
            assert "format" in names
        else:
            assert "format" not in names
        assert ("refresh" in names) == cmd.uses_providers


def test_defaults_come_only_from_param_model() -> None:
    from sobres.cli.main import app

    found = _click_commands(app)
    for cmd in all_commands():
        click_params = {p.name: p for p in found[cmd.name].params}
        for name, info in cmd.params.model_fields.items():
            click_default = click_params[name].default
            model_default = (
                None if info.is_required() else info.get_default(call_default_factory=True)
            )
            if isinstance(model_default, list | tuple):
                assert click_default in (None, (), []) or list(click_default) == list(model_default)
            elif hasattr(model_default, "isoformat"):
                assert click_default == model_default.isoformat()
            elif info.is_required():
                assert click_default in (None, ())
            else:
                assert click_default == model_default, f"{cmd.name}.{name}"


def test_help_text_comes_from_field_description() -> None:
    from sobres.cli.main import app

    found = _click_commands(app)
    for cmd in all_commands():
        click_params = {p.name: p for p in found[cmd.name].params}
        for name, info in cmd.params.model_fields.items():
            assert (info.description or "") in (click_params[name].help or "")


class _Portfolio(Params):
    tickers: TickerList = Field(description="t")
    weights: Weights = Field(default_factory=list, description="w")
    portfolio: str | None = Field(default=None, description="p")

    @model_validator(mode="after")
    def _rules(self) -> _Portfolio:
        if self.weights and len(self.weights) != len(self.tickers):
            raise ValueError(f"{len(self.weights)} weights for {len(self.tickers)} tickers")
        if self.weights and abs(sum(self.weights) - 1.0) > 1e-6:
            raise ValueError(f"weights sum to {sum(self.weights):.6f}, not 1.0")
        if self.portfolio and self.tickers:
            raise ValueError("--portfolio and --tickers are mutually exclusive")
        return self


def test_cross_field_validator_rejects_weight_count_mismatch() -> None:
    with pytest.raises(ValidationError, match="2 weights for 3 tickers"):
        _Portfolio(tickers=["A", "B", "C"], weights=[0.5, 0.5])
    with pytest.raises(ValidationError, match=r"not 1\.0"):
        _Portfolio(tickers=["A", "B"], weights=[0.5, 0.6])
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _Portfolio(tickers=["A"], portfolio="core")
    ok = _Portfolio(tickers="aapl, msft", weights="0.5 0.5")
    assert ok.tickers == ["AAPL", "MSFT"] and ok.weights == [0.5, 0.5]


def test_shared_types_parse_identically() -> None:
    class P(Params):
        tickers: TickerList

    for raw in (["AAPL", "msft"], "AAPL MSFT", "aapl,msft", ["AAPL,MSFT"]):
        assert P(tickers=raw).tickers == ["AAPL", "MSFT"]
    with pytest.raises(ValidationError):
        P(tickers=[])
    with pytest.raises(ValidationError):
        P(tickers=["BAD TICKER!"])


def test_validation_error_becomes_usage_error_naming_field() -> None:
    cmd = get_command("data.prices")
    with pytest.raises(UsageError) as exc:
        validate_params(cmd, {"tickers": ["AAPL"], "start": "not-a-date"})
    assert exc.value.exit_code == 2 and "start" in str(exc.value)
    with pytest.raises(UsageError, match="end"):
        validate_params(cmd, {"tickers": ["AAPL"], "start": "2020-01-02", "end": "2020-01-01"})
    with pytest.raises(UsageError, match="tickers"):
        validate_params(cmd, {"tickers": [], "start": "2020-01-02"})
    params = validate_params(cmd, {"tickers": ["aapl"], "start": "2020-01-02", "end": None})
    assert params.tickers == ["AAPL"]  # type: ignore[attr-defined]


def test_registry_is_queryable() -> None:
    schema = command_schema(get_command("data.prices"))
    assert schema["group"] == "data" and schema["command"] == "prices"
    params = {p["name"]: p for p in schema["params"]}
    assert params["tickers"]["positional"] and params["tickers"]["multiple"]
    assert params["field"]["choices"] == ["adj_close", "close", "open", "high", "low", "volume"]
    assert params["field"]["default"] == "adj_close"
    assert params["end"]["type"] == "date | None"
    assert "properties" in schema["json_schema"]
    assert field_schema(get_command("doctor").params)[0]["type"] == "bool"


def test_result_types_are_declared_models() -> None:
    for cmd in all_commands():
        assert issubclass(cmd.result, Result)
        assert issubclass(cmd.params, Params)
        assert cmd.help and cmd.name


def test_register_rejects_bad_declarations() -> None:
    with pytest.raises(TypeError):

        @register("bad.one", "x", result=MessageResult)
        def bad(p: int, ctx: object) -> MessageResult:  # type: ignore[misc]
            return MessageResult(message="")

    with pytest.raises(ValueError, match="registered twice"):

        @register("data.prices", "x", result=MessageResult)
        def dup(p: Params, ctx: object) -> MessageResult:
            return MessageResult(message="")


def test_deprecated_alias_warns_and_resolves() -> None:
    from sobres import registry as reg

    class P(Params):
        value: int = Field(default=1, description="v")

    def handler(p: P, ctx: object) -> MessageResult:
        return MessageResult(message=str(p.value))

    cmd = Command(
        name="test.new",
        help="h",
        params=P,
        result=MessageResult,
        handler=handler,
        aliases=("test.old",),
        param_aliases={"old_value": "value"},
    )
    reg._COMMANDS["test.new"] = cmd
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert get_command("test.old") is cmd
            params = validate_params(cmd, {"old_value": 3})
        assert params.value == 3  # type: ignore[attr-defined]
        assert any("deprecated" in str(w.message) for w in caught)
        with pytest.raises(KeyError):
            get_command("test.missing")
        app = build_app(typer.Typer(), lambda *_: None)
        names = set(typer_get_command(app).commands["test"].commands)  # type: ignore[attr-defined]
        assert {"new", "old"} <= names
    finally:
        del reg._COMMANDS["test.new"]


def test_greedy_list_options_accept_space_separated_values() -> None:
    from sobres.registry import _GreedyListCommand

    class G(_GreedyListCommand):
        greedy_options: ClassVar[set[str]] = {"--tickers", "--weights"}

    seen: list[list[str]] = []

    class Ctx:
        pass

    def fake_parse(self: Any, ctx: Any, args: list[str]) -> list[str]:
        seen.append(args)
        return args

    typer.core.TyperCommand.parse_args = fake_parse  # type: ignore[method-assign]
    try:
        G(name="g").parse_args(
            Ctx(),
            ["--tickers", "AAPL", "MSFT", "--weights", "0.5", "0.5", "--start", "x", "--tickers"],
        )
    finally:
        del typer.core.TyperCommand.parse_args
    assert seen[0] == [
        "--tickers",
        "AAPL",
        "--tickers",
        "MSFT",
        "--weights",
        "0.5",
        "--weights",
        "0.5",
        "--start",
        "x",
        "--tickers",
    ]
