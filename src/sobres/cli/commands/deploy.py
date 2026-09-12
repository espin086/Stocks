"""``sobres deploy`` — the CLI generates and checks its own deployment.

``compose`` and ``env`` print files generated from the configuration the CLI
resolves right now; ``check`` runs doctor's checks plus the deployment ones;
``health`` is what the container's ``HEALTHCHECK`` calls.
"""

from __future__ import annotations

import httpx
from pydantic import Field

from sobres import deploy as dep
from sobres.api import auth
from sobres.cli.commands.doctor import DoctorReport, build_report
from sobres.cli.context import Context
from sobres.doctor import run_checks
from sobres.registry import Params, register
from sobres.results import MessageResult

BIND_ALL = "0.0.0.0"  # a container must bind every interface to be reachable from the host


class ComposeParams(Params):
    port: int = Field(default=dep.CONTAINER_PORT, ge=1, le=65535, description="Published port.")
    host: str = Field(default=BIND_ALL, description="Bind address inside the container.")


@register(
    "deploy.compose",
    "Print a docker-compose.yml generated from the current configuration.",
    result=MessageResult,
    emits_data=False,
)
def compose(p: ComposeParams, ctx: Context) -> MessageResult:
    return MessageResult(message=dep.compose_document(ctx.config, port=p.port, host=p.host))


class EnvParams(Params):
    pass


@register(
    "deploy.env",
    "Print a .env template: every variable, its default and description; no secret values.",
    result=MessageResult,
    emits_data=False,
)
def env(p: EnvParams, ctx: Context) -> MessageResult:
    return MessageResult(message=dep.env_template(ctx.config))


class CheckParams(Params):
    host: str = Field(default=BIND_ALL, description="Bind address the deployment will use.")
    port: int = Field(default=dep.CONTAINER_PORT, ge=1, le=65535, description="Port.")
    offline: bool = Field(default=False, description="Skip network-dependent checks.")
    strict: bool = Field(default=False, description="Exit 1 on warnings as well as failures.")


@register(
    "deploy.check",
    "Preflight: doctor's checks plus image, database mount, bind, token and credentials.",
    result=DoctorReport,
    human_default=True,
)
def check(p: CheckParams, ctx: Context) -> DoctorReport:
    reports = run_checks(ctx, offline=p.offline)
    token_configured = auth.stored_token(ctx.storage.kv) is not None
    reports += dep.deployment_reports(
        ctx.config, host=p.host, port=p.port, token_configured=token_configured
    )
    report = build_report(reports, strict=p.strict)
    ctx.pending_exit_code = report.exit_code
    return report


class HealthParams(Params):
    port: int = Field(default=dep.CONTAINER_PORT, ge=1, le=65535, description="Server port.")
    timeout: float = Field(default=5.0, gt=0, description="Seconds to wait for an answer.")


@register(
    "deploy.health",
    "Ask the running server's health endpoint whether it is ready (exit 1 if not).",
    result=MessageResult,
    emits_data=False,
)
def health(p: HealthParams, ctx: Context) -> MessageResult:
    url = f"http://127.0.0.1:{p.port}/api/v1/health"
    try:
        response = httpx.get(url, timeout=p.timeout)
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        ctx.pending_exit_code = 1
        return MessageResult(message=f"not ready: {url} did not answer ({type(exc).__name__})")
    ready = bool(body.get("ready")) and body.get("app") == "sobres"
    if not ready:
        ctx.pending_exit_code = 1
        failing = [k for k, v in dict(body.get("checks", {})).items() if v == "fail"]
        return MessageResult(message="not ready: " + (", ".join(failing) or "health check failed"))
    return MessageResult(message=f"ready: sobres {body.get('version')} at port {p.port}")
