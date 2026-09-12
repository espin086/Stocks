"""Parity: every registered command has an HTTP route and a UI view.

Scenarios: One declaration, three surfaces; One route shape; Parity is tested,
not trusted; Adding a parameter reaches every surface; Types are declared
once; Full coverage; Forms are generated from the registry; Identical results;
Documented; Every CLI capability has a view; Targets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sobres.registry import all_commands, command_schema
from tests.invariants.test_every_command import SAMPLE_ARGS

MANIFEST = Path(__file__).resolve().parents[2] / "frontend" / "public" / "manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict[str, str]:
    return json.loads(MANIFEST.read_text())["views"]


@pytest.mark.parametrize("command", all_commands(), ids=lambda c: c.name)
def test_every_command_has_a_route(command: Any, api: TestClient) -> None:
    doc = api.get("/api/openapi.json").json()
    assert command.route in doc["paths"], command.name
    assert "post" in doc["paths"][command.route]
    operation = doc["paths"][command.route]["post"]
    assert operation["summary"] == command.help
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    ref = body_schema["$ref"].rsplit("/", 1)[-1]
    properties = doc["components"]["schemas"][ref]["properties"]
    for name, info in command.params.model_fields.items():
        assert (info.alias or name) in properties, f"{command.name} lacks API field {name}"


@pytest.mark.parametrize("command", all_commands(), ids=lambda c: c.name)
def test_every_command_has_a_view(command: Any, manifest: dict[str, str]) -> None:
    key = "doctor.command" if command.name == "doctor" else command.name
    assert key in manifest, f"frontend/public/manifest.json has no view for {command.name}"


def test_manifest_has_the_fixed_views(manifest: dict[str, str]) -> None:
    for view in ("settings", "doctor", "runs", "run", "portfolios", "portfolio", "jobs"):
        assert view in manifest
    assert manifest["run"] == "/runs/:id" and manifest["portfolio"] == "/portfolios/:name"


def test_defaults_are_identical_in_cli_api_and_schema(api: TestClient) -> None:
    doc = api.get("/api/openapi.json").json()
    for command in all_commands():
        ref = doc["paths"][command.route]["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]["$ref"].rsplit("/", 1)[-1]
        properties = doc["components"]["schemas"][ref]["properties"]
        for field in command_schema(command)["params"]:
            if field["default"] is not None and not field["multiple"]:
                assert properties[field["name"]].get("default") == field["default"], (
                    f"{command.name}.{field['name']}"
                )


def test_commands_endpoint_mirrors_the_registry(api: TestClient) -> None:
    listed = api.get("/api/v1/commands").json()["commands"]
    assert [c["name"] for c in listed] == [c.name for c in all_commands()]
    assert all("route" in c and "params" in c for c in listed)


def _params_from_args(name: str, args: list[str]) -> dict[str, Any]:
    """Turn a CLI sample into the JSON body the API takes (the registry does the parsing)."""
    from sobres.registry import get_command

    cmd = get_command(name)
    fields = cmd.params.model_fields
    positional = [
        n
        for n, f in fields.items()
        if isinstance(f.json_schema_extra, dict) and f.json_schema_extra.get("positional")
    ]
    body: dict[str, Any] = {}
    tokens = list(args[len(name.split(".")) :])
    i = 0
    pos_values: list[str] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            key = tok[2:].replace("-", "_")
            alias_to_name = {f.alias: n for n, f in fields.items() if f.alias}
            key = alias_to_name.get(key, key)
            if key in fields and fields[key].annotation is bool:
                body[key] = True
                i += 1
                continue
            values = []
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                values.append(tokens[i])
                i += 1
            body[key] = values if len(values) > 1 else values[0]
            continue
        pos_values.append(tok)
        i += 1
    if positional:
        multi = [n for n in positional if "list" in str(fields[n].annotation)]
        if multi:
            scalars = [n for n in positional if n not in multi]
            for n, v in zip(scalars, pos_values, strict=False):
                body[n] = v
            body[multi[0]] = pos_values[len(scalars) :]
        else:
            for n, v in zip(positional, pos_values, strict=False):
                body[n] = v
    body.pop("format", None)
    return body


COMPARABLE = [
    "cache.info",
    "commands",
    "config.path",
    "config.show",
    "data.factors",
    "data.fx",
    "data.macro",
    "data.prices",
    "db.info",
    "doctor",
    "optimize.risk",
    "portfolio.list",
    "run.list",
    "watchlist.list",
]


@pytest.mark.parametrize("name", COMPARABLE)
def test_identical_results_through_cli_and_api(
    name: str, make_client: Callable[..., TestClient], cli: Callable[..., Any]
) -> None:
    from tests.invariants.test_every_command import ENV, _strip_volatile

    api = make_client(**ENV)  # the same environment on both surfaces

    args = SAMPLE_ARGS[name]
    body = _params_from_args(name, args)
    from sobres.registry import get_command

    via_api = api.post(get_command(name).route, json=body, headers={"X-Test": "1"})
    assert via_api.status_code == 200, via_api.text
    cmd = get_command(name)
    if not cmd.emits_data:  # a message command prints its message; the API wraps it
        via_cli = cli(*args, env_extra=ENV)
        assert via_cli.exit_code == 0, via_cli.stderr
        assert via_api.json()["message"] == via_cli.stdout.strip()
        return
    via_cli = cli(*args, "--format", "json", env_extra=ENV)
    assert via_cli.exit_code == 0, via_cli.stderr
    assert _strip_volatile(json.dumps(via_api.json())) == _strip_volatile(via_cli.stdout)
