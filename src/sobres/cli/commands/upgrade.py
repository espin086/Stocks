"""``sobres upgrade`` — detect the installer, print the exact command, confirm, run."""

from __future__ import annotations

import subprocess

from pydantic import Field

from sobres import doctor as doctor_mod
from sobres.__about__ import __version__
from sobres.cli.context import Context
from sobres.core.errors import UsageError
from sobres.doctor import UPGRADE_COMMANDS, detect_installer
from sobres.registry import Params, register
from sobres.results import MessageResult


class UpgradeParams(Params):
    check: bool = Field(default=False, description="Only report whether a newer version exists.")
    yes: bool = Field(default=False, description="Skip the confirmation prompt.")


@register(
    "upgrade",
    "Upgrade sobres with the installer that installed it.",
    result=MessageResult,
    emits_data=False,
)
def upgrade(p: UpgradeParams, ctx: Context) -> MessageResult:
    installer = detect_installer(dict(ctx.environ))
    command = UPGRADE_COMMANDS[installer]
    latest = doctor_mod.latest_release()
    detail = {
        "installer": installer,
        "command": command,
        "installed": __version__,
        "latest": latest,
    }
    if p.check:
        if latest is None:
            return MessageResult(
                message="could not reach PyPI to check for a newer version", detail=detail
            )
        newer = latest != __version__
        return MessageResult(
            message=(
                f"{latest} is available (installed {__version__})"
                if newer
                else f"{__version__} is the latest"
            ),
            detail=detail,
        )
    ctx.note(f"detected installer: {installer}")
    ctx.note(f"upgrade command: {command}")
    if installer == "container":
        return MessageResult(
            message="running in the container: pull the new image and restart it", detail=detail
        )
    if not p.yes and not ctx.ask_confirm("run it now?", default=False):
        raise UsageError("upgrade cancelled", hint=f"run it yourself: {command}")
    completed = subprocess.run(command.split(), check=False)
    if completed.returncode != 0:
        raise UsageError(
            f"upgrade command exited {completed.returncode}", hint=f"run it yourself: {command}"
        )
    return MessageResult(
        message="upgraded; pending migrations apply on the next command", detail=detail
    )
