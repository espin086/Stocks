"""Tracing: no-op by default, SDK behind the extra, never fatal.

Scenarios: OpenTelemetry, opt-in; Enabling; Spanned operations; Span attributes;
Failed spans; Logs and traces correlate; Never fatal; Adapters instrument the
calls they make.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from sobres.observability import configure_logging, get_logger, new_run_id
from sobres.observability import tracing as tr


@pytest.fixture(autouse=True)
def _reset() -> Any:
    yield
    tr.shutdown()
    tr._state.update(tracer=None, active=False, warned=False)


def test_noop_by_default_without_sdk() -> None:
    assert tr.configure_tracing(None, None) is False
    assert not tr.is_active() and tr.current_trace_ids() is None
    with tr.span("x", {"a": 1}) as sp:
        sp.set_attribute("k", "v")
        sp.add_event("e")
        sp.record_exception(ValueError("x"))
        sp.set_error("d")
    assert tr.configure_tracing("", "none") is False


def test_missing_sdk_warns_once_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("opentelemetry.sdk"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    warnings: list[str] = []
    assert tr.configure_tracing("http://collector:4318", None, warn=warnings.append) is False
    assert tr.configure_tracing("http://collector:4318", None, warn=warnings.append) is False
    assert len(warnings) == 1 and "sobres[otel]" in warnings[0]


def test_records_carry_trace_id_when_active() -> None:
    pytest.importorskip("opentelemetry.sdk")
    err = io.StringIO()
    configure_logging("INFO", "json", stream=err)
    assert tr.configure_tracing(None, "console") is True
    rid = new_run_id()
    with tr.span("cli.test", {"command": "test", "api_key": "SECRET"}) as sp:
        sp.set_attribute("rows", 3)
        sp.add_event("progress", {"token": "SECRET", "n": 1})
        ids = tr.current_trace_ids()
        get_logger("t").info("inside")
    assert ids is not None and len(ids[0]) == 32 and len(ids[1]) == 16
    records = [json.loads(line) for line in err.getvalue().splitlines() if line.strip()]
    [record] = [r for r in records if r["event"] == "inside"]
    assert record["trace_id"] == ids[0] and record["span_id"] == ids[1] and record["run_id"] == rid
    assert "SECRET" not in err.getvalue()


def test_failed_span_records_exception_and_error_status() -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tr._state.update(tracer=provider.get_tracer("t"), active=True)
    with pytest.raises(ValueError), tr.span("boom", {"n": 1}):
        raise ValueError("bad")
    [finished] = exporter.get_finished_spans()
    assert finished.status.status_code.name == "ERROR"
    assert finished.attributes["n"] == 1
    assert any(e.name == "exception" for e in finished.events)


def test_exporter_failure_does_not_fail_command(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry.sdk")
    err = io.StringIO()
    configure_logging("WARNING", "json", stream=err)
    assert tr.configure_tracing(None, "console") is True  # the filter, not the wire, is under test
    exporter_log = logging.getLogger("opentelemetry.sdk.trace.export")
    for _ in range(3):
        exporter_log.error("Exception while exporting Span batch.")
    exporter_log.info("noise")
    with tr.span("work"):
        pass
    tr.shutdown()
    lines = [json.loads(line) for line in err.getvalue().splitlines() if line.strip()]
    warnings = [r for r in lines if "exporting Span batch" in str(r.get("event"))]
    assert len(warnings) == 1 and warnings[0]["level"] == "warning"


def test_activation_from_environment_through_the_cli(cli: Any) -> None:
    pytest.importorskip("opentelemetry.sdk")
    result = cli("commands", "--format", "json", env_extra={"OTEL_TRACES_EXPORTER": "console"})
    assert result.exit_code == 0
    json.loads(result.stdout)  # console exporter output never reaches stdout
