"""Every ``#### Scenario:`` heading has a test that references it by name.

Advisory (a warning) while a change is ``status: proposed``; a build failure
once its proposal is marked ``status: implemented``.

Scenarios: Every scenario has a test.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHANGES = REPO / "openspec" / "changes"
TESTS = REPO / "tests"
SCENARIO = re.compile(r"^#### Scenario:\s*(.+?)\s*$", re.MULTILINE)
STATUS = re.compile(r"^status:\s*(\w+)", re.MULTILINE)


def _scenarios() -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for change in sorted(p for p in CHANGES.iterdir() if p.is_dir() and p.name != "archive"):
        proposal = change / "proposal.md"
        status = "proposed"
        if proposal.exists():
            match = STATUS.search(proposal.read_text())
            status = match.group(1) if match else "proposed"
        names: list[str] = []
        for spec in change.glob("specs/*/spec.md"):
            names.extend(SCENARIO.findall(spec.read_text()))
        out[change.name] = (status, names)
    return out


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _test_corpus() -> str:
    return _squash("\n".join(p.read_text() for p in TESTS.rglob("*.py")))


def test_every_scenario_has_a_test() -> None:
    corpus = _test_corpus()
    missing_hard: list[str] = []
    missing_soft: list[str] = []
    for change, (status, names) in _scenarios().items():
        for name in names:
            if _squash(name) in corpus:
                continue
            (missing_hard if status == "implemented" else missing_soft).append(f"{change}: {name}")
    if missing_soft:
        warnings.warn(
            f"{len(missing_soft)} scenario(s) in proposed changes have no test yet", stacklevel=1
        )
    assert not missing_hard, "implemented scenarios without a test:\n" + "\n".join(missing_hard)


def test_scenario_names_are_unique_within_a_spec() -> None:
    for spec in CHANGES.glob("*/specs/*/spec.md"):
        names = SCENARIO.findall(spec.read_text())
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"{spec} repeats scenario titles: {dupes}"
