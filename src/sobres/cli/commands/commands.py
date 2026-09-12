"""``sobres commands`` — the registry, queryable."""

from __future__ import annotations

from sobres.cli.context import Context
from sobres.registry import Params, all_commands, command_schema, register
from sobres.results import CommandListing


class CommandsParams(Params):
    pass


@register("commands", "List every registered command with its parameters.", result=CommandListing)
def commands(p: CommandsParams, ctx: Context) -> CommandListing:
    schemas = [command_schema(c) for c in all_commands()]
    rows = [
        {
            "name": s["name"],
            "group": s["group"] or "",
            "help": s["help"],
            "params": ", ".join(f["name"] for f in s["params"]),
        }
        for s in schemas
    ]
    return CommandListing(rows=rows, columns=["name", "group", "help", "params"], commands=schemas)
