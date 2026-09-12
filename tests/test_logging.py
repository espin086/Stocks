"""Structured logging: stderr always, JSON when not a TTY, run id on every record.

Scenarios: stdout is results only; Machine output stays parseable; Every record
is structured; Human and machine renderings; Levels mean something specific;
Correlation; Context accumulates; Third-party noise is controlled; Optional
file sink; Failures carry cause; Storage; Computation boundaries.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
import structlog

from sobres.observability import configure_logging, get_logger, new_run_id, run_id
from sobres.observability.logging import resolve_level


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


_ANSI = __import__("re").compile(r"\x1b\[[0-9;]*m")


def _records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_all_records_go_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", "json")  # stream resolved at call time: pytest's stderr
    get_logger("t").warning("hello", n=1)
    logging.getLogger("third.party").warning("stdlib too")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Logging error" not in captured.err
    records = [json.loads(line) for line in captured.err.splitlines() if line.strip()]
    assert [r["event"] for r in records] == ["hello", "stdlib too"]
    assert records[1]["logger"] == "third.party" and records[1]["level"] == "warning"


def test_json_output_parseable_at_debug_level() -> None:
    err = io.StringIO()
    configure_logging("DEBUG", "json", stream=err)
    new_run_id()
    log = get_logger("sobres.test")
    log.debug("d", x=1)
    log.info("i", y="two")
    log.error("e", exc_info=ValueError("bad"))
    records = _records(err)
    assert [r["level"] for r in records] == ["debug", "info", "error"]
    for r in records:
        assert {"timestamp", "level", "logger", "event", "run_id"} <= set(r)
    assert records[0]["x"] == 1 and records[1]["y"] == "two"
    assert "ValueError" in str(records[2]["exception"])


def test_run_id_on_every_record() -> None:
    err = io.StringIO()
    configure_logging("INFO", "json", stream=err)
    rid = new_run_id()
    assert run_id() == rid and len(rid) == 12
    get_logger("a").info("one")
    with structlog.contextvars.bound_contextvars(provider="yfinance"):
        get_logger("b").info("two")
    get_logger("c").info("three")
    records = _records(err)
    assert all(r["run_id"] == rid for r in records)
    assert records[1]["provider"] == "yfinance" and "provider" not in records[2]


def test_human_rendering_on_a_tty() -> None:
    err = _Tty()
    configure_logging("INFO", "auto", stream=err)
    get_logger("a").info("human", mode="value")
    text = _ANSI.sub("", err.getvalue())
    assert "human" in text and "mode=value" in text
    assert not text.lstrip().startswith("{")
    plain = io.StringIO()
    configure_logging("INFO", "human", stream=plain)
    get_logger("a").info("forced human")
    assert not plain.getvalue().lstrip().startswith("{")


def test_default_level_is_warning_and_third_party_noise_is_suppressed() -> None:
    err = io.StringIO()
    configure_logging(stream=err)
    get_logger("a").info("hidden")
    logging.getLogger("yfinance").info("chatter")
    get_logger("a").warning("shown")
    records = _records(err)
    assert [r["event"] for r in records] == ["shown"]
    err = io.StringIO()
    configure_logging("DEBUG", "json", stream=err)
    logging.getLogger("yfinance").info("still hidden at DEBUG unless asked")
    assert _records(err) == []


def test_resolve_level_accepts_names_and_ints() -> None:
    assert resolve_level("debug") == logging.DEBUG and resolve_level(logging.ERROR) == logging.ERROR
    with pytest.raises(ValueError):
        resolve_level("loud")


def test_file_sink_writes_json_and_rotates(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "s.log"
    configure_logging("INFO", "json", stream=io.StringIO(), log_file=log_file)
    get_logger("a").info("to file", k=1)
    for handler in logging.getLogger().handlers:
        handler.flush()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "to file" and lines[0]["k"] == 1
    rotating = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert rotating and rotating[0].backupCount == 5 and rotating[0].maxBytes == 10 * 1024 * 1024
    configure_logging("WARNING", "json", stream=io.StringIO())


def test_get_logger_configures_lazily() -> None:
    from sobres.observability import logging as mod

    mod._configured["level"] = None
    log = get_logger("lazy")
    assert log is not None and mod._configured["level"] is not None
