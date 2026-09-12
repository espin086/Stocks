"""The error taxonomy and its exit codes.

Scenarios: Exit code contract; Actionable messages.
"""

from __future__ import annotations

import pytest

from sobres.core import errors
from sobres.core.errors import (
    EXIT_CODES,
    AlignmentError,
    ConfigurationError,
    CorruptDatabaseError,
    InsufficientDataError,
    ProviderError,
    SobresError,
    UnknownTickerError,
    UsageError,
)


def _leaves() -> list[type[SobresError]]:
    return [
        obj
        for obj in vars(errors).values()
        if isinstance(obj, type) and issubclass(obj, SobresError)
    ]


def test_exit_code_mapping_is_exhaustive() -> None:
    """Every class in the tree maps to one of the five documented codes."""
    assert {
        SobresError: 1,
        UsageError: 2,
        ConfigurationError: 3,
        ProviderError: 4,
        InsufficientDataError: 5,
    } == EXIT_CODES
    for cls in _leaves():
        assert cls.exit_code in {1, 2, 3, 4, 5}, cls
        base = next(b for b in cls.__mro__ if b in EXIT_CODES)
        assert cls.exit_code == EXIT_CODES[base], f"{cls.__name__} inherits a different code"


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (UsageError, 2),
        (ConfigurationError, 3),
        (CorruptDatabaseError, 3),
        (ProviderError, 4),
        (UnknownTickerError, 4),
        (InsufficientDataError, 5),
        (AlignmentError, 5),
    ],
)
def test_subclasses_inherit_their_family_code(cls: type[SobresError], code: int) -> None:
    assert cls.exit_code == code


def test_message_carries_next_step() -> None:
    err = ConfigurationError("key missing", hint="run: sobres config set fred_api_key <KEY>")
    assert "key missing" in str(err)
    assert "next: run: sobres config set" in str(err)


def test_unknown_ticker_names_symbol_and_provider() -> None:
    err = UnknownTickerError("ZZZZ", provider="yfinance")
    assert err.symbol == "ZZZZ"
    assert "yfinance" in str(err) and "ZZZZ" in str(err)
    assert err.exit_code == 4


def test_provider_error_without_provider_has_no_prefix() -> None:
    assert str(ProviderError("boom")) == "boom"
