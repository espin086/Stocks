"""``create_app``: the FastAPI application, generated from the command registry.

Every registered command becomes ``POST /api/v1/<group>/<name>`` with its
parameter model as the request body — one validation path shared with the
CLI. Long-running commands are dispatched as jobs (``202 {job_id}``) and
stream progress over SSE. Errors map 0001's taxonomy onto HTTP status codes
and carry the same actionable message the CLI prints, plus the run id.
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from sobres.__about__ import __version__
from sobres.api import auth
from sobres.api.jobs import JobRunner, job_event
from sobres.cli.context import Context
from sobres.config import Config, display_value, process_environment, resolve
from sobres.core.errors import (
    ConfigurationError,
    InsufficientDataError,
    ProviderError,
    SobresError,
    UsageError,
)
from sobres.data.storage.base import TERMINAL_JOB_STATES, OpenOptions, Storage, open_storage
from sobres.deploy import require_data_volume
from sobres.doctor import run_checks
from sobres.observability import get_logger, new_run_id, run_id, span
from sobres.observability.tracing import current_trace_ids
from sobres.registry import Command, all_commands, command_schema, validate_params
from sobres.settings import all_settings, get_setting

STATIC_DIR = Path(__file__).resolve().parent / "static"
API_PREFIX = "/api/v1"
READINESS_CHECKS = ("config-file", "db-reachable", "db-schema", "disk-space", "data-volume")
PUBLIC_PATHS = {f"{API_PREFIX}/health", f"{API_PREFIX}/auth/login", f"{API_PREFIX}/auth/logout"}
STATUS_FOR: dict[type[SobresError], int] = {
    UsageError: 400,
    ConfigurationError: 400,
    ProviderError: 502,
    InsufficientDataError: 422,
}


class LoginBody(BaseModel):
    token: str


class SettingBody(BaseModel):
    key: str
    value: str


class VerifyBody(BaseModel):
    value: str | None = None


@dataclass
class AppState:
    environ: dict[str, str]
    config: Config
    storage: Storage
    runner: JobRunner
    require_token: bool
    sources: dict[str, Any] = field(default_factory=dict)
    limiter: auth.RateLimiter = field(default_factory=auth.RateLimiter)

    def context(self) -> Context:
        return Context(
            config=self.config,
            environ=self.environ,
            interactive=False,
            sources=dict(self.sources),
            surface="api",
            _storage=self.storage,
        )


def create_app(
    environ: Mapping[str, str] | None = None,
    *,
    require_token: bool = False,
    config_path: Path | None = None,
    sources: dict[str, Any] | None = None,
    start_worker: bool = True,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the application over one resolved configuration and one opened storage."""
    env = process_environment() if environ is None else dict(environ)
    config = resolve(None, env, path=config_path)
    if config.error is not None:
        raise config.error
    require_data_volume(config)
    storage = open_storage(config.db_url, OpenOptions())
    runner = JobRunner(storage, config, env, sources=sources)
    state = AppState(
        environ=env,
        config=config,
        storage=storage,
        runner=runner,
        require_token=require_token,
        sources=dict(sources or {}),
    )
    app = FastAPI(
        title="sobres",
        version=__version__,
        description="Every CLI command as POST /api/v1/<group>/<name>; long-running ones as jobs.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.sobres = state
    log = get_logger("sobres.api")

    @app.on_event("startup")
    def _start() -> None:
        if start_worker:
            runner.start()

    @app.on_event("shutdown")
    def _stop() -> None:
        runner.stop()
        storage.close()

    # ----------------------------------------------------------- middleware
    @app.middleware("http")
    async def _observe(request: Request, call_next: Callable[[Request], Any]) -> Response:
        rid = new_run_id()
        started = time.perf_counter()
        carrier = {k: v for k, v in request.headers.items() if k in ("traceparent", "tracestate")}
        route_name = _registry_name(request.url.path)
        with span(
            "http.request",
            {"http.method": request.method, "http.route": request.url.path, "command": route_name},
            carrier=carrier,
        ) as sp:
            denied = _authorize(request, state)
            if denied is not None:
                response: Response = denied
            else:
                response = await call_next(request)
            sp.set_attribute("http.status_code", response.status_code)
            ids = current_trace_ids()
        response.headers["X-Run-Id"] = rid
        if ids is not None:
            response.headers["X-Trace-Id"] = ids[0]
        log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response

    # ------------------------------------------------------------ errors
    @app.exception_handler(SobresError)
    async def _sobres_error(request: Request, exc: SobresError) -> JSONResponse:
        status = next((code for cls, code in STATUS_FOR.items() if isinstance(exc, cls)), 500)
        body = {
            "error": exc.message,
            "hint": exc.hint,
            "error_class": type(exc).__name__,
            "exit_code": exc.exit_code,
            "run_id": run_id(),
        }
        return JSONResponse(body, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Same shape and status as the CLI's usage error: name the field and the constraint.
        problems = [
            ".".join(str(p) for p in err.get("loc", ()) if p != "body") + ": " + str(err.get("msg"))
            for err in exc.errors()
        ]
        return JSONResponse(
            {
                "error": "invalid parameters: " + "; ".join(problems),
                "hint": "see /api/docs for the parameter schema",
                "error_class": "UsageError",
                "exit_code": 2,
                "run_id": run_id(),
            },
            status_code=400,
        )

    @app.exception_handler(ValidationError)
    async def _validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse({"error": str(exc), "run_id": run_id()}, status_code=400)

    @app.exception_handler(Exception)
    async def _internal(request: Request, exc: Exception) -> JSONResponse:
        log.error("http.internal_error", error=f"{type(exc).__name__}: {exc}", exc_info=True)
        return JSONResponse(
            {
                "error": "internal error",
                "hint": f"quote run id {run_id()} when reporting this",
                "run_id": run_id(),
            },
            status_code=500,
            # Starlette's ServerErrorMiddleware handles this outside ``_observe``.
            headers={"X-Run-Id": run_id() or ""},
        )

    # ------------------------------------------------------------ core routes
    @app.get(f"{API_PREFIX}/health", tags=["meta"])
    def health() -> dict[str, Any]:
        # Readiness is doctor's own checks (the fast, offline ones), not a second notion of health.
        reports = run_checks(state.context(), offline=True, only=READINESS_CHECKS)
        checks = {r.name: r.status for r in reports}
        return {
            "app": "sobres",
            "version": __version__,
            "ok": True,
            "ready": not any(s == "fail" for s in checks.values()),
            "checks": checks,
            "token_required": state.require_token,
        }

    @app.get(f"{API_PREFIX}/commands", tags=["meta"])
    def commands() -> dict[str, Any]:
        return {"commands": [command_schema(c) for c in all_commands()]}

    @app.post(f"{API_PREFIX}/auth/login", tags=["auth"])
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        source = request.client.host if request.client else "unknown"
        if state.require_token and not state.limiter.allow(source):
            return JSONResponse({"error": "too many attempts"}, status_code=429)  # type: ignore[return-value]
        if not state.require_token:
            return {"ok": True, "token_required": False}
        if not auth.verify_token(body.token, auth.stored_token(state.storage.kv)):
            return JSONResponse({"error": "unauthorized"}, status_code=401)  # type: ignore[return-value]
        response.set_cookie(
            auth.COOKIE_NAME, body.token, httponly=True, samesite="strict", secure=False
        )
        return {"ok": True, "token_required": True}

    @app.post(f"{API_PREFIX}/auth/logout", tags=["auth"])
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(auth.COOKIE_NAME)
        return {"ok": True}

    # ------------------------------------------------------------ settings
    @app.get(f"{API_PREFIX}/settings", tags=["settings"])
    def settings_list() -> dict[str, Any]:
        cfg = resolve(None, state.environ, path=state.config.path)
        return {
            "settings": [
                {
                    "key": s.key,
                    "env": s.env,
                    "description": s.description,
                    "type": s.type,
                    "secret": s.secret,
                    "required": s.required,
                    "obtain": s.obtain,
                    "affects": list(s.affects),
                    "choices": list(s.choices),
                    "has_live_validator": s.validate_live is not None,
                    "value": display_value(s, cfg.get(s.key)),
                    "source": cfg.source(s.key),
                    "default": s.default,
                }
                for s in all_settings()
            ],
            "config_path": str(state.config.path),
        }

    @app.put(f"{API_PREFIX}/settings", tags=["settings"])
    def settings_put(body: SettingBody) -> dict[str, Any]:
        # The same code path as `sobres config set`: validate, then write the file at 0600.
        from sobres.cli.commands.config import ConfigSetParams, config_set

        result = config_set(ConfigSetParams(key=body.key, value=body.value), state.context())
        state.config = resolve(None, state.environ, path=state.config.path)
        state.runner._config = state.config
        return {"ok": True, "message": result.summary_line()}

    @app.post(f"{API_PREFIX}/settings/{{key}}/verify", tags=["settings"])
    def settings_verify(key: str, body: VerifyBody) -> dict[str, Any]:
        setting = get_setting(key)
        if setting.validate_live is None:
            raise UsageError(f"{key} has no live validator")
        value = body.value if body.value is not None else state.config.get(key)
        if not value:
            raise UsageError(f"{key} is not set; nothing to verify")
        outcome = setting.validate_live(str(value))
        return {"ok": outcome.ok, "message": outcome.message}

    # ---------------------------------------------------------------- jobs
    @app.get(f"{API_PREFIX}/jobs", tags=["jobs"])
    def jobs_list(limit: int = 20, state_filter: str | None = None) -> dict[str, Any]:
        return {
            "jobs": [job_event(j) for j in state.storage.jobs.list(limit=limit, state=state_filter)]
        }

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}", tags=["jobs"])
    def job_get(job_id: str) -> dict[str, Any]:
        job = state.storage.jobs.get(job_id)
        if job is None:
            raise UsageError(f"no job {job_id!r}")
        return job_event(job)

    @app.post(f"{API_PREFIX}/jobs/{{job_id}}/cancel", tags=["jobs"])
    def job_cancel(job_id: str) -> dict[str, Any]:
        job = state.runner.cancel(job_id)
        if job is None:
            raise UsageError(f"no job {job_id!r}")
        return job_event(job, "cancel requested")

    @app.get(f"{API_PREFIX}/jobs/{{job_id}}/events", tags=["jobs"])
    def job_events(job_id: str) -> StreamingResponse:
        job = state.storage.jobs.get(job_id)
        if job is None:
            raise UsageError(f"no job {job_id!r}")
        return StreamingResponse(
            _sse(state, job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---------------------------------------------------------- registry
    for cmd in all_commands():
        app.add_api_route(
            cmd.route,
            _make_endpoint(cmd, state),
            methods=["POST"],
            name=cmd.name,
            summary=cmd.help,
            tags=[cmd.group or "root"],
            status_code=202 if cmd.long_running else 200,
        )

    # ----------------------------------------------------------- frontend
    assets = (static_dir or STATIC_DIR) / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/manifest.json", include_in_schema=False)
    def manifest() -> Response:
        path = (static_dir or STATIC_DIR) / "manifest.json"
        if path.exists():
            return Response(path.read_text(encoding="utf-8"), media_type="application/json")
        return JSONResponse({"views": {}}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        root = static_dir or STATIC_DIR
        candidate = root / path
        if path and candidate.is_file() and candidate.resolve().is_relative_to(root.resolve()):
            media = "text/javascript" if path.endswith(".js") else None
            return Response(candidate.read_bytes(), media_type=media)
        index = root / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse(_PLACEHOLDER, status_code=200)

    return app


_PLACEHOLDER = """<!doctype html><title>sobres</title>
<body style="font-family:system-ui;background:#0b0f14;color:#e6edf3;padding:2rem">
<h1>sobres API is running</h1>
<p>The web UI's built assets are not present in this install. The API is at
<a href="/api/docs" style="color:#7cc4ff">/api/docs</a>. Build the frontend with
<code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>.</p></body>"""


def _registry_name(path: str) -> str | None:
    if not path.startswith(API_PREFIX + "/"):
        return None
    return ".".join(path[len(API_PREFIX) + 1 :].split("/"))


def _authorize(request: Request, state: AppState) -> Response | None:
    """401 for API calls without a valid token when one is required; never via query string."""
    path = request.url.path
    if not path.startswith(API_PREFIX) or path in PUBLIC_PATHS or not state.require_token:
        if "token" in request.query_params and path.startswith(API_PREFIX):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None
    if "token" in request.query_params:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    presented = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        presented = header[7:].strip()
    elif auth.COOKIE_NAME in request.cookies:
        presented = request.cookies[auth.COOKIE_NAME]
    if presented and auth.verify_token(presented, auth.stored_token(state.storage.kv)):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _make_endpoint(cmd: Command, state: AppState) -> Callable[..., Any]:
    params_model = cmd.params

    def endpoint(body: BaseModel, request: Request) -> Any:
        raw = body.model_dump(mode="json", exclude_unset=True)
        params = validate_params(cmd, raw)
        if cmd.long_running:
            carrier = {
                k: v for k, v in request.headers.items() if k in ("traceparent", "tracestate")
            }
            job = state.runner.submit(
                cmd,
                params.model_dump(mode="json"),
                run_id=run_id(),
                trace_context=carrier or None,
            )
            return JSONResponse(
                {**job_event(job, "queued"), "url": f"{API_PREFIX}/jobs/{job.id}"}, status_code=202
            )
        ctx = state.context()
        with span(f"api.{cmd.name}", {"command": cmd.name}):
            result = cmd.handler(params, ctx)
            if getattr(params, "save_run", False):
                from sobres.cli.main import record_run

                record_run(cmd, params, result, ctx)
        return result.payload()

    endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [
            inspect.Parameter(
                "body", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=params_model
            ),
            inspect.Parameter(
                "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
            ),
        ]
    )
    endpoint.__annotations__ = {"body": params_model, "request": Request, "return": Any}
    endpoint.__name__ = cmd.name.replace(".", "_")
    endpoint.__doc__ = cmd.help
    return endpoint


def _sse(state: AppState, job_id: str) -> Iterator[str]:
    """Current state first, then every event until the job is terminal."""
    q = state.runner.subscribe(job_id)
    try:
        job = state.storage.jobs.get(job_id)
        if job is None:
            return
        yield _frame(job_event(job, "current"))
        if job.state in TERMINAL_JOB_STATES:
            return
        last_state = job.state
        while True:
            try:
                event = q.get(timeout=1.0)
            except Exception:
                current = state.storage.jobs.get(job_id)
                if current is None:
                    return
                if current.state != last_state:
                    yield _frame(job_event(current, "state"))
                    last_state = current.state
                if current.state in TERMINAL_JOB_STATES:
                    return
                yield ": keepalive\n\n"
                continue
            yield _frame(event)
            if event["state"] in TERMINAL_JOB_STATES:
                return
    finally:
        state.runner.unsubscribe(job_id, q)


def _frame(event: dict[str, Any]) -> str:
    return f"event: job\ndata: {json.dumps(event, default=str)}\n\n"


__all__ = ["create_app"]
