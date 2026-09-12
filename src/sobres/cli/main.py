"""Root Typer application.

This is a scaffold. Commands are added by the OpenSpec changes under
`openspec/changes/` — see `openspec/project.md` for the layering rule:
all math lives in `sobres.core.*`; the CLI is a thin adapter.
"""

from __future__ import annotations

import typer

from sobres.__about__ import __version__

app = typer.Typer(
    name="sobres",
    help="sobres — equity analysis, portfolio optimization, and goal planning.",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the sobres version and exit.",
    ),
) -> None:
    """sobres root command."""


if __name__ == "__main__":
    app()
