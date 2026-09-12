"""The HTTP adapter: routes, errors, jobs, SSE, access control, settings, observability.

Scenarios: No business logic; Work is dispatched, not awaited; Progress streams;
Jobs survive a reload; Failure is reported, not swallowed; Cancellation;
Loopback by default; Non-local binding requires a token; Tokens are generated,
never chosen; Tokens are stored hashed; Unauthenticated requests; Rotation and
revocation; Token never appears in a URL; Every request is a trace; Inbound
trace context is honored; Context crosses into the job; The trace id reaches
the client; Job progress is not a log; Errors carry the shared taxonomy; No
stack traces to clients; CORS is closed by default; Rate limiting on a
reachable deployment; Settings page is generated; Live validation in the
browser; Doctor has a view; No Node needed to install the tool; Stack; Types
come from the API; Immediate feedback; Navigation does not cancel work;
Cancellable; Run history is browsable; Re-run and compare; Portfolios are
managed in the UI; The disclaimer carries over; Never a token in the URL.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sobres.api import auth
from sobres.core.errors import UsageError
from tests.api.conftest import state_of
from tests.conftest import SENTINEL_KEY

OPT = {
    "tickers": ["AAPL", "MSFT", "JNJ"],
    "start": "2019-01-01",
    "end": "2019-12-31",
    "fill": "ffill",
}


def test_health_and_docs(api: TestClient) -> None:
    health = api.get("/api/v1/health")
    assert health.status_code == 200 and health.json()["app"] == "sobres"
    assert "X-Run-Id" in health.headers
    assert api.get("/api/docs").status_code == 200
    doc = api.get("/api/openapi.json").json()
    assert doc["info"]["title"] == "sobres" and "/api/v1/data/prices" in doc["paths"]


def test_synchronous_command_returns_the_cli_payload(api: TestClient) -> None:
    response = api.post(
        "/api/v1/data/prices",
        json={"tickers": ["AAPL"], "start": "2020-01-01", "end": "2020-01-31"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["AAPL"] and body["provenance"]["currency"] == "USD"


def test_errors_carry_the_shared_taxonomy(
    api: TestClient, make_client: Callable[..., TestClient]
) -> None:
    usage = api.post("/api/v1/data/prices", json={"tickers": ["AAPL"], "start": "not-a-date"})
    assert usage.status_code == 400 and "start" in usage.json()["error"]
    assert usage.json()["run_id"] and usage.json()["exit_code"] == 2
    unknown = api.post("/api/v1/data/prices", json={"tickers": ["ZZZZ"], "start": "2020-01-01"})
    assert unknown.status_code == 502 and unknown.json()["error_class"] == "UnknownTickerError"
    too_few = api.post(
        "/api/v1/optimize/risk",
        json={**OPT, "tickers": ["AAPL", "MSFT"], "weights": [0.5, 0.5], "start": "2019-12-30"},
    )
    assert too_few.status_code == 422
    keyless = make_client(SOBRES_FIXTURE_DIR="")
    config = keyless.post("/api/v1/data/macro", json={"series": ["DGS10"], "start": "2020-01-01"})
    assert config.status_code == 400 and "SOBRES_FRED_API_KEY" in config.json()["error"]
    assert config.json()["hint"]


def test_internal_errors_hide_the_traceback(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.data import yfinance_provider

    def boom(self: Any, *a: Any, **k: Any) -> Any:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(yfinance_provider.YFinanceProvider, "get_prices", boom)
    response = api.post("/api/v1/data/prices", json={"tickers": ["AAPL"], "start": "2020-01-01"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "internal error" and "secret internals" not in response.text
    assert body["run_id"] == response.headers["X-Run-Id"]


def test_long_running_commands_are_jobs_with_streamed_progress(api: TestClient) -> None:
    started = time.perf_counter()
    response = api.post(
        "/api/v1/optimize/backtest", json={**OPT, "start": "2018-01-01", "lookback": "6m"}
    )
    assert response.status_code == 202 and (time.perf_counter() - started) < 5
    job = response.json()
    assert job["state"] == "queued" and job["url"].endswith(job["job_id"])
    assert api.get(job["url"]).json()["state"] == "queued"
    state = state_of(api)
    assert state.runner.run_pending() == 1
    done = api.get(job["url"]).json()
    assert done["state"] == "succeeded" and done["progress"] == 1.0
    assert done["result"]["n_rebalances"] >= 1 and done["error"] is None
    with api.stream("GET", job["url"] + "/events") as stream:
        frames = [line for line in stream.iter_lines() if line.startswith("data:")]
    events = [json.loads(f[5:]) for f in frames]
    assert events[-1]["state"] == "succeeded" and events[-1]["result"]["oos_start"]
    listed = api.get("/api/v1/jobs").json()["jobs"]
    assert listed[0]["job_id"] == job["job_id"]


def test_job_events_stream_progress_then_result(api: TestClient) -> None:
    response = api.post(
        "/api/v1/optimize/backtest", json={**OPT, "start": "2018-01-01", "lookback": "6m"}
    )
    job_id = response.json()["job_id"]
    state = state_of(api)
    q = state.runner.subscribe(job_id)
    state.runner.run_pending()
    events: list[dict[str, Any]] = []
    while not q.empty():
        events.append(q.get_nowait())
    assert events[0]["state"] == "running"
    progress = [
        e for e in events if e["state"] == "running" and "rebalance" in str(e.get("message"))
    ]
    assert progress and 0 < progress[-1]["progress"] <= 1
    assert events[-1]["state"] == "succeeded"


def test_failed_job_carries_the_error_class(api: TestClient) -> None:
    response = api.post("/api/v1/optimize/markowitz", json={**OPT, "tickers": ["AAPL", "ZZZZ"]})
    job_id = response.json()["job_id"]
    state_of(api).runner.run_pending()
    job = api.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "failed"
    assert job["error"]["error_class"] == "UnknownTickerError" and job["error"]["exit_code"] == 4
    assert "ZZZZ" in job["error"]["message"] and job["result"] is None


def test_cancellation_stops_at_the_next_checkpoint(api: TestClient) -> None:
    state = state_of(api)
    queued = api.post(
        "/api/v1/optimize/backtest", json={**OPT, "start": "2018-01-01", "lookback": "6m"}
    )
    job_id = queued.json()["job_id"]
    cancelled = api.post(f"/api/v1/jobs/{job_id}/cancel").json()
    assert cancelled["state"] == "cancelled"
    assert state.runner.run_pending() == 0
    # A running job: request the cancel from inside the first progress checkpoint.
    running = api.post(
        "/api/v1/optimize/backtest", json={**OPT, "start": "2018-01-01", "lookback": "6m"}
    )
    running_id = running.json()["job_id"]
    original = state.runner._publish

    def cancel_on_first_progress(event: dict[str, Any]) -> None:
        original(event)
        if event["state"] == "running" and event.get("message", "").startswith("rebalance 1 "):
            state.runner.cancel(running_id)

    state.runner._publish = cancel_on_first_progress  # type: ignore[method-assign]
    state.runner.run_pending()
    job = api.get(f"/api/v1/jobs/{running_id}").json()
    assert job["state"] == "cancelled" and job["result"] is None
    assert api.post("/api/v1/jobs/nope/cancel").status_code == 400
    assert api.get("/api/v1/jobs/nope").status_code == 400
    assert api.get("/api/v1/jobs/nope/events").status_code == 400


def test_job_survives_a_new_client(make_client: Callable[..., TestClient]) -> None:
    first = make_client()
    job_id = first.post("/api/v1/optimize/markowitz", json=OPT).json()["job_id"]
    state_of(first).runner.run_pending()
    second = make_client()
    job = second.get(f"/api/v1/jobs/{job_id}").json()
    assert job["state"] == "succeeded" and job["result"]["objective"] == "max_sharpe"


def test_loopback_needs_no_token_and_query_tokens_are_never_accepted(api: TestClient) -> None:
    assert api.get("/api/v1/commands").status_code == 200
    assert api.get("/api/v1/commands?token=abc").status_code == 401
    assert (
        api.post("/api/v1/auth/login", json={"token": "anything"}).json()["token_required"] is False
    )


def test_non_loopback_requires_a_stored_hashed_token(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(require_token=True)
    state = state_of(client)
    token = auth.ensure_token(state.storage.kv)
    assert token is not None and len(token) >= 43
    assert auth.ensure_token(state.storage.kv) is None  # already stored
    stored = state.storage.kv.get(auth.KV_KEY)
    assert token not in json.dumps(stored) and set(stored) == {"salt", "hash"}
    assert client.get("/api/v1/health").status_code == 200  # public
    denied = client.get("/api/v1/commands")
    assert denied.status_code == 401 and denied.json() == {"error": "unauthorized"}
    assert (
        client.get("/api/v1/commands", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert client.get(f"/api/v1/commands?token={token}").status_code == 401
    ok = client.get("/api/v1/commands", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    login = client.post("/api/v1/auth/login", json={"token": token})
    assert login.status_code == 200 and auth.COOKIE_NAME in login.cookies
    assert client.get("/api/v1/commands").status_code == 200  # cookie session
    assert client.post("/api/v1/auth/login", json={"token": "bad"}).status_code == 401
    rotated = auth.rotate_token(state.storage.kv)
    assert rotated != token
    assert client.get("/api/v1/commands").status_code == 401  # the old session stops working
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_login_attempts_are_rate_limited(make_client: Callable[..., TestClient]) -> None:
    client = make_client(require_token=True)
    auth.ensure_token(state_of(client).storage.kv)
    codes = [
        client.post("/api/v1/auth/login", json={"token": "bad"}).status_code for _ in range(12)
    ]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    limiter = auth.RateLimiter(limit=2, window_s=10)
    assert limiter.allow("a", now=0.0) and limiter.allow("a", now=1.0)
    assert not limiter.allow("a", now=2.0)
    assert limiter.allow("a", now=11.5)


def test_token_strength_rules() -> None:
    with pytest.raises(UsageError):
        auth.validate_strength("password")
    with pytest.raises(UsageError):
        auth.validate_strength("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    auth.validate_strength(auth.generate_token())
    stored = auth.hash_token("t0k3n")
    assert auth.verify_token("t0k3n", stored) and not auth.verify_token("other", stored)
    assert not auth.verify_token("t0k3n", None) and not auth.verify_token("", stored)
    assert (
        auth.is_loopback("127.0.0.1")
        and auth.is_loopback("localhost")
        and not auth.is_loopback("0.0.0.0")
    )


def test_cors_is_closed_by_default(api: TestClient) -> None:
    response = api.options(
        "/api/v1/commands",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_settings_endpoints_share_the_config_set_path(api: TestClient, env: dict[str, str]) -> None:
    listed = api.get("/api/v1/settings").json()
    keys = {s["key"]: s for s in listed["settings"]}
    assert keys["fred_api_key"]["secret"] and keys["fred_api_key"]["has_live_validator"]
    assert keys["fred_api_key"]["obtain"].startswith("https://")
    put = api.put("/api/v1/settings", json={"key": "fred_api_key", "value": SENTINEL_KEY})
    assert put.status_code == 200 and SENTINEL_KEY not in put.text
    again = {s["key"]: s for s in api.get("/api/v1/settings").json()["settings"]}
    assert again["fred_api_key"]["value"] == "****" + SENTINEL_KEY[-4:]
    assert again["fred_api_key"]["source"] == "file"
    from pathlib import Path

    assert SENTINEL_KEY in Path(env["SOBRES_CONFIG_FILE"]).read_text(encoding="utf-8")
    bad = api.put("/api/v1/settings", json={"key": "log_level", "value": "LOUD"})
    assert bad.status_code == 400
    assert api.post("/api/v1/settings/log_level/verify", json={}).status_code == 400


def test_settings_verify_runs_the_live_validator(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sobres.settings import LiveResult, get_setting

    monkeypatch.setattr(
        get_setting("fred_api_key"),
        "validate_live",
        lambda v: LiveResult(v == "GOOD", f"{v} checked"),
    )
    ok = api.post("/api/v1/settings/fred_api_key/verify", json={"value": "GOOD"}).json()
    assert ok == {"ok": True, "message": "GOOD checked"}
    assert api.post("/api/v1/settings/fred_api_key/verify", json={}).status_code == 400


def test_doctor_and_history_and_portfolios_over_the_api(api: TestClient) -> None:
    doctor = api.post("/api/v1/doctor", json={"offline": True}).json()
    assert doctor["summary"]["fail"] == 0 and {"python-version", "db-schema"} <= {
        c["name"] for c in doctor["checks"]
    }
    fixed = api.post("/api/v1/doctor", json={"offline": True, "fix": True}).json()
    assert "checks" in fixed
    saved = api.post(
        "/api/v1/portfolio/save",
        json={"name": "core", "tickers": ["AAPL", "MSFT"], "weights": [0.6, 0.4]},
    )
    assert saved.status_code == 200
    listed = api.post("/api/v1/portfolio/list", json={}).json()["rows"]
    assert listed[0]["name"] == "core"
    run = api.post(
        "/api/v1/optimize/risk",
        json={**OPT, "tickers": ["AAPL", "MSFT"], "weights": [0.6, 0.4], "save_run": True},
    )
    assert run.status_code == 200
    runs = api.post("/api/v1/run/list", json={}).json()["rows"]
    assert runs and runs[0]["command"] == "optimize.risk"
    shown = api.post("/api/v1/run/show", json={"id": runs[0]["id"]}).json()
    assert shown["run"]["params"]["weights"] == [0.6, 0.4]
    assert (
        api.post("/api/v1/portfolio/delete", json={"name": "core", "yes": True}).status_code == 200
    )


def test_terminal_only_commands_refuse_over_http(api: TestClient) -> None:
    assert api.post("/api/v1/serve", json={}).status_code == 400
    assert api.post("/api/v1/open", json={}).status_code == 400
    assert api.post("/api/v1/serve/token/rotate", json={}).status_code == 400


def test_every_response_is_traced_and_carries_the_run_id(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from sobres.observability import tracing as tr

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setitem(tr._state, "tracer", provider.get_tracer("t"))
    monkeypatch.setitem(tr._state, "active", True)
    parent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    response = api.post("/api/v1/optimize/markowitz", json=OPT, headers={"traceparent": parent})
    assert (
        response.status_code == 202
        and response.headers["X-Trace-Id"] == "0af7651916cd43dd8448eb211c80319c"
    )
    job_id = response.json()["job_id"]
    job = state_of(api).storage.jobs.get(job_id)
    assert job is not None and job.trace_context == {"traceparent": parent} and job.run_id
    state_of(api).runner.run_pending()
    names = {s.name: s for s in exporter.get_finished_spans()}
    assert (
        "http.request" in names
        and names["http.request"].attributes["command"] == "optimize.markowitz"
    )
    assert (
        format(names["http.request"].context.trace_id, "032x") == "0af7651916cd43dd8448eb211c80319c"
    )
    job_span = names["job.optimize.markowitz"]
    assert format(job_span.context.trace_id, "032x") == "0af7651916cd43dd8448eb211c80319c"


def test_spa_fallback_and_placeholder(api: TestClient, tmp_path: Any) -> None:
    from sobres.api import create_app

    home = api.get("/")
    assert home.status_code == 200 and "sobres" in home.text
    assert api.get("/manifest.json").status_code in (200, 404)
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>built spa</html>", encoding="utf-8")
    (static / "manifest.json").write_text('{"views": {"home": "/"}}', encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(state_of(api).environ, start_worker=False, static_dir=static)
    with TestClient(app) as client:
        assert client.get("/runs/42").text == "<html>built spa</html>"
        assert client.get("/manifest.json").json() == {"views": {"home": "/"}}
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/../etc/passwd").text == "<html>built spa</html>"
