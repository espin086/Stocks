"""Root Typer application and the one error boundary.

Global options (``--version``, ``--debug``, ``-v/-vv``, ``--log-level``,
``--log-format``) live on the root callback; every data-emitting command gets
``--format`` (and ``--refresh`` where it reads providers) from the registry
generator. No command is added here by hand.

The error boundary maps ``SobresError`` to its exit code and prints the
message with the run id; anything else is an internal error (exit 1) whose
traceback appears only under ``--debug``.
"""

from __future__ import annotations

import os
import sys
import traceback
import warnings
from dataclasses import dataclass
from typing import Any

import typer

from sobres.__about__ import __version__
from sobres.cli.context import Context
from sobres.cli.render import render
from sobres.core.errors import ConfigurationError, SobresError
from sobres.deploy import require_data_volume
from sobres.observability import configure_logging, new_run_id
from sobres.observability.tracing import configure_tracing, shutdown
from sobres.registry import FORMATS, Command, build_app, validate_params
from sobres.settings import (
    LOG_FILE,
    LOG_FORMAT,
    LOG_LEVEL,
    OTEL_ENDPOINT,
    OTEL_TRACES_EXPORTER,
    check_legacy_environment,
)

app = typer.Typer(
    name="sobres",
    help="sobres — equity analysis, portfolio optimization, and goal planning.",
    invoke_without_command=True,
    add_completion=True,
    rich_markup_mode=None,
)


@dataclass
class GlobalOptions:
    debug: bool = False
    verbose: int = 0
    log_level: str | None = None
    log_format: str | None = None


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the sobres version and exit.",
    ),
    debug: bool = typer.Option(False, "--debug", help="Print full tracebacks to stderr."),
    verbose: int = typer.Option(
        0, "-v", "--verbose", count=True, help="-v for INFO logs, -vv for DEBUG."
    ),
    log_level: str | None = typer.Option(
        None, "--log-level", help="Explicit log level: DEBUG, INFO, WARNING or ERROR."
    ),
    log_format: str | None = typer.Option(
        None, "--log-format", help="Log rendering: auto, human or json."
    ),
) -> None:
    """sobres root command."""
    ctx.obj = GlobalOptions(
        debug=debug, verbose=verbose, log_level=log_level, log_format=log_format
    )
    if ctx.invoked_subcommand is None:
        # Bare invocation is help, not an error (Click 8.2 made no_args_is_help exit 2).
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def _effective_level(opts: GlobalOptions, configured: str) -> str:
    if opts.log_level:
        return opts.log_level.upper()
    if opts.verbose >= 2:
        return "DEBUG"
    if opts.verbose == 1:
        return "INFO"
    return configured


def invoke(cmd: Command, raw: dict[str, Any], typer_ctx: typer.Context) -> None:
    """Run one registered command end to end: resolve, validate, execute, render."""
    opts = typer_ctx.find_root().obj or GlobalOptions()
    fmt = raw.pop("format", None)
    refresh = bool(raw.pop("refresh", False))
    rid = new_run_id()
    context: Context | None = None
    code = 0
    try:
        check_legacy_environment(os.environ)
        overrides = {
            LOG_LEVEL.key: opts.log_level.upper() if opts.log_level else None,
            LOG_FORMAT.key: opts.log_format,
        }
        context = Context.build(overrides, refresh=refresh, fmt=fmt, debug=opts.debug)
        if context.config.error is not None and cmd.name != "doctor":
            raise context.config.error
        if cmd.name not in ("doctor", "deploy.check"):
            require_data_volume(context.config)
        level = _effective_level(opts, str(context.config.get(LOG_LEVEL.key)))
        log_file = context.config.get(LOG_FILE.key)
        configure_logging(
            level,
            str(context.config.get(LOG_FORMAT.key)),
            log_file=None if not log_file else __import__("pathlib").Path(str(log_file)),
        )
        configure_tracing(
            context.config.get(OTEL_ENDPOINT.key),
            context.config.get(OTEL_TRACES_EXPORTER.key),
            warn=lambda m: (
                context.log.warning("tracing.unavailable", reason=m)
                if context is not None
                else None
            ),
        )
        if fmt is not None and fmt not in FORMATS:
            raise ConfigurationError(
                f"unknown --format {fmt!r}", hint=f"use one of: {', '.join(FORMATS)}"
            )
        if not context.config.exists and cmd.name != "init":
            context.note(
                "hint: no configuration found; run `sobres init` to set up keys and storage"
            )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            params = validate_params(cmd, raw)
        for w in caught:
            context.note(f"warning: {w.message}")
        from sobres.observability import span

        with span(f"cli.{cmd.name}", {"command": cmd.name}):
            context.log.info(
                "command.start", command=cmd.name, params=params.model_dump(mode="json")
            )
            result = cmd.handler(params, context)
            context.log.info("command.done", command=cmd.name)
            if getattr(params, "save_run", False):
                record_run(cmd, params, result, context)
        if fmt is None and (cmd.human_default or not cmd.emits_data):
            fmt = "table"
        render(result, fmt)
        code = context.pending_exit_code
    except SobresError as exc:
        code = exc.exit_code
        _report(exc, rid, opts.debug)
    except typer.Exit as exc:
        code = int(exc.exit_code or 0)
    except Exception as exc:
        code = 1
        _report(exc, rid, opts.debug, internal=True)
    finally:
        if context is not None:
            context.close()
        shutdown()
    if code:
        raise typer.Exit(code)


def record_run(cmd: Command, params: Any, result: Any, context: Context) -> None:
    """Persist a run: resolved parameters (after defaults), provenance and the result."""
    import uuid

    from sobres.data.storage.base import RunRecord

    payload = result.payload()
    provenance = payload.get("provenance", {}) if isinstance(payload, dict) else {}
    resolved = params.model_dump(mode="json", exclude={"save_run"})
    run = RunRecord(
        id=uuid.uuid4().hex[:12],
        command=cmd.name,
        params=resolved,
        result=payload,
        summary=result.summary_line(),
        estimators=dict(payload.get("estimators", {})) if isinstance(payload, dict) else {},
        window={k: provenance.get(k) for k in ("start", "end") if provenance.get(k)},
    )
    context.storage.runs.record(run)
    context.note(f"saved run {run.id} (`sobres run show {run.id}`)")


def _report(exc: BaseException, rid: str, debug: bool, *, internal: bool = False) -> None:
    if internal:
        message = (
            f"error: internal error ({type(exc).__name__}: {exc})\n"
            f"  next: rerun with --debug and report the run id {rid}"
        )
    else:
        message = f"error: {exc}"
    print(f"{message}\n  run id: {rid}", file=sys.stderr)
    if debug:
        traceback.print_exception(exc, file=sys.stderr)


build_app(app, invoke)


if __name__ == "__main__":  # pragma: no cover
    app()
