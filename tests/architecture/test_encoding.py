"""Portability rules are code, not review.

Scenario: Layering rules are code.

Windows defaults text I/O to the console code page (cp1252), macOS and Linux to
UTF-8. Every spec, fixture and source file in this repository is UTF-8, so a
text-mode read or write that leaves the encoding to the platform passes on the
developer's laptop and fails on the next platform in CI. The rule: every text-mode
``read_text`` / ``write_text`` / ``open`` names its encoding.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCANNED = ("src", "tests", "scripts", "site/scripts", ".github/scripts")
TEXT_METHODS = {"read_text", "write_text"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for sub in SCANNED:
        root = REPO / sub
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _binary_mode(call: ast.Call) -> bool:
    # ``open(path, mode)`` versus ``path.open(mode)``: the mode's position differs.
    index = 0 if isinstance(call.func, ast.Attribute) else 1
    mode: ast.expr | None = call.args[index] if len(call.args) > index else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _names_encoding(call: ast.Call) -> bool:
    return any(keyword.arg == "encoding" for keyword in call.keywords)


# ``.open`` on these is not a text file: descriptors, archives, compressed streams, a browser.
NOT_A_TEXT_FILE = {"os", "webbrowser", "tarfile", "zipfile", "gzip", "bz2", "lzma", "socket"}


def _is_os_call(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in NOT_A_TEXT_FILE
    )


def _offenders(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS:
            if not _names_encoding(node):
                lines.append(node.lineno)
        elif (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr == "open"
        ):
            if _is_os_call(func):
                continue
            if not _binary_mode(node) and not _names_encoding(node):
                lines.append(node.lineno)
    return lines


def test_every_text_mode_file_access_names_its_encoding() -> None:
    found = [
        f"{path.relative_to(REPO)}:{lineno}"
        for path in _python_files()
        for lineno in _offenders(path)
    ]
    assert not found, "text I/O without encoding= (breaks on Windows):\n  " + "\n  ".join(found)
