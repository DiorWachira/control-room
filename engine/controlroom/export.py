"""Freeze the replay API into static JSON for the public demo (GitHub Pages).

The 8 November replay is deterministic, so every answer the web app needs can be computed
once at build time by the real engine. The web build with VITE_STATIC=1 reads these files
instead of calling the API.

    python -m controlroom.export ../web/public/api
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def export(out: Path) -> list[Path]:
    from fastapi.testclient import TestClient

    from .api import app

    written: list[Path] = []
    with TestClient(app) as c:
        def save(path: str, rel: str) -> None:
            r = c.get(path)
            r.raise_for_status()
            f = out / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(r.json(), separators=(",", ":")), encoding="utf-8")
            written.append(f)

        for name in ("health", "status", "budgets", "replay", "incidents"):
            save(f"/api/{name}", f"{name}.json")
        for inc in c.get("/api/incidents").json():
            save(f"/api/incidents/{inc['id']}", f"incidents/{inc['id']}.json")
    return written


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "static-api")
    files = export(out)
    print(f"wrote {len(files)} files to {out}")
