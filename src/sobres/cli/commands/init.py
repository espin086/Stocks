"""``sobres init`` — the guided setup wizard over the settings registry.

Walks every declared setting in order, shows its description and where to
obtain it, prompts (no echo for secrets), offers live verification with
consent, sets up storage, writes the config file at 0600, runs doctor, and
prints one runnable first command. Re-running with no changes leaves the file
byte-identical. ``--non-interactive`` takes values from flags and environment
only and exits 3 naming any missing required value.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from sobres.cli.commands.doctor import DoctorReport, build_report
from sobres.cli.context import Context
from sobres.config import display_value, read_config_file, write_config_file
from sobres.core.errors import ConfigurationError
from sobres.doctor import run_checks
from sobres.registry import Params, register
from sobres.settings import Setting, all_settings


class InitParams(Params):
    non_interactive: bool = Field(
        default=False,
        description="Take values from flags and the environment only; never prompt.",
    )
    verify: bool = Field(
        default=True,
        description="Offer to verify keys with one live request (--no-verify to skip).",
    )
    offline: bool = Field(
        default=False, description="Skip network checks in the closing doctor run."
    )
    web: bool = Field(
        default=False,
        description="Open the settings page in the browser instead (sobres open settings).",
    )
    set_values: list[str] = Field(
        default_factory=list,
        alias="set",
        description="key=value pairs to apply without prompting, e.g. --set fred_api_key=ABC.",
    )


class InitReport(DoctorReport):
    config_path: str = ""
    db_location: str = ""
    first_command: str = ""
    changed: list[str] = Field(default_factory=list)

    def header_lines(self) -> list[str]:
        return [
            f"config: {self.config_path}",
            f"database: {self.db_location}",
            f"changed: {', '.join(self.changed) or 'nothing'}",
            f"try next: {self.first_command}",
        ]


def _parse_set(values: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values:
        key, sep, value = item.partition("=")
        if not sep:
            raise ConfigurationError(f"--set expects key=value, got {item!r}")
        out[key.strip()] = value.strip()
    return out


def _prompt_setting(setting: Setting, current: Any, ctx: Context, *, verify: bool) -> str | None:
    """Return the value to store (None to leave as is / unset)."""
    ctx.note("")
    ctx.note(f"{setting.key} — {setting.description}")
    if setting.obtain:
        ctx.note(f"  obtain: {setting.obtain}")
    if setting.affects:
        ctx.note(f"  needed by: {', '.join(setting.affects)}")
    if setting.choices:
        ctx.note(f"  one of: {', '.join(setting.choices)}")
    shown = display_value(setting, current)
    if current not in (None, ""):
        ctx.note(f"  current: {shown}")
    if current not in (None, "") and not ctx.ask_confirm(
        f"  current value {shown}; replace it?", default=False
    ):
        return str(current)
    label = f"  {setting.key}" + ("" if setting.required else " (enter to skip)")
    while True:
        answer = ctx.ask(label, secret=setting.secret)
        if answer == "":
            if setting.required:
                ctx.note("  a value is required")
                continue
            if setting.affects:
                ctx.note(f"  skipped; without it: {', '.join(setting.affects)} will not work")
            return None if current in (None, "") else str(current)
        try:
            setting.coerce(answer)
        except ConfigurationError as exc:
            ctx.note(f"  {exc.message}")
            continue
        if (
            setting.validate_live is not None
            and verify
            and ctx.ask_confirm("  verify it with one request now?", default=True)
        ):
            outcome = setting.validate_live(answer)
            ctx.note(f"  {outcome.message}")
            if not outcome.ok:
                choice = ctx.ask("  [r]etry, [k]eep anyway, or [s]kip", default="s").lower()[:1]
                if choice == "r":
                    continue
                if choice == "k":
                    return answer
                return None if current in (None, "") else str(current)
        return answer


@register(
    "init",
    "Guided setup of every setting; ends by running doctor.",
    result=InitReport,
    human_default=True,
)
def init(p: InitParams, ctx: Context) -> InitReport:
    if p.web:
        from sobres.cli.commands.serve import OpenParams, open_view

        opened = open_view(OpenParams(target=["settings"]), ctx)
        return InitReport(
            checks=[],
            summary={"ok": 0, "warn": 0, "fail": 0, "skip": 0},
            exit_code=0,
            config_path=str(ctx.config.path),
            db_location="",
            first_command=opened.summary_line(),
            changed=[],
        )
    existing = read_config_file(ctx.config.path)
    values: dict[str, Any] = dict(existing)
    explicit = _parse_set(p.set_values)
    changed: list[str] = []
    interactive = ctx.interactive and not p.non_interactive
    for setting in all_settings():
        if setting.key in explicit:
            setting.coerce(explicit[setting.key])
            if values.get(setting.key) != explicit[setting.key]:
                values[setting.key] = explicit[setting.key]
                changed.append(setting.key)
            continue
        if not interactive:
            env_value = next(
                (ctx.environ[n] for n in setting.env_names if ctx.environ.get(n)), None
            )
            if env_value is not None and values.get(setting.key) != env_value:
                values[setting.key] = env_value
                changed.append(setting.key)
            if setting.required and values.get(setting.key) in (None, ""):
                raise ConfigurationError(
                    f"required setting {setting.key} is not set",
                    hint=(
                        f"set {setting.env} in the environment or pass --set {setting.key}=<value>"
                    ),
                )
            continue
        new = _prompt_setting(setting, values.get(setting.key), ctx, verify=p.verify)
        if new is None:
            if setting.key in values:
                values.pop(setting.key)
                changed.append(setting.key)
        elif values.get(setting.key) != new:
            values[setting.key] = new
            changed.append(setting.key)
    if changed or not ctx.config.path.exists():
        write_config_file(ctx.config.path, values)
    # Re-resolve so storage setup and doctor see what was just written.
    fresh = Context.build(
        environ=ctx.environ,
        config_path=ctx.config.path,
        sources=ctx.sources,
        interactive=ctx.interactive,
        stderr=ctx.stderr,
        clock=ctx.clock,
    )
    try:
        storage = fresh.storage
        db_location = storage.location
        reports = run_checks(fresh, offline=p.offline)
    finally:
        fresh.close()
    report = build_report(reports, strict=False)
    first = (
        "sobres data macro DGS10 --start 2020-01-01"
        if values.get("fred_api_key")
        else "sobres data prices AAPL MSFT --start 2020-01-01"
    )
    return InitReport(
        checks=report.checks,
        summary=report.summary,
        exit_code=report.exit_code,
        config_path=str(ctx.config.path),
        db_location=db_location,
        first_command=first,
        changed=changed,
    )
