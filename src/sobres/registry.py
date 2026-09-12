"""The command registry: every command is one declaration.

A command declares a dotted name, one-line help, a pydantic parameter model, a
typed result and a handler. The Typer CLI is generated from the declarations
here (``build_app``); 0004 derives the HTTP API and UI forms from the same
objects. No command is added to Typer by hand — ``tests/cli/test_registry.py``
asserts the generated app has exactly one subcommand per registration.

Cross-field rules are model validators, never handler code, so they apply
identically on every surface.
"""

from __future__ import annotations

import inspect
import re
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, ClassVar, Literal, get_args, get_origin, get_type_hints

import typer
from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, ValidationError
from typer.core import TyperCommand

from sobres.core.errors import UsageError
from sobres.results import Result

# --------------------------------------------------------------------------- #
# Shared parameter types
# --------------------------------------------------------------------------- #


def _split_tokens(value: Any) -> Any:
    """Accept ``["AAPL","MSFT"]``, ``"AAPL MSFT"`` or ``"AAPL,MSFT"``."""
    if isinstance(value, str):
        return [t for t in re.split(r"[\s,]+", value.strip()) if t]
    if isinstance(value, list | tuple):
        out: list[Any] = []
        for item in value:
            out.extend(_split_tokens(item) if isinstance(item, str) else [item])
        return out
    return value


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


Ticker = Annotated[
    str,
    BeforeValidator(_upper),
    StringConstraints(min_length=1, pattern=r"^[A-Z0-9.^=\-]+$"),
]
TickerList = Annotated[list[Ticker], BeforeValidator(_split_tokens), Field(min_length=1)]
SeriesList = Annotated[
    list[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1)]],
    BeforeValidator(_split_tokens),
    Field(min_length=1),
]
Weights = Annotated[list[float], BeforeValidator(_split_tokens)]
Currency = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z]{3}$")]
CurrencyPairList = Annotated[
    list[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=6)]],
    BeforeValidator(_split_tokens),
    Field(min_length=1),
]
Frequency = Literal["daily", "weekly", "monthly", "quarterly", "annual"]
OutputFormat = Literal["table", "json", "csv"]
FORMATS: tuple[str, ...] = ("table", "json", "csv")


def positional(**kwargs: Any) -> Any:
    """Mark a field as a positional CLI argument (``sobres data prices AAPL MSFT``)."""
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra["positional"] = True
    return Field(json_schema_extra=extra, **kwargs)


class Params(BaseModel):
    """Base for parameter models: strict about unknown fields."""

    model_config = {"extra": "forbid", "populate_by_name": True}


# --------------------------------------------------------------------------- #
# Declarations
# --------------------------------------------------------------------------- #

Handler = Callable[[Any, Any], Result]


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    params: type[BaseModel]
    result: type[Result]
    handler: Handler
    emits_data: bool = True
    """Supports --format table|json|csv (and --refresh when it reads providers)."""
    uses_providers: bool = False
    human_default: bool = False
    """Render as a table even when piped (reports such as doctor); data commands default to CSV."""
    long_running: bool = False
    """Dispatched as a job over HTTP (0004): the request returns an id, progress streams."""
    aliases: tuple[str, ...] = ()
    """Deprecated former names, kept for one minor version with a warning."""
    param_aliases: dict[str, str] = field(default_factory=dict)
    """Deprecated former parameter names → current names."""

    @property
    def group(self) -> str | None:
        return self.name.rsplit(".", 1)[0] if "." in self.name else None

    @property
    def group_path(self) -> tuple[str, ...]:
        return tuple(self.name.split(".")[:-1])

    @property
    def leaf(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    @property
    def cli_name(self) -> str:
        return self.name.replace(".", " ").replace("_", "-")

    @property
    def report(self) -> bool:
        return bool(self.result.report)

    @property
    def route(self) -> str:
        """The HTTP route 0004 generates: ``POST /api/v1/<group>/<name>``."""
        return "/api/v1/" + "/".join(self.name.split("."))


_COMMANDS: dict[str, Command] = {}
GROUP_HELP: dict[str, str] = {
    "data": "Fetch and cache market, macro, factor and exchange-rate data.",
    "cache": "Inspect and clear cached provider observations.",
    "config": "Show and set declared settings.",
    "optimize": "Markowitz weights, the efficient frontier, a walk-forward backtest, a risk panel.",
    "portfolio": "Save, list, show and delete named portfolios.",
    "watchlist": "Named symbol lists.",
    "run": "Browse, inspect and compare recorded analysis runs.",
    "db": "Inspect, back up and repair the database.",
    "token": "Manage the deployment token.",
    "deploy": "Generate and check the container deployment.",
    "analyze": "Single-stock dashboards and factor-model regressions.",
    "plan": "Retirement, house, car, education and generic goals, with simulation.",
}


def register(
    name: str,
    help: str,
    *,
    result: type[Result],
    emits_data: bool = True,
    uses_providers: bool = False,
    human_default: bool = False,
    long_running: bool = False,
    aliases: Sequence[str] = (),
    param_aliases: dict[str, str] | None = None,
) -> Callable[[Handler], Handler]:
    """Declare a command. The handler's first annotation is its parameter model."""

    def decorate(handler: Handler) -> Handler:
        first_name = next(iter(inspect.signature(handler).parameters))
        try:
            params = get_type_hints(handler)[first_name]
        except (NameError, KeyError):
            params = None
        if not (inspect.isclass(params) and issubclass(params, BaseModel)):
            raise TypeError(f"{name}: handler's first parameter must be a pydantic model")
        if name in _COMMANDS:
            raise ValueError(f"command {name!r} registered twice")
        _COMMANDS[name] = Command(
            name=name,
            help=help,
            params=params,
            result=result,
            handler=handler,
            emits_data=emits_data,
            uses_providers=uses_providers,
            human_default=human_default,
            long_running=long_running,
            aliases=tuple(aliases),
            param_aliases=dict(param_aliases or {}),
        )
        return handler

    return decorate


def all_commands() -> list[Command]:
    _import_command_modules()
    return sorted(_COMMANDS.values(), key=lambda c: c.name)


def get_command(name: str) -> Command:
    _import_command_modules()
    try:
        return _COMMANDS[name]
    except KeyError:
        for cmd in _COMMANDS.values():
            if name in cmd.aliases:
                warnings.warn(
                    f"command {name!r} is deprecated; use {cmd.name!r}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                return cmd
        raise KeyError(name) from None


def _import_command_modules() -> None:
    # Command modules register on import; importing the package makes the
    # registry complete regardless of which module the caller touched first.
    import sobres.cli.commands  # noqa: F401


# --------------------------------------------------------------------------- #
# Introspection
# --------------------------------------------------------------------------- #


def field_schema(model: type[BaseModel]) -> list[dict[str, Any]]:
    """Per-field name, type, default, help and choices from the model alone."""
    out = []
    for name, info in model.model_fields.items():
        annotation = info.annotation
        out.append(
            {
                "name": name,
                "type": _type_name(annotation),
                "required": info.is_required(),
                "default": None
                if info.is_required()
                else _json_default(info.get_default(call_default_factory=True)),
                "help": info.description or "",
                "choices": list(_choices(annotation) or []),
                "positional": bool((info.json_schema_extra or {}).get("positional"))
                if isinstance(info.json_schema_extra, dict)
                else False,
                "multiple": _is_list(annotation),
            }
        )
    return out


def command_schema(cmd: Command) -> dict[str, Any]:
    return {
        "name": cmd.name,
        "group": cmd.group,
        "command": cmd.leaf,
        "help": cmd.help,
        "result": cmd.result.__name__,
        "report": cmd.report,
        "emits_data": cmd.emits_data,
        "long_running": cmd.long_running,
        "route": cmd.route,
        "aliases": list(cmd.aliases),
        "params": field_schema(cmd.params),
        "json_schema": cmd.params.model_json_schema(),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return list(value)
    return value


def _strip_annotated(annotation: Any) -> Any:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    annotation = _strip_annotated(annotation)
    origin = get_origin(annotation)
    if origin is not None and str(origin) in ("typing.Union", "<class 'types.UnionType'>"):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _strip_annotated(args[0]), True
    return annotation, False


def _is_list(annotation: Any) -> bool:
    inner, _ = _unwrap_optional(annotation)
    return get_origin(inner) is list


def _choices(annotation: Any) -> tuple[Any, ...] | None:
    inner, _ = _unwrap_optional(annotation)
    if get_origin(inner) is Literal:
        return tuple(get_args(inner))
    return None


def _scalar_type(annotation: Any) -> type:
    inner, _ = _unwrap_optional(annotation)
    if get_origin(inner) is list:
        inner = _strip_annotated(get_args(inner)[0])
    if get_origin(inner) is Literal:
        return str
    if inner in (int, float, bool):
        return inner  # type: ignore[no-any-return]
    return str


def _type_name(annotation: Any) -> str:
    inner, optional = _unwrap_optional(annotation)
    if get_origin(inner) is list:
        return f"list[{_scalar_type(inner).__name__}]"
    if get_origin(inner) is Literal:
        return "choice"
    name = getattr(inner, "__name__", str(inner))
    return f"{name}{' | None' if optional else ''}"


# --------------------------------------------------------------------------- #
# Typer generator
# --------------------------------------------------------------------------- #


class _GreedyListCommand(TyperCommand):
    """Let ``--tickers AAPL MSFT NVDA`` work: gather bare tokens after a list option.

    Click options cannot take a variable number of values, so before parsing the
    tokens following a list option (up to the next ``-``-prefixed token) are
    rewritten into repeated options.
    """

    greedy_options: ClassVar[set[str]] = set()

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        rewritten: list[str] = []
        i = 0
        while i < len(args):
            token = args[i]
            if token in self.greedy_options and i + 1 < len(args):
                rewritten.append(token)
                i += 1
                first = True
                while i < len(args) and (first or not args[i].startswith("-")):
                    if not first:
                        rewritten.append(token)
                    rewritten.append(args[i])
                    first = False
                    i += 1
                continue
            rewritten.append(token)
            i += 1
        return super().parse_args(ctx, rewritten)


def _cli_option_name(field_name: str) -> str:
    return "--" + field_name.replace("_", "-")


def build_parameters(cmd: Command) -> tuple[list[inspect.Parameter], dict[str, Any], set[str]]:
    """Typer parameters derived from the model's fields, types, defaults and help."""
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    greedy: set[str] = set()
    for name, info in cmd.params.model_fields.items():
        annotation = info.annotation
        scalar = _scalar_type(annotation)
        is_list = _is_list(annotation)
        _, optional = _unwrap_optional(annotation)
        choices = _choices(annotation)
        help_text = info.description or ""
        if choices:
            help_text = f"{help_text} [one of: {', '.join(str(c) for c in choices)}]".strip()
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        is_positional = bool(extra.get("positional"))
        option_name = _cli_option_name(info.alias or name)
        if is_list:
            typ: Any = list[scalar]  # type: ignore[valid-type]
            default: Any = None
            if not is_positional:
                greedy.add(option_name)
        else:
            typ = (
                scalar
                if (info.is_required() or not optional or scalar is bool)
                else (scalar | None)
            )
            default = (
                None
                if info.is_required()
                else _json_default(info.get_default(call_default_factory=True))
            )
            if scalar is bool and default is None:
                default = False
        if is_positional:
            param_default = typer.Argument(
                default, help=help_text, show_default=not info.is_required()
            )
        elif scalar is bool:
            param_default = typer.Option(bool(default), option_name, help=help_text)
        else:
            param_default = typer.Option(
                default, option_name, help=help_text, show_default=default is not None
            )
        params.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=param_default, annotation=typ
            )
        )
        annotations[name] = typ
    if cmd.emits_data:
        for extra_name, extra_typ, extra_default, extra_help in (
            (
                "format",
                str,
                None,
                "Output format [one of: table, json, csv]; default table on a TTY, csv when piped.",
            ),
        ):
            params.append(
                inspect.Parameter(
                    extra_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(extra_default, "--format", help=extra_help),
                    annotation=extra_typ | None,
                )
            )
            annotations[extra_name] = extra_typ | None
    if cmd.uses_providers:
        params.append(
            inspect.Parameter(
                "refresh",
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    False, "--refresh", help="Bypass the cache and re-fetch from the provider."
                ),
                annotation=bool,
            )
        )
        annotations["refresh"] = bool
    return params, annotations, greedy


def make_typer_callable(
    cmd: Command, invoke: Callable[[Command, dict[str, Any], typer.Context], None]
) -> tuple[Callable[..., None], set[str]]:
    """A function whose signature Typer turns into the subcommand."""
    params, annotations, greedy = build_parameters(cmd)

    def run(ctx: typer.Context, **kwargs: Any) -> None:
        invoke(cmd, kwargs, ctx)

    ctx_param = inspect.Parameter(
        "ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=typer.Context
    )
    run.__signature__ = inspect.Signature([ctx_param, *params])  # type: ignore[attr-defined]
    run.__annotations__ = {"ctx": typer.Context, **annotations, "return": None}
    run.__name__ = cmd.leaf.replace("-", "_")
    run.__doc__ = cmd.help
    return run, greedy


def build_app(
    root: typer.Typer, invoke: Callable[[Command, dict[str, Any], typer.Context], None]
) -> typer.Typer:
    """Attach every registered command to ``root`` under its (possibly nested) group.

    A command whose name is also a prefix of other commands (``serve`` beside
    ``serve.token.rotate``) becomes a group that runs the command when invoked
    without a subcommand.
    """
    commands = all_commands()
    names = {c.name for c in commands}
    groups: dict[tuple[str, ...], typer.Typer] = {(): root}

    def group_for(path: tuple[str, ...]) -> typer.Typer:
        if path in groups:
            return groups[path]
        parent = group_for(path[:-1])
        leaf = path[-1]
        default_cmd = next((c for c in commands if c.name == ".".join(path)), None)
        app = typer.Typer(
            name=leaf,
            help=(default_cmd.help if default_cmd else GROUP_HELP.get(leaf, f"{leaf} commands")),
            no_args_is_help=default_cmd is None,
            invoke_without_command=default_cmd is not None,
        )
        if default_cmd is not None:
            fn, greedy = make_typer_callable(default_cmd, invoke)
            cls = type(f"Greedy_{leaf}", (_GreedyListCommand,), {"greedy_options": greedy})
            parent.add_typer(app, name=leaf)
            _attach_default(app, default_cmd, fn)
            _ = cls
        else:
            parent.add_typer(app, name=leaf)
        groups[path] = app
        return app

    for cmd in commands:
        is_group_default = any(n.startswith(cmd.name + ".") for n in names)
        if is_group_default:
            group_for((*cmd.group_path, cmd.leaf))
            continue
        target = group_for(cmd.group_path)
        fn, greedy = make_typer_callable(cmd, invoke)
        cls = type(f"Greedy_{cmd.leaf}", (_GreedyListCommand,), {"greedy_options": greedy})
        target.command(name=cmd.leaf.replace("_", "-"), help=cmd.help, cls=cls)(fn)
        for alias in cmd.aliases:
            alias_leaf = alias.rsplit(".", 1)[-1]
            target.command(
                name=alias_leaf,
                help=f"Deprecated alias of `{cmd.cli_name}`.",
                cls=cls,
                hidden=True,
            )(fn)
    return root


def _attach_default(app: typer.Typer, cmd: Command, fn: Callable[..., None]) -> None:
    """Run ``cmd`` when its group is invoked without a subcommand."""

    def callback(ctx: typer.Context, **kwargs: Any) -> None:
        if ctx.invoked_subcommand is None:
            fn(ctx, **kwargs)

    callback.__signature__ = fn.__signature__  # type: ignore[attr-defined]
    callback.__annotations__ = dict(fn.__annotations__)
    callback.__doc__ = cmd.help
    app.callback(invoke_without_command=True)(callback)


def validate_params(cmd: Command, raw: dict[str, Any]) -> BaseModel:
    """Build the parameter model, turning validation errors into ``UsageError``."""
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        target = cmd.param_aliases.get(key, key)
        if target != key:
            warnings.warn(
                f"--{key} is deprecated; use --{target}", DeprecationWarning, stacklevel=2
            )
        if value is None or (
            isinstance(value, list) and not value and key not in cmd.params.model_fields
        ):
            continue
        if isinstance(value, list) and not value:
            continue
        cleaned[target] = value
    try:
        return cmd.params.model_validate(cleaned)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "input"
            problems.append(f"{loc}: {err['msg']}")
        raise UsageError(
            f"invalid parameters for `{cmd.cli_name}`: " + "; ".join(problems),
            hint=f"run: sobres {cmd.cli_name} --help",
        ) from None
