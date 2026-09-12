"""OpenTelemetry tracing: the API when installed and configured, a no-op otherwise.

An ordinary install carries no tracing dependency. When the standard
``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_TRACES_EXPORTER`` variables are set the
SDK (``pip install sobres[otel]``) is activated with no flag; if the SDK is
missing the tool warns once and continues. An unreachable exporter warns once
and never fails a command.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Protocol

from sobres.observability.redaction import scrub_mapping

_state: dict[str, Any] = {"tracer": None, "active": False, "warned": False}


class Span(Protocol):
    def set_attribute(self, key: str, value: Any) -> None: ...
    def record_exception(self, exc: BaseException) -> None: ...
    def set_error(self, description: str) -> None: ...
    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None: ...


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def set_error(self, description: str) -> None:
        return None

    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None:
        return None


class _OtelSpan:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def set_attribute(self, key: str, value: Any) -> None:
        scrubbed = scrub_mapping({key: value})[key]
        self._inner.set_attribute(key, scrubbed if _is_attr(scrubbed) else str(scrubbed))

    def record_exception(self, exc: BaseException) -> None:
        self._inner.record_exception(exc)

    def set_error(self, description: str) -> None:
        from opentelemetry.trace import Status, StatusCode

        self._inner.set_status(Status(StatusCode.ERROR, description))

    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None:
        attrs = scrub_mapping(attributes or {})
        self._inner.add_event(name, {k: v for k, v in attrs.items() if _is_attr(v)})


def _is_attr(value: Any) -> bool:
    return isinstance(value, str | bool | int | float)


class _OnceFilter(logging.Filter):
    """Let the exporter complain once, at WARNING, then drop the repeats."""

    def __init__(self) -> None:
        super().__init__()
        self.seen = False

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING or self.seen:
            return False
        self.seen = True
        record.levelno = logging.WARNING
        record.levelname = "WARNING"
        return True


_EXPORTER_LOGGERS = ("opentelemetry.sdk.trace.export", "opentelemetry.exporter.otlp")


def configure_tracing(
    endpoint: str | None,
    exporter: str | None,
    *,
    warn: Any = None,
) -> bool:
    """Activate the SDK when OTEL_* asks for it. Returns whether tracing is on.

    ``warn`` is a callable taking a message, used exactly once if the SDK is
    absent — the adapters own logging, so this module never logs itself.
    """
    _state.update(tracer=None, active=False)
    wants = bool(endpoint) or (exporter not in (None, "", "none"))
    if not wants:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        if warn is not None and not _state["warned"]:
            _state["warned"] = True
            warn(
                "OTEL_* is set but the OpenTelemetry SDK is not installed; "
                "run: pip install 'sobres[otel]'"
            )
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": "sobres"}))
    if exporter == "console":
        # stdout carries results only; spans are diagnostics and go to stderr.
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:  # pragma: no cover - the extra installs it
            if warn is not None and not _state["warned"]:
                _state["warned"] = True
                warn("OTLP exporter missing; run: pip install 'sobres[otel]'")
            return False
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    once = _OnceFilter()
    for name in _EXPORTER_LOGGERS:
        logger = logging.getLogger(name)
        for old in [f for f in logger.filters if isinstance(f, _OnceFilter)]:
            logger.removeFilter(old)
        logger.addFilter(once)
    # The global provider can only be set once per process; use ours directly so a
    # re-configuration (tests, a long-lived server) still traces through it.
    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        trace.set_tracer_provider(provider)
    _state.update(tracer=provider.get_tracer("sobres"), active=True, provider=provider)
    return True


def is_active() -> bool:
    return bool(_state["active"])


def shutdown() -> None:
    """Flush pending spans; never raises."""
    if not _state["active"]:
        return
    with contextlib.suppress(Exception):
        provider = _state.get("provider")
        flush = getattr(provider, "force_flush", None)
        if flush is not None:
            flush(timeout_millis=2000)


def current_trace_ids() -> tuple[str, str] | None:
    """(trace_id, span_id) as hex when inside an active span, else None."""
    if not _state["active"]:
        return None
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


class _SpanContext:
    def __init__(
        self,
        name: str,
        attributes: Mapping[str, Any] | None,
        carrier: Mapping[str, str] | None = None,
    ) -> None:
        self._name = name
        self._attributes = dict(attributes or {})
        self._carrier = dict(carrier or {})
        self._cm: Any = None
        self._span: Span = _NoopSpan()

    def __enter__(self) -> Span:
        tracer = _state["tracer"]
        if tracer is None:
            return self._span
        parent = None
        if self._carrier:
            from opentelemetry.propagate import extract

            parent = extract(self._carrier)
        self._cm = tracer.start_as_current_span(self._name, context=parent)
        inner = self._cm.__enter__()
        self._span = _OtelSpan(inner)
        for key, value in self._attributes.items():
            self._span.set_attribute(key, value)
        return self._span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None:
            self._span.record_exception(exc)
            self._span.set_error(type(exc).__name__)
        if self._cm is not None:
            self._cm.__exit__(exc_type, exc, tb)


def span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    *,
    carrier: Mapping[str, str] | None = None,
) -> _SpanContext:
    """Open a span; a no-op unless tracing is active. Attributes are redacted.

    ``carrier`` holds inbound W3C trace headers (``traceparent``) so an HTTP
    request's span becomes a child of the caller's trace.
    """
    return _SpanContext(name, attributes, carrier)
