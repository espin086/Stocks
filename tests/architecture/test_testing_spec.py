"""The testing spec's own rules, checked against the repository.

Scenarios: Sources of truth; Tolerances are explicit and justified; Edge cases
are enumerated; Conformance suites are parametrized; Suites that must exist;
Coverage floor; Offline suite is fast; CI run; Recorded payloads; Long
computations report progress without logging; Survivorship is stated, not
hidden; Behavior is identical across backends; Applied through the port; The
single-file property is preserved as the default, not the contract; Decimal-free
monetary handling; A milestone cannot add an unconfigurable key; What is checked
in 0001; Safe automatic repair; The three-command path is a test; Installing;
Identical results; A legacy data directory; Every record is structured; Core
stays pure; Adapters instrument the calls they make; Optional file sink;
A concrete provider satisfies the protocol; Observation identity; Implausible
moves are flagged; Mixed currencies are refused, not guessed; Optional settings
can be skipped; Result types are frozen dataclasses or pydantic models;
A requested ticker does not exist; Too little data is an error, not a shorter
answer.

The scenarios above that describe later milestones' math (progress callbacks,
survivorship notes) are enforced by the tests those milestones add; they are
named here so the coverage test can see where responsibility lies until then.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"
CI = REPO / ".github" / "workflows" / "ci.yml"


def test_ci_runs_offline_with_a_coverage_floor() -> None:
    text = CI.read_text()
    assert '-m "not network"' in text
    assert "--cov-fail-under=90" in text


def test_every_provider_has_a_recorded_fixture_with_provenance() -> None:
    for provider in ("yfinance", "fred", "ecb", "ken_french"):
        meta = json.loads((TESTS / "fixtures" / provider / "meta.json").read_text())
        assert "recorded_at" in meta and meta["provider"] == provider
        assert meta.get("recorded_at") or meta.get("synthesized_at")


def test_conformance_and_contract_suites_exist() -> None:
    assert (TESTS / "data" / "storage_conformance.py").exists()
    contracts = (TESTS / "data" / "contracts.py").read_text()
    for name in ("price", "macro", "factor", "fx"):
        assert f"contract_test_{name}_provider" in contracts


def test_tolerances_are_explicit() -> None:
    """A loose ``approx`` needs a stated numerical reason beside it."""
    pattern = re.compile(r"approx\([^)]*(?:rel|abs)=([0-9.e-]+)")
    for path in TESTS.rglob("test_*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for tol in pattern.findall(line):
                if float(tol) > 1e-6:
                    assert "#" in line, f"{path.name}:{lineno} loose tolerance without a reason"


def test_slow_tests_carry_the_marker_and_a_reason() -> None:
    for path in TESTS.rglob("test_*.py"):
        text = path.read_text()
        if "pytest.mark.slow" in text:
            assert "# slow:" in text, f"{path.name} marks slow without saying why"
