"""Shared fixtures: an isolated environment, fixture-backed providers, a CLI runner.

Every test runs against a temporary config file and SQLite database and
against the recorded payloads under ``tests/fixtures/``; nothing touches the
network or the developer's real configuration.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sobres.cli.context import Context
from sobres.data.fixtures import (
    FixtureEcbSource,
    FixtureFredSource,
    FixtureKenFrenchSource,
    FixtureYahooSource,
)
from sobres.data.storage.base import OpenOptions, Storage, open_storage
from sobres.observability import configure_logging

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SENTINEL_KEY = "SENTINEL-SECRET-abcdef1234567890"
FROZEN_NOW = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURES


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A clean environment: temp config, temp database, fixture-backed providers."""
    return {
        "SOBRES_CONFIG_FILE": str(tmp_path / "config" / "config.toml"),
        "SOBRES_DB_URL": f"sqlite:///{(tmp_path / 'data' / 'sobres.db').as_posix()}",
        "SOBRES_FIXTURE_DIR": str(FIXTURES),
        "SOBRES_LOG_FORMAT": "json",
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ.get("PATH", ""),
    }


@pytest.fixture
def make_context(env: dict[str, str]) -> Callable[..., Context]:
    """Build a ``Context`` over the isolated environment (frozen clock, no prompts)."""
    contexts: list[Context] = []

    def factory(**overrides: Any) -> Context:
        environ = dict(env)
        environ.update(overrides.pop("environ", {}))
        confirm = overrides.pop("confirm", lambda _q: True)
        ctx = Context.build(
            overrides.pop("overrides", None),
            environ,
            config_path=Path(environ["SOBRES_CONFIG_FILE"]),
            clock=lambda: FROZEN_NOW,
            interactive=False,
            confirm=confirm,
            **overrides,
        )
        contexts.append(ctx)
        return ctx

    yield factory  # type: ignore[misc]
    for ctx in contexts:
        ctx.close()


@pytest.fixture
def yahoo_source() -> FixtureYahooSource:
    return FixtureYahooSource(FIXTURES)


@pytest.fixture
def fred_source() -> FixtureFredSource:
    return FixtureFredSource(FIXTURES)


@pytest.fixture
def ecb_source() -> FixtureEcbSource:
    return FixtureEcbSource(FIXTURES)


@pytest.fixture
def ken_french_source() -> FixtureKenFrenchSource:
    return FixtureKenFrenchSource(FIXTURES)


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[Storage]:
    store = open_storage(f"sqlite:///{(tmp_path / 'store.db').as_posix()}", OpenOptions())
    yield store
    store.close()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli(runner: CliRunner, env: dict[str, str]) -> Callable[..., Any]:
    """Invoke the real Typer app in the isolated environment; returns the result."""
    from sobres.cli.main import app

    def invoke(
        *args: str, env_extra: dict[str, str] | None = None, input: str | None = None
    ) -> Any:
        environ = dict(env)
        environ.update(env_extra or {})
        configure_logging("WARNING", "json")
        return runner.invoke(app, list(args), env=environ, input=input, catch_exceptions=False)

    return invoke


@pytest.fixture(autouse=True)
def _quiet_logging() -> Iterator[None]:
    configure_logging("WARNING", "json")
    yield


def read_json(text: str) -> Any:
    """Parse stdout that must be exactly one JSON document."""
    return json.loads(text)
