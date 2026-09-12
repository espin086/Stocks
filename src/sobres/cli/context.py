"""The runtime context handed to every handler: config, storage, providers, I/O.

Handlers are adapters: they take the parameter model and this context, call the
data layer and ``core``, and return a typed result. Everything that touches the
world — the resolved configuration, the opened storage, the provider instances,
prompts and confirmations — is reached through here, which is what lets the
invariant tests run every command with a fake environment.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sobres.config import Config, resolve
from sobres.data.base import FactorProvider, FxProvider, MacroProvider, PriceProvider
from sobres.data.cache import ObservationCache
from sobres.data.storage.base import OpenOptions, Storage, open_storage
from sobres.observability import get_logger
from sobres.settings import FIXTURE_DIR, FRED_API_KEY, IMPLAUSIBLE_MOVE, SLOW_QUERY_MS


@dataclass
class Context:
    config: Config
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    refresh: bool = False
    fmt: str | None = None
    debug: bool = False
    interactive: bool = field(default_factory=lambda: bool(sys.stdin.isatty()))
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    stderr: Any = field(default_factory=lambda: sys.stderr)
    stdin: Any = field(default_factory=lambda: sys.stdin)
    confirm: Callable[[str], bool] | None = None
    prompt: Callable[[str, bool], str] | None = None
    sources: dict[str, Any] = field(default_factory=dict)
    """Test doubles for provider sources keyed by provider name."""
    open_options: OpenOptions = field(default_factory=OpenOptions)
    pending_exit_code: int = 0
    """Set by a handler whose result renders normally but must exit non-zero (doctor)."""
    _storage: Storage | None = field(default=None, repr=False)
    _cache: ObservationCache | None = field(default=None, repr=False)

    # ------------------------------------------------------------ construction
    @classmethod
    def build(
        cls,
        overrides: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
        *,
        config_path: Path | None = None,
        **kwargs: Any,
    ) -> Context:
        env = dict(os.environ) if environ is None else dict(environ)
        config = resolve(overrides, env, path=config_path)
        return cls(config=config, environ=env, **kwargs)

    @property
    def log(self) -> Any:
        return get_logger("sobres.cli")

    def today(self) -> date:
        return self.clock().date()

    # ----------------------------------------------------------------- storage
    @property
    def storage(self) -> Storage:
        if self._storage is None:
            self._storage = open_storage(self.config.db_url, self.open_options)
        return self._storage

    @property
    def cache(self) -> ObservationCache:
        if self._cache is None:
            self._cache = ObservationCache(self.storage.observations, clock=self.clock)
        return self._cache

    def close(self) -> None:
        if self._storage is not None:
            self._storage.close()
            self._storage = None
            self._cache = None

    # --------------------------------------------------------------- providers
    def _source(self, provider: str) -> Any:
        if provider in self.sources:
            return self.sources[provider]
        fixture_dir = self.config.get(FIXTURE_DIR.key)
        if fixture_dir:
            from sobres.data.fixtures import fixture_source

            self.sources[provider] = fixture_source(provider, Path(str(fixture_dir)))
            return self.sources[provider]
        return None

    def price_provider(self) -> PriceProvider:
        from sobres.data.yfinance_provider import YFinanceProvider

        return YFinanceProvider(
            source=self._source("yfinance"),
            cache=self.cache,
            implausible_move=float(self.config.get(IMPLAUSIBLE_MOVE.key)),
            refresh=self.refresh,
        )

    def macro_provider(self) -> MacroProvider:
        from sobres.data.fred_provider import FredProvider

        return FredProvider(
            self.config.get(FRED_API_KEY.key),
            source=self._source("fred"),
            cache=self.cache,
            refresh=self.refresh,
        )

    def factor_provider(self) -> FactorProvider:
        from sobres.data.ken_french import KenFrenchProvider

        return KenFrenchProvider(
            source=self._source("ken_french"), cache=self.cache, refresh=self.refresh
        )

    def fx_provider(self) -> FxProvider:
        from sobres.data.ecb_provider import EcbProvider

        return EcbProvider(source=self._source("ecb"), cache=self.cache, refresh=self.refresh)

    # --------------------------------------------------------------------- I/O
    def ask_confirm(self, question: str, *, default: bool = False) -> bool:
        if self.confirm is not None:
            return self.confirm(question)
        if not self.interactive:
            return default
        import typer

        return bool(typer.confirm(question, default=default))

    def ask(self, question: str, *, secret: bool = False, default: str = "") -> str:
        if self.prompt is not None:
            return self.prompt(question, secret)
        if not self.interactive:
            return default
        import typer

        answer = typer.prompt(
            question, default=default or None, hide_input=secret, show_default=False
        )
        return str(answer) if answer is not None else ""

    def note(self, message: str) -> None:
        """A human-facing line on stderr; never stdout."""
        print(message, file=self.stderr)

    @property
    def slow_query_ms(self) -> int:
        return int(self.config.get(SLOW_QUERY_MS.key))
