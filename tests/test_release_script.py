"""Contract tests for ``.github/scripts/check_release.py``.

The script's stdout is appended to ``$GITHUB_OUTPUT``, which accepts only
``key=value`` lines and fails the job on anything else. These tests run every
decision path with the index call stubbed and assert that contract, so a stray
informational print can never again turn a push to ``main`` red.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check_release.py"

# What $GITHUB_OUTPUT will accept: a bare key, "=", then anything.
OUTPUT_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    target: str,
    enabled: str,
    index: Callable[[str, str], set[str] | None],
) -> tuple[dict[str, str], str]:
    """Run ``main()`` and return parsed stdout outputs plus raw stderr."""
    module = load_script()
    monkeypatch.setenv("TARGET", target)
    monkeypatch.setenv("RELEASE_ENABLED", enabled)
    monkeypatch.setattr(module, "released_versions", index)
    module.main()
    out, err = capsys.readouterr()

    lines = [line for line in out.splitlines() if line.strip()]
    for line in lines:
        assert OUTPUT_LINE.match(line), (
            f"stdout line is not key=value and would fail $GITHUB_OUTPUT: {line!r}"
        )
    return dict(line.split("=", 1) for line in lines), err


def test_disarmed_publishes_nothing_and_keeps_stdout_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs, err = run(monkeypatch, capsys, target="pypi", enabled="", index=lambda *_: None)
    assert outputs["publish"] == "false"
    assert outputs["target"] == "pypi"
    assert "not armed" in err, "the human explanation belongs on stderr"


def test_armed_first_release_publishes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs, _ = run(monkeypatch, capsys, target="pypi", enabled="true", index=lambda *_: None)
    assert outputs["publish"] == "true"


def test_armed_existing_version_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sobres import __version__

    outputs, err = run(
        monkeypatch, capsys, target="pypi", enabled="true", index=lambda *_: {__version__}
    )
    assert outputs["publish"] == "false"
    assert "already on pypi" in err


def test_testpypi_rehearsal_ignores_arming(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs, _ = run(monkeypatch, capsys, target="testpypi", enabled="", index=lambda *_: None)
    assert outputs["publish"] == "true"
    assert outputs["target"] == "testpypi"


def test_every_mode_emits_exactly_the_three_outputs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for target, enabled in (("pypi", ""), ("pypi", "true"), ("testpypi", "")):
        outputs, _ = run(monkeypatch, capsys, target=target, enabled=enabled, index=lambda *_: None)
        assert set(outputs) == {"version", "target", "publish"}, (target, enabled, outputs)
