"""Smoke tests for the CLI scaffold.

These prove packaging + entry point wiring. Real behavior tests arrive with
each OpenSpec change under `openspec/changes/`.
"""

from typer.testing import CliRunner

from sobres import __version__
from sobres.cli.main import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_bare_invocation_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "sobres" in result.stdout


def test_version_callback_is_inert_when_flag_absent() -> None:
    """`--version` short-circuits; its absence must not alter normal dispatch."""
    from sobres.cli.main import _version_callback

    assert _version_callback(False) is None
