"""structlog wired to stderr, human on a TTY and JSON otherwise.

Rules (observability spec, 0001):

* every record goes to stderr — stdout is results only;
* a run id is bound to every record and quoted in the final error message;
* third-party loggers are routed through the same handler at WARNING;
* an optional JSON file sink rotates by size with a bounded backup count.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from pathlib import Path
from typing import Any, TextIO

import structlog

from sobres.observability.redaction import redact_processor

_RUN_ID_KEY = "run_id"
_configured: dict[str, Any] = {"level": None, "stream": None, "file": None}

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
NOISY_LOGGERS = (
    "yfinance",
    "peewee",
    "urllib3",
    "httpx",
    "httpcore",
    "sqlalchemy",
    "opentelemetry",
)


def new_run_id() -> str:
    """Generate and bind a fresh correlation id for one command or request."""
    rid = uuid.uuid4().hex[:12]
    structlog.contextvars.bind_contextvars(**{_RUN_ID_KEY: rid})
    return rid


def run_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get(_RUN_ID_KEY)
    return str(value) if value is not None else None


def _add_trace_ids(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    from sobres.observability.tracing import current_trace_ids

    ids = current_trace_ids()
    if ids is not None:
        event_dict.setdefault("trace_id", ids[0])
        event_dict.setdefault("span_id", ids[1])
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_trace_ids,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_processor,
    ]


def resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    try:
        return LEVELS[level.upper()]
    except KeyError:
        raise ValueError(f"unknown log level {level!r}; use one of {', '.join(LEVELS)}") from None


def configure_logging(
    level: str | int = "WARNING",
    fmt: str = "auto",
    stream: TextIO | None = None,
    log_file: Path | None = None,
) -> None:
    """(Re)configure logging for one process. Safe to call repeatedly.

    ``fmt`` is ``auto`` (human when the stream is a TTY, JSON otherwise),
    ``human`` or ``json``. The stream defaults to ``sys.stderr`` resolved at
    call time, so test runners that swap stderr are respected.
    """
    target = stream if stream is not None else sys.stderr
    numeric = resolve_level(level)
    is_tty = bool(getattr(target, "isatty", lambda: False)())
    use_json = fmt == "json" or (fmt == "auto" and not is_tty)
    renderer: Any = (
        structlog.processors.JSONRenderer(sort_keys=True)
        if use_json
        else structlog.dev.ConsoleRenderer(colors=is_tty)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(target)
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(numeric)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=_shared_processors(),
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(sort_keys=True),
                ],
            )
        )
        root.addHandler(file_handler)
    # Third-party chatter never rises above WARNING unless asked for explicitly.
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))
    structlog.configure(
        processors=[*_shared_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured.update(level=numeric, stream=target, file=log_file)


def get_logger(name: str) -> Any:
    """A bound structlog logger. ``configure_logging`` must have run once."""
    if _configured["level"] is None:
        configure_logging()
    return structlog.get_logger(name)
