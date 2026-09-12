"""The web UI's non-negotiables, checked at the source: what the SPA is built from.

These are static checks over ``frontend/`` — the libraries it declares, the
theme tokens it defines, how its charts and forms are written — plus a
known-answer WCAG contrast computation over the palette. They do not drive a
browser; ``npm run build`` (type check, bundle budget) is the other half and
runs in CI.

Scenarios: Chosen libraries; Defaults are visible, not hidden; The equivalent
command is always shown; Dark by default; Both themes are complete; Preference
persists; Contrast; Interactive efficient frontier; Backtest visualization;
Charts state their assumptions; Every chart's data is obtainable; Animation
serves comprehension; Reduced motion is respected; Animation never gates
interaction; Progress is real; Keyboard operable; Screen readers; Small
screens; Bundle size is a CI gate; Charts load on demand; Interaction latency.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SRC = FRONTEND / "src"


def _read(rel: str) -> str:
    return (FRONTEND / rel).read_text(encoding="utf-8")


def _sources() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): p.read_text(encoding="utf-8") for p in SRC.rglob("*.ts*")
    }


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", block))


def _theme_blocks() -> tuple[dict[str, str], dict[str, str]]:
    css = _read("src/theme/tokens.css")  # shared with site/ (0006)
    light = re.search(r":root \{(.*?)\}", css, re.S)
    dark = re.search(r"\.dark \{(.*?)\}", css, re.S)
    assert light and dark
    return _tokens(light.group(1)), _tokens(dark.group(1))


def _luminance(hex_color: str) -> float:
    # WCAG 2.1 relative luminance: sRGB channels linearized, weighted 0.2126/0.7152/0.0722.
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio (L1 + 0.05) / (L2 + 0.05), lighter over darker."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_formula_against_the_published_anchors() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)  # the classic AA edge


def test_chosen_libraries_and_strict_typescript() -> None:
    pkg = json.loads(_read("package.json"))
    deps = {**pkg["dependencies"], **pkg["devDependencies"]}
    for lib in (
        "react",
        "typescript",
        "vite",
        "tailwindcss",
        "@radix-ui/react-tabs",
        "@tanstack/react-query",
        "@tanstack/react-table",
        "echarts",
        "motion",
    ):
        assert lib in deps, lib
    ts = json.loads(re.sub(r"//.*", "", _read("tsconfig.json")))
    assert ts["compilerOptions"]["strict"] is True
    assert ts["compilerOptions"]["noUncheckedIndexedAccess"] is True


def test_defaults_are_visible_and_the_equivalent_command_is_shown() -> None:
    form = _read("src/forms/CommandForm.tsx")
    assert "p.default" in form  # initial values come from the registry's defaults
    assert "equivalent command" in form and "copy" in form
    # No "advanced" panel hides a meaning-changing default.
    assert "advanced" not in form.lower()


def test_dark_by_default_and_preference_persists_with_a_system_option() -> None:
    html = _read("index.html")
    assert '<html lang="en" class="dark">' in html
    assert 'localStorage.getItem("sobres.theme") || "dark"' in html
    theme = _read("src/theme/ThemeProvider.tsx")
    assert 'export type ThemePreference = "dark" | "light" | "system";' in theme
    assert "localStorage.setItem(KEY, p)" in theme
    assert 'matchMedia("(prefers-color-scheme: dark)")' in theme


def test_both_themes_define_the_same_tokens_and_charts_read_them() -> None:
    light, dark = _theme_blocks()
    assert set(light) == set(dark) and len(light) >= 16
    assert all(light[k] != dark[k] for k in ("bg", "fg", "accent"))
    theme = _read("src/theme/ThemeProvider.tsx")
    for token in ("--fg", "--fg-muted", "--border", "--accent", "--bg-elev", "--series-"):
        assert token in theme  # chart tokens are read from the CSS variables, per theme
    for name, text in _sources().items():
        if name.startswith("charts/"):
            assert not re.search(r"#[0-9a-fA-F]{6}", text), f"{name} hard-codes a colour"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_meets_wcag_aa(theme: str) -> None:
    light, dark = _theme_blocks()
    t = light if theme == "light" else dark
    pairs = [
        ("fg", "bg"),
        ("fg", "bg-elev"),
        ("fg-muted", "bg"),
        ("fg-muted", "bg-elev"),
        ("accent", "bg"),
        ("accent-fg", "accent"),
    ]
    for fg, bg in pairs:
        ratio = contrast(t[fg], t[bg])
        assert ratio >= 4.5, f"{theme}: {fg} on {bg} = {ratio:.2f}"
    for status in ("ok", "warn", "fail"):
        assert contrast(t[status], t["bg-elev"]) >= 3.0, f"{theme}: {status} icon on bg-elev"


def test_frontier_chart_marks_named_points_and_shows_weights() -> None:
    chart = _read("src/charts/FrontierChart.tsx")
    assert '"scatter", name: "min variance"' in chart
    assert '"scatter", name: "max Sharpe"' in chart
    assert 'type: "line", name: "frontier"' in chart
    assert "setSelected(row)" in chart and "tickers.map" in chart  # hover shows the weights


def test_backtest_charts_equity_drawdown_and_weights() -> None:
    chart = _read("src/charts/BacktestCharts.tsx")
    assert 'name: "strategy"' in chart and 'name: "equal weight"' in chart
    assert "function drawdown" in chart and 'name: "drawdown"' in chart
    assert "weights_history" in chart and 'stack: "w"' in chart


def test_charts_state_their_assumptions_beside_them() -> None:
    view = _read("src/views/ResultView.tsx")
    assert "ProvenanceBlock" in view
    assert (
        "estimators:" in view
        and "transaction costs" in view
        and "window" in _read("src/components/Provenance.tsx")
    )


def test_every_charts_data_is_a_table_and_a_csv() -> None:
    view = _read("src/views/ResultView.tsx")
    assert "<ResultTable" in view  # the rows every chart draws are also a table
    table = _read("src/components/ResultTable.tsx")
    assert "Download CSV" in table and "toCsv(columns, rows)" in table


def test_animation_serves_comprehension_and_never_gates_interaction() -> None:
    frontier = _read("src/charts/FrontierChart.tsx")
    assert "animationDuration: 900" in frontier  # the curve draws along its length
    echart = _read("src/charts/EChart.tsx")
    assert "animation: !prefersReducedMotion()" in echart
    for name, text in _sources().items():
        assert "pointer-events-none" not in text, name  # nothing is blocked while animating
        assert "await new Promise" not in text or "setTimeout" not in text, name


def test_reduced_motion_is_respected() -> None:
    css = _read("src/index.css")
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "prefers-reduced-motion: reduce" in _read("src/theme/ThemeProvider.tsx")


def test_progress_is_real() -> None:
    progress = _read("src/components/JobProgress.tsx")
    assert "job.progress" in progress and "aria-valuenow={percent}" in progress
    code = re.sub(r"/\*.*?\*/", "", progress, flags=re.S)  # the docstring names the anti-pattern
    assert "indeterminate" not in code.lower() and "animate-pulse" not in code


def test_keyboard_operable_with_visible_focus() -> None:
    css = _read("src/index.css")
    assert ":focus-visible { outline: 2px solid var(--accent)" in css
    for name, text in _sources().items():
        # Clickable elements are buttons or links, never bare divs with onClick.
        assert not re.search(r"<div[^>]*onClick", text), name
        assert "tabIndex={-1}" not in text, name


def test_screen_readers_get_a_text_alternative_for_every_chart() -> None:
    echart = _read("src/charts/EChart.tsx")
    assert 'role="img" aria-label={ariaLabel}' in echart
    for name, text in _sources().items():
        if name.startswith("charts/") and "<EChart" in text:
            assert text.count("<EChart ") == text.count("ariaLabel="), name
    assert "aria-label={name}" in _read("src/components/ResultTable.tsx")


def test_small_screens_scroll_tables_within_their_container() -> None:
    assert 'className="overflow-x-auto' in _read("src/components/ResultTable.tsx")
    assert 'name="viewport" content="width=device-width, initial-scale=1.0"' in _read("index.html")
    for name, text in _sources().items():
        assert "min-w-[" not in text and "w-[1" not in text, name  # no fixed wide widths
    assert "max-w-full" in _read("src/charts/EChart.tsx")


def test_bundle_size_is_a_ci_gate() -> None:
    pkg = json.loads(_read("package.json"))
    assert "check-bundle.mjs" in pkg["scripts"]["build"]  # the build itself fails over budget
    script = _read("scripts/check-bundle.mjs")
    assert "const BUDGET = 300 * 1024;" in script and "process.exit(1)" in script


def test_charts_load_on_demand() -> None:
    view = _read("src/views/ResultView.tsx")
    assert 'lazy(() => import("@/charts/FrontierChart")' in view
    assert 'lazy(() => import("@/charts/BacktestCharts")' in view
    vite = _read("vite.config.ts")
    assert "echarts" in vite and "motion" in vite  # split into their own chunks
    for name, text in _sources().items():
        if not name.startswith("charts/"):
            assert 'from "echarts' not in text, f"{name} imports ECharts eagerly"


def test_interaction_latency_uses_downsampling_and_canvas() -> None:
    chart = _read("src/charts/BacktestCharts.tsx")
    assert chart.count('sampling: "lttb"') >= 3 and "large: true" in chart
    assert 'renderer: "canvas"' in _read("src/charts/EChart.tsx")
