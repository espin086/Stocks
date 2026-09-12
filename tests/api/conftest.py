"""An in-process FastAPI test client over the isolated environment."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sobres.api import create_app


@pytest.fixture
def make_client(env: dict[str, str]) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def factory(require_token: bool = False, **extra_env: str) -> TestClient:
        environ = {**env, **extra_env}
        app = create_app(
            environ,
            require_token=require_token,
            config_path=Path(environ["SOBRES_CONFIG_FILE"]),
            start_worker=False,
        )
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()  # runs startup/shutdown handlers
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def state_of(client: TestClient) -> Any:
    return client.app.state.sobres  # type: ignore[attr-defined]
