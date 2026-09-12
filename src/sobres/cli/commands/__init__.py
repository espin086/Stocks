"""Command declarations. Importing this package registers every command."""

import importlib

MODULES: tuple[str, ...] = (
    "cache",
    "commands",
    "config",
    "data",
    "db",
    "doctor",
    "init",
    "optimize",
    "portfolio",
    "run",
    "serve",
    "upgrade",
    "watchlist",
)

for _name in MODULES:
    importlib.import_module(f"{__name__}.{_name}")
