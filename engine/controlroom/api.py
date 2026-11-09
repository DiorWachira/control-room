"""HTTP API and static host for the web app.

Modes
- replay (default): the engine runs the built-in 8 November scenario; "now" is 10:52 EAT.
- live: set PROMETHEUS_URL. The engine evaluates every EVAL_INTERVAL_S seconds against
  Prometheus and files tickets through Resolve when RESOLVE_URL + RESOLVE_TOKEN are set.

Run:  uvicorn controlroom.api:app --reload --port 8000
"""
from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import config as config_mod
from . import postmortem, scenario
from .adapters import from_env
from .engine import Engine
from .status import day_strip, public_state, uptime


class State:
    def __init__(self) -> None:
        self.config = config_mod.load()
        self.mode = "live" if os.environ.get("PROMETHEUS_URL") else "replay"
        self.lock = threading.Lock()
        self.frames: list[dict] = []
        if self.mode == "replay":
            self.engine, self.frames = scenario.run(self.config, scenario.NOW)
            self.profiles = scenario.profiles()
        else:
            from .sources import PrometheusSource

            sink, pager = from_env()
            self.engine = Engine(self.config, PrometheusSource(os.environ["PROMETHEUS_URL"]), sink, pager)
            self.profiles = {}
            self.engine.evaluate(datetime.now(timezone.utc))

    def loop(self, stop: threading.Event) -> None:
        interval = float(os.environ.get("EVAL_INTERVAL_S", "60"))
        while not stop.wait(interval):
            with self.lock:
                try:
                    self.engine.evaluate(datetime.now(timezone.utc))
                except Exception as e:  # keep the loop alive; surface in /api/health
                    self.last_error = repr(e)

    @property
    def snapshot(self) -> dict:
        return self.engine.last or {}


STATE: State | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global STATE
    STATE = State()
    stop = threading.Event()
    if STATE.mode == "live":
        threading.Thread(target=STATE.loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Control Room", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def S() -> State:
    assert STATE is not None
    return STATE


@app.get("/api/health")
def health():
    s = S()
    return {"ok": True, "mode": s.mode, "at": s.snapshot.get("at"), "last_error": getattr(s, "last_error", None)}


@app.get("/api/budgets")
def budgets():
    s = S()
    return {"mode": s.mode, **s.snapshot}


@app.get("/api/replay")
def replay():
    s = S()
    if s.mode != "replay":
        raise HTTPException(404, "Replay is only available in replay mode")
    eng = s.engine
    start = datetime.fromisoformat(s.frames[0]["at"])
    history = {}
    for svc in s.config.services:
        slo = next(o for o in svc.slos if not o.informational)
        p = s.profiles[(svc.id, slo.id)]
        history[svc.id] = [{"at": (start - timedelta(days=d)).isoformat(),
                            "remaining": 1 - p.mean(start - timedelta(days=d), s.config.window) / slo.budget}
                           for d in range(28, -1, -1)]
    return {"start": s.frames[0]["at"], "end": s.frames[-1]["at"], "step_s": 60, "frames": s.frames,
            "history": history, "incidents": [i.to_dict() for i in eng.incidents.incidents]}


@app.get("/api/status")
def status():
    s = S()
    snap = s.snapshot
    now = datetime.fromisoformat(snap["at"])
    cold = scenario.COLD_DAYS if s.mode == "replay" else {}
    notes = {}
    if s.mode == "replay":
        for h in scenario.HISTORY:
            notes[(h["service"], h["start"].astimezone(scenario.EAT).date())] = h["title"]
    services = []
    for svc in snap["services"]:
        services.append({
            "id": svc["id"], "name": svc["name"], "description": svc["description"],
            "state": public_state(s.engine, svc["id"], svc["state"]),
            "uptime_90d": uptime(s.config, s.profiles, svc["id"], now) if s.profiles else None,
            "days": day_strip(s.config, s.profiles, svc["id"], now, cold, notes) if s.profiles else [],
            "objectives": [{"name": o["name"], "objective": o["objective"]} for o in svc["slos"] if not o["informational"]],
        })
    def last_update(i):
        public = [e for e in i.timeline if e.kind != "probe"]
        return public[-1].to_dict() if public else None

    active = [i.to_dict(full=False) | {"last": last_update(i)}
              for i in s.engine.incidents.incidents if i.klass == "page" and i.status != "resolved"]
    history = [{"id": i.id, "service": i.service, "title": i.title, "start": i.opened_at.isoformat(),
                "end": i.resolved_at.isoformat() if i.resolved_at else None, "status": i.status, "detail": ""}
               for i in s.engine.incidents.incidents if i.klass == "page"]
    if s.mode == "replay":
        history += [{"id": h["id"], "service": h["service"], "title": h["title"], "start": h["start"].isoformat(),
                     "end": h["end"].isoformat(), "status": "resolved", "detail": h["detail"]} for h in scenario.HISTORY]
    history.sort(key=lambda h: h["start"], reverse=True)
    return {"mode": s.mode, "at": snap["at"], "services": services, "active": active, "history": history}


@app.get("/api/incidents")
def incidents():
    return [i.to_dict(full=False) for i in S().engine.incidents.incidents]


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str):
    s = S()
    inc = s.engine.incidents.get(incident_id)
    if inc is None:
        raise HTTPException(404, f"No incident {incident_id}")
    svc = s.config.service(inc.service)
    slo = next(o for o in svc.slos if o.id == inc.slo)
    now = datetime.fromisoformat(s.snapshot["at"])
    start = (inc.timeline[0].at if inc.timeline else inc.opened_at) - timedelta(minutes=11)
    trace, t = [], start
    while t <= now:
        r1 = s.engine.source.error_ratio(svc.id, slo, t, timedelta(hours=1))
        r5 = s.engine.source.error_ratio(svc.id, slo, t, timedelta(minutes=5))
        trace.append({"at": t.isoformat(), "h1": None if r1 is None else r1 / slo.budget, "m5": None if r5 is None else r5 / slo.budget})
        t += timedelta(minutes=1)
    row = next(o for x in s.snapshot["services"] if x["id"] == svc.id for o in x["slos"] if o["id"] == slo.id)
    return inc.to_dict() | {
        "service_name": svc.name, "slo_name": slo.name, "objective": slo.objective, "now": s.snapshot["at"],
        "remaining_now": row["remaining"], "gate": row["gate"], "trace": trace,
        "postmortem": postmortem.draft(inc, svc.name, slo.name, row["remaining"]),
    }


@app.get("/budget/{service}")
def deploy_gate(service: str, labels: str = Query("", description="Comma-separated PR labels")):
    """Called by the budget-gate GitHub Action. allow=false fails the deploy job."""
    s = S()
    svc = next((x for x in s.snapshot.get("services", []) if x["id"] == service), None)
    if svc is None:
        raise HTTPException(404, f"Unknown service {service}")
    rows = [{"slo": o["id"], "remaining": o["remaining"], "floor": o["gate"]["floor"], "armed": o["gate"]["armed"]}
            for o in svc["slos"] if not o["informational"]]
    blocked = [r for r in rows if r["armed"]]
    override = "emergency-fix" in {l.strip() for l in labels.split(",") if l.strip()}
    allow = not blocked or override
    reason = ("Budget above every floor" if not blocked else
              ("Override: emergency-fix label" if override else
               "Blocked: " + ", ".join(f"{r['slo']} at {r['remaining']:.1%} < {r['floor']:.0%}" for r in blocked)))
    return {"service": service, "allow": allow, "reason": reason, "slos": rows, "at": s.snapshot["at"]}


_dist = Path(os.environ.get("CONTROLROOM_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
