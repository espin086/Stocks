"""The settings registry.

Scenarios: Declaration shape; Four consumers, one source; A milestone cannot
add an unconfigurable key; Environment variables; Secrets never appear.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from sobres.config import mask_secret
from sobres.doctor import all_checks
from sobres.settings import ENV_PREFIX, Setting, all_settings, declare, is_secret_key

SRC = Path(__file__).resolve().parents[2] / "src" / "sobres"
ALLOWED_ENV_READERS = {"config.py", "settings.py", "main.py", "context.py"}


def _env_reads() -> dict[str, set[str]]:
    """Every ``os.environ[...]``/``os.getenv(...)`` literal in the source tree, by file."""
    found: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            literal: str | None = None
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
            ):
                literal = str(node.slice.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr in {"getenv"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    literal = str(node.args[0].value)
                if (
                    node.func.attr == "get"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "environ"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    literal = str(node.args[0].value)
            if literal is not None:
                found.setdefault(path.name, set()).add(literal)
    return found


def test_every_env_var_read_is_a_declared_setting() -> None:
    declared = {name for s in all_settings() for name in s.env_names}
    for filename, names in _env_reads().items():
        assert filename in ALLOWED_ENV_READERS, f"{filename} reads os.environ directly"
        assert names <= declared, f"{filename} reads undeclared env vars {names - declared}"


def test_no_module_touches_os_environ_outside_the_resolution_chain() -> None:
    pattern = re.compile(r"os\.environ|os\.getenv")
    for path in SRC.rglob("*.py"):
        if pattern.search(path.read_text()):
            assert path.name in ALLOWED_ENV_READERS, f"{path} touches os.environ"


def test_every_declared_env_var_starts_with_the_prefix() -> None:
    for setting in all_settings():
        if setting.standard:
            continue
        assert setting.env.startswith(ENV_PREFIX), setting.env


def test_declaration_shape() -> None:
    for s in all_settings():
        assert s.key and s.env and s.description
        assert s.type in {"str", "int", "float", "bool", "path"}
        assert isinstance(s.secret, bool) and isinstance(s.required, bool)
    fred = next(s for s in all_settings() if s.key == "fred_api_key")
    assert fred.secret and fred.obtain and fred.validate_live is not None and fred.affects


def test_every_setting_has_a_doctor_check() -> None:
    names = {c.name for c in all_checks()}
    for s in all_settings():
        assert f"setting:{s.key}" in names, s.key
        if s.validate_live is not None:
            assert f"setting-live:{s.key}" in names


def test_secret_name_rule_and_masking() -> None:
    assert (
        is_secret_key("fred_api_key") and is_secret_key("auth_token") and is_secret_key("x_secret")
    )
    assert not is_secret_key("log_level")
    assert mask_secret("abcdefgh") == "****efgh"


def test_declare_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="declared twice"):
        declare(Setting(key="fred_api_key", env="SOBRES_X", description="d"))
    with pytest.raises(ValueError, match="clashes"):
        declare(Setting(key="brand_new", env="SOBRES_LOG_LEVEL", description="d"))
