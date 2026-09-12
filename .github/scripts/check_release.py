#!/usr/bin/env python3
"""Decide whether the current commit should be published.

PyPI versions are immutable: re-uploading an existing version is a hard error,
not an overwrite. So "publish on every push to main" can only mean "publish when
the version declared in ``__about__.py`` is not yet on the index".

Writes ``version``, ``target`` and ``publish`` as ``KEY=value`` lines on stdout,
which the workflow appends to ``$GITHUB_OUTPUT``.

stdout is therefore a machine interface: it carries ONLY ``key=value`` lines.
Every human-facing message goes to stderr. ``$GITHUB_OUTPUT`` rejects any line
that is not ``key=value``, so a stray informational print on stdout fails the
whole job -- which is exactly what happened on the first push to ``main``.
``tests/test_release_script.py`` enforces the contract.

Run locally to see what the next push to main would do::

    python .github/scripts/check_release.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ABOUT = REPO_ROOT / "src" / "sobres" / "__about__.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

INDEXES = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
}

# PEP 440, restricted to the subset this project actually uses.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?$")


def note(message: str) -> None:
    """Human-facing progress line. stderr, never stdout -- stdout is $GITHUB_OUTPUT."""
    print(message, file=sys.stderr)


def emit(key: str, value: str) -> None:
    """The only writer to stdout: one ``key=value`` line for $GITHUB_OUTPUT."""
    print(f"{key}={value}")


def fail(message: str) -> None:
    """Emit a GitHub Actions error annotation and exit non-zero."""
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def read_version() -> str:
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"', ABOUT.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match:
        fail(f"Could not find __version__ in {ABOUT.relative_to(REPO_ROOT)}")
        raise AssertionError("unreachable")  # pragma: no cover
    return match.group(1)


def read_dist_name() -> str:
    return str(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["name"])


def released_versions(dist_name: str, target: str) -> set[str] | None:
    """Return every version on the index, or ``None`` if the project is new."""
    url = INDEXES[target].format(name=dist_name)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return set(json.load(response)["releases"])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # First ever release: the project does not exist on the index yet.
            return None
        fail(f"{target} returned HTTP {exc.code} for {dist_name}")
    except urllib.error.URLError as exc:
        # A network blip must not silently look like "nothing is published",
        # which would re-publish an existing version and fail at upload.
        fail(f"Could not reach {target}: {exc.reason}")
    raise AssertionError("unreachable")  # pragma: no cover


def main() -> None:
    target = os.environ.get("TARGET", "pypi")
    if target not in INDEXES:
        fail(f"TARGET must be one of {sorted(INDEXES)}, got {target!r}")

    # Arming switch. Publishing to real PyPI stays off until the repository
    # variable RELEASE_ENABLED is set to "true", so merging the pipeline itself
    # cannot fire a publish before Trusted Publishing is configured. TestPyPI
    # runs (workflow_dispatch) are always allowed -- that is how you rehearse.
    enabled = os.environ.get("RELEASE_ENABLED", "").strip().lower() == "true"
    if target == "pypi" and not enabled:
        note("Releases to PyPI are not armed (repository variable RELEASE_ENABLED != 'true').")
        note("See docs/RELEASING.md for the one-time Trusted Publishing setup.")
        emit("version", read_version())
        emit("target", target)
        emit("publish", "false")
        return

    version = read_version()
    if not VERSION_RE.match(version):
        fail(
            f"Version {version!r} is not a valid release version "
            f"(expected e.g. 1.2.3, 1.2.3rc1 or 1.2.3.dev0)"
        )

    dist_name = read_dist_name()
    existing = released_versions(dist_name, target)

    if existing is None:
        note(f"{dist_name} is not on {target} yet -- this would be the first release.")
        publish = True
    elif version in existing:
        note(f"{dist_name} {version} is already on {target}; nothing to publish.")
        publish = False
    else:
        note(f"{dist_name} {version} is not on {target}; it will be published.")
        publish = True

    # Release discipline: a version that ships must be described. Checked only
    # when actually publishing, so ordinary pushes are never blocked by it.
    if publish and CHANGELOG.exists():
        changelog = CHANGELOG.read_text(encoding="utf-8")
        if f"## [{version}]" not in changelog and f"## {version}" not in changelog:
            fail(
                f"CHANGELOG.md has no section for {version}. "
                f"Add a '## [{version}]' heading describing the release."
            )

    emit("version", version)
    emit("target", target)
    emit("publish", str(publish).lower())


if __name__ == "__main__":
    main()
