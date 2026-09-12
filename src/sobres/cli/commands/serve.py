"""``sobres serve`` and ``sobres open`` — the web UI and API from the terminal.

``serve`` binds loopback by default with no token; any other host requires a
token, generated and printed once if absent. ``open`` starts the server if
nothing answers on the port, waits for the health endpoint, prints the URL
(always, before any launch attempt) and opens the browser; headless is not an
error. Targets are the frontend view manifest's names, so ``open`` reaches
exactly the views that exist.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field

from sobres.api import auth
from sobres.cli.context import Context
from sobres.core.errors import ConfigurationError, UsageError
from sobres.registry import Params, positional, register
from sobres.results import MessageResult

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
MANIFEST = Path(__file__).resolve().parents[2] / "api" / "static" / "manifest.json"
SOURCE_MANIFEST = Path(__file__).resolve().parents[4] / "frontend" / "public" / "manifest.json"


def load_manifest() -> dict[str, str]:
    """View name → path template, from the built manifest (or the source one in a checkout)."""
    for path in (MANIFEST, SOURCE_MANIFEST):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.get("views", {}).items()}
    return {}


def resolve_target(target: list[str] | None, views: dict[str, str]) -> str:
    """``doctor`` → ``/doctor``; ``run 42`` → ``/runs/42``; a registry name → its view."""
    if not target:
        return "/"
    name, *args = target
    if name not in views:
        raise UsageError(
            f"unknown view {name!r}",
            hint="views: " + ", ".join(sorted(views)),
        )
    template = views[name]
    placeholders = [seg for seg in template.split("/") if seg.startswith(":")]
    if len(args) != len(placeholders):
        raise UsageError(
            f"view {name!r} takes {len(placeholders)} argument(s), got {len(args)}",
            hint=(
                f"usage: sobres open {name} " + " ".join(p[1:].upper() for p in placeholders)
            ).strip(),
        )
    path = template
    for placeholder, value in zip(placeholders, args, strict=True):
        path = path.replace(placeholder, value)
    return path


def probe(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    """The health document if a sobres server answers, ``{}`` if something else, None if nothing."""
    try:
        response = httpx.get(url + "/api/v1/health", timeout=timeout)
    except httpx.HTTPError:
        return None
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) and data.get("app") == "sobres" else {}


def launch_browser(url: str, ctx: Context) -> bool:
    """Honors ``BROWSER``; a failed launch prints the URL and is not an error."""
    ctx.note(f"sobres is at {url}")
    try:
        opened = bool(webbrowser.open(url))
    except Exception:
        opened = False
    if not opened:
        ctx.note("could not launch a browser here; open the URL above")
    return opened


class ServeParams(Params):
    host: str = Field(default=DEFAULT_HOST, description="Bind address; non-loopback needs a token.")
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535, description="Port.")
    open: bool = Field(default=False, description="Open the browser once healthy.")


def run_server(host: str, port: int, ctx: Context, *, ready: threading.Event | None = None) -> None:
    from sobres.api import create_app

    if ctx.surface == "api":
        raise UsageError("the server cannot start itself over HTTP")
    require_token = not auth.is_loopback(host)
    if require_token:
        fresh = auth.ensure_token(ctx.storage.kv)
        if fresh is not None:
            ctx.note(
                "WARNING: binding a non-loopback address exposes your financial data to the "
                "network. A deployment token was generated; paste it once in the browser:"
            )
            ctx.note(f"  token: {fresh}")
            ctx.note(
                "  it is stored hashed and will not be shown again (sobres serve token rotate)"
            )
        else:
            ctx.note("token required (stored); rotate with: sobres serve token rotate")
    ctx.close()  # the app opens its own storage
    app = create_app(
        ctx.environ, require_token=require_token, config_path=ctx.config.path, sources=ctx.sources
    )
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - the [web] extra installs it
        raise ConfigurationError(
            "uvicorn is not installed", hint="run: pip install 'sobres[web]'"
        ) from exc
    config = uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False)
    server = uvicorn.Server(config)
    if ready is not None:

        def _watch() -> None:
            while not server.started and not server.should_exit:
                time.sleep(0.05)
            ready.set()

        threading.Thread(target=_watch, daemon=True).start()
    try:
        server.run()
    finally:
        if ready is not None and server.started:
            ready.set()  # a server that ran did start, whether or not ``_watch`` noticed


@register(
    "serve", "Run the web UI and API (loopback by default).", result=MessageResult, emits_data=False
)
def serve(p: ServeParams, ctx: Context) -> MessageResult:
    url = f"http://{p.host}:{p.port}"
    ctx.note(f"serving sobres at {url} (Ctrl-C to stop)")
    if p.open:
        ready = threading.Event()

        def _open() -> None:
            if ready.wait(15):
                launch_browser(url, ctx)

        opener = threading.Thread(target=_open, daemon=True)
        opener.start()
        try:
            run_server(p.host, p.port, ctx, ready=ready)
        finally:
            if ready.is_set():
                opener.join(timeout=5)  # let the launch message land before stderr closes
    else:
        run_server(p.host, p.port, ctx)
    return MessageResult(message="server stopped")


class TokenRotateParams(Params):
    token: str | None = Field(
        default=None, description="Use this token instead of a generated one (must be strong)."
    )


@register(
    "serve.token.rotate",
    "Replace the deployment token; every existing session stops working.",
    result=MessageResult,
    emits_data=False,
)
def token_rotate(p: TokenRotateParams, ctx: Context) -> MessageResult:
    if ctx.surface == "api":
        raise UsageError("rotate the token from the CLI: sobres serve token rotate")
    token = auth.rotate_token(ctx.storage.kv, p.token)
    ctx.note("new deployment token (shown once, stored hashed):")
    ctx.note(f"  {token}")
    return MessageResult(message="token rotated; existing sessions are no longer valid")


class OpenParams(Params):
    target: list[str] = positional(
        default_factory=list,
        description=(
            "View to open: settings, doctor, runs, run <id>, portfolio <name>, or a command name."
        ),
    )
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535, description="Port to use or start on.")
    print_url: bool = Field(
        default=False, description="Print the URL instead of launching a browser."
    )


@register(
    "open",
    "Start the server if needed and open the browser to a view.",
    result=MessageResult,
    emits_data=False,
)
def open_view(p: OpenParams, ctx: Context) -> MessageResult:
    if ctx.surface == "api":
        raise UsageError("`sobres open` is a terminal command")
    views = load_manifest()
    path = resolve_target(p.target, views)
    if ctx.config.get("container"):
        # There is no browser here: say where the UI is reachable from the host.
        from sobres.deploy import host_url

        reachable, note = host_url(p.port, ctx.environ)
        ctx.note(f"sobres is at {reachable}{path}")
        if note:
            ctx.note(f"  ({note})")
        return MessageResult(message=reachable + path)
    base = f"http://{DEFAULT_HOST}:{p.port}"
    url = base + path
    health = probe(base)
    if health == {}:
        raise UsageError(
            f"something that is not sobres answers on port {p.port}",
            hint="choose another port with --port",
        )
    if health is not None:
        ctx.note(f"sobres is already running at {base}")
        if not p.print_url:
            launch_browser(url, ctx)
        else:
            ctx.note(f"sobres is at {url}")
        return MessageResult(message=url)
    ready = threading.Event()
    server = threading.Thread(
        target=run_server, args=(DEFAULT_HOST, p.port, ctx), kwargs={"ready": ready}, daemon=True
    )
    server.start()
    if not ready.wait(15):
        raise ConfigurationError(
            "the server did not become healthy within 15 seconds",
            hint="run: sobres serve --port <port> and read its log",
        )
    if p.print_url:
        ctx.note(f"sobres is at {url}")
    else:
        launch_browser(url, ctx)
    try:
        while server.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    return MessageResult(message=url)
