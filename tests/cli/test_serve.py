"""``sobres serve``, ``sobres open`` and the token subcommand.

Scenarios: `sobres open`; Server already running; Targets; Headless is not an
error; Browser choice is respected; Never a token in the URL; `sobres serve
--open`; `sobres init --web`; Non-local binding requires a token; Rotation and
revocation; Tokens are generated, never chosen.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import pytest

from sobres.api import auth
from sobres.cli.commands import serve as mod
from sobres.cli.context import Context
from sobres.core.errors import UsageError


def test_targets_come_from_the_manifest() -> None:
    views = mod.load_manifest()
    assert views["doctor"] == "/doctor" and views["run"] == "/runs/:id"
    assert mod.resolve_target(None, views) == "/"
    assert mod.resolve_target(["doctor"], views) == "/doctor"
    assert mod.resolve_target(["run", "42"], views) == "/runs/42"
    assert mod.resolve_target(["portfolio", "core"], views) == "/portfolios/core"
    assert mod.resolve_target(["optimize.markowitz"], views) == "/commands/optimize.markowitz"
    with pytest.raises(UsageError) as exc:
        mod.resolve_target(["nope"], views)
    assert "settings" in str(exc.value) and "doctor" in str(exc.value)
    with pytest.raises(UsageError, match="takes 1 argument"):
        mod.resolve_target(["run"], views)


def test_open_prints_url_and_never_fails_headless(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[str, int]] = []

    def fake_run_server(
        host: str, port: int, ctx: Context, *, ready: threading.Event | None = None
    ) -> None:
        started.append((host, port))
        assert ready is not None
        ready.set()

    monkeypatch.setattr(mod, "run_server", fake_run_server)
    monkeypatch.setattr(mod, "probe", lambda url, timeout=1.0: None)
    launched: list[str] = []
    monkeypatch.setattr(mod.webbrowser, "open", lambda url: launched.append(url) or False)
    result = cli("open", "doctor", "--port", "8799")
    assert result.exit_code == 0, result.stderr
    assert started == [("127.0.0.1", 8799)]
    assert "sobres is at http://127.0.0.1:8799/doctor" in result.stderr
    assert "could not launch a browser" in result.stderr  # headless: printed, exit 0
    assert launched == ["http://127.0.0.1:8799/doctor"]
    printed = cli("open", "run", "42", "--port", "8799", "--print-url")
    assert printed.exit_code == 0 and "http://127.0.0.1:8799/runs/42" in printed.stderr
    unknown = cli("open", "nope", "--port", "8799")
    assert unknown.exit_code == 2


def test_open_reuses_a_running_server_and_rejects_a_foreign_one(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "probe", lambda url, timeout=1.0: {"app": "sobres"})
    opened: list[str] = []
    monkeypatch.setattr(mod.webbrowser, "open", lambda url: opened.append(url) or True)
    result = cli("open", "settings", "--port", "8790")
    assert result.exit_code == 0 and "already running" in result.stderr
    assert opened == ["http://127.0.0.1:8790/settings"]
    monkeypatch.setattr(mod, "probe", lambda url, timeout=1.0: {})
    foreign = cli("open", "--port", "8790")
    assert foreign.exit_code == 2 and "not sobres" in foreign.stderr and "--port" in foreign.stderr


def test_probe_classifies_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    class _Resp:
        def __init__(self, payload: Any) -> None:
            self._payload = payload

        def json(self) -> Any:
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp({"app": "sobres", "ok": True}))
    assert mod.probe("http://x") == {"app": "sobres", "ok": True}
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp(ValueError("not json")))
    assert mod.probe("http://x") == {}
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _Resp({"other": 1}))
    assert mod.probe("http://x") == {}

    def refused(url: str, timeout: float) -> Any:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refused)
    assert mod.probe("http://x") is None


def test_browser_launch_honors_browser_env(
    monkeypatch: pytest.MonkeyPatch, make_context: Callable[..., Context]
) -> None:
    import webbrowser

    seen: list[str] = []
    monkeypatch.setenv("BROWSER", "echo")
    monkeypatch.setattr(webbrowser, "open", lambda url: seen.append(url) or True)
    ctx = make_context()
    assert mod.launch_browser("http://127.0.0.1:8787/", ctx) is True and seen

    def explode(url: str) -> bool:
        raise RuntimeError("no display")

    monkeypatch.setattr(webbrowser, "open", explode)
    assert mod.launch_browser("http://127.0.0.1:8787/", ctx) is False


def test_serve_runs_uvicorn_and_prints_a_token_for_non_loopback(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    configs: list[Any] = []

    class _Server:
        def __init__(self, config: Any) -> None:
            configs.append(config)
            self.started = True
            self.should_exit = False

        def run(self) -> None:
            return None

    monkeypatch.setattr(uvicorn, "Server", _Server)
    local = cli("serve", "--port", "8791")
    assert local.exit_code == 0 and "serving sobres at http://127.0.0.1:8791" in local.stderr
    assert "token" not in local.stderr.lower()
    exposed = cli("serve", "--host", "0.0.0.0", "--port", "8792")
    assert exposed.exit_code == 0
    assert "WARNING" in exposed.stderr and "token:" in exposed.stderr
    token = exposed.stderr.split("token: ")[1].split("\n")[0].strip()
    assert len(token) >= 43
    again = cli("serve", "--host", "0.0.0.0", "--port", "8792")
    assert "token required (stored)" in again.stderr and token not in again.stderr
    assert configs[-1].host == "0.0.0.0" and configs[-1].port == 8792
    opened: list[str] = []
    monkeypatch.setattr(mod.webbrowser, "open", lambda url: opened.append(url) or True)
    with_open = cli("serve", "--open", "--port", "8793")
    assert with_open.exit_code == 0
    import time

    time.sleep(0.3)
    assert opened == ["http://127.0.0.1:8793"]


def test_token_rotate_generates_or_validates(
    cli: Callable[..., Any], make_context: Callable[..., Context]
) -> None:
    first = cli("serve", "token", "rotate")
    assert first.exit_code == 0 and "new deployment token" in first.stderr
    token = first.stderr.strip().splitlines()[-1].strip()
    ctx = make_context()
    assert auth.verify_token(token, auth.stored_token(ctx.storage.kv))
    weak = cli("serve", "token", "rotate", "--token", "password")
    assert weak.exit_code == 2 and "too weak" in weak.stderr
    strong = auth.generate_token()
    chosen = cli("serve", "token", "rotate", "--token", strong)
    assert chosen.exit_code == 0
    assert auth.verify_token(strong, auth.stored_token(make_context().storage.kv))
    assert not auth.verify_token(token, auth.stored_token(make_context().storage.kv))
    assert json.loads(cli("commands", "--format", "json").stdout)["commands"]


def test_init_web_opens_settings(cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "probe", lambda url, timeout=1.0: {"app": "sobres"})
    monkeypatch.setattr(mod.webbrowser, "open", lambda url: calls.append([url]) or True)
    result = cli("init", "--web", "--non-interactive", "--offline")
    assert result.exit_code == 0, result.stderr
    assert calls == [["http://127.0.0.1:8787/settings"]]
