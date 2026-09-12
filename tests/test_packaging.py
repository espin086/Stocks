"""Packaging and release-hygiene tests.

These guard the release pipeline's assumptions from inside the test suite, so a
broken release is caught by `pytest` rather than by a failed upload.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from importlib.metadata import entry_points, version
from pathlib import Path

import pytest

from sobres import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_NAME = "sobres"

# PEP 440, restricted to the subset this project uses. Must stay in step with
# VERSION_RE in .github/scripts/check_release.py.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?$")


def test_version_is_a_valid_release_version() -> None:
    assert VERSION_RE.match(__version__), (
        f"{__version__!r} is not a version the release pipeline will accept"
    )


def test_installed_metadata_matches_source() -> None:
    """The built distribution reports the version `__about__.py` declares."""
    assert version(DIST_NAME) == __version__


def test_changelog_documents_the_current_version() -> None:
    """Every shippable version is described before it can be published."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    assert f"## [{__version__}]" in changelog, (
        f"CHANGELOG.md has no '## [{__version__}]' section. "
        "The release pipeline will refuse to publish this version."
    )


def test_console_script_is_registered() -> None:
    scripts = entry_points(group="console_scripts")
    assert "sobres" in scripts.names


def test_exactly_one_console_script_is_declared() -> None:
    """One name across every surface: no second alias entry point."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert list(pyproject["project"]["scripts"]) == ["sobres"]


@pytest.mark.parametrize("script", ["sobres"])
def test_console_script_runs(script: str) -> None:
    """The entry point resolves and executes as an installed command would."""
    module, _, attr = scripts_target(script).partition(":")
    result = subprocess.run(
        [sys.executable, "-c", f"from {module} import {attr}; {attr}(['--version'])"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert __version__ in result.stdout


def scripts_target(script: str) -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return str(pyproject["project"]["scripts"][script])


def test_distribution_name_is_stable() -> None:
    """Renaming the distribution silently would orphan users on PyPI."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == DIST_NAME
