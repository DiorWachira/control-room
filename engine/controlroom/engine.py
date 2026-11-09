"""The evaluator. Call evaluate(now) once a minute, in time order."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .adapters import MemoryPager, MemorySink, Pager, TicketSink
from .alerts import AlertTracker
from .burnrate import FIRING, budget_remaining, burn_rate, evaluate_tier, time_to_exhaustion
from .config import Config, prom_range
from .incidents import IncidentManager, TimelineEvent
from .sources import MetricSource


@dataclass(frozen=True)
class Annotation:
    """Something the engine did not compute: a probe result, a human note, a config change."""
    at: datetime
    service: str
    slo: str
    source: str
    text: str
    meta: str = ""
    key: bool = False
    kind: str = "note"  # note | ack | probe | change


@dataclass
class Engine:
    config: Config
    source: MetricSource
    sink: TicketSink = field(default_factory=MemorySink)
    pager: Pager = field(default_factory=MemoryPager)
    annotations: list[Annotation] = field(default_factory=list)
    quiet_period: timedelta = timedelta(minutes=60)

    def __post_init__(self) -> None:
        self.tracker = AlertTracker()
        self.incidents = IncidentManager(self.sink, self.pager, self.quiet_period)
        self.annotations = sorted(self.annotations, key=lambda a: a.at)
        self._delivered = 0
        self._gate: dict[tuple[str, str], bool] = {}
        self.last: dict | None = None
        windows = {self.config.window}
        for t in self.config.tiers:
            windows |= {t.long, t.short}
        self.windows = sorted(windows)

    def evaluate(self, now: datetime) -> dict:
        while self._delivered < len(self.annotations) and self.annotations[self._delivered].at <= now:
            a = self.annotations[self._delivered]
            self.incidents.record(a.service, a.slo, TimelineEvent(a.at, a.source, a.text, a.meta, a.key, a.kind))
            self._delivered += 1

        services = []
        for svc in self.config.services:
            slo_rows = []
            for slo in svc.slos:
                ratios = {w: self.source.error_ratio(svc.id, slo, now, w) for w in self.windows}
                rates = {w: burn_rate(r, slo) for w, r in ratios.items()}
                remaining = budget_remaining(ratios[self.config.window], slo)
                readings = [evaluate_tier(t, rates) for t in self.config.tiers]
                h1 = rates.get(timedelta(hours=1))
                context = {"remaining": remaining, "burn": {prom_range(w): r for w, r in rates.items()},
                           "error_ratio": {prom_range(w): r for w, r in ratios.items()}}
                if not slo.informational:
                    for rd in readings:
                        for ev in self.tracker.update(svc.id, slo.id, rd, now):
                            self.incidents.handle(ev, (svc.name, slo.name), context)
                    armed = remaining is not None and remaining < slo.deploy_floor
                    if self._gate.get((svc.id, slo.id), False) != armed:
                        if (svc.id, slo.id) in self._gate or armed:
                            self.incidents.record(svc.id, slo.id, TimelineEvent(
                                now, "Gate",
                                f"Deploy gate {'armed' if armed else 'open'}: budget {remaining:.1%} is {'under' if armed else 'back over'} the {slo.deploy_floor:.0%} floor."
                                + (" Deploys need the emergency-fix label." if armed else ""),
                                f"check budget-gate · {'failing' if armed else 'passing'}", kind="gate"))
                        self._gate[(svc.id, slo.id)] = armed
                tte = time_to_exhaustion(remaining, h1, self.config.window)
                slo_rows.append({
                    "id": slo.id, "name": slo.name, "objective": slo.objective, "informational": slo.informational,
                    "remaining": remaining, "error_ratio": context["error_ratio"], "burn": context["burn"],
                    "tte_seconds": tte.total_seconds() if tte is not None else None,
                    "drain_per_min": (h1 or 0.0) / (self.config.window.total_seconds() / 60),
                    "gate": {"floor": slo.deploy_floor, "armed": self._gate.get((svc.id, slo.id), False)},
                    "tiers": [{"id": r.tier.id, "name": r.tier.name, "severity": r.tier.severity, "threshold": r.tier.threshold,
                               "long": prom_range(r.tier.long), "short": prom_range(r.tier.short),
                               "long_rate": r.long_rate, "short_rate": r.short_rate,
                               "state": r.state if not slo.informational else "inactive"} for r in readings],
                })
            services.append({"id": svc.id, "name": svc.name, "callsign": svc.callsign, "description": svc.description,
                             "state": _service_state(slo_rows), "slos": slo_rows})

        self.incidents.tick(now)
        self.last = {"at": now.isoformat(), "services": services,
                     "incidents": [i.to_dict(full=False) for i in self.incidents.incidents]}
        return self.last

    def run(self, start: datetime, end: datetime, step: timedelta = timedelta(minutes=1)) -> list[dict]:
        frames, t = [], start
        while t <= end:
            frames.append(self.evaluate(t))
            t += step
        return frames


def _service_state(slos: list[dict]) -> str:
    live = [s for s in slos if not s["informational"]]
    sev = {t["severity"] for s in live for t in s["tiers"] if t["state"] == FIRING}
    if any(s["remaining"] is not None and s["remaining"] <= 0 for s in live):
        return "breach"
    if "page" in sev:
        return "page"
    if "ticket" in sev:
        return "ticket"
    return "nominal"
