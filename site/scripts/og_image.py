"""Render the link-preview image from the built page itself, so it depicts the actual product.

    npm run build && python site/scripts/og_image.py

Serves ``site/dist`` locally, opens the hero at 1200x630 in headless Chromium,
waits for the frontier to finish drawing, and writes ``site/public/og-image.png``.
"""

from __future__ import annotations

import glob
import http.server
import os
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[1]
DIST = SITE / "dist"
OUT = SITE / "public" / "og-image.png"


def main() -> None:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    # dist/ is served at /dist/ while the page expects /sobres/: rewrite the requests.
    with sync_playwright() as p:
        # PLAYWRIGHT_CHROMIUM points at a Chromium binary when the bundled one is not installed.
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM") or next(
            iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))), None
        )
        browser = p.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        page.route(
            "**/sobres/**",
            lambda route: route.continue_(url=route.request.url.replace("/sobres/", "/dist/")),
        )
        page.goto(f"http://127.0.0.1:{port}/sobres/index.html", wait_until="load")
        page.wait_for_timeout(3500)  # let the frontier draw and the max-Sharpe point land
        page.screenshot(path=str(OUT), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        browser.close()
    server.shutdown()
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
