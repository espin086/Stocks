"""``sobres doctor`` — every check actionable; exit 0 means it works."""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd
from pydantic import Field
from rich.console import Console
from rich.table import Table

from sobres.cli.context import Context
from sobres.doctor import CheckReport, exit_code, run_checks
from sobres.registry import Params, register
from sobres.results import Result

GLYPHS = {"ok": "✔", "warn": "!", "fail": "✘", "skip": "-"}


class DoctorReport(Result):
    index_label: ClassVar[str | None] = None
    column_kinds: ClassVar[dict[str, str]] = {
        "category": "text",
        "check": "text",
        "status": "text",
        "message": "text",
        "next": "text",
    }

    checks: list[dict[str, Any]]
    summary: dict[str, int]
    exit_code: int

    def table(self) -> pd.DataFrame:
        rows = [
            {
                "category": c["category"],
                "check": c["name"],
                "status": c["status"],
                "message": c["message"],
                "next": c.get("fix_hint") or "",
            }
            for c in self.checks
        ]
        return pd.DataFrame(rows, columns=["category", "check", "status", "message", "next"])

    def header_lines(self) -> list[str]:
        return []

    def render_rich(self, console: Console) -> None:
        """Grouped by category, one glyph line per check, then a one-line summary."""
        current = None
        for c in self.checks:
            if c["category"] != current:
                current = c["category"]
                console.print(f"\n[bold]{current}[/bold]")
            line = f"  {GLYPHS[c['status']]} {c['name']}: {c['message']}"
            if c.get("fixed"):
                line += f"  (fixed: {c['fixed']})"
            console.print(line, markup=False)
            if c["status"] in ("warn", "fail") and c.get("fix_hint"):
                console.print(f"      → {c['fix_hint']}", markup=False)
        s = self.summary
        console.print(
            f"\n{s['ok']} ok, {s['warn']} warnings, {s['fail']} failed, {s['skip']} skipped",
        )
        _ = Table  # rich Table is used by the generic renderer; kept for symmetry


class DoctorParams(Params):
    offline: bool = Field(
        default=False, description="Skip network-dependent checks (reported as skipped)."
    )
    fix: bool = Field(
        default=False, description="Apply every safe registered repair; never touches secrets."
    )
    strict: bool = Field(default=False, description="Exit 1 on warnings as well as failures.")


def build_report(reports: list[CheckReport], *, strict: bool) -> DoctorReport:
    checks = [
        {
            "name": r.name,
            "category": r.category,
            "status": r.status,
            "message": r.message,
            "fix_hint": r.fix_hint,
            "fixed": r.fixed,
            **({"detail": r.detail} if r.detail else {}),
        }
        for r in reports
    ]
    summary = {s: sum(1 for r in reports if r.status == s) for s in ("ok", "warn", "fail", "skip")}
    return DoctorReport(checks=checks, summary=summary, exit_code=exit_code(reports, strict=strict))


@register(
    "doctor", "Diagnose the install; every failing line says how to fix it.", result=DoctorReport
)
def doctor(p: DoctorParams, ctx: Context) -> DoctorReport:
    reports = run_checks(ctx, offline=p.offline, fix=p.fix)
    report = build_report(reports, strict=p.strict)
    if report.exit_code:
        ctx.pending_exit_code = report.exit_code
    return report
