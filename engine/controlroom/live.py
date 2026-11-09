"""Probe mode: rebuild the live engine from the probe history.

The engine is deterministic, so instead of keeping state between GitHub Actions runs it replays
the whole probe history (5-minute steps) every time. Incident ids come from the service and the
minute the incident opened, so they never change between rebuilds. Side effects (Telegram pages)
are not sent during the rebuild; `notify.py` sends them once, afterwards, for new incidents only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapters import MemorySink
from .config import Config, parse_duration
from .engine import Annotation, Engine
from .probelog import EAT, ProbeLogSource, read_log

STEP = timedelta(minutes=5)


@dataclass
class ProbeSink(MemorySink):
    """Stable ticket ids: CR-<callsign>-<MMDD>-<HHMM> in EAT, from the incident's opening minute."""
    callsigns: dict[str, str] = field(default_factory=dict)

    def open(self, title: str, priority: str, body: dict) -> str:
        at = datetime.fromisoformat(body["opened_at"]).astimezone(EAT)
        tid = f"CR-{self.callsigns.get(body['service'], body['service'][:5].upper())}-{at:%m%d-%H%M}"
        self.tickets[tid] = {"title": title, "priority": priority, "body": body, "notes": [], "status": "open"}
        return tid


@dataclass
class RebuildPager:
    """During a rebuild nothing is sent. The timeline says whether a pager is configured, so the
    record is honest: notify.py delivers the page after the rebuild when one is."""
    configured: bool
    sent: list[str] = field(default_factory=list)

    def page(self, text: str) -> bool:
        self.sent.append(text)
        return self.configured


def pager_configured() -> bool:
    return bool((os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")) or os.environ.get("PAGER_WEBHOOK_URL"))


def load_acks(data_dir: Path) -> list[Annotation]:
    """Acks recorded from Telegram (notify.py) become timeline events, like a human note."""
    f = data_dir / "acks.json"
    if not f.is_file():
        return []
    out = []
    for a in json.loads(f.read_text(encoding="utf-8")):
        out.append(Annotation(datetime.fromisoformat(a["at"]), a["service"], a["slo"], "Dior",
                              a.get("text", "Acknowledged from Telegram."), "ack · telegram", kind="ack"))
    return out


def build(cfg: Config, data_dir: str | Path, now: datetime | None = None) -> tuple[Engine, ProbeLogSource]:
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    records = [r for r in read_log(data_dir / "runs") if r.at <= now]
    src = ProbeLogSource(records, parse_duration(cfg.probe.get("lookback", "30m")))
    sink = ProbeSink(prefix="CR", callsigns={s.id: s.callsign for s in cfg.services})
    eng = Engine(cfg, src, sink, RebuildPager(pager_configured()), annotations=load_acks(data_dir))
    first = src.first_seen()
    if first is not None:
        t = datetime.fromtimestamp(first.timestamp() // STEP.total_seconds() * STEP.total_seconds() + STEP.total_seconds(), timezone.utc)
        while t < now:
            eng.evaluate(t)
            t += STEP
    eng.evaluate(now)
    return eng, src
