"""HTTP API and static host for the web app.

Modes (the status board, /api/budgets, /api/incidents and the deploy gate follow the mode;
the budget wall's /api/replay and the RSV-10xx replay incidents are always available):
- replay (default): the built-in 8 November scenario; "now" is 10:52 EAT.
- probes: CONTROLROOM_PROBE_DATA=<dir with runs/*.jsonl>. The engine rebuilds from the probe
  history (probes.yaml) every EVAL_INTERVAL_S seconds. This is what the public board shows.
- live: PROMETHEUS_URL set. Evaluates every EVAL_INTERVAL_S against Prometheus, files tickets in
  Resolve when RESOLVE_URL + RESOLVE_TOKEN are set, and persists state to CONTROLROOM_STATE_DB.

Run:  uvicorn controlroom.api:app --reload --port 8000
"""
from __future__ import annotations

import os
import threading
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import config as config_mod
from . import live, postmortem, probelog, scenario
from .adapters import from_env
from .engine import Engine
from .status import day_strip, public_state, uptime

STALE_AFTER = timedelta(minutes=45)  # no probe for this long: the board says "no signal"


class State:
    def __init__(self) -> None:
        self.config = config_mod.load()
        self.lock = threading.Lock()
        self.last_error: str | None = None
        # The replay is always computed: it powers the budget wall and the RSV-10xx pages.
        replay_cfg = self.config.only({svc for svc, _ in scenario.profiles()})
        self.replay_engine, self.frames = scenario.run(replay_cfg, scenario.NOW)
        self.profiles = scenario.profiles()
        self.probe_dir = os.environ.get("CONTROLROOM_PROBE_DATA")
        self.src: probelog.ProbeLogSource | None = None
        self.postmortems: dict = {}
        if os.environ.get("PROMETHEUS_URL"):
            from .sources import PrometheusSource
            from .store import Store

            self.mode = "live"
            sink, pager = from_env()
            self.engine = Engine(self.config, PrometheusSource(os.environ["PROMETHEUS_URL"]), sink, pager)
            self.store = Store(os.environ.get("CONTROLROOM_STATE_DB", "controlroom-state.db"))
            self.store.load(self.engine)
            self.tick()
        elif self.probe_dir:
            self.mode = "probes"
            self.watch = config_mod.load(config_mod.probes_path())
            self.rebuild()
            self.load_postmortems()
        else:
            self.mode = "replay"
            self.engine = self.replay_engine

    @property
    def cfg(self):
        return self.watch if self.mode == "probes" else self.config

    def load_postmortems(self) -> None:
        """LLM rewrites cached by export.refine_postmortems (probe mode only)."""
        import json

        f = Path(self.probe_dir) / "postmortems.json" if self.probe_dir else None
        self.postmortems = json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}

    def rebuild(self) -> None:
        self.engine, self.src = live.build(self.watch, self.probe_dir)

    def tick(self) -> None:
        self.engine.evaluate(datetime.now(timezone.utc))
        self.store.save(self.engine)
        hc = os.environ.get("HEALTHCHECK_URL")  # dead-man switch: healthchecks.io pages if pings stop
        if hc:
            try:
                urllib.request.urlopen(hc, timeout=5).close()
            except Exception as e:  # noqa: BLE001
                self.last_error = f"healthcheck ping failed: {e!r}"

    def loop(self, stop: threading.Event) -> None:
        interval = float(os.environ.get("EVAL_INTERVAL_S", "60"))
        while not stop.wait(interval):
            with self.lock:
                try:
                    self.rebuild() if self.mode == "probes" else self.tick()
                    self.last_error = None
                except Exception as e:  # keep the loop alive; surface in /api/health
                    self.last_error = repr(e)

    @property
    def snapshot(self) -> dict:
        return self.engine.last or {}

    def find(self, incident_id: str):
        for eng, cfg in ((self.engine, self.cfg), (self.replay_engine, self.config)):
            inc = eng.incidents.get(incident_id)
            if inc is not None:
                return eng, cfg, inc
        return None, None, None


STATE: State | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global STATE
    STATE = State()
    stop = threading.Event()
    if STATE.mode in ("live", "probes"):
        threading.Thread(target=STATE.loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Control Room", version="0.2.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def S() -> State:
    assert STATE is not None
    return STATE


def _last_probe(s: State, service: str) -> datetime | None:
    return s.src.last_seen(service) if s.src else None


@app.get("/api/health")
def health():
    s = S()
    at = s.snapshot.get("at")
    out = {"ok": True, "mode": s.mode, "at": at, "last_error": s.last_error}
    if s.mode == "probes":
        last = max((r.at for r in s.src.records), default=None) if s.src else None
        out["last_probe"] = last.isoformat() if last else None
        out["stale"] = last is None or datetime.fromisoformat(at) - last > STALE_AFTER
    return out


@app.get("/api/budgets")
def budgets():
    s = S()
    return {"mode": s.mode, **s.snapshot}


@app.get("/api/replay")
def replay():
    s = S()
    eng = s.replay_engine
    start = datetime.fromisoformat(s.frames[0]["at"])
    history = {}
    for svc in eng.config.services:
        slo = next(o for o in svc.slos if not o.informational)
        p = s.profiles[(svc.id, slo.id)]
        history[svc.id] = [{"at": (start - timedelta(days=d)).isoformat(),
                            "remaining": 1 - p.mean(start - timedelta(days=d), s.config.window) / slo.budget}
                           for d in range(28, -1, -1)]
    return {"start": s.frames[0]["at"], "end": s.frames[-1]["at"], "step_s": 60, "frames": s.frames,
            "history": history, "incidents": [i.to_dict() for i in eng.incidents.incidents]}


def _outage_days(eng: Engine, service: str, now: datetime) -> set:
    days = set()
    for i in eng.incidents.incidents:
        if i.service == service and i.klass == "page":
            d, end = i.opened_at.astimezone(probelog.EAT).date(), (i.resolved_at or now).astimezone(probelog.EAT).date()
            while d <= end:
                days.add(d)
                d += timedelta(days=1)
    return days


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
        row = {"id": svc["id"], "name": svc["name"], "description": svc["description"],
               "state": public_state(s.engine, svc["id"], svc["state"]),
               "objectives": [{"name": o["name"], "objective": o["objective"]} for o in svc["slos"] if not o["informational"]]}
        if s.mode == "replay":
            row |= {"uptime_90d": uptime(s.config, s.profiles, svc["id"], now),
                    "days": day_strip(s.config, s.profiles, svc["id"], now, cold, notes)}
        elif s.mode == "probes":
            last = _last_probe(s, svc["id"])
            if last is None or now - last > STALE_AFTER:
                row["state"] = "nosignal"
            probe = s.watch.service(svc["id"]).probe or {}
            row |= {"uptime_90d": probelog.uptime(s.src, svc["id"], now),
                    "days": probelog.day_strip(s.watch, s.src, svc["id"], now, _outage_days(s.engine, svc["id"], now)),
                    "last_probe": last.isoformat() if last else None, "url": probe.get("url")}
        else:
            row |= {"uptime_90d": None, "days": []}
        services.append(row)

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
    out = {"mode": s.mode, "at": snap["at"], "services": services, "active": active, "history": history}
    if s.mode == "probes":
        first = s.src.first_seen() if s.src else None
        out["since"] = first.isoformat() if first else None
        out["interval"] = s.watch.probe.get("interval", "15m")
    return out


@app.get("/api/incidents")
def incidents():
    return [i.to_dict(full=False) for i in S().engine.incidents.incidents]


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str):
    s = S()
    eng, cfg, inc = s.find(incident_id)
    if inc is None:
        raise HTTPException(404, f"No incident {incident_id}")
    svc = cfg.service(inc.service)
    slo = next(o for o in svc.slos if o.id == inc.slo)
    now = datetime.fromisoformat(eng.last["at"])
    start = (inc.timeline[0].at if inc.timeline else inc.opened_at) - timedelta(minutes=11)
    end = min(now, inc.resolved_at + timedelta(minutes=30)) if inc.resolved_at else now
    step = max(timedelta(minutes=1), (end - start) / 360)
    trace, t = [], start
    while t <= end:
        r1 = eng.source.error_ratio(svc.id, slo, t, timedelta(hours=1))
        r5 = eng.source.error_ratio(svc.id, slo, t, timedelta(minutes=5))
        trace.append({"at": t.isoformat(), "h1": None if r1 is None else r1 / slo.budget, "m5": None if r5 is None else r5 / slo.budget})
        t += step
    row = next(o for x in eng.last["services"] if x["id"] == svc.id for o in x["slos"] if o["id"] == slo.id)
    return inc.to_dict() | {
        "service_name": svc.name, "slo_name": slo.name, "objective": slo.objective, "now": eng.last["at"],
        "remaining_now": row["remaining"], "gate": row["gate"], "trace": trace,
        "replay": eng is s.replay_engine and s.mode != "replay",
        "postmortem": postmortem.draft(inc, svc.name, slo.name, row["remaining"])
                      | ({"refined": s.postmortems[inc.id]} if inc.id in s.postmortems else {}),
    }


def gate_answer(snapshot: dict, service: str, labels: str = "") -> dict | None:
    svc = next((x for x in snapshot.get("services", []) if x["id"] == service), None)
    if svc is None:
        return None
    rows = [{"slo": o["id"], "remaining": o["remaining"], "floor": o["gate"]["floor"], "armed": o["gate"]["armed"]}
            for o in svc["slos"] if not o["informational"]]
    blocked = [r for r in rows if r["armed"]]
    override = "emergency-fix" in {l.strip() for l in labels.split(",") if l.strip()}
    allow = not blocked or override
    reason = ("Budget above every floor" if not blocked else
              ("Override: emergency-fix label" if override else
               "Blocked: " + ", ".join(f"{r['slo']} at {r['remaining']:.1%} < {r['floor']:.0%}" for r in blocked)))
    return {"service": service, "allow": allow, "reason": reason, "slos": rows, "at": snapshot["at"]}


@app.get("/budget/{service}")
def deploy_gate(service: str, labels: str = Query("", description="Comma-separated PR labels")):
    """Called by the budget-gate GitHub Action. allow=false fails the deploy job."""
    ans = gate_answer(S().snapshot, service, labels)
    if ans is None:
        raise HTTPException(404, f"Unknown service {service}")
    return ans


_dist = Path(os.environ.get("CONTROLROOM_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
