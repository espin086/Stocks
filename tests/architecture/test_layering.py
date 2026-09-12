"""Layering rules are code, not review.

Scenarios: Layering rules are code; Literals that must not exist; Core stays
pure; Drivers are confined to adapters; Call sites are vendor-agnostic; Core
remains I/O-free; Repositories perform no computation; No business logic;
Consistency with the data providers; Provider protocols are the same pattern;
Kinds and their locations; Markers are declared; No Typer command exists that
is not a registry declaration.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "sobres"
TESTS = REPO / "tests"

NETWORK_MODULES = {
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "socket",
    "aiohttp",
    "yfinance",
    "pandas_datareader",
}
DB_MODULES = {"sqlite3", "sqlalchemy", "psycopg", "psycopg2", "duckdb", "alembic"}
LOGGING_MODULES = {"logging", "structlog", "opentelemetry"}
NUMERIC_MODULES = {"numpy", "scipy", "statsmodels", "cvxpy", "sklearn"}
VENDOR_MODULES = {"yfinance", "pandas_datareader"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _full_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _files(sub: str) -> list[Path]:
    return sorted((SRC / sub).rglob("*.py"))


def test_core_imports_no_network_database_logging_or_tracing() -> None:
    for path in _files("core"):
        imported = _imports(path)
        assert not imported & NETWORK_MODULES, f"{path.name} imports network"
        assert not imported & DB_MODULES, f"{path.name} imports a database module"
        assert not imported & LOGGING_MODULES, f"{path.name} imports logging or tracing"
        assert not any(m.startswith("sobres.data") for m in _full_imports(path)), path.name
        assert not any(m.startswith("sobres.cli") for m in _full_imports(path)), path.name
        assert "open(" not in path.read_text().replace("os.open", ""), f"{path.name} opens a file"


def test_core_imports_no_logging_or_tracing() -> None:
    for path in _files("core"):
        assert not _imports(path) & LOGGING_MODULES, path.name


def test_db_drivers_imported_only_in_adapters() -> None:
    for path in SRC.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        assert not _imports(path) & DB_MODULES, f"{path.relative_to(SRC)} imports a database driver"


def test_cli_and_api_import_no_numerical_library() -> None:
    for sub in ("cli", "api"):
        if not (SRC / sub).exists():
            continue
        for path in _files(sub):
            assert not _imports(path) & NUMERIC_MODULES, f"{path.relative_to(SRC)} does math"


def test_vendor_modules_only_inside_data_layer() -> None:
    for path in SRC.rglob("*.py"):
        if path.is_relative_to(SRC / "data"):
            continue
        assert not _imports(path) & VENDOR_MODULES, f"{path.relative_to(SRC)} imports a vendor"


def test_storage_layer_imports_no_core_math() -> None:
    for path in _files("data/storage"):
        full = _full_imports(path)
        assert not any(m.startswith("sobres.core") and m != "sobres.core.errors" for m in full), (
            path.name
        )
        assert not _imports(path) & NUMERIC_MODULES, path.name


RATE_MULTIPLY = re.compile(r"[*/]\s*(rate|rates|fx_rate|fx)\b|\b(rate|rates|fx_rate)\s*[*/]")


def test_no_rate_arithmetic_outside_currency_module() -> None:
    for path in SRC.rglob("*.py"):
        if path.name == "currency.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            assert not RATE_MULTIPLY.search(code), (
                f"{path.relative_to(SRC)}:{lineno} applies a rate"
            )


PERIODS_LITERAL = re.compile(r"(?<![\w.])(252|52|12)(?![\w.])")
ANNUALIZATION_HINT = re.compile(r"annual|sqrt|periods", re.IGNORECASE)


def test_no_bare_periods_per_year_literal_outside_conventions() -> None:
    for path in SRC.rglob("*.py"):
        if path.name == "conventions.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            if PERIODS_LITERAL.search(code) and ANNUALIZATION_HINT.search(code):
                pytest.fail(
                    f"{path.relative_to(SRC)}:{lineno} carries a bare periods-per-year literal"
                )


def test_no_typer_command_outside_the_generator() -> None:
    pattern = re.compile(r"@\w+\.command\(|\.command\(")
    for path in SRC.rglob("*.py"):
        if path.name in {"registry.py"}:
            continue
        text = path.read_text()
        assert not pattern.search(text), f"{path.relative_to(SRC)} adds a Typer command by hand"


def test_test_taxonomy_directories_and_markers() -> None:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert "--strict-markers" in options["addopts"]
    markers = {m.split(":")[0] for m in options["markers"]}
    assert markers == {"network", "slow"}
    for sub in ("core", "data", "cli", "architecture", "invariants", "network"):
        assert (TESTS / sub).is_dir(), sub
    for path in TESTS.rglob("test_*.py"):
        if path.parent == TESTS:
            continue  # cross-cutting suites at the top level are allowed by 0000
        assert path.parent.name in {
            "core",
            "data",
            "cli",
            "architecture",
            "invariants",
            "network",
        }, path


def test_network_tests_are_marked() -> None:
    for path in (TESTS / "network").rglob("test_*.py"):
        assert "pytest.mark.network" in path.read_text(), path
