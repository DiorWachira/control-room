"""Freeze the API into static JSON for the public site (GitHub Pages).

    python -m controlroom.export OUT                          # replay only (CI, e2e)
    python -m controlroom.export OUT --probe-data DIR         # live board from the probe log
    python -m controlroom.export OUT --probe-data DIR --probe --notify   # what the cron runs

With --probe-data the status board, incidents and deploy gate come from the probe history
(probes.yaml); the budget wall and the RSV-10xx pages always come from the 8 November replay.
--probe runs one probe round first; --notify sends due Telegram pages and reads acks back.
Resolved live incidents get an LLM postmortem rewrite when ANTHROPIC_API_KEY is set (cached in
DIR/postmortems.json, so each incident is rewritten once).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _write(out: Path, rel: str, data) -> Path:
    f = out / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return f


def refine_postmortems(state, data_dir: Path) -> int:
    from . import postmortem

    cache_file = data_dir / "postmortems.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else {}
    n = 0
    for inc in state.engine.incidents.incidents:
        if inc.status != "resolved" or inc.id in cache:
            continue
        svc = state.cfg.service(inc.service)
        slo = next(o for o in svc.slos if o.id == inc.slo)
        refined = postmortem.refine(postmortem.draft(inc, svc.name, slo.name, None), inc)
        if refined:
            cache[inc.id] = refined
            n += 1
    if n:
        cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return n


def export(out: Path, probe_data: Path | None = None, probe: bool = False, notify: bool = False) -> list[Path]:
    if probe_data is not None:
        probe_data = probe_data.resolve()
        os.environ["CONTROLROOM_PROBE_DATA"] = str(probe_data)
        if probe:
            from . import config as config_mod
            from .probe_runner import run_round

            run_round(config_mod.load(config_mod.probes_path()), probe_data / "runs")

    from fastapi.testclient import TestClient

    from . import api

    written: list[Path] = []
    with TestClient(api.app) as c:
        state = api.S()
        if probe_data is not None:
            if notify:
                from . import notify as notify_mod

                report = notify_mod.run(state.engine, probe_data)
                print("notify:", report)
                if report["acks"]:
                    state.rebuild()  # acks land on the timeline in this same build
            if refine_postmortems(state, probe_data):
                state.load_postmortems()

        def save(path: str, rel: str) -> None:
            r = c.get(path)
            r.raise_for_status()
            written.append(_write(out, rel, r.json()))

        for name in ("health", "status", "budgets", "replay", "incidents"):
            save(f"/api/{name}", f"{name}.json")
        ids = {i["id"] for i in c.get("/api/incidents").json()} | {i["id"] for i in c.get("/api/replay").json()["incidents"]}
        for iid in sorted(ids):
            save(f"/api/incidents/{iid}", f"incidents/{iid}.json")
        # The deploy gate as static files: the budget-gate action applies emergency-fix itself.
        for svc in c.get("/api/budgets").json()["services"]:
            written.append(_write(out.parent / "budget", f"{svc['id']}.json", api.gate_answer(state.snapshot, svc["id"])))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default="static-api", type=Path)
    ap.add_argument("--probe-data", type=Path)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args()
    files = export(a.out, a.probe_data, a.probe, a.notify)
    print(f"wrote {len(files)} files under {a.out.parent}")
