"""Where error ratios come from.

Every source answers one question: over the window ending at `end`, what fraction of
valid events were bad? The engine never cares whether that comes from Prometheus or
from a recorded scenario, which is what makes the maths testable with synthetic series.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .config import SLO, prom_range


class MetricSource(Protocol):
    def error_ratio(self, service: str, slo: SLO, end: datetime, window: timedelta) -> float | None:
        """Bad / valid over (end - window, end]. None when there were no valid events."""


@dataclass(frozen=True)
class Segment:
    start: datetime
    end: datetime
    ratio: float


@dataclass
class Profile:
    """Piecewise-constant error ratio, assuming steady traffic.

    Integrating segments analytically keeps a 28-day window O(segments), so a replay of
    hundreds of frames stays fast.
    """

    baseline: float
    segments: list[Segment] = field(default_factory=list)

    def add(self, start: datetime, end: datetime, ratio: float) -> "Profile":
        if end <= start:
            raise ValueError("segment end must be after start")
        for s in self.segments:
            if start < s.end and s.start < end:
                raise ValueError(f"segment {start}–{end} overlaps {s.start}–{s.end}")
        self.segments.append(Segment(start, end, ratio))
        self.segments.sort(key=lambda s: s.start)
        return self

    def ratio_at(self, t: datetime) -> float:
        for s in self.segments:
            if s.start <= t < s.end:
                return s.ratio
        return self.baseline

    def mean(self, end: datetime, window: timedelta) -> float:
        start = end - window
        total = window.total_seconds()
        acc = self.baseline * total
        for s in self.segments:
            lo, hi = max(start, s.start), min(end, s.end)
            if hi > lo:
                acc += (s.ratio - self.baseline) * (hi - lo).total_seconds()
        return acc / total


class ProfileSource:
    """In-memory source for tests and the built-in replay."""

    def __init__(self, profiles: dict[tuple[str, str], Profile]):
        self.profiles = profiles

    def error_ratio(self, service: str, slo: SLO, end: datetime, window: timedelta) -> float | None:
        p = self.profiles.get((service, slo.id))
        return None if p is None else p.mean(end, window)


class PrometheusSource:
    """Instant queries against the Prometheus HTTP API (`/api/v1/query`)."""

    def __init__(self, base_url: str, timeout: float = 10.0):
        import httpx  # imported lazily so tests never need a network stack

        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout)

    def query(self, promql: str, at: datetime) -> float | None:
        r = self.client.get(f"{self.base_url}/api/v1/query", params={"query": promql, "time": at.timestamp()})
        r.raise_for_status()
        result = r.json()["data"]["result"]
        if not result:
            return None
        return float(result[0]["value"][1])

    def error_ratio(self, service: str, slo: SLO, end: datetime, window: timedelta) -> float | None:
        rng = prom_range(window)
        bad = self.query(slo.error_query.replace("$window", rng), end)
        valid = self.query(slo.valid_query.replace("$window", rng), end)
        if not valid:
            return None
        return max(0.0, (bad or 0.0) / valid)
