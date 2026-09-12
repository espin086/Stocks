"""The HTTP adapter (0004): FastAPI routes generated from the command registry.

No business logic lives here — request handling, validation, serialization,
job dispatch and access control only. ``pip install sobres[web]`` brings the
runtime; the built SPA ships under ``static/``.
"""

from sobres.api.app import create_app

__all__ = ["create_app"]
