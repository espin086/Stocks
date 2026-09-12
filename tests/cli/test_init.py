"""``sobres init`` — the guided wizard.

Scenarios: Guided, in the terminal; Idempotent and re-runnable; Optional
settings can be skipped; Live validation with consent; Storage is set up;
Non-interactive mode; Ends with proof; Time to first result; The three-command
path is a test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sobres.cli.commands.init import InitParams, init
from sobres.cli.context import Context
from sobres.core.errors import ConfigurationError
from sobres.settings import LiveResult, Setting, all_settings, get_setting


def test_non_interactive_writes_config_sets_up_storage_and_runs_doctor(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    result = cli("init", "--non-interactive", "--offline", "--format", "json")
    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    assert doc["config_path"] == env["SOBRES_CONFIG_FILE"]
    assert doc["db_location"].endswith("sobres.db")
    assert Path(doc["config_path"]).exists() and Path(doc["db_location"]).exists()
    assert doc["first_command"].startswith("sobres data prices")
    assert {c["name"] for c in doc["checks"]} >= {"python-version", "db-schema", "config-file"}
    assert not any(c["status"] == "fail" for c in doc["checks"])
    table = cli("init", "--non-interactive", "--offline", "--format", "table")
    assert "try next: sobres data prices" in table.stdout and "database:" in table.stdout


def test_rerun_without_changes_is_byte_identical(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    cli("init", "--non-interactive", "--offline", "--set", "fred_api_key=ABCD1234")
    path = Path(env["SOBRES_CONFIG_FILE"])
    before = path.read_bytes()
    result = cli("init", "--non-interactive", "--offline", "--format", "json")
    assert result.exit_code == 0
    assert path.read_bytes() == before
    doc = json.loads(result.stdout)
    assert doc["changed"] == [] and doc["first_command"].startswith("sobres data macro")


def test_non_interactive_takes_values_from_environment(
    cli: Callable[..., Any], env: dict[str, str]
) -> None:
    result = cli(
        "init",
        "--non-interactive",
        "--offline",
        "--format",
        "json",
        env_extra={"SOBRES_LOG_LEVEL": "INFO"},
    )
    assert "log_level" in json.loads(result.stdout)["changed"]
    assert 'log_level = "INFO"' in Path(env["SOBRES_CONFIG_FILE"]).read_text(encoding="utf-8")


def test_non_interactive_missing_required_exits_3_naming_it(
    make_context: Callable[..., Context],
) -> None:
    from sobres import settings as reg

    required = Setting(key="zz_required", env="SOBRES_ZZ_REQUIRED", description="d", required=True)
    reg._REGISTRY[required.key] = required
    try:
        with pytest.raises(ConfigurationError) as exc:
            init(InitParams(non_interactive=True, offline=True), make_context())
        assert exc.value.exit_code == 3
        assert "zz_required" in str(exc.value) and "SOBRES_ZZ_REQUIRED" in str(exc.value)
    finally:
        del reg._REGISTRY[required.key]


def test_bad_set_syntax_and_value(cli: Callable[..., Any]) -> None:
    assert cli("init", "--non-interactive", "--offline", "--set", "nonsense").exit_code == 3
    assert cli("init", "--non-interactive", "--offline", "--set", "log_level=LOUD").exit_code == 3


class _Wizard:
    """Scripted answers for the interactive path: prompts and confirmations in order."""

    def __init__(self, answers: dict[str, list[str]], confirms: dict[str, list[bool]]) -> None:
        self.answers, self.confirms = answers, confirms
        self.seen: list[str] = []

    def prompt(self, question: str, secret: bool) -> str:
        self.seen.append(question)
        for key, values in self.answers.items():
            if key in question and values:
                return values.pop(0)
        return ""

    def confirm(self, question: str) -> bool:
        self.seen.append(question)
        for key, values in self.confirms.items():
            if key in question and values:
                return values.pop(0)
        return False


def _interactive(make_context: Callable[..., Context], wizard: _Wizard, **kw: Any) -> Context:
    ctx = make_context(prompt=wizard.prompt, confirm=wizard.confirm, **kw)
    ctx.interactive = True
    return ctx


def test_guided_wizard_walks_every_setting_and_masks_secrets(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    fred = get_setting("fred_api_key")
    monkeypatch.setattr(fred, "validate_live", lambda v: LiveResult(True, "FRED accepted the key"))
    wizard = _Wizard({"fred_api_key": ["SECRET9999"], "log_level": ["INFO"]}, {"verify it": [True]})
    ctx = _interactive(make_context, wizard)
    report = init(InitParams(offline=True), ctx)
    assert "fred_api_key" in report.changed and "log_level" in report.changed
    assert report.exit_code == 0
    assert (
        len([q for q in wizard.seen if "(enter to skip)" in q or q.strip().startswith("fred")]) >= 1
    )
    # every declared setting was walked, in order
    walked = [q for q in wizard.seen if any(q.strip().startswith(s.key) for s in all_settings())]
    assert [q.strip().split(" ")[0] for q in walked] == [s.key for s in all_settings()]
    text = ctx.config.path.read_text(encoding="utf-8")
    assert 'fred_api_key = "SECRET9999"' in text
    # re-run: current values are shown masked and kept when not replaced
    wizard2 = _Wizard({}, {"replace it": [False]})
    ctx2 = _interactive(make_context, wizard2)
    err = __import__("io").StringIO()
    ctx2.stderr = err
    report2 = init(InitParams(offline=True), ctx2)
    assert report2.changed == []
    assert "****9999" in err.getvalue() and "SECRET9999" not in err.getvalue()


def test_failed_live_validation_never_stores_silently(
    make_context: Callable[..., Context], monkeypatch: pytest.MonkeyPatch
) -> None:
    fred = get_setting("fred_api_key")
    monkeypatch.setattr(fred, "validate_live", lambda v: LiveResult(v == "GOOD", f"{v} checked"))
    # retry once with a bad key, then a good one
    wizard = _Wizard(
        {"fred_api_key": ["BAD", "GOOD"], "[r]etry": ["r"]}, {"verify it": [True, True]}
    )
    ctx = _interactive(make_context, wizard)
    init(InitParams(offline=True), ctx)
    assert 'fred_api_key = "GOOD"' in ctx.config.path.read_text(encoding="utf-8")
    # skip after a failure: nothing stored
    ctx.config.path.unlink()
    wizard = _Wizard({"fred_api_key": ["BAD"], "[r]etry": ["s"]}, {"verify it": [True]})
    ctx = _interactive(make_context, wizard)
    init(InitParams(offline=True), ctx)
    assert "fred_api_key" not in ctx.config.path.read_text(encoding="utf-8")
    # keep anyway is an explicit choice
    ctx.config.path.unlink()
    wizard = _Wizard({"fred_api_key": ["BAD"], "[r]etry": ["k"]}, {"verify it": [True]})
    ctx = _interactive(make_context, wizard)
    init(InitParams(offline=True), ctx)
    assert 'fred_api_key = "BAD"' in ctx.config.path.read_text(encoding="utf-8")


def test_optional_setting_skipped_names_affected_commands(
    make_context: Callable[..., Context],
) -> None:
    wizard = _Wizard({}, {})
    ctx = _interactive(make_context, wizard)
    err = __import__("io").StringIO()
    ctx.stderr = err
    report = init(InitParams(offline=True), ctx)
    assert report.changed == []
    assert "without it: data.macro" in err.getvalue()
    assert "obtain: https://fred.stlouisfed.org" in err.getvalue()


def test_invalid_interactive_value_is_re_prompted(make_context: Callable[..., Context]) -> None:
    wizard = _Wizard({"log_level": ["LOUD", "ERROR"]}, {})
    ctx = _interactive(make_context, wizard)
    init(InitParams(offline=True), ctx)
    assert 'log_level = "ERROR"' in ctx.config.path.read_text(encoding="utf-8")


def test_ends_by_running_doctor(cli: Callable[..., Any]) -> None:
    result = cli("init", "--non-interactive", "--offline", "--format", "table")
    assert "python-version" in result.stdout and " ok," in result.stdout
