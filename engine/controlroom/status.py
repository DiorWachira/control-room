"""Public status: per-service lamp, 90-day day strip and incident history."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from .config import Config
from .engine import Engine
from .sources import Profile

EAT = timezone(timedelta(hours=3))


def public_state(engine: Engine, service: str, svc_state: str) -> str:
    if svc_state == "breach":
        return "outage"
    for inc in engine.incidents.incidents:
        if inc.service == service and inc.klass == "page" and inc.status != "resolved":
            return "degraded"
    return "nominal"


def day_strip(config: Config, profiles: dict[tuple[str, str], Profile], service: str, now: datetime,
              cold_days: dict[tuple[str, date], int], notes: dict[tuple[str, date], str], days: int = 90) -> list[dict]:
    svc = config.service(service)
    today = now.astimezone(EAT).date()
    out = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        start = datetime.combine(d, time(0), EAT)
        end = min(start + timedelta(days=1), now)
        status, worst = "nominal", 0.0
        for slo in svc.slos:
            p = profiles.get((service, slo.id))
            if p is None or slo.informational:
                continue
            daily = p.mean(end, end - start) / slo.budget
            worst = max(worst, daily)
            for seg in p.segments:
                lo, hi = max(seg.start, start), min(seg.end, end)
                if hi - lo >= timedelta(minutes=5) and seg.ratio / slo.budget >= 14.4:
                    status = "outage"
            if status != "outage" and daily >= 1.0:
                status = "burning"
        cold = cold_days.get((service, d), 0)
        if status == "nominal" and cold:
            status = "cold"
        note = notes.get((service, d)) or {
            "outage": "Page-level burn", "burning": f"Budget burned {worst:.1f}× for the day",
            "cold": f"{cold} cold starts, none counted", "nominal": "Nominal, no budget burned"}[status]
        out.append({"date": d.isoformat(), "status": status, "burn": round(worst, 3), "note": note})
    return out


def uptime(config: Config, profiles: dict[tuple[str, str], Profile], service: str, now: datetime, days: int = 90) -> float | None:
    svc = config.service(service)
    # The public uptime figure uses the strictest objective (availability), not a latency SLO.
    primary = max((s for s in svc.slos if not s.informational), key=lambda s: s.objective, default=None)
    p = profiles.get((service, primary.id)) if primary else None
    return None if p is None else 1.0 - p.mean(now, timedelta(days=days))
