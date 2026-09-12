"""The error taxonomy: one base, narrow leaves, each with an exit code.

Design (0001): ``SobresError`` → 1, ``UsageError`` → 2, ``ConfigurationError``
→ 3, ``ProviderError`` → 4, ``InsufficientDataError`` → 5. The CLI maps an
exception to its class's ``exit_code`` and prints the message; a traceback is
never shown for an anticipated failure unless ``--debug`` is given.

Every message for a code-3/4/5 error states what failed *and* the next action.
"""

from __future__ import annotations

from typing import ClassVar


class SobresError(Exception):
    """Base of every anticipated failure. Unexpected internal error → exit 1."""

    exit_code: ClassVar[int] = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n  next: {self.hint}"
        return self.message


class UsageError(SobresError):
    """Bad input: an invalid flag value, an infeasible constraint, mixed units."""

    exit_code = 2


class ConfigurationError(SobresError):
    """A missing key, an unreadable config file, an unknown storage backend."""

    exit_code = 3


class CorruptDatabaseError(ConfigurationError):
    """The database failed its integrity check on open."""


class ProviderError(SobresError):
    """The upstream data source failed, timed out, or changed shape."""

    exit_code = 4

    def __init__(
        self, message: str, *, provider: str | None = None, hint: str | None = None
    ) -> None:
        prefix = f"{provider}: " if provider else ""
        super().__init__(prefix + message, hint=hint)
        self.provider = provider


class UnknownTickerError(ProviderError):
    """A requested symbol returned no data from the provider."""

    def __init__(self, symbol: str, *, provider: str | None = None) -> None:
        super().__init__(
            f"no data returned for ticker {symbol!r}",
            provider=provider,
            hint="check the symbol spelling and exchange suffix (e.g. NESN.SW, 7203.T)",
        )
        self.symbol = symbol


class InsufficientDataError(SobresError):
    """Fewer observations than the requested computation needs."""

    exit_code = 5


class AlignmentError(InsufficientDataError):
    """Series from different sources share too little (or no) overlap."""


class OptimizationError(SobresError):
    """The solver did not converge. Reserved by 0002; declared with the taxonomy."""

    exit_code = 1


class StorageError(SobresError):
    """A storage operation failed for a reason other than configuration."""

    exit_code = 1


class StorageConflictError(StorageError):
    """A write conflicted with an existing row (unique / primary-key violation)."""


class StorageConstraintError(StorageError):
    """A write violated a constraint other than uniqueness (check, not-null, FK)."""


class StorageLockedError(StorageError):
    """Two writers contended past the bounded retry limit."""


EXIT_CODES: dict[type[SobresError], int] = {
    SobresError: 1,
    UsageError: 2,
    ConfigurationError: 3,
    ProviderError: 4,
    InsufficientDataError: 5,
}
"""The public exit-code contract, in one place, for the tests to check against."""
