"""The built-in replay: Sunday 8 November 2026, RepoLens's Examiner outage.

Everything the UI shows in demo mode is computed by the real engine from these error-ratio
profiles. Only what the engine cannot know is written down here: human notes, probe
details, and incidents closed before the replay starts (they live in Resolve).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .adapters import MemoryPager, MemorySink
from .config import Config
from .engine import Annotation, Engine
from .sources import Profile, ProfileSource

UTC = timezone.utc
EAT = timezone(timedelta(hours=3), "EAT")


def eat(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=EAT).astimezone(UTC)


REPLAY_START = eat(2026, 11, 8, 9, 30)
NOW = eat(2026, 11, 8, 10, 52)  # the moment demo mode presents as "now"
WARMUP_START = eat(2026, 11, 6, 9, 0)


def profiles() -> dict[tuple[str, str], Profile]:
    P = {}
    P[("resolve", "api-availability")] = Profile(0.00013).add(eat(2026, 10, 21, 13, 40), eat(2026, 10, 21, 14, 12), 0.0555)
    P[("resolve", "api-latency")] = (Profile(0.0012)
                                     .add(eat(2026, 9, 19, 10, 0), eat(2026, 9, 19, 10, 6), 0.6)
                                     .add(eat(2026, 10, 21, 13, 40), eat(2026, 10, 21, 14, 12), 0.35))
    P[("repolens", "scan-success")] = (Profile(0.0025)
                                       .add(eat(2026, 9, 1, 14, 0), eat(2026, 9, 1, 16, 0), 0.03)
                                       .add(eat(2026, 9, 30, 11, 5), eat(2026, 9, 30, 11, 46), 1.0)
                                       .add(eat(2026, 10, 27, 6, 2), eat(2026, 10, 27, 6, 20), 0.2375)
                                       .add(eat(2026, 11, 8, 9, 41), eat(2026, 11, 8, 10, 11), 0.40)
                                       .add(eat(2026, 11, 8, 10, 11), eat(2026, 11, 8, 10, 24), 0.02))
    P[("repolens", "examiner-fallback")] = (Profile(0.07)
                                            .add(eat(2026, 11, 8, 9, 41), eat(2026, 11, 8, 10, 11), 0.64)
                                            .add(eat(2026, 11, 8, 10, 11), eat(2026, 11, 8, 10, 24), 0.03))
    P[("jobbridge", "match-latency")] = (Profile(0.02)
                                         .add(eat(2026, 10, 9, 18, 5), eat(2026, 10, 9, 18, 47), 0.7)
                                         .add(eat(2026, 11, 5, 9, 30), eat(2026, 11, 30, 0, 0), 0.065))
    P[("jobbridge", "auth-availability")] = Profile(0.0001).add(eat(2026, 11, 2, 21, 14), eat(2026, 11, 2, 21, 28), 0.25)
    return P


ANNOTATIONS = [
    Annotation(eat(2026, 11, 8, 9, 41, 20), "repolens", "scan-success", "Probe",
               "Fixture scan of tiny-repo failed: the Examiner got a 503 from the primary model.", "trace 4bf92f…e21a", True, "probe"),
    Annotation(eat(2026, 11, 8, 9, 58, 12), "repolens", "scan-success", "Dior", "Acknowledged from Telegram.", "ack", False, "ack"),
    Annotation(eat(2026, 11, 8, 10, 4, 40), "repolens", "scan-success", "Dior",
               "Provider status shows elevated 503s on the primary model. Our chain waits 20 s on it before falling back.", "internal note"),
    Annotation(eat(2026, 11, 8, 10, 11), "repolens", "scan-success", "Dior",
               "Set EXAMINER_MODEL_ORDER=flash,pro. Env flag only, no deploy.", "config change", True, "change"),
    Annotation(eat(2026, 11, 8, 10, 48, 30), "repolens", "scan-success", "Probe",
               "Cold start: woke in 34 s, inside the 50 s window. Logged as cold_start, not counted.", "probe cold_start", False, "probe"),
]

# Days on which the only slow responses were cold starts (excluded from the SLI).
COLD_DAYS = {("repolens", date(2026, 10, 14)): 7, ("repolens", date(2026, 11, 3)): 9, ("repolens", date(2026, 11, 6)): 6}

# Incidents closed before the replay window. In live mode these come from Resolve.
HISTORY = [
    {"id": "RSV-1031", "service": "jobbridge", "start": eat(2026, 11, 2, 21, 14), "end": eat(2026, 11, 2, 21, 28),
     "title": "Sign-in unavailable for 14 minutes",
     "detail": "The Neo4j container hit its memory limit and took auth with it. Auth now degrades without the graph."},
    {"id": "RSV-1024", "service": "repolens", "start": eat(2026, 10, 27, 6, 2), "end": eat(2026, 10, 27, 6, 20),
     "title": "Slow first scans after deploy", "detail": "Two wakes took 61 s and 58 s, past the 50 s window, so they were counted."},
    {"id": "RSV-1017", "service": "resolve", "start": eat(2026, 10, 21, 13, 40), "end": eat(2026, 10, 21, 14, 12),
     "title": "Ticket list slow and failing (p95 1.9 s)", "detail": "Demo traffic exhausted the Neon connection pool; moved to the pooled endpoint."},
    {"id": "RSV-1009", "service": "jobbridge", "start": eat(2026, 10, 9, 18, 5), "end": eat(2026, 10, 9, 18, 47),
     "title": "Match reasons slow (p95 4.1 s)", "detail": "The explanation model was cold after a VM reboot; added a warm-up call to boot."},
]


def build_engine(config: Config) -> Engine:
    return Engine(config, ProfileSource(profiles()), MemorySink(reserved=[1039, 1042], next_number=1043), MemoryPager(), list(ANNOTATIONS))


def run(config: Config, until: datetime = NOW) -> tuple[Engine, list[dict]]:
    """Warm the engine up coarsely (so slow tiers already open before the replay start), then
    evaluate minute by minute. Returns the engine and the per-minute frames from REPLAY_START."""
    eng = build_engine(config)
    t = WARMUP_START
    while t < REPLAY_START:
        eng.evaluate(t)
        t += timedelta(minutes=15)
    frames = eng.run(REPLAY_START, until, timedelta(minutes=1))
    return eng, frames
