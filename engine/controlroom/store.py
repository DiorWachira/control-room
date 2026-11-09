"""Engine state in SQLite, so a restart of the live engine never re-opens a ticket.

Saved after every evaluation, loaded on boot: alert lifecycle states, incidents with their
timelines, deploy-gate states and the memory sink's ticket counter. One row per key, JSON values.
(Probe mode does not need this: it rebuilds deterministically from the probe history.)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .adapters import MemorySink
from .alerts import _State
from .engine import Engine
from .incidents import Incident, TimelineEvent


def _dt(x: str | None) -> datetime | None:
    return datetime.fromisoformat(x) if x else None


def incident_from_dict(d: dict) -> Incident:
    inc = Incident(d["id"], d["service"], d["slo"], d["class"], d["title"], d["priority"], _dt(d["opened_at"]),
                   status=d["status"], firing=set(d["firing"]), context=d.get("context", {}),
                   acked_at=_dt(d["sla"].get("responded_at")), quiet_since=_dt(d.get("quiet_since")),
                   resolved_at=_dt(d.get("resolved_at")))
    inc.timeline = [TimelineEvent(_dt(e["at"]), e["source"], e["text"], e["meta"], e["key"], e["kind"]) for e in d.get("timeline", [])]
    return inc


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._db() as db:
            db.execute("create table if not exists state (key text primary key, value text not null)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, eng: Engine) -> None:
        rows = {
            "alerts": [{"key": list(k), "state": s.state, "since": s.since.isoformat() if s.since else None,
                        "fired_at": s.fired_at.isoformat() if s.fired_at else None} for k, s in eng.tracker.states.items()],
            "incidents": [i.to_dict() for i in eng.incidents.incidents],
            "gate": [[k[0], k[1], v] for k, v in eng._gate.items()],
            "delivered": eng._delivered,
            "sink": {"next_number": eng.sink.next_number} if isinstance(eng.sink, MemorySink) else {},
            "last": eng.last,
        }
        with self._db() as db:  # one transaction: all or nothing
            db.executemany("insert or replace into state (key, value) values (?, ?)",
                           [(k, json.dumps(v)) for k, v in rows.items()])

    def load(self, eng: Engine) -> bool:
        with self._db() as db:
            rows = {k: json.loads(v) for k, v in db.execute("select key, value from state")}
        if not rows:
            return False
        eng.tracker.states = {tuple(a["key"]): _State(a["state"], _dt(a["since"]), _dt(a["fired_at"])) for a in rows.get("alerts", [])}
        eng.incidents.incidents = [incident_from_dict(d) for d in rows.get("incidents", [])]
        eng._gate = {(g[0], g[1]): bool(g[2]) for g in rows.get("gate", [])}
        eng._delivered = int(rows.get("delivered", 0))
        if isinstance(eng.sink, MemorySink) and rows.get("sink"):
            eng.sink.next_number = rows["sink"]["next_number"]
        eng.last = rows.get("last")
        return True
