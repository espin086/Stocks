#!/usr/bin/env python3
"""Write the API's OpenAPI document to ``frontend/openapi.json``.

The frontend's TypeScript client is generated from this file; CI regenerates
both and fails on a diff, so an API change that would break the UI breaks the
build rather than the user.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"


def build_document() -> dict[str, object]:
    from sobres.api import create_app

    tmp = Path(tempfile.mkdtemp())
    env = {
        "SOBRES_CONFIG_FILE": str(tmp / "config.toml"),
        "SOBRES_DB_URL": f"sqlite:///{(tmp / 'schema.db').as_posix()}",
    }
    app = create_app(env, start_worker=False)
    doc = app.openapi()
    # The version changes every release; the client does not.
    doc["info"]["version"] = "generated"
    return dict(doc)


def main(argv: list[str]) -> int:
    doc = build_document()
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if "--check" in argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print(f"{OUT} is stale; run: python scripts/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
