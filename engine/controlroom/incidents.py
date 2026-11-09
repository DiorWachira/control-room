"""Incidents close the loop: alert -> Resolve ticket -> page -> timeline -> postmortem draft.

One incident per (service, SLO, class). Class "page" covers both page tiers; "ticket" is the
slow 3-day tier. A ticket-tier alert caused by a burn that already paged is suppressed, so
one bad morning never opens two tickets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .adapters import Pager, TicketSink
from .alerts import AlertEvent, key_str

PRIORITY = {"page-1h": "P1", "page-6h": "P2", "ticket-3d": "P3"}
SLA = {"P1": (timedelta(minutes=30), timedelta(hours=4)), "P2": (timedelta(hours=1), timedelta(hours=8)), "P3": (timedelta(days=1), timedelta(days=5))}


def fmt_rate(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.1f}×" if x >= 10 else f"{x:.2f}×"


@dataclass
class TimelineEvent:
    at: datetime
    source: str
    text: str
    meta: str = ""
    key: bool = False
    kind: str = "note"

    def to_dict(self) -> dict:
        return {"at": self.at.isoformat(), "source": self.source, "text": self.text, "meta": self.meta, "key": self.key, "kind": self.kind}


@dataclass
class Incident:
    id: str
    service: str
    slo: str
    klass: str
    title: str
    priority: str
    opened_at: datetime
    status: str = "firing"  # firing | monitoring | resolved
    firing: set[str] = field(default_factory=set)
    timeline: list[TimelineEvent] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    acked_at: datetime | None = None
    quiet_since: datetime | None = None
    resolved_at: datetime | None = None

    def add(self, ev: TimelineEvent) -> None:
        self.timeline.append(ev)
        self.timeline.sort(key=lambda e: e.at)

    @property
    def sla(self) -> dict:
        respond, resolve = SLA[self.priority]
        return {"respond_by": (self.opened_at + respond).isoformat(), "resolve_by": (self.opened_at + resolve).isoformat(),
                "responded_at": self.acked_at.isoformat() if self.acked_at else None}

    def to_dict(self, full: bool = True) -> dict:
        d = {"id": self.id, "service": self.service, "slo": self.slo, "class": self.klass, "title": self.title,
             "priority": self.priority, "status": self.status, "opened_at": self.opened_at.isoformat(),
             "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
             "firing": sorted(self.firing), "sla": self.sla,
             "quiet_since": self.quiet_since.isoformat() if self.quiet_since else None}
        if full:
            d["timeline"] = [e.to_dict() for e in self.timeline]
            d["context"] = self.context
        return d


class IncidentManager:
    def __init__(self, sink: TicketSink, pager: Pager, quiet_period: timedelta = timedelta(minutes=60),
                 ticket_suppress: timedelta = timedelta(days=3)):
        self.sink, self.pager = sink, pager
        self.quiet_period, self.ticket_suppress = quiet_period, ticket_suppress
        self.incidents: list[Incident] = []
        self._pre: dict[tuple[str, str], list[TimelineEvent]] = {}

    # ---- lookup -------------------------------------------------------------
    def open_for(self, service: str, slo: str, klass: str | None = None) -> Incident | None:
        for inc in reversed(self.incidents):
            if inc.service == service and inc.slo == slo and inc.status != "resolved" and (klass is None or inc.klass == klass):
                return inc
        return None

    def get(self, incident_id: str) -> Incident | None:
        return next((i for i in self.incidents if i.id == incident_id), None)

    # ---- inputs -------------------------------------------------------------
    def record(self, service: str, slo: str, ev: TimelineEvent) -> None:
        """An event about an SLO (probe result, human note, gate change). Goes to the open
        incident, or waits in a short buffer so the incident that follows can include it."""
        inc = self.open_for(service, slo)
        if inc:
            inc.add(ev)
            if ev.kind == "ack" and inc.acked_at is None:
                inc.acked_at = ev.at
            return
        buf = self._pre.setdefault((service, slo), [])
        buf.append(ev)
        cutoff = ev.at - timedelta(hours=2)
        self._pre[(service, slo)] = [e for e in buf if e.at >= cutoff]

    def handle(self, ev: AlertEvent, names: tuple[str, str], context: dict) -> None:
        service, slo, tier = ev.key
        svc_name, slo_name = names
        klass = "page" if ev.severity == "page" else "ticket"

        if ev.kind == "pending":
            if klass == "ticket":
                return  # the slow tier's short window is 6 h; its "pending" is noise on a timeline
            self.record(service, slo, TimelineEvent(
                ev.at, "Engine",
                f"Short window {fmt_rate(ev.short_rate)} is over {ev.threshold:g}×, long window only {fmt_rate(ev.long_rate)}. "
                f"{ev.tier_name} is pending; a blip would end here.", f"state pending · {key_str(ev.key)}", kind="engine"))
            return

        if ev.kind == "firing":
            if klass == "ticket" and self._recently_paged(service, slo, ev.at):
                self.record(service, slo, TimelineEvent(ev.at, "Engine", f"{ev.tier_name} tier fired; same burn as the open page, so no second ticket.",
                                                        f"suppressed · {key_str(ev.key)}", kind="engine"))
                return
            inc = self.open_for(service, slo, klass)
            fired = TimelineEvent(ev.at, "Engine",
                                  f"Long window {fmt_rate(ev.long_rate)} and short window {fmt_rate(ev.short_rate)} both over {ev.threshold:g}×: {ev.tier_name} fires.",
                                  f"state firing · key {key_str(ev.key)}", key=True, kind="engine")
            if inc is None:
                self._open(ev, klass, svc_name, slo_name, context, fired)
            else:
                inc.firing.add(tier)
                inc.add(fired)
                if inc.status == "monitoring":
                    inc.status, inc.quiet_since = "firing", None
                    self.sink.set_status(inc.id, "open")
                if PRIORITY[tier] < inc.priority:
                    inc.priority = PRIORITY[tier]
                    self.sink.note(inc.id, f"Escalated to {inc.priority}: {ev.tier_name} fired.")
            return

        if ev.kind == "resolved":
            inc = self.open_for(service, slo, klass)
            if inc is None:
                return
            inc.firing.discard(tier)
            inc.add(TimelineEvent(ev.at, "Engine", f"Short window back to {fmt_rate(ev.short_rate)}, under {ev.threshold:g}×: {ev.tier_name} resets.",
                                  f"state resolved · {key_str(ev.key)}", key=not inc.firing, kind="engine"))
            if not inc.firing and inc.status == "firing":
                inc.status, inc.quiet_since = "monitoring", ev.at
                self.sink.set_status(inc.id, "monitoring")
                self.sink.note(inc.id, f"All {klass} tiers clear at {ev.at:%H:%M} UTC. Monitoring; auto-resolves after {int(self.quiet_period.total_seconds() // 60)} quiet minutes.")

    def tick(self, now: datetime) -> None:
        for inc in self.incidents:
            if inc.status == "monitoring" and inc.quiet_since and now - inc.quiet_since >= self.quiet_period:
                inc.status, inc.resolved_at = "resolved", now
                inc.add(TimelineEvent(now, "Engine", f"Quiet for {int(self.quiet_period.total_seconds() // 60)} minutes: incident resolved.", "state closed", key=True, kind="engine"))
                self.sink.set_status(inc.id, "resolved")
                self.sink.note(inc.id, "Resolved by Control Room. Postmortem draft is ready for review.")

    # ---- internals ----------------------------------------------------------
    def _recently_paged(self, service: str, slo: str, at: datetime) -> bool:
        return any(i.service == service and i.slo == slo and i.klass == "page" and at - i.opened_at <= self.ticket_suppress for i in self.incidents)

    def _open(self, ev: AlertEvent, klass: str, svc_name: str, slo_name: str, context: dict, fired: TimelineEvent) -> Incident:
        service, slo, tier = ev.key
        priority = PRIORITY[tier]
        title = f"{svc_name} “{slo_name}” SLO burning {fmt_rate(ev.long_rate)} budget"
        tid = self.sink.open(title, priority, {"service": service, "slo": slo, "tier": tier, "context": context})
        inc = Incident(tid, service, slo, klass, title, priority, ev.at, firing={tier}, context=context)
        for pre in self._pre.pop((service, slo), []):
            if ev.at - pre.at <= timedelta(hours=1):
                inc.add(pre)
                if pre.kind == "ack":
                    inc.acked_at = pre.at
        inc.add(fired)
        respond, resolve = SLA[priority]
        inc.add(TimelineEvent(ev.at + timedelta(seconds=3), "Resolve",
                              f"{tid} opened, {priority}, with SLO context, burn rates and budget left. SLA clock starts: respond {_human(respond)}, resolve {_human(resolve)}.",
                              "ticket opened", kind="ticket"))
        if klass == "page":
            ok = self.pager.page(f"[{priority}] {title} · {tid}")
            inc.add(TimelineEvent(ev.at + timedelta(seconds=5), "Pager", "Page delivered to Dior." if ok else "Page could not be delivered; check pager config.",
                                  "page sent" if ok else "page failed", kind="page"))
        self.incidents.append(inc)
        return inc


def _human(td: timedelta) -> str:
    mins = int(td.total_seconds() // 60)
    if mins % 1440 == 0:
        return f"{mins // 1440} d"
    if mins % 60 == 0:
        return f"{mins // 60} h"
    return f"{mins} m"
