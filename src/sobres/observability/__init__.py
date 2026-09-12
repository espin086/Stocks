"""Structured logging (always on) and OpenTelemetry tracing (opt-in).

Both instrument the adapters and the I/O layer; ``core/`` imports neither.
"""

from sobres.observability.logging import configure_logging, get_logger, new_run_id, run_id
from sobres.observability.tracing import span

__all__ = ["configure_logging", "get_logger", "new_run_id", "run_id", "span"]
