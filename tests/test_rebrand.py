"""0011 — the rename is complete: no residual old name anywhere it matters.

Scenario: No residual old name (packaging spec, 0011).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Where the old names are allowed to survive: the changelog records history,
# the 0011 change documents the rename itself, and legacy_code/ is the
# pre-rewrite work preserved as-is.
ALLOWED = {
    REPO_ROOT / "CHANGELOG.md",
}
ALLOWED_DIRS = (
    REPO_ROOT / "openspec" / "changes" / "0011-rebrand-sobres",
    REPO_ROOT / "openspec" / "changes" / "0000-release-engineering",
    REPO_ROOT / "legacy_code",
    REPO_ROOT / ".git",
)
SCANNED_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".cfg", ".txt", ".ini", ".json"}

OLD_NAME = re.compile("quant" + "folio", re.IGNORECASE)
OLD_SCRIPT = re.compile(r"\b" + "q" + "f" + r"\b")


def _scannable_files() -> list[Path]:
    files = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if path in ALLOWED or any(path.is_relative_to(d) for d in ALLOWED_DIRS):
            continue
        if any(part in {"node_modules", ".venv", "dist", "build"} for part in path.parts):
            continue
        files.append(path)
    return files


def test_no_residual_old_name() -> None:
    offenders = []
    for path in _scannable_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if OLD_NAME.search(line) or OLD_SCRIPT.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "old name still present:\n" + "\n".join(offenders)
