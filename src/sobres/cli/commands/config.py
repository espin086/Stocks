"""``sobres config`` — set, show (masked) and locate the config file."""

from __future__ import annotations

from sobres.cli.context import Context
from sobres.config import display_value, read_config_file, write_config_file
from sobres.registry import Params, positional, register
from sobres.results import MessageResult, RecordsResult
from sobres.settings import all_settings, get_setting


class ConfigSetParams(Params):
    key: str = positional(description="Setting key, e.g. fred_api_key.")
    value: str = positional(description="Value to store.")


@register(
    "config.set",
    "Persist a setting to the config file (mode 0600).",
    result=MessageResult,
    emits_data=False,
)
def config_set(p: ConfigSetParams, ctx: Context) -> MessageResult:
    setting = get_setting(p.key)
    setting.coerce(p.value)  # validates type and choices
    values = read_config_file(ctx.config.path)
    values[setting.key] = p.value
    write_config_file(ctx.config.path, values)
    return MessageResult(
        message=f"{setting.key} = {display_value(setting, p.value)} written to {ctx.config.path}"
    )


class ConfigShowParams(Params):
    pass


@register(
    "config.show",
    "Show every setting, its value (secrets masked) and source.",
    result=RecordsResult,
)
def config_show(p: ConfigShowParams, ctx: Context) -> RecordsResult:
    rows = [
        {
            "key": s.key,
            "value": display_value(s, ctx.config.get(s.key)),
            "source": ctx.config.source(s.key),
            "env": s.env,
        }
        for s in all_settings()
    ]
    return RecordsResult(rows=rows, columns=["key", "value", "source", "env"])


class ConfigPathParams(Params):
    pass


@register("config.path", "Print the config file location.", result=MessageResult, emits_data=False)
def config_path_cmd(p: ConfigPathParams, ctx: Context) -> MessageResult:
    return MessageResult(message=str(ctx.config.path))


class ConfigUnsetParams(Params):
    key: str = positional(description="Setting key to remove from the config file.")


@register(
    "config.unset", "Remove a setting from the config file.", result=MessageResult, emits_data=False
)
def config_unset(p: ConfigUnsetParams, ctx: Context) -> MessageResult:
    setting = get_setting(p.key)
    values = read_config_file(ctx.config.path)
    removed = values.pop(setting.key, None) is not None
    if removed:
        write_config_file(ctx.config.path, values)
    return MessageResult(
        message=f"{setting.key} {'removed from' if removed else 'was not set in'} {ctx.config.path}"
    )
