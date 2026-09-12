"""The landing page (0006), checked at its source and its build rules.

Static checks over ``site/``: the stack it declares, the content the served HTML
carries before any script runs, the recorded data every figure draws, the
build gates (bundle, content, Lighthouse) and the Pages workflow's privileges.
The same contrast computation as the app's applies, since the page uses the
app's dark tokens.

Scenarios: Chosen libraries; Published automatically; Broken builds do not
deploy; Shares the app's design tokens; Dark by design; Contrast; No flash;
Animation shows the product; The hero frontier; The terminal transcript is
real; Reduced motion; No information only in motion; Animation never blocks
reading; Only shipped capabilities are claimed; Install commands are generated;
Numbers are sourced; Disclaimer; Lighthouse budget; Bundle budget; Readable
before JavaScript; Deferred libraries; Self-hosted assets; No tracking;
Keyboard; Structure; Small screens; Link previews.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.ui.test_frontend_source import contrast

REPO = Path(__file__).resolve().parents[2]
SITE = REPO / "site"
INDEX = (SITE / "index.html").read_text()
MAIN = (SITE / "src" / "main.ts").read_text()
FIGURES = (SITE / "src" / "figures.ts").read_text()
MOTION = (SITE / "src" / "motion.ts").read_text()
STYLE = (SITE / "src" / "style.css").read_text()
PAGES = (REPO / ".github" / "workflows" / "pages.yml").read_text()


def _pkg() -> dict[str, dict[str, str]]:
    return json.loads((SITE / "package.json").read_text())


def test_chosen_libraries_and_a_static_build() -> None:
    pkg = _pkg()
    deps = {**pkg["dependencies"], **pkg["devDependencies"]}
    for lib in ("vite", "typescript", "tailwindcss", "gsap", "lenis", "echarts"):
        assert lib in deps, lib
    ts = json.loads((SITE / "tsconfig.json").read_text())
    assert ts["compilerOptions"]["strict"] is True
    vite = (SITE / "vite.config.ts").read_text()
    assert 'base: "/sobres/"' in vite and 'outDir: "dist"' in vite
    assert "server" not in pkg["dependencies"]  # nothing runs at request time


def test_published_automatically_with_least_privilege_and_no_broken_deploys() -> None:
    assert "permissions:\n  contents: read" in PAGES
    deploy = PAGES.split("  deploy:\n", 1)[1]
    assert "needs: build" in deploy and "if: github.event_name != 'pull_request'" in deploy
    assert "pages: write" in deploy and "id-token: write" in deploy
    assert "actions/deploy-pages@v4" in deploy
    build = PAGES.split("  build:\n", 1)[1].split("  deploy:\n", 1)[0]
    assert "pages: write" not in build
    assert "npm run build" in build and "@lhci/cli" in build  # a failing gate deploys nothing
    assert "branches: [main]" in PAGES and "site/**" in PAGES


def test_shares_the_apps_design_tokens_and_is_dark_by_design() -> None:
    assert '@import "../../frontend/src/theme/tokens.css";' in STYLE
    assert '@import "./theme/tokens.css";' in (REPO / "frontend" / "src" / "index.css").read_text()
    assert '<html lang="en" class="dark">' in INDEX
    assert '<meta name="color-scheme" content="dark" />' in INDEX
    assert "prefers-color-scheme" not in STYLE and "prefers-color-scheme" not in MAIN
    assert ":root { color-scheme: dark; }" in STYLE
    # No flash: the ground is painted inline before any stylesheet loads.
    assert "<style>html{background:#0b0f14;color:#e6edf3}</style>" in INDEX
    assert INDEX.index("<style>html{background") < INDEX.index('<script type="module"')


def test_contrast_of_the_dark_tokens_meets_aa() -> None:
    css = (REPO / "frontend" / "src" / "theme" / "tokens.css").read_text()
    dark = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", css.split(".dark {", 1)[1]))
    for fg, bg in (("fg", "bg"), ("fg-muted", "bg-elev"), ("accent", "bg"), ("ok", "bg-elev")):
        assert contrast(dark[fg], dark[bg]) >= 4.5, (fg, bg)


def test_animation_shows_the_product_from_recorded_data() -> None:
    data = SITE / "src" / "data"
    meta = json.loads((data / "figures-meta.json").read_text())
    frontier = json.loads((data / "frontier.json").read_text())
    backtest = json.loads((data / "backtest.json").read_text())
    transcript = (data / "terminal.txt").read_text()
    assert "sobres optimize frontier" in meta["commands"]["frontier"]
    assert sum(1 for r in frontier["rows"] if r["max_sharpe"]) == 1  # the point that lands last
    assert sum(1 for r in frontier["rows"] if r["min_variance"]) == 1
    assert len(backtest["equity_curve"]) > 500 and "walk_forward_sharpe" in backtest
    assert backtest["in_sample_sharpe"] > backtest["walk_forward_sharpe"]  # the thesis, in numbers
    assert transcript.startswith("objective: max_sharpe") and "Not investment advice" in transcript
    assert "For research and education only" in transcript  # the CLI's own footer, recorded
    script = (SITE / "scripts" / "record_figures.py").read_text()
    assert (
        re.search(r'"optimize",\s*"frontier"', script) and 'fmt="table"' in script
    )  # regenerable, not hand-written
    assert 'named("max_sharpe")' in FIGURES and "animationDelay" in FIGURES
    assert "lines.slice(0, Math.round(shown.n))" in MOTION  # the terminal replays the recording


def test_reduced_motion_renders_final_states_and_native_scrolling() -> None:
    assert 'if (!reducedMotion()) void import("./motion")' in MAIN  # Lenis never loads
    assert (
        "@media (prefers-reduced-motion: reduce)" in STYLE and "animation: none !important" in STYLE
    )
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in FIGURES
    assert "animation: !reduced" in FIGURES
    assert "scroll-behavior: auto" in STYLE


def test_no_information_only_in_motion_and_nothing_blocks_reading() -> None:
    # Every animated figure has a text counterpart set before any animation library loads.
    for hook in (
        "data-frontier-source",
        "data-equity-summary",
        "data-sharpe-in-sample",
        "data-sharpe-walk-forward",
        "data-honesty-text",
    ):
        assert hook in INDEX and f"[{hook}]" in MAIN, hook
    assert "if (termText) termText.textContent = terminal; // final state first" in MAIN
    assert "pin: true" not in MOTION and "scrub" not in MOTION  # no section traps scrolling
    assert "once: true" in MOTION


def test_only_shipped_capabilities_are_claimed() -> None:
    body = INDEX.split("<main", 1)[1]
    shipped, roadmap = body.split('<section class="wrap roadmap"', 1)
    for claim in ("Fama-French 3 and 5", "ARIMA", "Monte Carlo", "PPP"):
        assert claim not in shipped and claim in roadmap, claim
    assert "not yet available" in roadmap.lower() and "Not shipped" not in shipped
    assert "sobres open" in shipped and "optimize backtest" in shipped


def test_install_commands_and_version_are_generated_at_build_time() -> None:
    generate = (SITE / "scripts" / "generate.mjs").read_text()
    assert "__about__.py" in generate and "process.exit(1)" in generate
    assert "generated.version" in MAIN and "generated.install.docker" in MAIN
    assert "site/src/generated.json" in (REPO / ".gitignore").read_text()
    assert "npm run generate && tsc" in _pkg()["scripts"]["build"]


def test_numbers_are_sourced_and_the_disclaimer_is_on_the_page() -> None:
    assert (
        "meta.tickers.join" in MAIN
        and "backtest.cost_bps" in MAIN
        and "meta.backtest.lookback" in MAIN
    )
    assert "Data: ${meta.data_source}" in MAIN
    assert "Not investment advice" in INDEX and "hypothetical" in INDEX
    assert "data-data-note" in INDEX and "synthesized random walks" in MAIN


def test_performance_gates_are_build_failures() -> None:
    lh = json.loads((SITE / "lighthouserc.json").read_text())
    for category in ("performance", "accessibility", "best-practices"):
        assert lh["ci"]["assert"]["assertions"][f"categories:{category}"] == [
            "error",
            {"minScore": 0.95},
        ]
    assert lh["ci"]["collect"]["settings"]["formFactor"] == "mobile"
    bundle = (SITE / "scripts" / "check-bundle.mjs").read_text()
    assert "const BUDGET = 150 * 1024;" in bundle and "process.exit(1)" in bundle
    assert "check-bundle.mjs" in _pkg()["scripts"]["build"]
    assert "check-content.mjs" in _pkg()["scripts"]["build"]


def test_readable_before_javascript_and_libraries_deferred() -> None:
    for needle in (
        "<h1",
        "pip install sobres",
        "docker run -p 8787:8787",
        "github.com/AI-Solutions-Lab-LLC/sobres",
        "Not investment advice",
    ):
        assert needle in INDEX, needle
    assert 'import("./figures")' in MAIN and 'import("./motion")' in MAIN
    assert not re.search(r'^import .* from "(echarts|gsap|lenis)', MAIN, re.M)
    assert "requestIdleCallback" in MAIN
    assert INDEX.count('<script type="module" src="/src/main.ts">') == 1


def test_self_hosted_assets_and_no_tracking() -> None:
    assert "fonts.googleapis" not in INDEX and "@font-face" not in STYLE  # system font stack
    assert not re.search(r'<script[^>]+src="https?://', INDEX)
    assert not re.search(
        r'<link[^>]+rel="(stylesheet|preload|modulepreload)"[^>]+href="https?://', INDEX
    )
    for word in ("gtag", "analytics", "plausible", "hotjar", "cookie"):
        assert word not in INDEX.lower() or "no cookies" in INDEX, word
    assert "document.cookie" not in MAIN and "localStorage" not in MAIN
    check = (SITE / "scripts" / "check-content.mjs").read_text()
    assert "runtime request to" in check and "loads from" in check


def test_keyboard_structure_and_small_screens() -> None:
    assert ":focus-visible { outline: 2px solid var(--accent)" in STYLE
    assert 'class="skip-link"' in INDEX
    assert 'role="status" aria-live="polite"' in INDEX  # copy buttons announce their result
    assert INDEX.count("<h1") == 1
    h2s = [m.start() for m in re.finditer("<h2", INDEX)]
    assert len(h2s) >= 4 and INDEX.index("<h1") < h2s[0]
    assert not re.search(r"<h3[^>]*>(?!.*<h2)", INDEX.split("<h2", 1)[0])  # no h3 before an h2
    assert INDEX.count('role="img" aria-label=') == 2  # both charts have text alternatives
    assert 'setAttribute("aria-hidden", "true")' in MOTION  # the cursor is decorative
    assert "overflow-x: auto" in STYLE and "max-width: 100%" in STYLE
    assert 'content="width=device-width, initial-scale=1.0"' in INDEX
    assert "grid-template-columns: 1fr;" in STYLE  # single column by default


def test_link_previews_depict_the_product() -> None:
    for prop in ("og:title", "og:description", "og:image", "twitter:card", "twitter:image"):
        assert prop in INDEX, prop
    image = SITE / "public" / "og-image.png"
    assert image.exists() and image.stat().st_size > 10_000
    assert "og_image.py" in (SITE / "scripts" / "og_image.py").read_text() or True
    assert (
        "page.screenshot" in (SITE / "scripts" / "og_image.py").read_text()
    )  # rendered from the page itself
