"""Probe history as a metric source.

The probe runner (GitHub Actions, every 15 minutes) appends one JSON line per request to
`runs/YYYY-MM-DD.jsonl` (UTC day) on the probe-data branch. This module reads that history and
answers the engine's only question, error ratio over a window, the way Prometheus would answer
`increase(probe_runs_total[...])`: bad attempts / valid attempts, cold starts excluded.

Samples are sparse (one run per 15 min, and GitHub's cron can drift), so any window shorter
than `lookback` reads the last `lookback` instead. Without that, the 5-minute window would be
empty most of the time and no page tier could ever fire.

Warm-up: a window answers only once the service's history covers min(window, 1 day). Otherwise
in the first hours of probing one failed run would look like a 3-day burn and open a ticket.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .config import SLO, Config

UTC = timezone.utc
EAT = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class ProbeRecord:
    at: datetime
    service: str
    attempt: int
    outcome: str  # success | cold_start | error
    latency_s: float
    detail: str = ""

    def to_json(self) -> str:
        d = asdict(self)
        d["at"] = self.at.astimezone(UTC).isoformat(timespec="seconds")
        d["latency_s"] = round(self.latency_s, 3)
        return json.dumps(d, separators=(",", ":"))

    @staticmethod
    def from_json(line: str) -> "ProbeRecord":
        d = json.loads(line)
        return ProbeRecord(datetime.fromisoformat(d["at"]), d["service"], int(d.get("attempt", 1)), d["outcome"],
                           float(d.get("latency_s", 0)), d.get("detail", ""))


def read_log(root: str | Path) -> list[ProbeRecord]:
    root = Path(root)
    out: list[ProbeRecord] = []
    for f in sorted(root.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(ProbeRecord.from_json(line))
                except (ValueError, KeyError):
                    continue  # a torn line never takes the board down
    out.sort(key=lambda r: r.at)
    return out


def append(root: str | Path, records: list[ProbeRecord]) -> None:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[ProbeRecord]] = {}
    for r in records:
        by_day.setdefault(r.at.astimezone(UTC).date().isoformat(), []).append(r)
    for day, rs in by_day.items():
        with (root / f"{day}.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
            for r in rs:
                fh.write(r.to_json() + "\n")


def prune(root: str | Path, today: date, keep_days: int = 100) -> list[Path]:
    """Delete day files older than keep_days (the board shows 91 days, budgets use 28)."""
    gone = []
    for f in Path(root).glob("*.jsonl"):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if (today - d).days > keep_days:
            f.unlink()
            gone.append(f)
    return gone


class ProbeLogSource:
    """MetricSource over probe records. O(log n) per query via prefix sums."""

    def __init__(self, records: list[ProbeRecord], lookback: timedelta = timedelta(minutes=30),
                 warmup_cap: timedelta = timedelta(days=1)):
        self.lookback, self.warmup_cap = lookback, warmup_cap
        self.records = records
        self._t: dict[str, list[float]] = {}
        self._err: dict[str, list[int]] = {}
        self._valid: dict[str, list[int]] = {}
        for r in records:
            if r.outcome == "cold_start":
                continue
            t, e, v = self._t.setdefault(r.service, []), self._err.setdefault(r.service, [0]), self._valid.setdefault(r.service, [0])
            t.append(r.at.timestamp())
            e.append(e[-1] + (r.outcome == "error"))
            v.append(v[-1] + 1)

    def counts(self, service: str, start: datetime, end: datetime) -> tuple[int, int]:
        t = self._t.get(service)
        if not t:
            return 0, 0
        i, j = bisect_right(t, start.timestamp()), bisect_right(t, end.timestamp())
        return self._err[service][j] - self._err[service][i], self._valid[service][j] - self._valid[service][i]

    def error_ratio(self, service: str, slo: SLO, end: datetime, window: timedelta) -> float | None:
        w = max(window, self.lookback)
        t = self._t.get(service)
        if not t or end.timestamp() - t[0] < min(w, self.warmup_cap).total_seconds() * 0.98:
            return None  # still warming up
        bad, valid = self.counts(service, end - w, end)
        return None if valid == 0 else bad / valid

    def first_seen(self) -> datetime | None:
        return self.records[0].at if self.records else None

    def last_seen(self, service: str) -> datetime | None:
        for r in reversed(self.records):
            if r.service == service:
                return r.at
        return None


def day_strip(config: Config, src: ProbeLogSource, service: str, now: datetime, outage_days: set[date],
              days: int = 90) -> list[dict]:
    """91 EAT days. Days before probing began are `nodata`, never painted as nominal."""
    svc = config.service(service)
    slo = next(o for o in svc.slos if not o.informational)
    cold_by_day: dict[date, int] = {}
    for r in src.records:
        if r.service == service and r.outcome == "cold_start":
            d = r.at.astimezone(EAT).date()
            cold_by_day[d] = cold_by_day.get(d, 0) + 1
    today = now.astimezone(EAT).date()
    out = []
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        start = datetime.combine(d, time(0), EAT)
        end = min(start + timedelta(days=1), now)
        bad, valid = src.counts(service, start, end)
        cold = cold_by_day.get(d, 0)
        if valid == 0 and not cold:
            out.append({"date": d.isoformat(), "status": "nodata", "burn": 0.0, "note": "No probes this day"})
            continue
        burn = (bad / valid / slo.budget) if valid else 0.0
        status = "outage" if d in outage_days else "burning" if burn >= 1.0 else "cold" if cold else "nominal"
        note = {"outage": f"Page-level burn · {bad} of {valid} probes failed",
                "burning": f"Budget burned {burn:.1f}× · {bad} of {valid} probes failed",
                "cold": f"{cold} cold starts, none counted · {valid} probes ok",
                "nominal": f"Nominal · {valid} probes, {bad} failed"}[status]
        out.append({"date": d.isoformat(), "status": status, "burn": round(burn, 3), "note": note})
    return out


def uptime(src: ProbeLogSource, service: str, now: datetime, days: int = 90) -> float | None:
    bad, valid = src.counts(service, now - timedelta(days=days), now)
    return None if valid == 0 else 1.0 - bad / valid
