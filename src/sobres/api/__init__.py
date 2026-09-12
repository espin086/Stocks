"""The HTTP adapter (0004): FastAPI routes generated from the command registry.

No business logic lives here — request handling, validation, serialization,
job dispatch and access control only. ``pip install sobres[web]`` brings the
runtime; the built SPA ships under ``static/``. ``create_app`` is imported
lazily so the base install (no FastAPI) can still import ``sobres.api.auth``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_app"]


def create_app(*args: Any, **kwargs: Any) -> Any:
    from sobres.api.app import create_app as _create_app

    return _create_app(*args, **kwargs)
