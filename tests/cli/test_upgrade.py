"""``sobres upgrade`` — detect, print, confirm, run.

Scenarios: Installer is detected, not assumed; Confirmation before acting;
Post-upgrade migration.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

import pytest

from sobres import doctor as doc


def test_detects_installer_and_prints_matching_command(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doc, "latest_release", lambda: "9.9.9")
    result = cli("upgrade", "--check")
    assert result.exit_code == 0 and "9.9.9 is available" in result.stdout
    result = cli("upgrade", input="n\n")
    assert result.exit_code == 2 and "cancelled" in result.stderr
    assert "detected installer: pip" in result.stderr
    assert "-m pip install --upgrade sobres" in result.stderr
    container = cli("upgrade", env_extra={"SOBRES_CONTAINER": "1"})
    assert (
        container.exit_code == 0
        and "docker pull" in container.stderr
        and "pull the new image" in container.stdout
    )


def test_check_when_pypi_unreachable_or_current(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doc, "latest_release", lambda: None)
    assert "could not reach PyPI" in cli("upgrade", "--check").stdout
    from sobres import __version__

    monkeypatch.setattr(doc, "latest_release", lambda: __version__)
    assert "is the latest" in cli("upgrade", "--check").stdout


def test_yes_runs_the_command(cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc, "latest_release", lambda: None)
    calls: list[list[str]] = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda cmd, check: (calls.append(cmd), _Done())[1])
    result = cli("upgrade", "--yes")
    assert result.exit_code == 0 and calls and calls[0][-1] == "sobres"
    assert "pending migrations apply on the next command" in result.stdout

    class _Failed:
        returncode = 3

    monkeypatch.setattr(subprocess, "run", lambda cmd, check: _Failed())
    failed = cli("upgrade", "--yes")
    assert failed.exit_code == 2 and "exited 3" in failed.stderr
