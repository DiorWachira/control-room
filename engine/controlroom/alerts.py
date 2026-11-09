"""Alert lifecycle: inactive -> pending -> firing -> resolved, deduplicated per key.

The key is (service, slo, tier). A transition is emitted once; staying in a state
emits nothing, so a firing alert can never open a second ticket.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .burnrate import FIRING, PENDING, TierReading

AlertKey = tuple[str, str, str]


def key_str(key: AlertKey) -> str:
    return "/".join(key)


@dataclass(frozen=True)
class AlertEvent:
    kind: str  # "pending" | "firing" | "resolved"
    key: AlertKey
    at: datetime
    severity: str
    tier_name: str
    long_rate: float | None
    short_rate: float | None
    threshold: float


@dataclass
class _State:
    state: str = "inactive"
    since: datetime | None = None
    fired_at: datetime | None = None


@dataclass
class AlertTracker:
    states: dict[AlertKey, _State] = field(default_factory=dict)

    def firing(self) -> list[AlertKey]:
        return [k for k, s in self.states.items() if s.state == FIRING]

    def update(self, service: str, slo: str, reading: TierReading, now: datetime) -> list[AlertEvent]:
        key = (service, slo, reading.tier.id)
        st = self.states.setdefault(key, _State())
        new = reading.state
        events: list[AlertEvent] = []

        def ev(kind: str) -> AlertEvent:
            t = reading.tier
            return AlertEvent(kind, key, now, t.severity, t.name, reading.long_rate, reading.short_rate, t.threshold)

        if new == FIRING and st.state != FIRING:
            st.state, st.since, st.fired_at = FIRING, now, now
            events.append(ev("firing"))
        elif new != FIRING and st.state == FIRING:
            # The short window dropping under the threshold resets the alert quickly.
            st.state, st.since, st.fired_at = "inactive", now, None
            events.append(ev("resolved"))
        elif new == PENDING and st.state == "inactive":
            st.state, st.since = PENDING, now
            events.append(ev("pending"))
        elif new != PENDING and st.state == PENDING:
            st.state, st.since = "inactive", now
        return events
