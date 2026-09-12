"""Redaction at the formatter: secrets never reach a log or a span.

Scenarios: Redaction; Secrets in URLs; Enforced by test.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import pytest

from sobres.observability import configure_logging, get_logger
from sobres.observability.redaction import REDACTED, scrub_mapping, scrub_text, scrub_value
from sobres.registry import all_commands
from tests.conftest import SENTINEL_KEY
from tests.invariants.test_every_command import SAMPLE_ARGS


def test_keys_matching_sensitive_names_are_redacted() -> None:
    event = {
        "api_key": "x",
        "Authorization": "Bearer y",
        "password": "p",
        "my_token": "t",
        "client_secret": "s",
        "nested": {"fred_api_key": "k", "fine": "v"},
        "list": ["http://u:p@h/", {"token": 1}],
        "fine": "value",
    }
    out = scrub_mapping(event)
    assert out["api_key"] == REDACTED and out["Authorization"] == REDACTED
    assert out["password"] == REDACTED and out["my_token"] == REDACTED
    assert out["client_secret"] == REDACTED
    assert out["nested"] == {"fred_api_key": REDACTED, "fine": "v"}
    assert out["list"] == [f"http://{REDACTED}@h/", {"token": REDACTED}]
    assert out["fine"] == "value"


def test_api_key_stripped_from_logged_url() -> None:
    url = "https://api.stlouisfed.org/fred/series?series_id=DGS10&api_key=ABC123&file_type=json"
    assert (
        scrub_text(url)
        == f"https://api.stlouisfed.org/fred/series?series_id=DGS10&api_key={REDACTED}&file_type=json"
    )
    assert scrub_text("postgresql://user:pass@db/x") == f"postgresql://{REDACTED}@db/x"
    assert scrub_text("Authorization: Bearer abc.def") == f"Authorization: Bearer {REDACTED}"
    assert scrub_text("nothing here") == "nothing here"
    exc = scrub_value(None, ValueError("token=abc"))
    assert isinstance(exc, ValueError) and str(exc) == f"token={REDACTED}"
    assert scrub_value("count", 3) == 3


def test_formatter_redacts_records_including_exception_context() -> None:
    err = io.StringIO()
    configure_logging("DEBUG", "json", stream=err)
    get_logger("t").info("fetch", url="https://x/?api_key=SECRET", api_key="SECRET", fine="ok")
    try:
        raise RuntimeError("password=SECRET in message")
    except RuntimeError:
        get_logger("t").exception("failed")
    text = err.getvalue()
    assert "SECRET" not in text
    record = json.loads(text.splitlines()[0])
    assert record["api_key"] == REDACTED and record["fine"] == "ok"


@pytest.mark.parametrize("name", [c.name for c in all_commands()])
def test_sentinel_credential_never_in_stderr(
    name: str, cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres import doctor as doc

    monkeypatch.setattr(doc, "latest_release", lambda: None)
    args = SAMPLE_ARGS[name]
    env_extra = {"SOBRES_FRED_API_KEY": SENTINEL_KEY, "SOBRES_LOG_LEVEL": "DEBUG"}
    result = (
        cli("--log-level", "DEBUG", *args, "--format", "json", env_extra=env_extra)
        if "--format" not in args
        else cli("--log-level", "DEBUG", *args, env_extra=env_extra)
    )
    assert SENTINEL_KEY not in result.stderr, name
    assert SENTINEL_KEY not in result.stdout, name
